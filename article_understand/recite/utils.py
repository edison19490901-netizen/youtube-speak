"""通用辅助函数。"""

import re
from datetime import date, datetime

_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def format_duration(seconds: int) -> str:
    """格式化秒数为 MM:SS 或 H:MM:SS。"""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def weekday_label(iso_date: str) -> str:
    """把 YYYY-MM-DD 转成中文星期。"""
    try:
        return _WEEKDAYS[datetime.strptime(iso_date, "%Y-%m-%d").weekday()]
    except Exception:
        return ""


def first_letter_hint(text: str, language: str) -> str:
    """生成背诵首字/首字母提示卡。

    英文：每个单词的首字母（大写，空格连接）。
    中文：按句读切分后每段的首字（连在一起）。
    """
    text = text.strip()
    if not text:
        return ""
    if language == "zh":
        segs = re.split(r"[，。！？、；：,.!?;:\s]+", text)
        return "".join(s[0] for s in segs if s)
    tokens = re.findall(r"[A-Za-z']+", text)
    return " ".join(t[0].upper() for t in tokens)


def estimate_recite_minutes(word_count: int, language: str) -> int:
    """估算全文背诵一遍所需分钟数。"""
    rate = 120 if language == "zh" else 90   # 中文字/分，英文词/分
    if word_count <= 0:
        return 0
    minutes = word_count / rate
    # 背诵节奏更慢，向上取整并至少 1 分钟
    return max(1, int(minutes // 1) + (1 if minutes % 1 > 0 else 0))


def today_iso() -> str:
    return date.today().isoformat()
