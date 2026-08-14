"""智读 CLI —— 从中文/英文文章、博客、视频字幕、文档生成深度解读材料。

用法:
    # 从视频字幕
    python -m article_understand "https://youtube.com/watch?v=xxx"

    # 从网页文章 URL
    python -m article_understand "https://example.com/blog/post"

    # 从本地文件（.srt / .txt / .md / .docx / .pdf）
    python -m article_understand --file subtitles.srt

    # 从 stdin 粘贴文本
    cat article.txt | python -m article_understand -t "文章标题"
"""

import hashlib
import os
import sys
from pathlib import Path

import click

from . import __version__
from .downloader import (
    download_subtitles,
    fetch_web_article,
    is_youtube_url,
    SubtitleInfo,
)
from .parser import parse_srt, parse_file, parse_article, detect_language
from .analyzer import analyze, save_analysis
from .outputs import workbook

DEFAULT_OUTPUT_DIR = Path(__file__).parent.parent / "output"


def _echo_ok(text: str) -> None:
    click.secho(text, fg="green")


def _echo_step(text: str) -> None:
    click.secho(text, fg="cyan", bold=True)


def _echo_err(text: str) -> None:
    click.secho(text, fg="red")


def _echo_warn(text: str) -> None:
    click.secho(text, fg="yellow")


@click.command(
    name="article-understand",
    help="从中文/英文文章、博客、字幕生成深度解读材料。",
)
@click.argument("url", required=False, default=None)
@click.option(
    "--file", "-f",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="本地文件路径（.srt 字幕 或 .txt 文章/字幕）",
)
@click.option(
    "--title", "-t",
    default=None,
    help="材料标题（用于 --file 或 stdin 输入时）",
)
@click.option(
    "--speaker", "-s",
    default="",
    help="作者/来源（默认自动判断）",
)
@click.option(
    "--source",
    type=click.Choice(["article", "blog", "subtitle", "auto"]),
    default="auto",
    help="材料类型（默认 auto: 按输入方式自动判断）",
)
@click.option(
    "--language", "-l",
    type=click.Choice(["zh", "en", "auto"]),
    default="auto",
    help="材料语言（默认 auto: 自动检测；仅英文材料生成金句单词）",
)
@click.option(
    "--model", "-m",
    default="deepseek-chat",
    help="DeepSeek 模型名称 (默认: deepseek-chat)",
)
@click.option(
    "--api-key",
    default=None,
    help="DeepSeek API Key（默认从 DEEPSEEK_API_KEY 环境变量读取）",
)
@click.option(
    "--output-dir", "-d",
    default=str(DEFAULT_OUTPUT_DIR),
    help=f"输出根目录 (默认: {DEFAULT_OUTPUT_DIR})",
)
@click.version_option(version=__version__)
def main(
    url: str | None,
    file: Path | None,
    title: str | None,
    speaker: str,
    source: str,
    language: str,
    model: str,
    api_key: str | None,
    output_dir: str,
) -> None:
    """主入口。"""
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    api_key = _load_api_key(api_key)
    out_dir = Path(output_dir)

    # ═══════════════════════════════════════════
    # Step 1: 获取材料
    # ═══════════════════════════════════════════
    click.echo()

    if file is not None:
        info, parsed = _step_file(file, title or file.stem, speaker, out_dir)
    elif url is not None:
        info, parsed = _step_url(url, title, out_dir)
    else:
        info, parsed = _step_stdin(title or "粘贴文本", speaker, out_dir)

    # 语言检测
    lang = language if language != "auto" else detect_language(parsed.full_text)
    source_type = info.subtitle_type  # 已设置为 article/blog/subtitle
    click.echo(f"   Language: {'中文' if lang == 'zh' else 'English'}")
    click.echo(f"   Source:   {source_type}")

    if parsed.word_count < 30:
        _echo_warn("   Content too short, analysis may be limited.")

    # ═══════════════════════════════════════════
    # Step 2: AI 分析
    # ═══════════════════════════════════════════
    _echo_step("[2/3] AI analysis (DeepSeek API)...")
    click.echo("   (processing, may take 10-60s for long materials)")

    try:
        analysis = analyze(
            full_text=parsed.full_text,
            title=info.video_title,
            source_type=source_type,
            language=lang,
            api_key=api_key,
            model=model,
        )
    except ValueError as e:
        _echo_err(f"API config error: {e}")
        sys.exit(1)
    except RuntimeError as e:
        _echo_err(f"Analysis failed: {e}")
        sys.exit(1)

    click.echo(f"   Spoken summary: script {len(analysis.spoken_summary.script_zh) if analysis.spoken_summary else 0} ZH paras")
    click.echo(f"   Deconstruction: {len(analysis.deconstruction.sections) if analysis.deconstruction else 0} sections")
    if analysis.practical_application:
        click.echo(f"   Application: {len(analysis.practical_application.actionable_skills)} skills, {len(analysis.practical_application.thinking_models)} models")
    if analysis.golden_words:
        click.echo(f"   Golden words: {len(analysis.golden_words.golden_sentences)} sentences, {len(analysis.golden_words.vocabulary)} vocab")

    if analysis.usage and analysis.usage.total_tokens > 0:
        cost_str = f"¥{analysis.usage.cost_cny:.4f}"
        click.echo(f"   API cost: {cost_str} ({analysis.usage.total_tokens} tokens)")

    video_dir = out_dir / info.video_id
    video_dir.mkdir(parents=True, exist_ok=True)
    save_analysis(analysis, video_dir / "analysis.json")

    # ═══════════════════════════════════════════
    # Step 3: 生成输出
    # ═══════════════════════════════════════════
    _echo_step("\n[3/3] Generate workbook...")

    workbook_path = video_dir / "workbook.html"
    workbook.generate(analysis, info, parsed, workbook_path)

    click.echo()
    _echo_ok(f"  [OK] Workbook: {workbook_path}")

    _echo_ok(f"\nDone! Open in browser: {workbook_path}")


# ── 输入源处理 ──────────────────────────────


def _step_url(url: str, title: str | None, out_dir: Path) -> tuple[SubtitleInfo, "object"]:
    """从 URL 获取材料：YouTube 链接下载字幕，否则抓取网页文章。"""
    if is_youtube_url(url):
        _echo_step("[1/3] Download subtitles from YouTube...")
        try:
            info = download_subtitles(url, out_dir)
        except (ValueError, RuntimeError) as e:
            _echo_err(f"Download failed: {e}")
            sys.exit(1)
        click.echo(f"   Title: {info.video_title}")
        click.echo(f"   Channel: {info.uploader}")
        parsed = parse_srt(info.subtitle_path)
        info.subtitle_type = "subtitle"
        return info, parsed

    _echo_step("[1/3] Fetch web article...")
    try:
        text = fetch_web_article(url)
    except ValueError as e:
        _echo_err(str(e))
        sys.exit(1)

    parsed = parse_article(text)
    video_id = "url_" + hashlib.md5(url.encode()).hexdigest()[:8]
    info = SubtitleInfo(
        video_id=video_id,
        video_title=title or _domain_of(url),
        uploader=_domain_of(url),
        duration_seconds=0,
        subtitle_path=out_dir / video_id / "article.txt",
        subtitle_type="article",
        language="en",
    )
    click.echo(f"   Title: {info.video_title}")
    click.echo(f"   Words: {parsed.word_count}, Paragraphs: {parsed.full_text.count(chr(10) + chr(10)) + 1}")
    return info, parsed


def _step_file(
    file_path: Path, title: str, speaker: str, out_dir: Path
) -> tuple[SubtitleInfo, "object"]:
    """从文件读取材料（.srt 字幕 / .txt 文章）。"""
    _echo_step("[1/3] Read material from file...")
    click.echo(f"   File: {file_path}")

    parsed = parse_file(file_path)
    click.echo(f"   Words: {parsed.word_count}")

    video_id = file_path.stem
    source_type = "subtitle" if file_path.suffix.lower() == ".srt" else "article"

    info = SubtitleInfo(
        video_id=video_id,
        video_title=title,
        uploader=speaker or "本地文件",
        duration_seconds=parsed.sentence_count * 5,
        subtitle_path=file_path,
        subtitle_type=source_type,
        language="en",
    )
    return info, parsed


def _step_stdin(
    title: str, speaker: str, out_dir: Path
) -> tuple[SubtitleInfo, "object"]:
    """从标准输入读取文本。"""
    _echo_step("[1/3] Read material from stdin...")
    click.echo("   (paste text and press Ctrl+Z then Enter on Windows, Ctrl+D on Unix)")

    text = sys.stdin.read()
    if not text.strip():
        _echo_err("No input received from stdin.")
        sys.exit(1)

    parsed = parse_article(text)
    click.echo(f"   Title: {title}")
    click.echo(f"   Words: {parsed.word_count}")

    video_id = "stdin_" + hashlib.md5(text[:200].encode()).hexdigest()[:8]
    info = SubtitleInfo(
        video_id=video_id,
        video_title=title,
        uploader=speaker or "粘贴文本",
        duration_seconds=0,
        subtitle_path=out_dir / video_id / "input.txt",
        subtitle_type="article",
        language="en",
    )
    return info, parsed


# ── 辅助函数 ────────────────────────────────


def _domain_of(url: str) -> str:
    """粗略提取 URL 的域名作为来源名。"""
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc or "网页文章"
    except Exception:
        return "网页文章"


def _load_api_key(explicit_key: str | None) -> str | None:
    """加载 API Key：优先显式传入，其次 .env 文件，最后环境变量。"""
    if explicit_key:
        return explicit_key

    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key

    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")

    return None


if __name__ == "__main__":
    main()
