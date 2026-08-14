"""AI 分析 prompt 模板。

将四个解读模块合并为一个 prompt，要求 DeepSeek 以结构化 JSON 返回：
  - 口播总结（结构化摘要 + 口播稿，中英各一份）
  - 解构材料（文章结构、每部分论点论据、写作技巧）
  - 实际应用（可操作技能 + 思维模型）
  - 金句和单词（仅英文材料）
"""

_SOURCE_LABELS = {
    "article": "文章",
    "blog": "博客",
    "subtitle": "字幕文本",
}


def build_analysis_prompt(
    full_text: str,
    title: str = "",
    source_type: str = "article",
    language: str = "en",
) -> str:
    """构建完整的分析 prompt。

    Args:
        full_text: 材料全文（文章段落以空行分隔）。
        title: 材料标题。
        source_type: "article" | "blog" | "subtitle"。
        language: "zh" | "en"（用于决定是否生成金句单词）。
    """
    title_line = f'\n标题: "{title}"\n' if title else ""
    source_label = _SOURCE_LABELS.get(source_type, source_type)
    lang_label = "中文材料" if language == "zh" else "英文材料"
    golden_json, golden_rules = _golden_words_json(language)

    return f"""你是一名资深的文章分析师与写作教练，善于拆解文章结构、提炼可迁移的方法论。
请仔细阅读下面的材料，并产出完整的深度解读。

材料类型: {source_label}
材料语言: {lang_label}
{title_line}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{full_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

请严格按照下面的 JSON 结构返回。不要输出任何 JSON 之外的内容，不要用 markdown 代码块包裹。

{{
  "spoken_summary": {{
    "summary_zh": "中文结构化摘要（4-6 条要点，每条独立一行，用换行分隔，不要加序号或星号）",
    "summary_en": "English structured summary (4-6 bullet points, one per line, no numbering)",
    "script_zh": ["中文口播稿第 1 段", "第 2 段", "……（4-6 段）"],
    "script_en": ["English script paragraph 1", "……（4-6 段）"]
  }},
  "deconstruction": {{
    "overview": "对整篇文章写法的总览（结构、主线、风格，80-150 字）",
    "sections": [
      {{
        "title": "该部分简短标题",
        "role": "在文章中的作用（引入/提出论点/论证/例证/转折/结论）",
        "argument": "该部分的核心论点",
        "evidence": "支撑该论点的论据（数据/例子/引用/逻辑推演）",
        "technique": "该部分使用的写作技巧"
      }}
    ],
    "writing_techniques": [
      {{
        "name": "技巧名",
        "example": "从原文摘录一个体现该技巧的例子",
        "effect": "这个技巧达到的效果"
      }}
    ]
  }},
  "practical_application": {{
    "actionable_skills": [
      {{
        "skill": "可操作技能/方法名",
        "how_to_apply": "如何应用（怎么做，具体一点）",
        "example": "一个具体的使用步骤或例子"
      }}
    ],
    "thinking_models": [
      {{
        "model": "思维模型/可迁移的思考能力",
        "explanation": "这个思维方式的解释",
        "how_to_use": "什么场景下使用、怎么用"
      }}
    ]
  }}{golden_json}
}}

━━━━━━━━━━━━━━━━━━━━━━━━━
具体要求（请严格遵守）:
━━━━━━━━━━━━━━━━━━━━━━━━━

1. spoken_summary —— 口播总结:
   - summary_zh / summary_en: 各写 4-6 条结构化要点，概括材料核心内容。
     每条要点单独一行，不要加序号、编号或星号前缀。
   - script_zh: 中文口播稿，面向「照着朗读录音」的读者。共 4-6 段，每段 2-3 句，
     口语化、节奏自然、按自然停顿分段。第 1 段开场（点出主题 + 为什么值得听），
     中间段按材料主线展开，最后一段收尾（总结要点 + 抛给听众）。每段是一个数组元素。
   - script_en: 同样的英文口播稿，不要逐字翻译，按英文口语习惯重写，同样 4-6 段。

2. deconstruction —— 解构材料（文章是怎么写的）:
   - overview: 用中文概括整篇文章的写法（结构骨架、叙事主线、整体风格）。
   - sections: 按材料的实际结构划分，通常 4-8 个部分。每部分给出:
     * title: 简短标题
     * role: 该部分在全文中的作用（引入/提出论点/论证/例证/转折/结论）
     * argument: 该部分的核心论点
     * evidence: 支撑论据（数据、案例、引文、逻辑推演等）
     * technique: 使用的写作技巧（如设问、对比、讲故事、列数据、引权威、排比等）
   - writing_techniques: 提炼 3-6 个全文层面可借鉴的写作技巧，附原文例子。

3. practical_application —— 实际应用:
   - actionable_skills: 提取 3-5 个读者看完就能照着操作的技能/方法，
     例如「用黄金圈三步拆解一个决策」「把大目标拆成 30 天最小行动」。
     how_to_apply 说明具体做法，example 给出一个可执行步骤。
   - thinking_models: 提取 3-5 个可迁移的思维模型/认知能力，
     说明它是什么、什么时候用、怎么用。
   - 如果材料本身可操作性强，actionable_skills 要多；如果偏观点/认知，thinking_models 要多。

4. 通用规则:
   - 所有字段都必须填写，不能留空字符串或空数组。
   - context_sentence / example 等需要引原文的地方，必须从原文摘录，不要自己编。
   - 中文解释用口语化的表达，不要教科书腔。
   - 返回纯 JSON，不要用 ```json ``` 包裹。

{golden_rules}"""


def _golden_words_json(language: str) -> tuple[str, str]:
    """返回金句单词的 JSON 片段与使用规则。

    仅英文材料生成金句单词；中文材料返回空片段（保持 JSON 合法）。
    """
    if language == "zh":
        return "", ""

    golden_json = """
  ,
  "golden_words": {
    "golden_sentences": [
      {
        "sentence": "值得摘抄背诵的原文句子",
        "why_good": "为什么好（修辞、排比、用词、观点表达等）",
        "chinese_meaning": "中文释义"
      }
    ],
    "vocabulary": [
      {
        "word": "值得学习的单词或短语",
        "context_sentence": "该词在原文中出现的完整句子",
        "difficulty": "★☆☆ / ★★☆ / ★★★",
        "chinese_note": "中文释义 + 使用场景（简短）"
      }
    ]
  }"""

    golden_rules = """5. golden_words —— 金句和单词（仅英文材料）:
   - golden_sentences: 挑 6-10 句值得摘抄背诵的原文句子，说明好在哪
     （修辞、排比、用词精妙、观点表达有力等），并给出中文释义。
   - vocabulary: 挑 8-12 个值得学习的单词/短语，附原文语境句、难度分级、中文注释。
   - 难度分级参考: ★☆☆ = 基础但用法灵活, ★★☆ = 日常中等, ★★★ = 高级/俚语/熟语。
"""
    return golden_json, golden_rules
