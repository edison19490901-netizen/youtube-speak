"""YouTube Speak CLI —— 从字幕文本生成英语口语练习材料。

用法:
    # 从 YouTube 下载
    python -m youtube_speak "https://youtube.com/watch?v=xxx"

    # 从字幕文件（.srt / .txt）
    python -m youtube_speak --file subtitles.txt

    # 从 stdin
    cat subtitles.txt | python -m youtube_speak -t "My Video"
"""

import os
import sys
from pathlib import Path

import click

from . import __version__
from .downloader import download_subtitles, SubtitleInfo, _extract_video_id
from .parser import parse_srt, parse_file
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
    name="youtube-speak",
    help="从字幕文本生成英语口语练习材料。",
)
@click.argument("url", required=False, default=None)
@click.option(
    "--file", "-f",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="字幕文件路径（.srt 或 .txt）",
)
@click.option(
    "--title", "-t",
    default=None,
    help="视频/音频标题（用于 --file 或 stdin 输入时）",
)
@click.option(
    "--speaker", "-s",
    default="Unknown",
    help="演讲者/频道名（默认: Unknown）",
)
@click.option(
    "--level", "-l",
    type=click.Choice(["beginner", "intermediate", "advanced"]),
    default="beginner",
    help="英语水平 (默认: beginner)",
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
    level: str,
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

    # 读取 .env
    api_key = _load_api_key(api_key)
    out_dir = Path(output_dir)

    # ═══════════════════════════════════════════
    # Step 1: 获取字幕
    # ═══════════════════════════════════════════
    click.echo()

    if file is not None:
        info, parsed = _step_file(file, title or file.stem, speaker, out_dir)
    elif url is not None:
        info, parsed = _step_download(url, out_dir)
    else:
        info, parsed = _step_stdin(title or "stdin", speaker, out_dir)

    # ═══════════════════════════════════════════
    # Step 2: AI 分析
    # ═══════════════════════════════════════════
    _echo_step("[2/3] AI analysis (DeepSeek API)...")
    click.echo("   (processing, may take 10-30s for long subtitles)")

    try:
        analysis = analyze(
            full_text=parsed.full_text,
            sentences=parsed.sentences,
            video_title=info.video_title,
            level=level,
            api_key=api_key,
            model=model,
        )
    except ValueError as e:
        _echo_err(f"API config error: {e}")
        sys.exit(1)
    except RuntimeError as e:
        _echo_err(f"Analysis failed: {e}")
        sys.exit(1)

    click.echo(f"   Vocabulary: {len(analysis.vocabulary)} items")
    click.echo(f"   Golden sentences: {len(analysis.golden_sentences)} items")
    click.echo(f"   Shadowing chunks: {len(analysis.shadowing)} chunks")
    click.echo(f"   Difficult spots: {len(analysis.difficult_spots)} items")

    video_dir = out_dir / info.video_id
    analysis_json = video_dir / "analysis.json"
    save_analysis(analysis, analysis_json)

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

def _step_download(url: str, out_dir: Path) -> tuple[SubtitleInfo, "ParsedSubtitle"]:
    """从 YouTube 下载字幕。"""
    _echo_step("[1/3] Download subtitles from YouTube...")

    try:
        info = download_subtitles(url, out_dir)
    except ValueError as e:
        _echo_err(f"URL parse error: {e}")
        sys.exit(1)
    except RuntimeError as e:
        _echo_err(f"Download failed: {e}")
        sys.exit(1)

    click.echo(f"   Title: {info.video_title}")
    click.echo(f"   Channel: {info.uploader}")
    click.echo(f"   Subtitle: {info.subtitle_type} ({info.language})")
    click.echo(f"   Sentences: ...")

    parsed = parse_srt(info.subtitle_path)
    click.echo(f"   Sentences: {parsed.sentence_count}, Words: {parsed.word_count}")

    if parsed.word_count < 30:
        _echo_warn("   Content too short, analysis may be limited.")

    return info, parsed


def _step_file(
    file_path: Path, title: str, speaker: str, out_dir: Path
) -> tuple[SubtitleInfo, "ParsedSubtitle"]:
    """从文件读取字幕。"""
    _echo_step("[1/3] Read subtitles from file...")
    click.echo(f"   File: {file_path}")
    click.echo(f"   Title: {title}")

    parsed = parse_file(file_path)
    click.echo(f"   Sentences: {parsed.sentence_count}, Words: {parsed.word_count}")

    if parsed.word_count < 30:
        _echo_warn("   Content too short, analysis may be limited.")

    # 用文件名作为 ID
    video_id = file_path.stem
    video_dir = out_dir / video_id
    video_dir.mkdir(parents=True, exist_ok=True)

    info = SubtitleInfo(
        video_id=video_id,
        video_title=title,
        uploader=speaker,
        duration_seconds=parsed.sentence_count * 5,
        subtitle_path=file_path,
        subtitle_type="file",
        language="en",
    )

    return info, parsed


def _step_stdin(
    title: str, speaker: str, out_dir: Path
) -> tuple[SubtitleInfo, "ParsedSubtitle"]:
    """从标准输入读取字幕。"""
    _echo_step("[1/3] Read subtitles from stdin...")
    click.echo("   (paste text and press Ctrl+Z then Enter on Windows, Ctrl+D on Unix)")

    text = sys.stdin.read()
    if not text.strip():
        _echo_err("No input received from stdin.")
        sys.exit(1)

    from .parser import parse_text

    parsed = parse_text(text)
    click.echo(f"   Title: {title}")
    click.echo(f"   Sentences: {parsed.sentence_count}, Words: {parsed.word_count}")

    if parsed.word_count < 30:
        _echo_warn("   Content too short, analysis may be limited.")

    import hashlib
    video_id = "stdin_" + hashlib.md5(text[:200].encode()).hexdigest()[:8]
    video_dir = out_dir / video_id
    video_dir.mkdir(parents=True, exist_ok=True)

    info = SubtitleInfo(
        video_id=video_id,
        video_title=title,
        uploader=speaker,
        duration_seconds=parsed.sentence_count * 5,
        subtitle_path=video_dir / "input.txt",
        subtitle_type="stdin",
        language="en",
    )

    return info, parsed


# ── 辅助函数 ────────────────────────────────

def _load_api_key(explicit_key: str | None) -> str | None:
    """加载 API Key：优先显式传入，其次 .env 文件，最后环境变量。"""
    if explicit_key:
        return explicit_key

    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")

    return None


if __name__ == "__main__":
    main()
