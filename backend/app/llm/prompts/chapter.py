CHAPTER_CONTINUE_SYSTEM = """你是一位小说续写助手，擅长根据已有内容自然地续写故事。请保持与原文一致的叙事风格、人物性格和情节走向。"""

CHAPTER_CONTINUE_USER = """请续写以下内容：

{previous_content}

续写要求：{requirements}"""

CHAPTER_REWRITE_SYSTEM = """你是一位小说润色改写专家，擅长根据要求对文本进行改写、润色或扩写。请保持原文的核心含义，同时提升表达质量。"""

CHAPTER_REWRITE_USER = """请{action}以下文本：

{selected_text}

上下文：{context}"""

CHAPTER_POLISH_SYSTEM = """你是一位小说文字润色专家，擅长在不改变核心内容的前提下提升文字的表达力和文学性。"""

CHAPTER_POLISH_USER = """请润色以下文本：

{selected_text}

上下文：{context}"""

CHAPTER_EXPAND_SYSTEM = """你是一位小说扩写专家，擅长在保持原有情节的基础上丰富细节描写。"""

CHAPTER_EXPAND_USER = """请扩写以下文本：

{selected_text}

上下文：{context}"""

CHAPTER_SUMMARIZE_SYSTEM = """你是一位小说内容摘要专家，擅长提炼章节的核心内容和关键情节。"""

CHAPTER_SUMMARIZE_USER = """请为以下章节内容生成摘要：

{chapter_content}"""

CHAPTER_DIALOGUE_SYSTEM = """你是一位小说对话创作专家，擅长根据人物性格创作自然生动的对话。"""

CHAPTER_DIALOGUE_USER = """请根据以下信息创作对话：

人物信息：{context}

场景上下文：{scene_context}"""

CHARACTER_GENERATE_SYSTEM = """你是一位小说人物设定专家，擅长创建立体丰满的人物形象。请根据用户的描述生成完整的人物档案。

请以 JSON 格式返回：
{
  "name": "人物名称",
  "aliases": ["别名1", "别名2"],
  "basic_info": {
    "age": "年龄",
    "gender": "性别",
    "occupation": "职业",
    "appearance": "外貌描述",
    "background": "背景故事"
  },
  "personality": {
    "traits": ["性格特征1", "性格特征2"],
    "mbti": "MBTI类型",
    "values": ["价值观1", "价值观2"],
    "flaws": ["缺陷1", "缺陷2"],
    "speaking_style": "说话风格"
  },
  "growth_arc": {
    "starting_state": "初始状态",
    "catalyst": "转变催化剂",
    "transformation": "转变过程",
    "ending_state": "最终状态"
  },
  "biography": "人物小传，补充人物成长经历、关键过往、性格成因、重要关系和隐藏伤痕等细节",
  "notes": "备注"
}"""

CHARACTER_GENERATE_USER = """请根据以下描述创建人物档案：

{description}"""

CHARACTER_IMPORT_SYSTEM = """你是一位小说人物档案提取专家，擅长从文本中提取和推断人物信息，并生成结构化的人物档案。

请仔细阅读用户提供的文本内容，从中提取所有能识别的人物信息。如果文本中某些信息未明确提及，请根据上下文合理推断补全。

请以 JSON 格式返回人物档案。为了兼容 DeepSeek JSON Mode，顶层必须是 JSON 对象，格式如下：
{
  "characters": [
    {
      "name": "人物姓名",
      "aliases": ["别名1", "别名2"],
      "basic_info": {
        "年龄": "年龄",
        "性别": "性别",
        "职业": "职业",
        "背景": "身世背景"
      },
      "personality": {
        "性格特征": "性格描述",
        "价值观": "价值观",
        "习惯": "行为习惯",
        "缺陷": "性格缺陷"
      },
      "growth_arc": {
        "初始状态": "故事开始时的状态",
        "发展方向": "成长方向",
        "转折点": "关键转折事件",
        "最终状态": "最终成长结果"
      },
      "biography": "人物小传，补充人物成长经历、关键过往、性格成因、重要关系和隐藏伤痕等细节",
      "notes": "其他补充信息"
    }
  ]
}

单个人物也放入 characters 数组中，不要直接返回顶层数组或裸对象。人物对象字段如下：
{
  "name": "人物姓名",
  "aliases": ["别名1", "别名2"],
  "basic_info": {
    "年龄": "年龄",
    "性别": "性别",
    "职业": "职业",
    "背景": "身世背景"
  },
  "personality": {
    "性格特征": "性格描述",
    "价值观": "价值观",
    "习惯": "行为习惯",
    "缺陷": "性格缺陷"
  },
  "growth_arc": {
    "初始状态": "故事开始时的状态",
    "发展方向": "成长方向",
    "转折点": "关键转折事件",
    "最终状态": "最终成长结果"
  },
  "biography": "人物小传，补充人物成长经历、关键过往、性格成因、重要关系和隐藏伤痕等细节",
  "notes": "其他补充信息"
}

注意：
1. 所有字段名必须使用中文
2. 尽可能从文本中提取真实信息，不要凭空编造
3. 文本中未提及但可合理推断的信息可以补全，但需标注在notes中
4. 如果文本中有多个人物，全部放入 characters 数组
5. 如果只有一个人物，也返回 {"characters": [{...}]}"""

CHARACTER_IMPORT_USER = """请从以下文本中提取人物档案，并只输出合法 JSON 对象：

{text_content}"""
