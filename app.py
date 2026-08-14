"""智读 Web —— 浏览器端入口。

输入：中文/英文文章、博客、字幕（粘贴文本 / 视频或网页链接 / 本地文档）
输出：交互式 HTML 解读看板（口播总结、解构、实际应用、金句单词、统计）

用法:
    python app.py
    # 或生产环境:
    gunicorn app:app --bind 0.0.0.0:$PORT
"""

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from flask import Flask, render_template_string, request, redirect, url_for, send_file

# 把 article_understand 加入 path
sys.path.insert(0, str(Path(__file__).parent))

from article_understand.downloader import (
    download_subtitles,
    fetch_web_article,
    is_youtube_url,
    SubtitleInfo,
)
from article_understand.parser import parse_srt, parse_file, parse_article, detect_language
from article_understand.analyzer import analyze, save_analysis
from article_understand.outputs.workbook import generate as generate_workbook

app = Flask(__name__)

OUTPUT_ROOT = Path(__file__).parent / "output"

_LANG_LABELS = {"zh": "中文", "en": "English"}
_SOURCE_LABELS = {"article": "文章", "blog": "博客", "subtitle": "字幕"}

# ── 首页 ────────────────────────────────────

HOME_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="智读">
<link rel="apple-touch-icon" href="/static/brain.png">
<link rel="manifest" href="/manifest.json">
<title>智读 — 深度解读 · 口播总结 · 解构 · 实际应用 · 金句单词</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    font-family: "PingFang SC","Microsoft YaHei",sans-serif;
    background: #f5f5f5; color: #2c2c2c;
    display: flex; justify-content: center; padding: 40px 16px;
  }
  .wrap { max-width: 520px; width: 100%; }
  h1 { text-align:center; font-size:24px; margin-bottom:8px; color:#1a1a2e; }
  .sub { text-align:center; color:#888; font-size:13px; margin-bottom:28px; }
  .card {
    background:#fff; border-radius:12px; padding:28px 24px;
    box-shadow:0 2px 8px rgba(0,0,0,0.06); margin-bottom:16px;
  }
  .card h2 { font-size:16px; color:#e94560; margin-bottom:14px; }
  label { display:block; font-size:13px; font-weight:600; color:#555; margin-bottom:4px; }
  input, select, textarea {
    width:100%; padding:10px 12px; font-size:14px; border:1px solid #ddd;
    border-radius:6px; margin-bottom:12px;
    font-family: inherit;
  }
  textarea { min-height:140px; resize:vertical; }
  input:focus, select:focus, textarea:focus { outline:none; border-color:#e94560; }
  .hint { font-size:11px; color:#aaa; margin-top:-8px; margin-bottom:14px; }
  .divider { text-align:center; color:#ccc; margin:16px 0; font-size:12px; }
  button {
    width:100%; padding:12px; font-size:15px; font-weight:700;
    background:#e94560; color:#fff; border:none; border-radius:8px;
    cursor:pointer; transition:background 0.2s;
  }
  button:hover { background:#d63850; }
  .msg { padding:12px; border-radius:6px; font-size:13px; margin-top:12px; display:none; }
  .msg.info { background:#e8f4fd; color:#1a6aaa; }
  .msg.done { background:#e6f9e6; color:#2a7a2a; }
  .msg.err { background:#fde8e8; color:#a33; }
  .nav { text-align:center; margin-top:8px; }
  .nav a { font-size:13px; color:#e94560; text-decoration:none; }
</style>
</head>
<body>
<div class="wrap">
  <h1>🧠 智读</h1>
  <p class="sub">粘贴文本 · 视频/文章链接 · 上传文档，一键生成深度解读看板</p>

  <div class="card">
    <h2>📥 输入材料</h2>
    <form method="POST" action="/process" enctype="multipart/form-data">
      <label>粘贴文本</label>
      <textarea name="text" placeholder="把文章 / 博客 / 字幕正文粘贴到这里…">{{ text or '' }}</textarea>
      <label>视频 / 文章链接</label>
      <input name="url" type="url" placeholder="https://…（视频链接自动获取字幕，文章链接自动抓取正文）" value="{{ url or '' }}">
      <label>上传文档</label>
      <input name="file" type="file" accept=".srt,.txt,.md,.rtf,.docx,.pdf">
      <label>标题（可选）</label>
      <input name="title" type="text" placeholder="给这份解读取个名字">
      <p class="hint">以上三种方式任选其一：文本、链接（视频/文章）、或文档（.srt / .txt / .md / .docx / .pdf）</p>
      <button type="submit">🚀 生成解读</button>
    </form>
  </div>

  <div class="nav">
    <a href="/library">📚 查看文库</a>
  </div>

  {% if error %}
  <div class="msg err" style="display:block">{{ error }}</div>
  {% endif %}
</div>
</body>
</html>"""

WORKING_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>处理中...</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family: "PingFang SC","Microsoft YaHei",sans-serif; background:#f5f5f5; display:flex; justify-content:center; align-items:center; min-height:100vh; }
  .box { text-align:center; padding:40px; }
  .spinner { width:48px; height:48px; border:4px solid #eee; border-top:4px solid #e94560; border-radius:50%; animation:spin 0.8s linear infinite; margin:0 auto 20px; }
  @keyframes spin { to { transform:rotate(360deg); } }
  h2 { font-size:18px; color:#1a1a2e; margin-bottom:8px; }
  p { font-size:13px; color:#888; }
  .meta { margin-top:16px; font-size:12px; color:#aaa; }
</style>
</head>
<body>
<div class="box">
  <div class="spinner"></div>
  <h2>AI 正在解读材料...</h2>
  <p>{{ status }}</p>
  <p class="meta">通常需要 10-60 秒，请耐心等候</p>
</div>
</body>
</html>"""


@app.route("/")
def home():
    return render_template_string(HOME_HTML)


@app.route("/manifest.json")
def manifest():
    return send_file(str(Path(__file__).parent / "manifest.json"), mimetype="application/json")


@app.route("/process", methods=["POST"])
def process():
    url = request.form.get("url", "").strip()
    text = request.form.get("text", "").strip()
    uploaded = request.files.get("file")
    title = request.form.get("title", "").strip()
    api_key = _load_api_key()

    if not api_key:
        return render_template_string(
            HOME_HTML,
            error="未设置 DEEPSEEK_API_KEY。请在 .env 或环境变量中配置。",
            url=url, text=text, title=title,
        )

    try:
        # ── 输入分流 ──
        if url and is_youtube_url(url):
            parsed, info, uploader = _from_youtube(url, OUTPUT_ROOT)
        elif url:
            parsed, info, uploader = _from_web(url, title)
        elif text:
            parsed, info, uploader = _from_text(text, title)
        elif uploaded and uploaded.filename:
            parsed, info, uploader = _from_upload(uploaded, title)
        else:
            return render_template_string(
                HOME_HTML,
                error="请粘贴文章文本、输入链接或上传文件。",
                title=title,
            )

        # ── 语言检测 ──
        lang = detect_language(parsed.full_text)

        # ── AI 分析 ──
        analysis = analyze(
            full_text=parsed.full_text,
            title=info.video_title,
            source_type=info.subtitle_type,
            language=lang,
            api_key=api_key,
            model="deepseek-chat",
        )

        # ── 保存 ──
        video_dir = OUTPUT_ROOT / info.video_id
        video_dir.mkdir(parents=True, exist_ok=True)
        save_analysis(analysis, video_dir / "analysis.json")

        # ── 生成看板 ──
        workbook_path = video_dir / "workbook.html"
        generate_workbook(analysis, info, parsed, workbook_path)

        return redirect(url_for("result", video_id=info.video_id))

    except ValueError as e:
        return render_template_string(HOME_HTML, error=str(e), url=url, text=text, title=title)
    except RuntimeError as e:
        return render_template_string(HOME_HTML, error=str(e), url=url, text=text, title=title)
    except Exception as e:
        return render_template_string(
            HOME_HTML,
            error=f"未知错误: {e}",
            url=url, text=text, title=title,
        )


@app.route("/result/<video_id>")
def result(video_id):
    """直接提供生成的 workbook.html。"""
    workbook_path = OUTPUT_ROOT / video_id / "workbook.html"
    if not workbook_path.exists():
        return "Workbook not found. It may have been cleaned up. Please generate again.", 404
    return send_file(str(workbook_path), mimetype="text/html; charset=utf-8")


@app.route("/library")
def library():
    """文库 —— 列出所有已生成的解读看板。"""
    items = []
    if OUTPUT_ROOT.exists():
        for subdir in sorted(OUTPUT_ROOT.iterdir(), reverse=True):
            if not subdir.is_dir():
                continue
            analysis_json = subdir / "analysis.json"
            if not analysis_json.exists():
                continue
            try:
                data = json.loads(analysis_json.read_text(encoding="utf-8"))
                meta = data.get("meta", {})
                usage = data.get("usage", {})
                cost_cny = usage.get("cost_cny", 0)
                total_tokens = usage.get("total_tokens", 0)
                lang = meta.get("language", "en")
                source_type = meta.get("source_type", "article")
                spoken = data.get("spoken_summary", {})
                decon = data.get("deconstruction", {})
                practical = data.get("practical_application", {})
                gw = data.get("golden_words") or {}
                items.append({
                    "video_id": subdir.name,
                    "title": meta.get("title") or (spoken.get("summary_zh") or subdir.name)[:80],
                    "lang": lang,
                    "lang_label": _LANG_LABELS.get(lang, lang),
                    "source_label": _SOURCE_LABELS.get(source_type, source_type),
                    "section_count": len(decon.get("sections", [])),
                    "skill_count": len(practical.get("actionable_skills", [])),
                    "golden_count": len(gw.get("golden_sentences", [])),
                    "cost_cny": cost_cny,
                    "total_tokens": total_tokens,
                })
            except Exception:
                pass

    return render_template_string(LIBRARY_HTML, items=items)


LIBRARY_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="智读">
<link rel="apple-touch-icon" href="/static/brain.png">
<link rel="manifest" href="/manifest.json">
<title>文库 — 智读</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:"PingFang SC","Microsoft YaHei",sans-serif; background:#f5f5f5; color:#2c2c2c; }
  .wrap { max-width:600px; margin:0 auto; padding:24px 16px; }
  h1 { text-align:center; font-size:20px; color:#1a1a2e; margin-bottom:6px; }
  .sub { text-align:center; color:#888; font-size:12px; margin-bottom:24px; }
  .nav { text-align:center; margin-bottom:20px; }
  .nav a { font-size:13px; color:#e94560; text-decoration:none; }
  .card {
    display:block; background:#fff; border-radius:10px; padding:16px 20px;
    margin-bottom:10px; box-shadow:0 1px 4px rgba(0,0,0,0.05);
    text-decoration:none; color:inherit; transition:box-shadow 0.2s;
  }
  .card:hover { box-shadow:0 2px 12px rgba(0,0,0,0.1); }
  .card h3 { font-size:15px; color:#1a1a2e; margin-bottom:6px; }
  .card .badges { margin-bottom:6px; }
  .card .badge {
    display:inline-block; font-size:11px; padding:1px 10px; border-radius:10px;
    background:#eef; color:#556; margin-right:6px;
  }
  .card .badge.lang-zh { background:#fdecee; color:#b03a4e; }
  .card .badge.lang-en { background:#e8f4fd; color:#1a6aaa; }
  .card .meta { font-size:12px; color:#888; }
  .card .meta span { margin-right:14px; }
  .empty { text-align:center; padding:60px 20px; color:#aaa; font-size:14px; }
  .footer { text-align:center; padding:24px; color:#bbb; font-size:11px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>📚 解读文库</h1>
  <p class="sub">{{ items|length }} 份解读</p>
  <div class="nav"><a href="/">← 返回首页</a></div>

  {% if items %}
    {% for item in items %}
    <a class="card" href="/result/{{ item.video_id }}">
      <h3>{{ item.title }}</h3>
      <div class="badges">
        <span class="badge lang-{{ item.lang }}">🌐 {{ item.lang_label }}</span>
        <span class="badge">📄 {{ item.source_label }}</span>
      </div>
      <div class="meta">
        <span>📐 {{ item.section_count }} 部分</span>
        <span>🛠 {{ item.skill_count }} 技能</span>
        <span>💎 {{ item.golden_count }} 金句</span>
        {% if item.total_tokens > 0 %}
        <span>💰 ¥{{ "%.4f"|format(item.cost_cny) }}</span>
        {% endif %}
      </div>
    </a>
    {% endfor %}
  {% else %}
    <div class="empty">
      <p>还没有生成任何解读</p>
      <p style="margin-top:8px;"><a href="/">去生成第一个 →</a></p>
    </div>
  {% endif %}

  <div class="footer">智读</div>
</div>
</body>
</html>"""


# ── 输入源处理 ────────────────────────────────────


def _from_youtube(url: str, output_root: Path) -> tuple:
    """YouTube 链接 → 下载字幕并解析。"""
    info = download_subtitles(url, output_root)
    parsed = parse_srt(info.subtitle_path)
    info.subtitle_type = "subtitle"
    return parsed, info, info.uploader


def _from_web(url: str, title: str) -> tuple:
    """网页文章链接 → 抓取正文。"""
    text = fetch_web_article(url)
    parsed = parse_article(text)
    uploader = _domain_of(url)
    video_id = "url_" + hashlib.md5(url.encode()).hexdigest()[:8]
    info = SubtitleInfo(
        video_id=video_id,
        video_title=title or uploader,
        uploader=uploader,
        duration_seconds=0,
        subtitle_path=output_root_for(video_id),
        subtitle_type="article",
        language="en",
    )
    return parsed, info, uploader


def _from_text(text: str, title: str) -> tuple:
    """粘贴文本 → 按文章解析。"""
    parsed = parse_article(text)
    uploader = "粘贴文本"
    safe_title = _slug(title) or "粘贴文本"
    video_id = "text_" + hashlib.md5(text[:200].encode()).hexdigest()[:8]
    info = SubtitleInfo(
        video_id=video_id,
        video_title=title or "粘贴文本",
        uploader=uploader,
        duration_seconds=0,
        subtitle_path=output_root_for(video_id),
        subtitle_type="article",
        language="en",
    )
    return parsed, info, uploader


def _from_upload(uploaded, title: str) -> tuple:
    """上传文件 → .srt 按字幕、其余文本/文档按文章解析。"""
    suffix = Path(uploaded.filename).suffix.lower()
    supported = (".srt", ".txt", ".md", ".rtf", ".docx", ".pdf")
    if suffix not in supported:
        raise ValueError(
            f"不支持的文件格式: {suffix}。"
            "请上传 .srt / .txt / .md / .rtf / .docx / .pdf 文件。"
        )

    tmp_dir = Path(tempfile.gettempdir()) / "article_understand"
    tmp_dir.mkdir(exist_ok=True)
    file_path = tmp_dir / uploaded.filename
    uploaded.save(str(file_path))

    parsed = parse_file(file_path)
    stem = Path(uploaded.filename).stem
    safe_id = "".join(c if c.isalnum() or c in "_-" else "_" for c in stem)
    source_type = "subtitle" if suffix == ".srt" else "article"
    info = SubtitleInfo(
        video_id=safe_id,
        video_title=title or uploaded.filename,
        uploader="本地文件",
        duration_seconds=parsed.sentence_count * 5,
        subtitle_path=file_path,
        subtitle_type=source_type,
        language="en",
    )
    return parsed, info, info.uploader


def output_root_for(video_id: str) -> Path:
    """构造输出目录下的路径占位（供 SubtitleInfo.subtitle_path 使用）。"""
    video_dir = OUTPUT_ROOT / video_id
    video_dir.mkdir(parents=True, exist_ok=True)
    return video_dir / "input.txt"


def _domain_of(url: str) -> str:
    """粗略提取 URL 的域名作为来源名。"""
    try:
        return re.sub(r"^www\.", "", __import__("urllib.parse", fromlist=["urlparse"]).urlparse(url).netloc) or "网页文章"
    except Exception:
        return "网页文章"


def _slug(title: str) -> str:
    """把标题转成安全的目录名片段。"""
    s = re.sub(r"[^\w一-鿿-]+", "_", title).strip("_")
    return s[:60]


# ── 辅助 ────────────────────────────────────


def _load_api_key() -> str:
    """加载 API Key：环境变量 或 .env 文件。"""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
