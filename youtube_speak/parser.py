"""字幕解析与清洗模块。

将 SRT 格式的字幕文件解析为干净的句子列表，保留时间轴信息。
"""

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TimedSentence:
    """带时间戳的单句。"""

    text: str
    start_seconds: float
    end_seconds: float


@dataclass
class ParsedSubtitle:
    """解析后的字幕结果。"""

    sentences: list[TimedSentence] = field(default_factory=list)
    full_text: str = ""  # 纯文本全文（无时间戳）

    @property
    def word_count(self) -> int:
        return len(self.full_text.split())

    @property
    def sentence_count(self) -> int:
        return len(self.sentences)


# ── 非语言内容的清理模式 ──────────────────────────────

CLEANUP_PATTERNS: list[tuple[str, str]] = [
    # HTML 标签
    (r"<[^>]+>", ""),
    # 音乐标记
    (r"♪+.*?♪+", ""),
    (r"\[Music\]", ""),
    (r"\[music\]", ""),
    (r"\(music\)", ""),
    (r"\(upbeat music\)", ""),
    (r"\(instrumental\)", ""),
    # 掌声/笑声标记
    (r"\[Applause\]", ""),
    (r"\[applause\]", ""),
    (r"\[Laughter\]", ""),
    (r"\[laughter\]", ""),
    (r"\(applause\)", ""),
    (r"\(laughter\)", ""),
    (r"\(crowd cheering\)", ""),
    # 其他非语言标记
    (r"\[inaudible\]", ""),
    (r"\(silence\)", ""),
    (r"\(pause\)", ""),
    # YouTube 自动字幕常见噪声
    (r"\[ __ \]", ""),
    (r"\[__\]", ""),
    # 多余空白
    (r"\n{3,}", "\n\n"),
    (r" {2,}", " "),
]


def parse_srt(srt_path: Path) -> ParsedSubtitle:
    """解析 SRT 字幕文件。

    Args:
        srt_path: .srt 字幕文件路径。

    Returns:
        ParsedSubtitle: 包含结构化句子和全文。
    """
    raw_text = srt_path.read_text(encoding="utf-8")

    # Step 1: 解析 SRT 块
    entries = _parse_srt_blocks(raw_text)
    if not entries:
        return ParsedSubtitle()

    # Step 2: 清洗每条字幕文本
    entries = _clean_entries(entries)

    # Step 3: 合并连续片段
    entries = _merge_adjacent(entries, max_gap=0.8)

    # Step 4: 按句子边界切分
    sentences = _split_sentences(entries)

    # Step 5: 生成全文
    full_text = " ".join(s.text for s in sentences)

    return ParsedSubtitle(sentences=sentences, full_text=full_text)


def _parse_srt_blocks(raw: str) -> list[dict]:
    """解析 SRT 原始文本为结构化条目列表。

    每个条目: {index, start_sec, end_sec, text}
    """
    entries = []
    # SRT 块由空行分隔
    blocks = re.split(r"\n\s*\n", raw.strip())

    # 时间格式: 00:01:23,456 --> 00:01:27,890
    time_re = re.compile(
        r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
        r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
    )

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        time_match = time_re.search(block)
        if not time_match:
            continue

        groups = time_match.groups()
        start_sec = (
            int(groups[0]) * 3600
            + int(groups[1]) * 60
            + int(groups[2])
            + int(groups[3]) / 1000
        )
        end_sec = (
            int(groups[4]) * 3600
            + int(groups[5]) * 60
            + int(groups[6])
            + int(groups[7]) / 1000
        )

        # 文本在时间戳之后
        text_start = time_match.end()
        text = block[text_start:].strip()
        # 去掉 SRT 块首的序号（可能出现在时间戳之前）
        # 把多行文本合并为一行
        text = " ".join(text.splitlines())

        entries.append({
            "start_sec": start_sec,
            "end_sec": end_sec,
            "text": text,
        })

    return entries


def _clean_entries(entries: list[dict]) -> list[dict]:
    """逐条清洗字幕文本。"""
    cleaned = []
    for entry in entries:
        text = entry["text"]
        for pattern, replacement in CLEANUP_PATTERNS:
            text = re.sub(pattern, replacement, text)
        text = text.strip()
        # 跳过清洗后变成空的条目
        if text and len(text) > 1:
            entry["text"] = text
            cleaned.append(entry)
    return cleaned


def _merge_adjacent(entries: list[dict], max_gap: float = 0.8) -> list[dict]:
    """合并时间上相邻的条目（同一说话人连续说话）。

    Args:
        max_gap: 两条字幕间允许的最大间隔秒数，超过则不合并。
    """
    if not entries:
        return []

    merged = [dict(entries[0])]

    for entry in entries[1:]:
        gap = entry["start_sec"] - merged[-1]["end_sec"]
        if gap <= max_gap:
            # 合并文本，扩展结束时间
            merged[-1]["text"] += " " + entry["text"]
            merged[-1]["end_sec"] = entry["end_sec"]
        else:
            merged.append(dict(entry))

    return merged


def _split_sentences(entries: list[dict]) -> list[TimedSentence]:
    """按句子边界（句号、问号、感叹号）切分字幕条目。

    保持大致的时间戳：如果一条字幕包含多个句子，
    按字符比例分配时间。
    """
    sentences = []
    # 句子结束标记: . ! ? 后面跟空格或结束
    sentence_end_re = re.compile(r"([.!?])\s+")

    for entry in entries:
        text = entry["text"]
        start = entry["start_sec"]
        end = entry["end_sec"]
        duration = end - start

        # 找到所有句子边界
        parts = sentence_end_re.split(text)
        # parts 会是: [text0, sep0, text1, sep1, text2, ...]
        # 或没有分隔符时: [text]

        if len(parts) == 1:
            # 没有句子边界，直接作为一个句子
            sentences.append(TimedSentence(
                text=text.strip(),
                start_seconds=start,
                end_seconds=end,
            ))
        else:
            # 重建句子: parts[0] + parts[1], parts[2] + parts[3], ...
            current_sentence = ""
            char_pos = 0
            total_chars = len(text)

            for i in range(0, len(parts) - 1, 2):
                segment = parts[i] + (parts[i + 1] if i + 1 < len(parts) else "")
                current_sentence += segment

                if i + 1 < len(parts) - 1:  # 还有更多内容
                    # 计算这个句子的大致时间
                    sent_chars = len(current_sentence)
                    ratio = sent_chars / total_chars if total_chars > 0 else 0
                    sent_end = start + duration * (char_pos + sent_chars) / total_chars
                    sent_start = start + duration * char_pos / total_chars

                    s = current_sentence.strip()
                    if s and len(s) > 1:
                        sentences.append(TimedSentence(
                            text=s,
                            start_seconds=sent_start,
                            end_seconds=sent_end,
                        ))
                    char_pos += sent_chars
                    current_sentence = ""

            # 最后一个片段
            if i + 2 < len(parts):
                remaining = parts[i + 2]
                current_sentence += remaining

            if current_sentence.strip() and len(current_sentence.strip()) > 1:
                sent_start = start + duration * char_pos / total_chars
                sentences.append(TimedSentence(
                    text=current_sentence.strip(),
                    start_seconds=sent_start,
                    end_seconds=end,
                ))

    return sentences


def format_timestamp(seconds: float) -> str:
    """格式化秒数为 MM:SS 格式。"""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def parse_text(text: str, interval: float = 5.0) -> ParsedSubtitle:
    """从纯文本解析字幕（无时间戳时使用）。

    按句子边界切分，自动分配假时间戳。

    Args:
        text: 纯文本字幕内容。
        interval: 每句分配的假时间间隔（秒）。

    Returns:
        ParsedSubtitle: 解析结果。
    """
    # 清洗
    for pattern, replacement in CLEANUP_PATTERNS:
        text = re.sub(pattern, replacement, text)
    text = text.strip()

    if not text:
        return ParsedSubtitle()

    # 按句子边界切分
    raw_sentences = re.split(r"(?<=[.!?])\s+", text)

    sentences = []
    full_parts = []

    for i, raw in enumerate(raw_sentences):
        s = raw.strip()
        if not s or len(s) < 2:
            continue
        sentences.append(TimedSentence(
            text=s,
            start_seconds=i * interval,
            end_seconds=(i + 1) * interval - 0.5,
        ))
        full_parts.append(s)

    return ParsedSubtitle(
        sentences=sentences,
        full_text=" ".join(full_parts),
    )


def parse_file(file_path: Path) -> ParsedSubtitle:
    """自动检测文件格式并解析。

    Args:
        file_path: 字幕文件路径 (.srt 或 .txt)。

    Returns:
        ParsedSubtitle: 解析结果。
    """
    suffix = file_path.suffix.lower()

    if suffix == ".srt":
        return parse_srt(file_path)
    else:
        text = file_path.read_text(encoding="utf-8")
        return parse_text(text)
