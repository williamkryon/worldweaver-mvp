# llm.py
import os
import json
from dotenv import load_dotenv
from openai import OpenAI

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
        - 3_characters (list of dict: {{name, role, short_desc}})
        - initial_hook

        All content must be written in {lang_ui}.
        Keep all sections concise (max 2–3 sentences each).
        After the JSON, add a very short "notes" paragraph.
        """

def build_opening_scene_prompt(world_obj, lang_ui):
    return f"""
        Use {lang_ui}.
        Based strictly on this world:
        {json.dumps(world_obj["summary"], ensure_ascii=False)}

        Generate the opening scene of a short adventure.
        Rules:
        - 2–4 vivid sentences, no more.
        - Must directly reference the world's summary, locations, or characters.
        - End with EXACTLY 3 action options in numbered form:
        1. ...
        2. ...
        3. ...
        """