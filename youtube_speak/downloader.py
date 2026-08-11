"""YouTube 字幕下载模块。

使用 youtube-transcript-api 直接获取字幕，
通过 YouTube oEmbed API 获取视频元信息。
无需 JS runtime 或 cookies。
"""

import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from youtube_transcript_api import YouTubeTranscriptApi


@dataclass
class SubtitleInfo:
    """字幕下载结果。"""

    video_id: str
    video_title: str
    uploader: str
    duration_seconds: int
    subtitle_path: Path  # .srt 文件路径
    subtitle_type: str  # "manual" | "auto"
    language: str


def _extract_video_id(url: str) -> str:
    """从 YouTube URL 中提取视频 ID。"""
    patterns = [
        r"youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})",
        r"youtu\.be/([a-zA-Z0-9_-]{11})",
        r"youtube\.com/embed/([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"Cannot extract video ID from URL: {url}")


def _fetch_metadata(video_id: str) -> dict:
    """通过 YouTube oEmbed API 获取视频元信息（无需认证）。"""
    oembed_url = (
        f"https://www.youtube.com/oembed?"
        f"url=https://www.youtube.com/watch?v={video_id}&format=json"
    )
    try:
        req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {
                "title": data.get("title", "Unknown"),
                "uploader": data.get("author_name", "Unknown"),
            }
    except Exception:
        return {"title": "Unknown", "uploader": "Unknown"}


def _format_time(seconds: float) -> str:
    """将浮点秒数格式化为 SRT 时间戳: HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _transcript_to_srt(transcript: list[dict], output_path: Path) -> Path:
    """将 transcript API 返回的数据写为 SRT 文件。"""
    lines = []
    for i, entry in enumerate(transcript, 1):
        start = entry["start"]
        duration = entry.get("duration", 0)
        end = start + duration
        text = entry["text"].replace("\n", " ").strip()

        lines.append(str(i))
        lines.append(f"{_format_time(start)} --> {_format_time(end)}")
        lines.append(text)
        lines.append("")  # 空行分隔

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def download_subtitles(
    url: str,
    output_dir: Path,
    languages: list[str] | None = None,
) -> SubtitleInfo:
    """下载 YouTube 视频字幕和元信息。

    优先手动上传字幕，fallback 到自动生成字幕。

    Args:
        url: YouTube 视频 URL。
        output_dir: 输出目录。
        languages: 优先尝试的语言列表，默认 ["en", "en-US", "en-GB"]。

    Returns:
        SubtitleInfo: 包含视频元信息和字幕文件路径。
    """
    if languages is None:
        languages = ["en", "en-US", "en-GB"]

    video_id = _extract_video_id(url)
    video_output_dir = output_dir / video_id
    video_output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: 获取视频元信息
    meta = _fetch_metadata(video_id)

    # Step 2: 尝试获取字幕（先手动后自动）
    api = YouTubeTranscriptApi()
    transcript = None
    subtitle_type = "manual"
    used_lang = "en"

    # 先尝试手动字幕
    try:
        available = api.list(video_id)
        for t in available:
            lang_code = t.language_code if hasattr(t, 'language_code') else t.get('language_code', '')
            is_generated = t.is_generated if hasattr(t, 'is_generated') else t.get('is_generated', True)
            if lang_code in languages and not is_generated:
                transcript = api.fetch(video_id, languages=[lang_code])
                subtitle_type = "manual"
                used_lang = lang_code
                break
    except Exception:
        pass

    # Fallback: 自动生成字幕
    if transcript is None:
        try:
            transcript = api.fetch(video_id, languages=languages)
            subtitle_type = "auto"
            used_lang = languages[0]
        except Exception as e:
            raise RuntimeError(
                f"Cannot download subtitles for video {video_id}.\n"
                f"  Error: {e}\n"
                f"  Please verify:\n"
                f"    1. The video exists and is accessible\n"
                f"    2. The video has English subtitles (manual or auto-generated)"
            )

    if not transcript:
        raise RuntimeError(
            f"No subtitle content found for video {video_id}."
        )

    # Step 3: 写入 SRT 文件
    srt_path = video_output_dir / f"{video_id}.{used_lang}.srt"
    _transcript_to_srt(transcript, srt_path)

    # 计算时长
    duration = 0
    if transcript:
        last = transcript[-1]
        duration = int(last["start"] + last.get("duration", 0))

    return SubtitleInfo(
        video_id=video_id,
        video_title=meta["title"],
        uploader=meta["uploader"],
        duration_seconds=duration,
        subtitle_path=srt_path,
        subtitle_type=subtitle_type,
        language=used_lang,
    )
