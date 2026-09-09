"""本地视频 / 音频 → 字幕转写模块。

把用户上传的视频（或纯音频）先抽成 16k 单声道 WAV，再用 faster-whisper
在本地转写为带时间戳的 SRT 字幕，供下游 ``parse_srt`` 走统一的解读流程。

转写后端是「可插拔」的：本模块只负责 ffmpeg 抽音频 + 把结果写 SRT，
具体识别由 :func:`transcribe_audio` 完成。当前实现是 faster-whisper（离线、免费），
后续想换火山引擎等在线 ASR 时，只需替换 :func:`transcribe_audio` 的内部实现。

依赖（可选）:
    faster-whisper    转写引擎（未安装时给出安装提示，不影响其他输入方式）
    ffmpeg            抽音频（系统可执行文件，需在 PATH）

可通过环境变量覆盖：
    WHISPER_MODEL        模型名（默认 "small"）
    WHISPER_DEVICE       计算设备（默认 auto：有 CUDA 用 cuda，否则 cpu）
    WHISPER_COMPUTE_TYPE 计算精度（默认 cuda→float16，cpu→int8）
"""

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

# 可转写的媒体扩展名（区分视频 / 音频，仅用于校验与提示）
MEDIA_EXTS = {
    ".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".wmv",
    ".flv", ".ts", ".3gp", ".mpg", ".mpeg", ".ogv",
}
AUDIO_EXTS = {
    ".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus",
    ".wma", ".aiff",
}
SUPPORTED_EXTS = MEDIA_EXTS | AUDIO_EXTS

_VIDEO_HINT = "/".join(sorted(MEDIA_EXTS, key=len))

DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", "small")

# 模块级缓存 WhisperModel（首次加载后复用，避免每次转写都重新载入）
_model_cache: dict = {}


def _local_model_dir(model_size: str) -> Path:
    """仓库根目录下的本地模型目录：<repo>/models/faster-whisper-<size>。"""
    return Path(__file__).resolve().parent.parent / "models" / f"faster-whisper-{model_size}"


def _resolve_model(model_size: str) -> str:
    """优先用已下载到仓库 models/ 下的本地模型目录（离线可用），否则按仓库名在线下载。"""
    if model_size and "/" not in model_size:
        local = _local_model_dir(model_size)
        if local.is_dir():
            return str(local)
    return model_size


@dataclass
class Transcript:
    """一次转写的结果。"""

    language: str          # whisper 检测到的语言代码，如 "en" / "zh"
    duration_seconds: int  # 内容时长（按最后一句时间戳）
    srt_path: Path         # 生成的 SRT 文件路径


# ── ffmpeg ──────────────────────────────────────


def find_ffmpeg() -> str:
    """定位 ffmpeg 可执行文件，找不到则抛出带指引的 RuntimeError。"""
    exe = os.environ.get("WHISPER_FFMPEG") or shutil.which("ffmpeg")
    if exe:
        return exe
    raise RuntimeError(
        "缺少 ffmpeg，无法从视频中抽取音频。\n"
        "请先安装 ffmpeg 并加入 PATH（Windows: winget install ffmpeg）。"
    )


def extract_audio(media_path: Path, wav_path: Path) -> None:
    """用 ffmpeg 把任意媒体抽成 16k 单声道 WAV（whisper 的标准输入）。"""
    ffmpeg = find_ffmpeg()
    cmd = [
        ffmpeg, "-y", "-loglevel", "error",
        "-i", str(media_path),
        "-vn", "-ac", "1", "-ar", "16000",
        str(wav_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        msg = detail[-1] if detail else "未知错误"
        raise RuntimeError(f"ffmpeg 抽音频失败: {msg}")


# ── faster-whisper ──────────────────────────────


def _device_and_compute() -> tuple[str, str]:
    """决定计算设备与精度：默认有 CUDA 用 cuda/float16，否则 cpu/int8。"""
    device = os.environ.get("WHISPER_DEVICE", "").lower()
    if not device:
        device = "cpu"
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                device = "cuda"
        except Exception:
            pass

    compute_type = os.environ.get("WHISPER_COMPUTE_TYPE", "").lower()
    if not compute_type:
        compute_type = "float16" if device == "cuda" else "int8"
    return device, compute_type


def _load_model(model_size: str):
    """加载（并缓存）WhisperModel。faster-whisper 未安装时给出安装指引。"""
    global _model_cache
    if model_size in _model_cache:
        return _model_cache[model_size]

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError(
            "缺少 faster-whisper，无法转写本地视频/音频。\n"
            "请先执行: pip install faster-whisper\n"
            "（首次转写会自动下载识别模型，约需数百 MB）"
        )

    device, compute_type = _device_and_compute()
    try:
        # 优先本地 models/faster-whisper-<size>，否则按模型名在线下载
        model = WhisperModel(_resolve_model(model_size), device=device, compute_type=compute_type)
    except Exception as e:
        # 常见于模型需从 HuggingFace 下载但网络不通（可配镜像）
        if "hf_" in str(e).lower() or "huggingface" in str(e).lower() or isinstance(e, (OSError, ValueError)):
            raise RuntimeError(
                f"加载 whisper 模型失败: {e}\n"
                "模型需从 HuggingFace 下载。若网络受限，可把模型放到仓库 "
                "models/faster-whisper-small/ 目录，或设置镜像后重试:\n"
                "  export HF_ENDPOINT=https://hf-mirror.com   (Windows: set HF_ENDPOINT=https://hf-mirror.com)"
            )
        raise RuntimeError(f"加载 whisper 模型失败: {e}")

    _model_cache[model_size] = model
    return model


def transcribe_audio(
    wav_path: Path,
    model_size: str = DEFAULT_MODEL,
    language: str | None = None,
) -> tuple[list[dict], str, float]:
    """对 16k WAV 做语音识别。

    Args:
        wav_path: 16k 单声道 WAV 路径。
        model_size: whisper 模型名（如 "tiny"/"base"/"small"/"medium"）。
        language: 强制语言代码（None 表示自动检测）。

    Returns:
        (segments, language, duration)
        segments: [{start, end, text}]，单位秒。
    """
    model = _load_model(model_size)
    segments_iter, info = model.transcribe(
        str(wav_path),
        language=language,
        task="transcribe",
        beam_size=5,
    )

    segments = []
    end = 0.0
    for seg in segments_iter:
        text = seg.text.strip()
        if text:
            segments.append({"start": seg.start, "end": seg.end, "text": text})
            end = max(end, seg.end)

    lang = getattr(info, "language", None) or "en"
    duration = float(getattr(info, "duration", 0) or end or 0)
    return segments, lang, duration


# ── SRT 输出 ────────────────────────────────────


def _format_time(seconds: float) -> str:
    """将秒数格式化为 SRT 时间戳: HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def segments_to_srt(segments: list[dict], output_path: Path) -> Path:
    """把识别出的片段写成 SRT 文件。"""
    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{_format_time(seg['start'])} --> {_format_time(seg['end'])}")
        lines.append(seg["text"])
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


# ── 顶层入口 ────────────────────────────────────


def transcribe_to_srt(
    media_path: Path,
    output_srt: Path,
    model_size: str = DEFAULT_MODEL,
    language: str | None = None,
) -> Transcript:
    """把本地视频/音频文件转写成 SRT 字幕。

    Args:
        media_path: 上传的媒体文件路径。
        output_srt: 要写出的 .srt 路径。
        model_size: whisper 模型名。
        language: 强制语言（None = 自动检测）。

    Returns:
        Transcript：包含语言、时长与 SRT 路径。

    Raises:
        RuntimeError: 缺少 ffmpeg / faster-whisper / 转写失败。
        ValueError: 转写结果为空（静音或无有效语音）。
    """
    output_srt.parent.mkdir(parents=True, exist_ok=True)

    tmp_dir = Path(tempfile.mkdtemp(prefix="zhidu_whisper_"))
    try:
        wav_path = tmp_dir / "audio.wav"
        extract_audio(media_path, wav_path)

        segments, lang, duration = transcribe_audio(wav_path, model_size, language)
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

    if not segments:
        raise ValueError(
            "未能从该媒体中识别到语音内容。请确认文件有清晰的语音轨道，"
            "或该格式被 ffmpeg 支持。"
        )

    segments_to_srt(segments, output_srt)
    return Transcript(
        language=lang,
        duration_seconds=int(round(duration)),
        srt_path=output_srt,
    )
