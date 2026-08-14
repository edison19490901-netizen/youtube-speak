"""AI 分析模块 —— DeepSeek API 调用。

将材料全文发送到 DeepSeek API，一次调用完成全部解读任务：
  - spoken_summary:   口播总结（结构化摘要 + 口播稿，中英各一份）
  - deconstruction:   解构材料（结构总览、每部分论点论据、写作技巧）
  - practical_application: 实际应用（可操作技能 + 思维模型）
  - golden_words:     金句和单词（仅英文材料）

返回结构化 JSON，由 Output 模块消费。
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI

from .prompts import build_analysis_prompt

# 送入模型的全文字数上限（超出从最近段落边界截断，避免触发上下文/输出截断）
MAX_FULL_TEXT_CHARS = 60000


# ── 数据结构 ─────────────────────────────────────


@dataclass
class Meta:
    language: str = "en"        # "zh" | "en"
    source_type: str = "article"  # "article" | "blog" | "subtitle"
    title: str = ""
    truncated: bool = False


@dataclass
class SpokenSummary:
    summary_zh: str = ""
    summary_en: str = ""
    script_zh: list[str] = field(default_factory=list)
    script_en: list[str] = field(default_factory=list)


@dataclass
class Section:
    title: str = ""
    role: str = ""
    argument: str = ""
    evidence: str = ""
    technique: str = ""


@dataclass
class WritingTechnique:
    name: str = ""
    example: str = ""
    effect: str = ""


@dataclass
class Deconstruction:
    overview: str = ""
    sections: list[Section] = field(default_factory=list)
    writing_techniques: list[WritingTechnique] = field(default_factory=list)


@dataclass
class ActionableSkill:
    skill: str = ""
    how_to_apply: str = ""
    example: str = ""


@dataclass
class ThinkingModel:
    model: str = ""
    explanation: str = ""
    how_to_use: str = ""


@dataclass
class PracticalApplication:
    actionable_skills: list[ActionableSkill] = field(default_factory=list)
    thinking_models: list[ThinkingModel] = field(default_factory=list)


@dataclass
class GoldenSentence:
    sentence: str = ""
    why_good: str = ""
    chinese_meaning: str = ""


@dataclass
class VocabularyItem:
    word: str = ""
    context_sentence: str = ""
    difficulty: str = "★★☆"
    chinese_note: str = ""


@dataclass
class GoldenWords:
    golden_sentences: list[GoldenSentence] = field(default_factory=list)
    vocabulary: list[VocabularyItem] = field(default_factory=list)


@dataclass
class UsageInfo:
    """API 调用用量与费用。"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_cny: float = 0.0


@dataclass
class AnalysisResult:
    """完整的解读结果。"""

    meta: Meta = field(default_factory=Meta)
    spoken_summary: SpokenSummary | None = None
    deconstruction: Deconstruction | None = None
    practical_application: PracticalApplication | None = None
    golden_words: GoldenWords | None = None
    usage: UsageInfo | None = None


# ── 主入口 ───────────────────────────────────────


def analyze(
    full_text: str,
    title: str = "",
    source_type: str = "article",
    language: str = "en",
    api_key: str | None = None,
    model: str = "deepseek-chat",
) -> AnalysisResult:
    """调用 DeepSeek API 解读材料。

    Args:
        full_text: 材料全文（文章段落以空行分隔）。
        title: 材料标题。
        source_type: "article" | "blog" | "subtitle"。
        language: 材料语言 "zh" | "en"（决定是否生成金句单词）。
        api_key: DeepSeek API key，默认从 DEEPSEEK_API_KEY 环境变量读取。
        model: 模型名称。

    Returns:
        AnalysisResult: 结构化的解读结果。

    Raises:
        ValueError: 未配置 API key 时。
        RuntimeError: API 返回空内容或输出被截断时。
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

    # 超长文本截断（保留段落边界）
    text_for_model, truncated = _cap_text(full_text)
    prompt = build_analysis_prompt(
        text_for_model,
        title=title,
        source_type=source_type,
        language=language,
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一名资深的文章分析师与写作教练，擅长拆解文章结构、"
                    "提炼可迁移的方法论。请严格按照要求的 JSON 格式输出，"
                    "不要输出任何 JSON 之外的内容。确保 JSON 完整闭合，"
                    "所有字符串都要正确转义。"
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
            "DeepSeek API 输出被截断 (finish_reason=length)。\n"
            "材料可能过长或内容过复杂，请尝试更短的材料。"
        )

    result = _parse_response(raw)
    result.meta.language = language
    result.meta.source_type = source_type
    result.meta.title = title
    result.meta.truncated = truncated

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


def _cap_text(full_text: str) -> tuple[str, bool]:
    """超长文本从最近段落边界截断。"""
    if len(full_text) <= MAX_FULL_TEXT_CHARS:
        return full_text, False
    head = full_text[:MAX_FULL_TEXT_CHARS]
    idx = head.rfind("\n\n")
    if idx > MAX_FULL_TEXT_CHARS // 2:
        head = head[:idx]
    return head, True


# ── JSON 解析 ────────────────────────────────────


def _parse_response(raw: str) -> AnalysisResult:
    """解析 DeepSeek 返回的 JSON 为 AnalysisResult。"""
    text = raw.strip()

    # 去除可能的 markdown 代码块包裹
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()

    data = _safe_json_load(text)

    result = AnalysisResult()

    # ── spoken_summary ──
    ss = data.get("spoken_summary", {})
    if ss:
        result.spoken_summary = SpokenSummary(
            summary_zh=ss.get("summary_zh", ""),
            summary_en=ss.get("summary_en", ""),
            script_zh=_as_str_list(ss.get("script_zh", [])),
            script_en=_as_str_list(ss.get("script_en", [])),
        )

    # ── deconstruction ──
    de = data.get("deconstruction", {})
    if de:
        sections = []
        for s in de.get("sections", []):
            if isinstance(s, dict):
                sections.append(Section(
                    title=str(s.get("title", "")),
                    role=str(s.get("role", "")),
                    argument=str(s.get("argument", "")),
                    evidence=str(s.get("evidence", "")),
                    technique=str(s.get("technique", "")),
                ))
        techniques = []
        for t in de.get("writing_techniques", []):
            if isinstance(t, dict):
                techniques.append(WritingTechnique(
                    name=str(t.get("name", "")),
                    example=str(t.get("example", "")),
                    effect=str(t.get("effect", "")),
                ))
        result.deconstruction = Deconstruction(
            overview=str(de.get("overview", "")),
            sections=sections,
            writing_techniques=techniques,
        )

    # ── practical_application ──
    pa = data.get("practical_application", {})
    if pa:
        skills = []
        for s in pa.get("actionable_skills", []):
            if isinstance(s, dict):
                skills.append(ActionableSkill(
                    skill=str(s.get("skill", "")),
                    how_to_apply=str(s.get("how_to_apply", "")),
                    example=str(s.get("example", "")),
                ))
        models = []
        for m in pa.get("thinking_models", []):
            if isinstance(m, dict):
                models.append(ThinkingModel(
                    model=str(m.get("model", "")),
                    explanation=str(m.get("explanation", "")),
                    how_to_use=str(m.get("how_to_use", "")),
                ))
        result.practical_application = PracticalApplication(
            actionable_skills=skills,
            thinking_models=models,
        )

    # ── golden_words（仅英文材料可能返回）──
    gw = data.get("golden_words")
    if gw:
        sentences = []
        for s in gw.get("golden_sentences", []):
            if isinstance(s, dict):
                sentences.append(GoldenSentence(
                    sentence=str(s.get("sentence", "")),
                    why_good=str(s.get("why_good", "")),
                    chinese_meaning=str(s.get("chinese_meaning", "")),
                ))
        vocab = []
        for v in gw.get("vocabulary", []):
            if isinstance(v, dict):
                vocab.append(VocabularyItem(
                    word=str(v.get("word", "")),
                    context_sentence=str(v.get("context_sentence", "")),
                    difficulty=str(v.get("difficulty", "★★☆")),
                    chinese_note=str(v.get("chinese_note", "")),
                ))
        result.golden_words = GoldenWords(
            golden_sentences=sentences,
            vocabulary=vocab,
        )

    return result


def _as_str_list(value) -> list[str]:
    """把 AI 返回的脚本字段规范化为字符串列表。

    兼容 AI 把数组当字符串返回的情况（按空行/换行拆分）。
    """
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        parts = re.split(r"\n\s*\n|\n", value.strip())
        return [p.strip() for p in parts if p.strip()]
    return []


def _safe_json_load(text: str) -> dict:
    """安全解析 JSON，支持截断修复。"""
    # 先尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
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
    if start != -1:
        truncated = text[start:]
        for _ in range(10):
            try:
                return json.loads(truncated + "}")
            except json.JSONDecodeError:
                pass
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


# ── 序列化 / 反序列化 ─────────────────────────────


def save_analysis(result: AnalysisResult, output_path: Path) -> None:
    """将分析结果序列化保存为 JSON 文件。"""
    data = {
        "meta": {
            "language": result.meta.language,
            "source_type": result.meta.source_type,
            "title": result.meta.title,
            "truncated": result.meta.truncated,
        },
        "spoken_summary": {
            "summary_zh": result.spoken_summary.summary_zh if result.spoken_summary else "",
            "summary_en": result.spoken_summary.summary_en if result.spoken_summary else "",
            "script_zh": result.spoken_summary.script_zh if result.spoken_summary else [],
            "script_en": result.spoken_summary.script_en if result.spoken_summary else [],
        },
        "deconstruction": {
            "overview": result.deconstruction.overview if result.deconstruction else "",
            "sections": [
                {
                    "title": s.title,
                    "role": s.role,
                    "argument": s.argument,
                    "evidence": s.evidence,
                    "technique": s.technique,
                }
                for s in (result.deconstruction.sections if result.deconstruction else [])
            ],
            "writing_techniques": [
                {
                    "name": t.name,
                    "example": t.example,
                    "effect": t.effect,
                }
                for t in (result.deconstruction.writing_techniques if result.deconstruction else [])
            ],
        },
        "practical_application": {
            "actionable_skills": [
                {
                    "skill": s.skill,
                    "how_to_apply": s.how_to_apply,
                    "example": s.example,
                }
                for s in (result.practical_application.actionable_skills if result.practical_application else [])
            ],
            "thinking_models": [
                {
                    "model": m.model,
                    "explanation": m.explanation,
                    "how_to_use": m.how_to_use,
                }
                for m in (result.practical_application.thinking_models if result.practical_application else [])
            ],
        },
        "golden_words": None,
        "usage": {
            "prompt_tokens": result.usage.prompt_tokens if result.usage else 0,
            "completion_tokens": result.usage.completion_tokens if result.usage else 0,
            "total_tokens": result.usage.total_tokens if result.usage else 0,
            "cost_cny": result.usage.cost_cny if result.usage else 0,
        },
    }

    if result.golden_words is not None:
        data["golden_words"] = {
            "golden_sentences": [
                {
                    "sentence": g.sentence,
                    "why_good": g.why_good,
                    "chinese_meaning": g.chinese_meaning,
                }
                for g in result.golden_words.golden_sentences
            ],
            "vocabulary": [
                {
                    "word": v.word,
                    "context_sentence": v.context_sentence,
                    "difficulty": v.difficulty,
                    "chinese_note": v.chinese_note,
                }
                for v in result.golden_words.vocabulary
            ],
        }

    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_analysis(json_path: Path) -> AnalysisResult:
    """从 JSON 文件恢复 AnalysisResult。"""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    result = _parse_response(json.dumps(data, ensure_ascii=False))

    # 恢复 meta（_parse_response 只解析内容字段，meta 在此补全）
    meta = data.get("meta", {})
    result.meta.language = meta.get("language", "en")
    result.meta.source_type = meta.get("source_type", "article")
    result.meta.title = meta.get("title", "")
    result.meta.truncated = meta.get("truncated", False)

    usage = data.get("usage", {})
    if usage:
        result.usage = UsageInfo(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            cost_cny=usage.get("cost_cny", 0.0),
        )

    return result
