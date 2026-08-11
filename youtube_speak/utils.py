"""共享工具函数。"""


def format_duration(seconds: int) -> str:
    """格式化秒数为可读的时间字符串。

    >>> format_duration(3661)
    '1h 1m'
    >>> format_duration(125)
    '2m 5s'
    """
    if seconds <= 0:
        return "N/A"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h > 0:
        return f"{h}h {m}m"
    s = seconds % 60
    return f"{m}m {s}s"
