"""AI 分析 prompt 模板。

将 5 个分析任务合并为一个 prompt，要求 DeepSeek 以结构化 JSON 返回。
"""


def build_analysis_prompt(
    full_text: str,
    video_title: str = "",
    level: str = "beginner",
) -> str:
    """构建完整的分析 prompt。

    Args:
        full_text: 完整字幕文本。
        video_title: 视频标题。
        level: 学习者水平。
    """
    level_guide = _level_guide(level)
    title_line = f'\n视频标题: "{video_title}"\n' if video_title else ""

    return f"""你是一名专业的英语口语教练。你的学生是中文母语者，英语水平为{level}。
请仔细分析以下英文访谈/对话字幕，提炼出最有价值的口语学习材料。
{title_line}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{full_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

请严格按照下面的 JSON 结构返回分析结果。不要输出任何 JSON 之外的内容，
不要用 markdown 代码块包裹。

{{
  "vocabulary": [
    {{
      "word": "值得学习的单词或短语（原文）",
      "context_sentence": "该词在字幕中出现的完整句子",
      "difficulty": "★☆☆ / ★★☆ / ★★★",
      "chinese_note": "中文释义 + 使用场景说明（简短）"
    }}
  ],
  "golden_sentences": [
    {{
      "pattern": "句型模板（用 ... 或 [sth] 表示可替换部分）",
      "example": "完整例句",
      "usage_scenario": "这个句型在什么场景下用（一句话概括）",
      "chinese_explanation": "中文解释这个句型的用法和语气"
    }}
  ],
  "summary": {{
    "summary_en": "150-200 词的英文内容摘要",
    "summary_zh": "100-150 字的中文内容摘要",
    "retelling_hints": [
      {{
        "hint": "用英文写的复述提示关键信息 1（不要求完整句，给出关键线索即可）",
        "reference_answer": "用英文写的一段完整参考复述 1（80-150 词），学生点击查看"
      }},
      {{
        "hint": "用英文写的复述提示关键信息 2",
        "reference_answer": "用英文写的一段完整参考复述 2（80-150 词）"
      }}
    ]
  }},
  "shadowing": [
    {{
      "chunk_text": "适合跟读的一段英文（10-25 词为宜，按口语节奏分段）",
      "pause_after": "short / medium / long",
      "stress_hints": "重音或连读提示，例如: stress on 'actually', link 'kind of' -> 'kinda'"
    }}
  ],
  "difficult_spots": [
    {{
      "sentence": "原文中可能难理解的句子",
      "difficulty_point": "难点说明（俚语、文化梗、省略表达、语速太快导致模糊等）",
      "chinese_note": "用中文解释这句话的意思和为什么难"
    }}
  ]
}}

━━━━━━━━━━━━━━━━━━━━━━━━━
具体要求（请严格遵守）:
━━━━━━━━━━━━━━━━━━━━━━━━━

1. vocabulary:
   - 提取 8-15 个{level_guide['vocab_count']}高频实用的单词或短语
   - 优先选择口语中出现频率高的，而不是生僻词
   - 难度分级参考: ★☆☆ = 基础词但口语中用法灵活, ★★☆ = 日常中等难度, ★★★ = 俚语/熟语/高级表达
   - {level_guide['vocab_focus']}

2. golden_sentences:
   - 提取 8-12 个值得背诵的口语句型
   - 句型要「模板化」: 保留固定搭配，用 ... 标注可替换部分
   - 优先选: 高频句型、万能开头、衔接语、地道回应
   - {level_guide['sentence_focus']}

3. summary & retelling_hints:
   - summary_en 用自然的英文概括内容，不要照抄原文
   - retelling_hints 必须恰好包含 6-8 条，按内容逻辑顺序排列
   - 每条包含:
     * hint: 英文关键词/短语提示，覆盖视频中不同的关键段落
     * reference_answer: 给学生的英文参考复述段落（80-150 词），
       用自然的英文写，避免照抄原文，适合学生朗读学习

4. shadowing:
   - 将原文**重新组织**为适合跟读的段落（不是照搬原文）
   - 每段 10-25 词，按意群和换气点分段
   - pause_after: short(逗号级停顿) / medium(句号级停顿) / long(段落间停顿)
   - stress_hints: 标注该句中需要重读的词和重要的连读（用英文简短标注）
   - 控制总段数在 8-15 段，选取最有代表性的段落，不需要覆盖全文字幕

5. difficult_spots:
   - 找出 3-8 处{level_guide['difficulty_focus']}可能感到困难的表达
   - 困难来源: 俚语、文化梗、省略表达、语速快导致的连读模糊、非字面意思

6. 通用规则:
   - 所有字段都必须填写，不能留空字符串
   - context_sentence 和 example 必须从原文中取，不要自己编
   - Chinese explanations 用口语化的中文，不要教科书腔
   - 返回纯 JSON，不要用 ```json ``` 包裹"""


def _level_guide(level: str) -> dict:
    """根据水平返回针对性指导。"""
    guides = {
        "beginner": {
            "vocab_count": "",
            "vocab_focus": "重点选口语高频词和基础短语搭配，难词控制在 ★★☆ 以内",
            "sentence_focus": "重点选简单但万能的句型，如问候、回应、表达观点、请求澄清等",
            "difficulty_focus": "初级水平",
        },
        "intermediate": {
            "vocab_count": "",
            "vocab_focus": "选中等难度以上的地道表达和短语动词，适当包含 ★★★ 俚语",
            "sentence_focus": "选复杂句型和逻辑连接句型，如让步、假设、对比等",
            "difficulty_focus": "中级水平",
        },
        "advanced": {
            "vocab_count": "",
            "vocab_focus": "重点选高级词汇、熟语、行业术语和微妙表达",
            "sentence_focus": "选复杂句型和修辞表达，如倒装、强调、虚拟语气等",
            "difficulty_focus": "高级水平",
        },
    }
    return guides.get(level, guides["beginner"])
