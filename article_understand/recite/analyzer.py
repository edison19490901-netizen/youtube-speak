"""AI 意群分块模块 —— DeepSeek API 调用。

将材料全文发送到 DeepSeek API，一次调用完成意群分块：
  - chunks: 每块原文 + 背诵提示关键词
  - advice: 背诵建议

返回结构化 ReciteMaterial，由 planner / output 模块消费。
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI

from .prompts import build_chunk_prompt

# 送入模型的全文字数上限（超出从最近段落边界截断，避免触发上下文/输出截断）
MAX_FULL_TEXT_CHARS = 60000


# ── 数据结构 ─────────────────────────────────────


@dataclass
class Chunk:
    index: int = 0       # 1 起
    text: str = ""
    hint: str = ""


@dataclass
class ReciteMaterial:
    title_suggested: str = ""
    chunks: list[Chunk] = field(default_factory=list)
    advice: str = ""
    language: str = "en"   # "zh" | "en"


@dataclass
class UsageInfo:
    """API 调用用量与费用。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_cny: float = 0.0


@dataclass
class AnalyzeResult:
    """分块结果 + 用量 + 是否截断。"""

    material: ReciteMaterial = field(default_factory=ReciteMaterial)
    usage: UsageInfo | None = None
    truncated: bool = False


# ── 主入口 ───────────────────────────────────────


def analyze(
    full_text: str,
    title: str = "",
    language: str = "en",
    source_type: str = "article",
    api_key: str | None = None,
    model: str = "deepseek-chat",
) -> ReciteMaterial:
    """调用 DeepSeek API 对材料做意群分块。

    Args:
        full_text: 材料全文（段落以空行分隔）。
        title: 材料标题。
        language: 材料语言 "zh" | "en"。
        source_type: "article" | "blog" | "speech" | "subtitle"。
        api_key: DeepSeek API key，默认从 DEEPSEEK_API_KEY 环境变量读取。
        model: 模型名称。

    Returns:
        AnalyzeResult: 结构化分块结果 + 用量 + 是否截断。

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
    prompt = build_chunk_prompt(
        text_for_model,
        title=title,
        language=language,
        source_type=source_type,
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一名资深的语言教师与记忆训练专家。请严格按照要求的 JSON 格式输出，"
                    "不要输出任何 JSON 之外的内容。确保 JSON 完整闭合，所有字符串都要正确转义。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=16384,
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
    result.language = language

    usage = None
    if response.usage:
        prompt_tokens = response.usage.prompt_tokens or 0
        completion_tokens = response.usage.completion_tokens or 0
        total_tokens = response.usage.total_tokens or 0
        # DeepSeek-chat: ¥1/1M input, ¥2/1M output
        cost_cny = (prompt_tokens / 1_000_000) * 1 + (completion_tokens / 1_000_000) * 2
        usage = UsageInfo(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_cny=round(cost_cny, 6),
        )

    return AnalyzeResult(material=result, usage=usage, truncated=truncated)


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


def _parse_response(raw: str) -> ReciteMaterial:
    """解析 DeepSeek 返回的 JSON 为 ReciteMaterial。"""
    text = raw.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()

    data = _safe_json_load(text)

    result = ReciteMaterial(
        title_suggested=str(data.get("title_suggested", "") or ""),
        advice=str(data.get("advice", "") or ""),
    )

    chunks = data.get("chunks", [])
    for i, c in enumerate(chunks, 1):
        if not isinstance(c, dict):
            continue
        text_c = str(c.get("text", "") or "").strip()
        if not text_c:
            continue
        result.chunks.append(Chunk(
            index=i,
            text=text_c,
            hint=str(c.get("hint", "") or "").strip(),
        ))

    return result


def _safe_json_load(text: str) -> dict:
    """安全解析 JSON，支持截断修复。"""
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


def save_material(
    material: ReciteMaterial,
    meta: dict,
    usage: UsageInfo | None,
    output_path: Path,
) -> None:
    """将分块结果 + 元信息 + 用量保存为 JSON 文件。"""
    data = {
        "meta": meta,
        "material": {
            "title_suggested": material.title_suggested,
            "language": material.language,
            "advice": material.advice,
            "chunks": [
                {
                    "index": c.index,
                    "text": c.text,
                    "hint": c.hint,
                }
                for c in material.chunks
            ],
        },
        "usage": {
            "prompt_tokens": usage.prompt_tokens if usage else 0,
            "completion_tokens": usage.completion_tokens if usage else 0,
            "total_tokens": usage.total_tokens if usage else 0,
            "cost_cny": usage.cost_cny if usage else 0.0,
        },
    }
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_material(json_path: Path) -> dict:
    """从 JSON 文件恢复 {meta, material, usage} 字典。"""
    return json.loads(json_path.read_text(encoding="utf-8"))
