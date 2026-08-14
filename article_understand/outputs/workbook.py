"""交互式解读看板 HTML 生成器。

将解读结果渲染为可交互的单页 HTML 看板，纯浏览器打开即可阅读。
"""

import re
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from ..analyzer import AnalysisResult
from ..downloader import SubtitleInfo
from ..parser import ParsedSubtitle
from ..utils import format_duration

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

_LANG_LABELS = {"zh": "中文", "en": "English"}
_SOURCE_LABELS = {"article": "文章", "blog": "博客", "subtitle": "字幕"}


def generate(
    analysis: AnalysisResult,
    subtitle_info: SubtitleInfo,
    parsed: ParsedSubtitle,
    output_path: Path,
) -> Path:
    """生成交互式解读看板 HTML。

    Args:
        analysis: AI 解读结果。
        subtitle_info: 材料来源信息。
        parsed: 解析后的文本。
        output_path: 输出文件路径 (.html)。

    Returns:
        生成的 HTML 文件路径。
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=True,
    )
    template = env.get_template("article.html.j2")

    duration_str = format_duration(subtitle_info.duration_seconds)
    if subtitle_info.subtitle_type != "subtitle":
        duration_str = ""  # 文章/博客不显示（无实际时长）
    lang = analysis.meta.language

    spoken = analysis.spoken_summary
    decon = analysis.deconstruction
    practical = analysis.practical_application
    gw = analysis.golden_words

    context = {
        "title": subtitle_info.video_title,
        "uploader": subtitle_info.uploader,
        "duration": duration_str,
        "date": date.today().isoformat(),
        "source_type": subtitle_info.subtitle_type,
        "lang_label": _LANG_LABELS.get(lang, lang),
        "source_label": _SOURCE_LABELS.get(subtitle_info.subtitle_type, subtitle_info.subtitle_type),
        "truncated": analysis.meta.truncated,
        # 口播总结
        "summary_zh_points": _points(spoken.summary_zh) if spoken else [],
        "summary_en_points": _points(spoken.summary_en) if spoken else [],
        "script_zh": _clean_list(spoken.script_zh) if spoken else [],
        "script_en": _clean_list(spoken.script_en) if spoken else [],
        # 解构
        "overview": decon.overview if decon else "",
        "sections": [
            {
                "title": s.title,
                "role": s.role,
                "argument": s.argument,
                "evidence": s.evidence,
                "technique": s.technique,
            }
            for s in (decon.sections if decon else [])
        ],
        "writing_techniques": [
            {
                "name": t.name,
                "example": t.example,
                "effect": t.effect,
            }
            for t in (decon.writing_techniques if decon else [])
        ],
        # 实际应用
        "actionable_skills": [
            {
                "skill": s.skill,
                "how_to_apply": s.how_to_apply,
                "example": s.example,
            }
            for s in (practical.actionable_skills if practical else [])
        ],
        "thinking_models": [
            {
                "model": m.model,
                "explanation": m.explanation,
                "how_to_use": m.how_to_use,
            }
            for m in (practical.thinking_models if practical else [])
        ],
        # 金句单词
        "golden_sentences": [
            {
                "sentence": g.sentence,
                "why_good": g.why_good,
                "chinese_meaning": g.chinese_meaning,
            }
            for g in (gw.golden_sentences if gw else [])
        ],
        "vocabulary": [
            {
                "word": v.word,
                "context_sentence": v.context_sentence,
                "difficulty": v.difficulty,
                "chinese_note": v.chinese_note,
            }
            for v in (gw.vocabulary if gw else [])
        ],
        # 统计
        "word_count": parsed.word_count,
        "section_count": len(decon.sections) if decon else 0,
        "technique_count": len(decon.writing_techniques) if decon else 0,
        "skill_count": len(practical.actionable_skills) if practical else 0,
        "model_count": len(practical.thinking_models) if practical else 0,
        "golden_count": len(gw.golden_sentences) if gw else 0,
        "vocab_count": len(gw.vocabulary) if gw else 0,
        "usage": {
            "prompt_tokens": analysis.usage.prompt_tokens if analysis.usage else 0,
            "completion_tokens": analysis.usage.completion_tokens if analysis.usage else 0,
            "total_tokens": analysis.usage.total_tokens if analysis.usage else 0,
            "cost_cny": analysis.usage.cost_cny if analysis.usage else 0,
        },
    }

    rendered = template.render(**context)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    return output_path


# ── 渲染辅助 ────────────────────────────────────

_BULLET_RE = re.compile(r"^[-*•▪●]+\s*")


def _points(text: str) -> list[str]:
    """把摘要文本拆成干净的要点列表（去掉序号/星号前缀）。"""
    if not text:
        return []
    points = []
    for line in text.splitlines():
        line = _BULLET_RE.sub("", line.strip())
        line = re.sub(r"^\d+[\.、．]?\s*", "", line)
        if line:
            points.append(line)
    return points


def _clean_list(items: list[str]) -> list[str]:
    """去掉口播稿段落首尾空白。"""
    return [i.strip() for i in items if i and i.strip()]
