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