"""AI 分析模块 —— DeepSeek API 调用。

将字幕文本发送到 DeepSeek API，一次调用完成全部 5 个分析任务：
  - vocabulary:   高频词汇/短语提取 + 难度分级
  - golden_sentences: 口语句型模板
  - summary:      内容摘要 + 复述要点
  - shadowing:    影子跟读分段文本
  - difficult_spots: 难点注释

返回结构化 JSON，由 Output 模块消费。
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI

from .prompts import build_analysis_prompt


@dataclass
class VocabularyItem:
    word: str
    context_sentence: str
    difficulty: str  # "★☆☆" | "★★☆" | "★★★"
    chinese_note: str


@dataclass
class GoldenSentence:
    pattern: str
    example: str
    usage_scenario: str
    chinese_explanation: str


@dataclass
class RetellingHint:
    hint: str
    reference_answer: str


@dataclass
class Summary:
    summary_en: str
    summary_zh: str
    retelling_hints: list[RetellingHint] = field(default_factory=list)


@dataclass
class ShadowingChunk:
    chunk_text: str
    pause_after: str  # "short" | "medium" | "long"
    stress_hints: str  # 重音/连读提示


@dataclass
class DifficultSpot:
    sentence: str
    difficulty_point: str
    chinese_note: str


@dataclass
class UsageInfo:
    """API 调用用量与费用。"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_cny: float = 0.0


@dataclass
class AnalysisResult:
    """完整的分析结果。"""

    vocabulary: list[VocabularyItem] = field(default_factory=list)
    golden_sentences: list[GoldenSentence] = field(default_factory=list)
    summary: Summary | None = None
    shadowing: list[ShadowingChunk] = field(default_factory=list)
    difficult_spots: list[DifficultSpot] = field(default_factory=list)
    usage: UsageInfo | None = None


def analyze(
    full_text: str,
    sentences: list,
    video_title: str = "",
    level: str = "beginner",
    api_key: str | None = None,
    model: str = "deepseek-chat",
) -> AnalysisResult:
    """调用 DeepSeek API 分析字幕文本。

    Args:
        full_text: 完整字幕文本。
        sentences: TimedSentence 列表。
        video_title: 视频标题，帮助 AI 理解上下文。
        level: 学习者水平 ("beginner" | "intermediate" | "advanced")。
        api_key: DeepSeek API key，默认从 DEEPSEEK_API_KEY 环境变量读取。
        model: 模型名称。

    Returns:
        AnalysisResult: 结构化的分析结果。
    """
    if api_key is None:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")

    if not api_key:
        raise ValueError(
            "请设置 DEEPSEEK_API_KEY 环境变量，或传入 api_key 参数。\n"
            "获取 Key: https://platform.deepseek.com/api_keys"
        )

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
    )

    prompt = build_analysis_prompt(full_text, video_title, level)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一名专业的英语口语教练，擅长帮助中文母语者学习英语口语。"
                    "你的任务是从英文对话文本中提炼出最有价值的学习材料。"
                    "请严格按照要求的 JSON 格式输出，不要输出任何 JSON 之外的内容。"
                    "确保 JSON 完整闭合，所有字符串都要正确转义。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=8192,
        response_format={"type": "json_object"},
    )

    finish = response.choices[0].finish_reason
    raw = response.choices[0].message.content
    if raw is None:
        raise RuntimeError("DeepSeek API 返回了空内容。")

    if finish == "length":
        raise RuntimeError(
            "DeepSeek API 输出被截断 (finish_reason=length)。"
            "字幕可能太长，请尝试更短的视频。"
        )

    result = _parse_response(raw)

    # 捕获用量并计算费用
    if response.usage:
        prompt_tokens = response.usage.prompt_tokens or 0
        completion_tokens = response.usage.completion_tokens or 0
        total_tokens = response.usage.total_tokens or 0
        # DeepSeek-chat: ¥1/1M input, ¥2/1M output
        cost_cny = (prompt_tokens / 1_000_000) * 1 + (completion_tokens / 1_000_000) * 2
        result.usage = UsageInfo(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_cny=round(cost_cny, 6),
        )

    return result


def _parse_response(raw: str) -> AnalysisResult:
    """解析 DeepSeek 返回的 JSON 为 AnalysisResult。"""
    # 保存原始响应（调试用）
    text = raw.strip()

    # 去除可能的 markdown 代码块包裹
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()

    data = _safe_json_load(text)

    result = AnalysisResult()

    # 解析 vocabulary
    for item in data.get("vocabulary", []):
        result.vocabulary.append(VocabularyItem(
            word=item.get("word", ""),
            context_sentence=item.get("context_sentence", ""),
            difficulty=item.get("difficulty", "★★☆"),
            chinese_note=item.get("chinese_note", ""),
        ))

    # 解析 golden_sentences
    for item in data.get("golden_sentences", []):
        result.golden_sentences.append(GoldenSentence(
            pattern=item.get("pattern", ""),
            example=item.get("example", ""),
            usage_scenario=item.get("usage_scenario", ""),
            chinese_explanation=item.get("chinese_explanation", ""),
        ))

    # 解析 summary
    summary_data = data.get("summary", {})
    if summary_data:
        hints_raw = summary_data.get("retelling_hints", [])
        hints = []
        for item in hints_raw:
            if isinstance(item, str):
                # 兼容旧格式：纯字符串
                hints.append(RetellingHint(hint=item, reference_answer=""))
            else:
                hints.append(RetellingHint(
                    hint=item.get("hint", ""),
                    reference_answer=item.get("reference_answer", ""),
                ))
        result.summary = Summary(
            summary_en=summary_data.get("summary_en", ""),
            summary_zh=summary_data.get("summary_zh", ""),
            retelling_hints=hints,
        )

    # 解析 shadowing
    for item in data.get("shadowing", []):
        result.shadowing.append(ShadowingChunk(
            chunk_text=item.get("chunk_text", ""),
            pause_after=item.get("pause_after", "short"),
            stress_hints=item.get("stress_hints", ""),
        ))

    # 解析 difficult_spots
    for item in data.get("difficult_spots", []):
        result.difficult_spots.append(DifficultSpot(
            sentence=item.get("sentence", ""),
            difficulty_point=item.get("difficulty_point", ""),
            chinese_note=item.get("chinese_note", ""),
        ))

    return result


def _safe_json_load(text: str) -> dict:
    """安全解析 JSON，支持截断修复。"""
    # 先尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        pass

    # 尝试找到 JSON 起止位置
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        truncated = text[start:end + 1]
        try:
            return json.loads(truncated)
        except json.JSONDecodeError:
            pass

    # 尝试修复未闭合的字符串和数组
    # 简单策略：在最后一个完整键值对后截断
    if start != -1:
        truncated = text[start:]
        # 尝试逐步缩短直到能解析
        for _ in range(10):
            try:
                return json.loads(truncated + "}")
            except json.JSONDecodeError:
                pass
            # 移除最后一个不完整的字段
            last_comma = truncated.rfind(',\n  "')
            if last_comma == -1:
                last_comma = truncated.rfind(',\n    "')
            if last_comma == -1:
                break
            truncated = truncated[:last_comma]

    raise RuntimeError(
        f"无法解析 API 返回的 JSON。\n"
        f"原始内容前 500 字符:\n{text[:500]}"
    )


def save_analysis(result: AnalysisResult, output_path: Path) -> None:
    """将分析结果序列化保存为 JSON 文件。"""
    data = {
        "vocabulary": [
            {
                "word": v.word,
                "context_sentence": v.context_sentence,
                "difficulty": v.difficulty,
                "chinese_note": v.chinese_note,
            }
            for v in result.vocabulary
        ],
        "golden_sentences": [
            {
                "pattern": g.pattern,
                "example": g.example,
                "usage_scenario": g.usage_scenario,
                "chinese_explanation": g.chinese_explanation,
            }
            for g in result.golden_sentences
        ],
        "summary": {
            "summary_en": result.summary.summary_en if result.summary else "",
            "summary_zh": result.summary.summary_zh if result.summary else "",
            "retelling_hints": [
                {"hint": h.hint, "reference_answer": h.reference_answer}
                for h in (result.summary.retelling_hints if result.summary else [])
            ],
        },
        "shadowing": [
            {
                "chunk_text": s.chunk_text,
                "pause_after": s.pause_after,
                "stress_hints": s.stress_hints,
            }
            for s in result.shadowing
        ],
        "difficult_spots": [
            {
                "sentence": d.sentence,
                "difficulty_point": d.difficulty_point,
                "chinese_note": d.chinese_note,
            }
            for d in result.difficult_spots
        ],
        "usage": {
            "prompt_tokens": result.usage.prompt_tokens if result.usage else 0,
            "completion_tokens": result.usage.completion_tokens if result.usage else 0,
            "total_tokens": result.usage.total_tokens if result.usage else 0,
            "cost_cny": result.usage.cost_cny if result.usage else 0,
        },
    }
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_analysis(json_path: Path) -> AnalysisResult:
    """从 JSON 文件恢复 AnalysisResult。"""
    return _parse_response(json_path.read_text(encoding="utf-8"))
