# llm.py
import os
import json
from dotenv import load_dotenv
from openai import OpenAI
from utils import extract_json
try:
    import streamlit as st
except ImportError:
    st = None

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.error("请在项目根目录创建 .env 文件并写入 OPENAI_API_KEY=你的key")
    st.stop()

client = OpenAI(api_key=OPENAI_API_KEY)

# ---------------------------
# 统一的 GPT 调用函数
# ---------------------------
def call_gpt(system_prompt, user_prompt, temperature=0.8, max_tokens=1200):
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        out_text = completion.choices[0].message.content.strip()

        # ---- 写入 Log 文件 ----
        with open("gpt_log.txt", "a", encoding="utf-8") as f:
            f.write("\n\n==================== NEW CALL ====================\n")
            f.write("=== SYSTEM PROMPT ===\n")
            f.write(system_prompt + "\n\n")
            f.write("=== USER PROMPT ===\n")
            f.write(user_prompt + "\n\n")
            f.write("=== GPT RAW OUTPUT ===\n")
            f.write(out_text + "\n")
            f.write("==================================================\n")


        return completion.choices[0].message.content.strip()

    except Exception as e:
        return f"(Error calling GPT: {e})"


# ---------------------------
# Prompt 模板（集中管理）
# ---------------------------

WORLD_GEN_SYSTEM = """
    You are a professional TTRPG world designer.
    Your job is to produce compact, clean, structured JSON describing a fictional world.

    Rules:
    - Never include explanations outside the JSON (except brief notes after).
    - Keep all text concise, vivid, and easy to play in an adventure.
    - Keep descriptions no longer than 2–3 sentences each.
    - Do not invent new sections not requested.
    - Do not add comments, disclaimers, or markdown.
    """

DM_SYSTEM = """
    You are a professional TTRPG Dungeon Master.
    Your task is to narrate scenes and present clear, meaningful choices.

    General Rules:
    - Do NOT use speaker labels ("DM:" "Player:" etc.).
    - Write short, tight narrative paragraphs (2–4 sentences).
    - Always maintain consistency with world facts and main quest.
    - Keep pacing dynamic: each round must progress the story.
    - Avoid lists except for final 3 numbered action options.
    - Never explain rules or meta-thought.
    """

EVENT_SYSTEM = """
    You are a state machine. 
    Your ONLY job is to output strict JSON based on a template.
    You MUST NOT output narrative, only fill JSON fields.
    Never add any text outside the JSON.

    OPTIONS RULE (非常重要):
    - 你必须输出一个名为 "options" 的数组。
    - options 的数量必须精确满足以下规则：

    若 action_type = "combat"：
        options 必须有 EXACTLY 3 个动作：
        - 一个进攻类
        - 一个防御/闪避类
        - 一个逃跑类

    若 action_type = "exploration"：
        options 必须 EXACTLY 3 个：观察 / 深入调查 / 移动到新地点

    若 action_type = "social"：
        options 必须 EXACTLY 3 个：继续提问 / 转换话题 / 结束对话离开

    若 action_type = "stealth"：
        options 必须 EXACTLY 2 个：继续潜行 / 躲藏静止

    若 action_type = "item"：
        options 必须 EXACTLY 2 个：使用物品 / 收集并离开

    若 action_type = "move"：
        options 必须 EXACTLY 3 个：左路线 / 右路线 / 返回安全区

    如果你生成的 options 数量不符合要求，你必须立刻重写正确版本。

    JSON VALIDATION (必须满足):
    - 你必须输出一个包含以下字段的 JSON 对象：
        dm_text (string)
        options (list)
        health_change (number)
        world_state_change (object)
        player_change (object)
        npc_change (list)
    - 不得缺少字段，不得多出字段。
    - 若缺少任何字段，你必须自动重写。

    IMPORTANT FAILSAFE (必须执行):
    If your output violates ANY rule above — including:
    - wrong event_type behavior,
    - wrong chapter behavior,
    - repeating a clue already in info_given,
    - creating new lore not supported by the world,
    - giving information deeper than allowed by info_level,
    - not using npc personality traits/speech_style,
    - including narrative outside JSON,
    - including explanations or apologies,
    - generating options that do not match action_type,

    Then you MUST discard the attempt and regenerate a CORRECT version.
    Only output strict JSON that follows ALL rules.
    Never output meta comments.
    """

ACTION_PARSER_SYSTEM = """
    你是动作意图分析器。你的任务是把玩家输入解析成结构化行为。

    你只能输出 JSON，不要解释。

    JSON 模板：
    {
    "action_type": "combat | exploration | social | stealth | item | move",
    "target": "动作对象（如果有）",
    "intent": "意图（询问 / 调查 / 攻击 / 支援 / 移动 等）",
    "topic": "主题内容（女巫 / 水晶 / 魔法阵 等）",
    "risk": "low | medium | high"
    }

    规则：
    - action_type 必须从上述六种中选一个。
    - 若无法判断，则 action_type = "social"。
    """

# --------- 构造 prompt 的 helper 函数 ---------
def build_world_prompt(idea, lang_ui):
    return f"""
        The user writes in: {lang_ui}

        Create a compact RPG world based on the idea:
        "{idea}"

        Output JSON with EXACTLY these keys:
        - title
        - summary
        - 3_locations (list of dict: {{name, description}})
        - 3_characters (list of dict: {{
            "name": "角色名",
            "role": "职业/身份",
            "desc": "角色描述",
            "base_traits": [ "简洁的性格形容词，3个以内" ],
            "speech_style": "一句话描述说话方式"
        }})
        - initial_hook

        All content must be written in {lang_ui}.
        Keep all sections concise (max 2–3 sentences each).
        After the JSON, add a very short "notes" paragraph.
        """

def build_opening_scene_prompt(world_obj, lang_ui):
    return f"""
        使用 {lang_ui}。

        你必须根据这个世界的内容生成一个结构化的开场事件：
        世界总结：
        {json.dumps(world_obj["summary"], ensure_ascii=False)}

        地点列表：
        {json.dumps(world_obj["locations"], ensure_ascii=False)}

        主要角色：
        {json.dumps(world_obj["characters"], ensure_ascii=False)}

        开场事件规则（务必严格遵守）：
        - 氛围：2~4 句
        - 内容必须发生在某个具体地点（地点名需点名）
        - 至少出现 1 个世界中的角色（体现性格 traits 与 speech_style）
        - 必须引出一个“开端冲突”（例如：异动、骚乱、失踪、可疑人物）
        - 不得给任何深层秘密（序章只能浅提示）

        行动选项必须 EXACTLY 3 个，分别对应：
        1. exploration（调查/观察）
        2. social（与某个角色交谈）
        3. move（前往一个新地点）

        选项格式（严格）：
        1. 文本
        2. 文本
        3. 文本
    """

def parse_action(action_text):
    prompt = f"玩家行动：{action_text}\n请输出结构化行为 JSON："
    raw = call_gpt(ACTION_PARSER_SYSTEM, prompt, max_tokens=200)
    return extract_json(raw)

def build_event_prompt(
        world_obj,
        player_action,
        parsed_action,
        lang_ui,
        info_level,
        chapter
    ):
    """
    纯事件 Prompt 构造器
    不依赖 AdventureManager，不使用 self
    """

    parsed = json.loads(parsed_action)

    action_type = parsed.get("action_type", "social")
    target = parsed.get("target", "")
    intent = parsed.get("intent", "")
    topic = parsed.get("topic", "")
    risk = parsed.get("risk", "low")

    world_state = world_obj.get("world_state", {})
    player_stats = world_obj.get("player_stats", {})
    characters = world_obj.get("characters", [])

    story_beats = world_obj.get("story_beats", {})

    # DM 输出必须严格遵守 action_type 的事件结构
    ACTION_HARD_RULE = f"""
        本回合事件类型是：{action_type}
        你必须完全按照该事件类型进行叙述。不得偏离。

        【combat】
        - 必须出现敌人或威胁
        - 必须有攻击/闪避/受伤
        - 必须体现 risk（风险）高低
        - 不得输出探索类线索，不得输出社交对话

        【exploration】
        - 必须出现调查行为
        - 必须发现“新的”线索（禁止重复 info_given）
        - 必须描述具体环境（地点结构/痕迹/声音）
        - 不得输出战斗，不得出现深层秘密

        【social】
        - 必须包含 NPC 对话（必须体现 speech_style）
        - 必须对应 target 的角色
        - 对话必须推动信息层级（shallow/medium/major）
        - 不得创建新角色

        【stealth】
        - 必须强调隐藏、侦察、紧张气氛
        - 必须有“被发现风险”
        - 不得给主线信息

        【item】
        - 必须描述一个具体物品
        - 必须提供关于物品的新用途或线索
        - 不得写战斗或社交

        【move】
        - 必须抵达一个具体地点
        - 必须描述抵达后的新状况
        - 必须提供新的行动方向
        - 不得写战斗、不写深线索
        """

    # 事件类型模板：让 GPT 真的使用事件类型
    EVENT_TYPE_GUIDE = f"""
        事件类型说明（你必须严格遵守 action_type）：

        1. combat（战斗事件）
        - 必须包含敌人、攻击、伤害、风险
        - 必须有至少一个战斗动作（攻击/格挡/躲闪）
        - 必须根据 risk 输出合适的危险程度描述

        2. exploration（探索事件）
        - 必须包含观察、调查、线索、发现
        - 必须给出新的信息，不得重复旧信息
        - 场景必须具体（地点结构、声音、痕迹）

        3. social（社交事件）
        - 必须包含对话、回应、情绪变化
        - target 若存在 → 必须与该角色互动
        - 必须推动剧情（不能只给氛围）

        4. stealth（潜行事件）
        - 必须出现潜伏、暗影、侦察、隐藏行为
        - 必须强调风险与隐蔽性

        5. item（物品事件）
        - 必须描述物品的细节、用途或秘密
        - 必须发现新的线索或产生新风险

        6. move（移动事件）
        - 必须描述新地点或环境变化
        - 必须给出抵达后的新状况与选择
        """

    # 强制章节驱动剧情节奏
    CHAPTER_RULE = f"""
        当前章节：{chapter}

        你必须根据章节强制调整事件内容：

        0（序章）：
        - 只能给浅层信息
        - 冲突必须很轻
        - 不能出现重大秘密
        - 不得出现强敌

        1（线索阶段）：
        - exploration 必须给 medium 信息
        - social 必须给模糊但推进剧情的回答
        - move 必须引导到“关键地点”

        2（冲突阶段）：
        - exploration 必须给重大线索（major）
        - 环境必须危险化（更紧张）
        - social 必须体现情绪变化 trust/fear

        3（危机逼近）：
        - 必须出现紧迫感
        - 事件必须暗示终局
        - exploration 必须给关键信息碎片
        - social 必须出现 NPC 的恐惧或犹豫

        4（终章前夕）：
        - 必须出现核心秘密的 80% 线索
        - 气氛必须紧绷
        - 事件必须感觉到“马上要决战”

        5（最终章）：
        - 不再使用本事件模板
        - 最终章由终章 prompt 生成
        """
    return f"""
        你是这个世界的 DM。你的事件必须遵守以下内容：
        ==================== 必须使用的语言 ====================
        {lang_ui}

        ==================== 玩家行为（解析后，必须使用） ====================
        action_type: {action_type}
        target: {target}
        intent: {intent}
        topic: {topic}
        risk: {risk}
        完整解析：{parsed_action}

        ==================== 当前章节的故事骨架（必须使用） ====================
        story_beats:
        {json.dumps(story_beats, ensure_ascii=False)}

        在本章节，你必须参考以下 beats：

        若 chapter == 0：使用 story_beats["setup"]
        若 chapter == 1：使用 story_beats["first_clue"]
        若 chapter == 2：使用 story_beats["midpoint_twist"]
        若 chapter == 3：使用 story_beats["escalation"]
        若 chapter == 4：使用 story_beats["pre_final"]

        规则：
        - 你必须引用该章节 beats 里的至少 1 个字段
        - 你必须推动剧情向 beats 指向的方向前进
        - 事件必须体现 beats 的剧情意义（例如：冲突升级、时间压力、接近真相）
        - 禁止跳章节使用未来 beats
        - 禁止泄露 finale 的 true_cause（最终真相）

        ==================== ACTION 类型硬规则 ====================
        {ACTION_HARD_RULE}

        ==================== 事件类型模板 ====================
        {EVENT_TYPE_GUIDE}

        ==================== 章节规则（必须遵守） ====================
        {CHAPTER_RULE}

        ==================== 世界状态（必须影响气氛） ====================
        {json.dumps(world_state, ensure_ascii=False)}

        ==================== 玩家状态 ====================
        {json.dumps(player_stats, ensure_ascii=False)}

        ==================== NPC 性格约束（必须遵守） ====================
        每个 NPC 的个性如下，所有行为必须符合这些 personality：
        {json.dumps(characters, ensure_ascii=False)}

        NPC 规则：
        - traits 决定情绪底色（例如 冷静/冲动/神秘）
        - speech_style 决定说话方式（例如 短句/粗声/戏弄）
        - DM 在写 NPC 对话或动作时必须体现这些风格
        - DM 不得改变 NPC 性格，不得混淆不同角色的说话方式

        ==================== 玩家原始输入 ====================
        "{player_action}"

        ==================== 信息层级（你必须遵守） ====================
        本回合信息等级：{info_level}

        ==================== 已知信息（禁止重复） ====================
        这些线索已经给过，禁止重复解释：
        {world_obj["memory"]["info_given"]}

        信息规则：
        - shallow：只能给非常浅的线索，不得给任何关键秘密
        - medium：可以透露中等线索，但不得泄露最终真相
        - major：可以透露重大信息或剧情节点，但必须保留关键部分
        - deepening：玩家对同一 topic 的追问，只能给“更细节的补充”，禁止重复
        - reveal：主线已接近终点，可以揭露最重要的秘密
        - no_information：本回合不应提供剧情信息（例如战斗/移动/潜行）

        ==================== 当前剧情章节：{chapter} ====================
        请严格按照该章节规则生成事件：

        # 0：序章（世界开场）
        - 主要任务：建立气氛、背景、初始冲突
        - 禁止透露任何核心秘密
        - 引导玩家认识角色与环境
        - 事件动作应该轻量（不激烈）

        # 1：线索阶段（推进）
        - 可以给浅层线索
        - 允许轻微冲突
        - NPC 回答必须含糊、保留
        - 不要透露幕后真相

        # 2：冲突阶段（重要）
        - 事件必须出现转折点或危险升级
        - 线索必须变得重要
        - NPC 关系必须有变化（trust/fear生效）
        - 环境也应变得紧张

        # 3：危机逼近（重大阶段）
        - 必须出现“大事件预兆”
        - 氛围明显变强
        - 玩家每个选择都显得重要
        - 可以揭示部分大秘密，但必须保留最终答案

        # 4：终章前夕（高潮前紧张）
        - 必须出现“逼近真相”的直接证据或关键事件
        - 冲突到达最高点
        - NPC 会表现出强烈情绪变化
        - 除非必要，禁止收尾事件

        # 5：最终章
        - 必须揭示全部真相
        - 结局必须完整
        - options 留空

        ==================== 事件类型与章节协同（必须遵守） ====================

        在本章节内，事件类型（{action_type}）必须服从章节目标。
        例如：
        - 序章的 combat 是小规模冲突
        - 冲突阶段的 exploration 要给出节点级线索
        - 危机逼近阶段的 social 必须带重大情绪变化
        - 终章前夕的所有事件都必须带有“临界点”意义

        ==================== 严格输出 JSON（不要旁白，不要解释） ====================
        结构如下：
        {{
        "dm_text": "2~4句，必须体现 action_type 对事件的真实影响。",
        "options": ["基于 action_type 的行动选择"],
        "health_change": 整数,
        "world_state_change": {{}},
        "player_change": {{}},
        "npc_change": []
        }}

        严格要求：
        - 不得输出与 action_type 无关的事件内容。
        - dm_text 必须体现玩家意图（intent）与目标（target）。
        - 不得重复旧信息（尤其是 topic 相关）。
        - options 必须与 action_type 对应。
        """