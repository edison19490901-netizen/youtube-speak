"""背诵看板 HTML 生成器。

将意群分块结果 + 艾宾浩斯计划渲染为交互式单页 HTML：
  - 原文分块（提示卡 / 首字提示 / 遮罩自测）
  - 逐块复习表
  - 每日打卡清单（localStorage 记忆）

`build_context` 生成模板上下文，供独立 recite.html 与「嵌入智读看板」两处共用。
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from ..analyzer import ReciteMaterial, UsageInfo
from ...parser import ParsedSubtitle
from ..planner import Schedule
from ..utils import (
    estimate_recite_minutes,
    first_letter_hint,
    today_iso,
    weekday_label,
)

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

_LANG_LABELS = {"zh": "中文", "en": "English"}
_SOURCE_LABELS = {
    "article": "文章",
    "blog": "博客",
    "speech": "演讲稿",
    "subtitle": "字幕",
}


def build_context(
    material: ReciteMaterial,
    meta: dict,
    parsed: ParsedSubtitle,
    schedule: Schedule,
    usage: UsageInfo | None,
) -> dict:
    """构建背诵看板的模板上下文（recite.html 与嵌入智读看板共用）。"""
    lang = material.language
    title = meta.get("title") or material.title_suggested or "未命名材料"
    chunk_count = len(material.chunks)
    word_count = parsed.word_count

    return {
        # 头部
        "title": title,
        "title_suggested": material.title_suggested,
        "lang_label": _LANG_LABELS.get(lang, lang),
        "lang": lang,
        "source_label": _SOURCE_LABELS.get(meta.get("source_type", "article"), meta.get("source_type", "article")),
        "date": today_iso(),
        "truncated": meta.get("truncated", False),
        "material_id": meta.get("material_id", "recite"),
        # 统计
        "word_count": word_count,
        "chunk_count": chunk_count,
        "est_minutes": estimate_recite_minutes(word_count, lang),
        # 分块
        "advice": material.advice,
        "chunks": [
            {
                "index": c.index,
                "text": c.text,
                "hint": c.hint,
                "first_hint": first_letter_hint(c.text, lang),
                "word_count": _chunk_size(c.text, lang),
            }
            for c in material.chunks
        ],
        # 计划
        "schedule": {
            "intervals": list(schedule.intervals),
            "chunks_per_day": schedule.chunks_per_day,
            "total_days": schedule.total_days,
            "start_date": schedule.start_date,
            "per_chunk": [
                {
                    "index": cs.index,
                    "learn_day": cs.learn_day,
                    "learn_date": cs.learn_date,
                    "learn_weekday": weekday_label(cs.learn_date),
                    "review_days": cs.review_days,
                    "review_dates": cs.review_dates,
                }
                for cs in schedule.chunks
            ],
            "daily": [
                {
                    "day": dp.day,
                    "date": dp.date,
                    "weekday": weekday_label(dp.date),
                    "learn": dp.learn,
                    "review": dp.review,
                }
                for dp in schedule.daily
            ],
        },
        # 用量
        "usage": {
            "prompt_tokens": usage.prompt_tokens if usage else 0,
            "completion_tokens": usage.completion_tokens if usage else 0,
            "total_tokens": usage.total_tokens if usage else 0,
            "cost_cny": usage.cost_cny if usage else 0.0,
        },
    }


def generate(
    material: ReciteMaterial,
    meta: dict,
    parsed: ParsedSubtitle,
    schedule: Schedule,
    usage: UsageInfo | None,
    output_path: Path,
) -> Path:
    """生成交互式背诵看板 HTML。

    Args:
        material: AI 意群分块结果。
        meta: 元信息 {title, language, source_type, truncated}。
        parsed: 解析后的原始文本（用于字数统计）。
        schedule: 艾宾浩斯计划。
        usage: API 用量与费用。
        output_path: 输出 .html 路径。

    Returns:
        生成的 HTML 文件路径。
    """
    output_path = Path(output_path)
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=True,
    )
    template = env.get_template("recite.html.j2")

    rendered = template.render(**build_context(material, meta, parsed, schedule, usage))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    return output_path


def _chunk_size(text: str, language: str) -> int:
    """统计单块的字数（中文按字、英文按词）。"""
    from ...parser import count_words

    return count_words(text)
