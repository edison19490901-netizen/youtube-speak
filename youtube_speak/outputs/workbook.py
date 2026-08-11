"""交互式 Workbook HTML 生成器。

将分析结果渲染为可交互的单页 HTML 学习看板。
纯浏览器打开，无需 PDF 依赖。
"""

from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from ..analyzer import AnalysisResult
from ..downloader import SubtitleInfo
from ..parser import ParsedSubtitle
from ..utils import format_duration

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def generate(
    analysis: AnalysisResult,
    subtitle_info: SubtitleInfo,
    parsed: ParsedSubtitle,
    output_path: Path,
) -> Path:
    """生成交互式 Workbook HTML。

    Args:
        analysis: AI 分析结果。
        subtitle_info: 字幕下载信息。
        parsed: 解析后的字幕。
        output_path: 输出文件路径 (.html)。

    Returns:
        生成的 HTML 文件路径。
    """
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("workbook.html.j2")

    duration_str = format_duration(subtitle_info.duration_seconds)

    rendered = template.render(
        title=subtitle_info.video_title,
        uploader=subtitle_info.uploader,
        duration=duration_str,
        date=date.today().isoformat(),
        subtitle_type=subtitle_info.subtitle_type,
        summary=_summary_dict(analysis),
        golden_sentences=[
            {
                "pattern": g.pattern,
                "example": g.example,
                "usage_scenario": g.usage_scenario,
                "chinese_explanation": g.chinese_explanation,
            }
            for g in analysis.golden_sentences
        ],
        vocabulary=[
            {
                "word": v.word,
                "context_sentence": v.context_sentence,
                "difficulty": v.difficulty,
                "chinese_note": v.chinese_note,
            }
            for v in analysis.vocabulary
        ],
        shadowing=[
            {
                "chunk_text": s.chunk_text,
                "pause_after": s.pause_after,
                "stress_hints": s.stress_hints,
            }
            for s in analysis.shadowing
        ],
        difficult_spots=[
            {
                "sentence": d.sentence,
                "difficulty_point": d.difficulty_point,
                "chinese_note": d.chinese_note,
            }
            for d in analysis.difficult_spots
        ],
        word_count=parsed.word_count,
        vocab_count=len(analysis.vocabulary),
        sentence_count=len(analysis.golden_sentences),
        shadow_count=len(analysis.shadowing),
        difficult_count=len(analysis.difficult_spots),
        usage={
            "prompt_tokens": analysis.usage.prompt_tokens if analysis.usage else 0,
            "completion_tokens": analysis.usage.completion_tokens if analysis.usage else 0,
            "total_tokens": analysis.usage.total_tokens if analysis.usage else 0,
            "cost_cny": analysis.usage.cost_cny if analysis.usage else 0,
        },
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    return output_path


def _summary_dict(analysis: AnalysisResult) -> dict:
    if analysis.summary is None:
        return {
            "summary_en": "",
            "summary_zh": "",
            "retelling_hints": [],
        }
    return {
        "summary_en": analysis.summary.summary_en,
        "summary_zh": analysis.summary.summary_zh,
        "retelling_hints": [
            {"hint": h.hint, "reference_answer": h.reference_answer}
            for h in analysis.summary.retelling_hints
        ],
    }
