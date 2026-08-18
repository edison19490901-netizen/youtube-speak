"""艾宾浩斯复习计划器 —— 纯确定性计算，不调用 AI。

为意群块生成两套计划：
  1. 逐块复习表：每块在「背诵日」后的第 1/2/4/7/15 天复习（间隔可配）。
  2. 每日清单：每天「新背哪几块 + 复习哪几块」，支持打卡。

日期以「开始背诵日」为第 1 天；未指定时默认今天。
"""

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

# 经典艾宾浩斯复习间隔（天）
DEFAULT_INTERVALS = (1, 2, 4, 7, 15)


@dataclass
class ChunkSchedule:
    index: int            # 1 起
    learn_day: int
    learn_date: str       # YYYY-MM-DD
    review_days: list[int] = field(default_factory=list)
    review_dates: list[str] = field(default_factory=list)


@dataclass
class DayPlan:
    day: int
    date: str
    learn: list[int] = field(default_factory=list)    # 当天新背的块（1 起）
    review: list[int] = field(default_factory=list)   # 当天复习的块（1 起）


@dataclass
class Schedule:
    intervals: tuple[int, ...] = DEFAULT_INTERVALS
    chunks_per_day: int = 2
    total_days: int = 0
    start_date: str = ""
    chunks: list[ChunkSchedule] = field(default_factory=list)
    daily: list[DayPlan] = field(default_factory=list)

    @property
    def review_milestones(self) -> int:
        """每个块总共复习的次数（= 间隔数）。"""
        return len(self.intervals)


def default_chunks_per_day(chunk_count: int) -> int:
    """按块数自动确定每天新背的块数：块多则每天多背一些。"""
    if chunk_count <= 0:
        return 2
    return min(4, max(2, math.ceil(chunk_count / 7)))


def build_schedule(
    chunk_count: int,
    start_date: date | None = None,
    intervals: tuple[int, ...] = DEFAULT_INTERVALS,
    chunks_per_day: int | None = None,
) -> Schedule:
    """构建完整的艾宾浩斯背诵计划。

    Args:
        chunk_count: 意群块总数。
        start_date: 开始背诵日（第 1 天），默认今天。
        intervals: 复习间隔天数，如 (1, 2, 4, 7, 15)。
        chunks_per_day: 每天新背块数，默认按块数自动确定。

    Returns:
        Schedule: 逐块复习表 + 每日清单。
    """
    if start_date is None:
        start_date = date.today()
    cpd = chunks_per_day or default_chunks_per_day(chunk_count)

    # 逐块：学习日 + 复习日
    chunk_schedules: list[ChunkSchedule] = []
    max_day = 0
    for i in range(chunk_count):
        learn_day = i // cpd + 1
        review_days = [learn_day + d for d in intervals]
        max_day = max(max_day, learn_day, *review_days)
        chunk_schedules.append(ChunkSchedule(
            index=i + 1,
            learn_day=learn_day,
            learn_date=_iso(start_date + timedelta(days=learn_day - 1)),
            review_days=list(review_days),
            review_dates=[_iso(start_date + timedelta(days=d - 1)) for d in review_days],
        ))

    # 每日清单
    daily: list[DayPlan] = []
    for day in range(1, max_day + 1):
        d = _iso(start_date + timedelta(days=day - 1))
        daily.append(DayPlan(
            day=day,
            date=d,
            learn=[cs.index for cs in chunk_schedules if cs.learn_day == day],
            review=[cs.index for cs in chunk_schedules if day in cs.review_days],
        ))

    return Schedule(
        intervals=tuple(intervals),
        chunks_per_day=cpd,
        total_days=max_day,
        start_date=_iso(start_date),
        chunks=chunk_schedules,
        daily=daily,
    )


def _iso(d: date) -> str:
    return d.isoformat()
