"""AI 意群分块 prompt 模板。

把全文切成若干个「意群块」（chunk）—— 每个块是有完整独立含义的语义单元，
方便逐块背诵、积木式串联。要求 DeepSeek 以结构化 JSON 返回：
  - chunks: 每块原文 + 背诵提示关键词
  - advice: 针对这份材料的背诵建议
"""

_SOURCE_LABELS = {
    "article": "文章",
    "blog": "博客",
    "speech": "演讲稿",
    "subtitle": "字幕文本",
}


def build_chunk_prompt(
    full_text: str,
    title: str = "",
    language: str = "en",
    source_type: str = "article",
) -> str:
    """构建意群分块 prompt。

    Args:
        full_text: 材料全文（段落以空行分隔）。
        title: 材料标题。
        language: "zh" | "en"，决定分块尺寸与提示词语言。
        source_type: "article" | "blog" | "speech" | "subtitle"。
    """
    title_line = f'\n标题: "{title}"\n' if title else ""
    source_label = _SOURCE_LABELS.get(source_type, source_type)
    lang_label = "中文" if language == "zh" else "英文"
    size_rule, hint_rule = _size_rules(language)
    advice_rule = _advice_rule(language)

    return f"""你是一名资深的语言教师与记忆训练专家，擅长把文本切成最适合背诵的「意群块」。
请阅读下面的材料，把它切分成若干个意群块（chunk）。

材料类型: {source_label}
材料语言: {lang_label}
{title_line}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{full_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

请严格按照下面的 JSON 结构返回，不要输出任何 JSON 之外的内容，不要用 markdown 代码块包裹。

{{
  "title_suggested": "为这份背诵材料起的标题（若材料本身有清晰标题则原样返回）",
  "chunks": [
    {{
      "text": "第 1 块原文（逐字保留原文，含标点）",
      "hint": "这一块的背诵提示关键词"
    }}
  ],
  "advice": "针对这份材料的背诵建议（1-3 句）"
}}

━━━━━━━━━━━━━━━━━━━━━━━━━
意群分块规则（请严格遵守）:
━━━━━━━━━━━━━━━━━━━━━━━━━

1. 意群块 = 有独立完整含义的语义单元。{size_rule}
2. 全文必须完整覆盖：块与块首尾相接、顺序不变，不得增删改原文任何一个字或标点。
3. 不要机械地按句号切分：一句话若语义完整可单独成块，一个长句若跨两个意思可拆成两半块，但每块内部要能独立成诵、逻辑自洽。
4. 块的数量：视材料长度而定，通常 8-30 块。太短的材料可以少于 8 块，超长材料不超过 30 块。宁可块数少而每块完整，不要切得稀碎。
5. {hint_rule}

{advice_rule}"""


def _size_rules(language: str) -> tuple[str, str]:
    """返回分块尺寸规则与提示词规则。"""
    if language == "zh":
        return (
            "每块通常 2-4 句、40-100 字，不超过 120 字。",
            "hint 用中文短语（1-6 个字），是这一块的核心意思或关键词，用于触发回忆。",
        )
    return (
        "Each chunk is usually 2-4 sentences, 25-70 words, up to ~90 words.",
        "hint should be a short English phrase (1-5 words) capturing the chunk's core idea, used as a recall trigger.",
    )


def _advice_rule(language: str) -> str:
    """返回背诵建议的要求。"""
    if language == "zh":
        return (
            "6. advice 用中文写：指出这块材料背起来容易卡壳的地方（如超长句、生僻词、并列结构），"
            "并给 1-3 句实用的背诵建议（如：把第 3 块拆成两句先背、用第 5 块的提示词做联想）。"
        )
    return (
        "6. advice: write in English, pointing out where this material is likely to trip you up "
        "(long sentences, tricky words, parallel structures) and give 1-3 practical recitation tips "
        "(e.g. split chunk 3 into two breaths, use chunk 5's keyword as a memory anchor)."
    )
