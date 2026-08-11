"""YouTube Speak Web —— 浏览器端入口。

用法:
    python app.py
    # 或生产环境:
    gunicorn app:app --bind 0.0.0.0:$PORT
"""

import os
import sys
import tempfile
import hashlib
from pathlib import Path

from flask import Flask, render_template_string, request, redirect, url_for, send_file

# 把 youtube_speak 加入 path
sys.path.insert(0, str(Path(__file__).parent))

from youtube_speak.downloader import download_subtitles, _extract_video_id
from youtube_speak.parser import parse_srt, parse_file, ParsedSubtitle
from youtube_speak.analyzer import analyze, save_analysis
from youtube_speak.outputs.workbook import generate as generate_workbook

app = Flask(__name__)

OUTPUT_ROOT = Path(__file__).parent / "output"

# ── 首页 ────────────────────────────────────

HOME_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>YouTube Speak — 英语口语练习册生成器</title>
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
  .card h2 { font-size:16px; color:#e94560; margin-bottom:16px; }
  label { display:block; font-size:13px; font-weight:600; color:#555; margin-bottom:4px; }
  input, select { width:100%; padding:10px 12px; font-size:14px; border:1px solid #ddd; border-radius:6px; margin-bottom:14px; }
  input:focus, select:focus { outline:none; border-color:#e94560; }
  .hint { font-size:11px; color:#aaa; margin-top:-10px; margin-bottom:14px; }
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
</style>
</head>
<body>
<div class="wrap">
  <h1>🎙️ YouTube Speak</h1>
  <p class="sub">输入 YouTube 链接或上传字幕文件，生成交互式英语口语练习册</p>

  <div class="card">
    <h2>🔗 粘贴 YouTube 链接</h2>
    <form method="POST" action="/process">
      <label>YouTube URL</label>
      <input name="url" type="url" placeholder="https://www.youtube.com/watch?v=..." value="{{ url or '' }}">
      <label>英语水平</label>
      <select name="level">
        <option value="beginner" {% if level=='beginner' %}selected{% endif %}>初级 (beginner)</option>
        <option value="intermediate" {% if level=='intermediate' %}selected{% endif %}>中级 (intermediate)</option>
        <option value="advanced" {% if level=='advanced' %}selected{% endif %}>高级 (advanced)</option>
      </select>
      <button type="submit">🚀 生成练习册</button>
    </form>
  </div>

  <p class="divider">— 或者 —</p>

  <div class="card">
    <h2>📁 上传字幕文件</h2>
    <form method="POST" action="/process" enctype="multipart/form-data">
      <label>字幕文件 (.srt 或 .txt)</label>
      <input name="file" type="file" accept=".srt,.txt">
      <label>视频/音频标题</label>
      <input name="title" type="text" placeholder="给这个练习册取个名字" value="{{ title or '' }}">
      <label>英语水平</label>
      <select name="level">
        <option value="beginner" selected>初级 (beginner)</option>
        <option value="intermediate">中级 (intermediate)</option>
        <option value="advanced">高级 (advanced)</option>
      </select>
      <button type="submit">🚀 生成练习册</button>
    </form>
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
  <h2>AI 正在分析字幕...</h2>
  <p>{{ status }}</p>
  <p class="meta">通常需要 10-30 秒，请耐心等候</p>
</div>
</body>
</html>"""


@app.route("/")
def home():
    return render_template_string(HOME_HTML)


@app.route("/process", methods=["POST"])
def process():
    url = request.form.get("url", "").strip()
    uploaded = request.files.get("file")
    title = request.form.get("title", "").strip()
    level = request.form.get("level", "beginner")
    api_key = _load_api_key()

    if not api_key:
        return render_template_string(
            HOME_HTML,
            error="未设置 DEEPSEEK_API_KEY。请在 .env 或环境变量中配置。",
            url=url, title=title, level=level,
        )

    try:
        if url:
            # ── YouTube 模式 ──
            video_id = _extract_video_id(url)
            info = download_subtitles(url, OUTPUT_ROOT)
            parsed = parse_srt(info.subtitle_path)
        elif uploaded and uploaded.filename:
            # ── 文件上传模式 ──
            suffix = Path(uploaded.filename).suffix.lower()
            if suffix not in (".srt", ".txt"):
                return render_template_string(
                    HOME_HTML,
                    error=f"不支持的文件格式: {suffix}，请上传 .srt 或 .txt 文件。",
                    title=title, level=level,
                )
            # 保存到临时位置
            tmp_dir = Path(tempfile.gettempdir()) / "youtube_speak"
            tmp_dir.mkdir(exist_ok=True)
            file_path = tmp_dir / uploaded.filename
            uploaded.save(str(file_path))
            # 解析
            from youtube_speak.parser import parse_file as _parse_file
            from youtube_speak.downloader import SubtitleInfo
            parsed = _parse_file(file_path)
            video_id = Path(uploaded.filename).stem
            # 清理文件名中的特殊字符
            safe_id = "".join(c if c.isalnum() or c in "_-" else "_" for c in video_id)
            # 准备输出目录
            video_dir = OUTPUT_ROOT / safe_id
            video_dir.mkdir(parents=True, exist_ok=True)
            info = SubtitleInfo(
                video_id=safe_id,
                video_title=title or uploaded.filename,
                uploader="Uploaded",
                duration_seconds=parsed.sentence_count * 5,
                subtitle_path=file_path,
                subtitle_type="file",
                language="en",
            )
        else:
            return render_template_string(
                HOME_HTML,
                error="请粘贴 YouTube 链接或上传字幕文件。",
                level=level,
            )

        # ── AI 分析 ──
        analysis = analyze(
            full_text=parsed.full_text,
            sentences=parsed.sentences,
            video_title=info.video_title,
            level=level,
            api_key=api_key,
            model="deepseek-chat",
        )

        # ── 保存 ──
        video_dir = OUTPUT_ROOT / info.video_id
        video_dir.mkdir(parents=True, exist_ok=True)
        save_analysis(analysis, video_dir / "analysis.json")

        # ── 生成 workbook.html ──
        workbook_path = video_dir / "workbook.html"
        generate_workbook(analysis, info, parsed, workbook_path)

        return redirect(url_for("result", video_id=info.video_id))

    except ValueError as e:
        return render_template_string(HOME_HTML, error=str(e), url=url, title=title, level=level)
    except RuntimeError as e:
        return render_template_string(HOME_HTML, error=str(e), url=url, title=title, level=level)
    except Exception as e:
        return render_template_string(
            HOME_HTML,
            error=f"未知错误: {e}",
            url=url, title=title, level=level,
        )


@app.route("/result/<video_id>")
def result(video_id):
    """直接提供生成的 workbook.html。"""
    workbook_path = OUTPUT_ROOT / video_id / "workbook.html"
    if not workbook_path.exists():
        return "Workbook not found. It may have been cleaned up. Please generate again.", 404
    return send_file(str(workbook_path), mimetype="text/html; charset=utf-8")


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
