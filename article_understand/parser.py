"""文本解析与清洗模块。

支持：
  - SRT 字幕文件解析（保留时间轴）
  - 纯文本文章/博客解析（保留段落结构）
  - 中英文句边界切分
  - 材料语言检测（zh / en）
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

# 句结束标点：英文 + 中文
_SENTENCE_END = ".!?。！？；"


@dataclass
class TimedSentence:
    """带时间戳的单句。"""

    text: str
    start_seconds: float
    end_seconds: float


@dataclass
class ParsedSubtitle:
    """解析后的文本结果。"""

    sentences: list[TimedSentence] = field(default_factory=list)
    full_text: str = ""  # 纯文本全文（文章保留段落 \n\n，字幕用空格连接）

    @property
    def word_count(self) -> int:
        return count_words(self.full_text)

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


# ── 字数统计与语言检测 ──────────────────────────────

_CJK_RANGES = [
    (0x4E00, 0x9FFF),  # CJK 统一表意文字
    (0x3400, 0x4DBF),  # 扩展 A
    (0xF900, 0xFAFF),  # 兼容表意文字
    (0x3000, 0x303F),  # CJK 标点（。等）
]


def count_words(text: str) -> int:
    """统计字数：英文按空格分词，中文按字计数。"""
    cjk_count = 0
    latin_tokens = 0
    token: list[str] = []
    for ch in text:
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in _CJK_RANGES):
            cjk_count += 1
        elif ch.isalnum():
            token.append(ch)
        else:
            if token:
                latin_tokens += 1
                token = []
    if token:
        latin_tokens += 1
    return cjk_count + latin_tokens


def detect_language(text: str) -> str:
    """粗略判断材料语言: "zh" | "en"。

    按 CJK 字符在有效字符（CJK + 拉丁字母）中的占比判断，
    占比 > 0.3 判定为中文材料，否则为英文材料。
    """
    cjk = 0
    latin = 0
    for ch in text:
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in _CJK_RANGES):
            cjk += 1
        elif ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
            latin += 1
    total = cjk + latin
    if total == 0:
        return "en"
    return "zh" if (cjk / total) > 0.3 else "en"


# ── SRT 解析 ──────────────────────────────────────


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
    lang = detect_language(" ".join(s.text for s in sentences[:50]))
    sep = "" if lang == "zh" else " "
    full_text = sep.join(s.text for s in sentences)

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
    """按句子边界（中英文句号、问号、感叹号、分号）切分字幕条目。

    保持大致的时间戳：如果一条字幕包含多个句子，
    按字符比例分配时间。
    """
    sentences = []
    # 句子结束标记: 英文 .!? 或中文 。！？； 后跟空格或结束
    sentence_end_re = re.compile(r"([.!?。！？；])\s*")

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

            i = 0
            while i < len(parts) - 1:
                segment = parts[i] + parts[i + 1]
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
                i += 2

            # 最后一个片段（无尾标点的残留文本）
            if i < len(parts):
                current_sentence += parts[i]

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


# ── 纯文本解析 ────────────────────────────────────


def parse_article(text: str) -> ParsedSubtitle:
    """从纯文本解析文章/博客，保留段落结构。

    段落（空行分隔）在 full_text 中以 `\n\n` 保留，
    供 AI 解构文章结构使用。

    Args:
        text: 文章正文。

    Returns:
        ParsedSubtitle: 解析结果。
    """
    # 清洗
    for pattern, replacement in CLEANUP_PATTERNS:
        text = re.sub(pattern, replacement, text)
    text = text.strip()

    if not text:
        return ParsedSubtitle()

    # 规范段落: 空行分隔
    paragraphs = re.split(r"\n\s*\n", text)
    paragraphs = [re.sub(r"\s*\n\s*", " ", p).strip() for p in paragraphs]
    paragraphs = [p for p in paragraphs if p]

    if not paragraphs:
        return ParsedSubtitle()

    full_text = "\n\n".join(paragraphs)

    sentences = []
    for i, para in enumerate(paragraphs):
        for s in re.split(r"(?<=[.!?。！？；])\s*", para):
            s = s.strip()
            if s and len(s) > 1:
                sentences.append(TimedSentence(
                    text=s,
                    start_seconds=i * 5.0,
                    end_seconds=(i + 1) * 5.0 - 0.5,
                ))

    return ParsedSubtitle(sentences=sentences, full_text=full_text)


def parse_text(text: str, interval: float = 5.0) -> ParsedSubtitle:
    """从纯文本解析（无时间戳时使用）。

    按句子边界切分，自动分配假时间戳。句子间用空格连接。
    兼容旧接口；文章类文本请使用 :func:`parse_article`。

    Args:
        text: 纯文本内容。
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
    raw_sentences = re.split(r"(?<=[.!?。！？；])\s*", text)

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
        file_path: 文件路径（.srt / .txt / .md / .rtf / .docx / .pdf）。

    Returns:
        ParsedSubtitle: 解析结果。

    Raises:
        ValueError: 文件中没有可解析的文本时。
        RuntimeError: 缺少解析 .docx/.pdf 所需的依赖时。
    """
    suffix = file_path.suffix.lower()

    if suffix == ".srt":
        return parse_srt(file_path)
    elif suffix == ".docx":
        text = parse_docx(file_path)
    elif suffix == ".pdf":
        text = parse_pdf(file_path)
    elif suffix == ".rtf":
        text = _strip_rtf(_read_text(file_path))
    else:  # .txt / .md 等纯文本
        text = _read_text(file_path)

    if not text or not text.strip():
        raise ValueError(f"文件 {file_path.name} 中没有可解析的文本内容。")
    return parse_article(text)


def _read_text(path: Path) -> str:
    """读取文本文件，自动尝试 UTF-8，失败则回退到 GBK（兼容中文文档）。"""
    for enc in ("utf-8", "gbk"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def parse_docx(path: Path) -> str:
    """用 python-docx 提取 Word 文档的段落文本（段落间以空行分隔）。"""
    try:
        from docx import Document
    except ImportError:
        raise RuntimeError(
            "缺少 python-docx 依赖，无法解析 .docx。\n"
            "请先执行: pip install python-docx"
        )

    doc = Document(str(path))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def parse_pdf(path: Path) -> str:
    """用 pypdf 提取 PDF 文档的文本（按页，页间以空行分隔）。"""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError(
            "缺少 pypdf 依赖，无法解析 .pdf。\n"
            "请先执行: pip install pypdf"
        )

    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(text)
    return "\n\n".join(pages)


def _strip_rtf(text: str) -> str:
    """简易 RTF → 纯文本：段落/换行标记转成换行，去掉控制字与花括号。"""
    # 段落、换行、制表标记 → 换行
    text = re.sub(r"\\(?:par|line|sect|tab)\b", "\n", text)
    # 去掉控制字（\word 与 \'hh 转义）
    text = re.sub(r"\\(?:'[0-9a-fA-F]{2}|[a-zA-Z]+(?:-?\d+)?)", "", text)
    # 去掉成对花括号
    text = text.replace("{", "").replace("}", "")
    return text
