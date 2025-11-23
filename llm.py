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
        return completion.choices[0].message.content.strip()

    except Exception as e:
        return f"(Error calling GPT: {e})"


# ---------------------------
# Prompt 模板（集中管理）
# ---------------------------

WORLD_GEN_SYSTEM = "You are an expert worldbuilder for tabletop RPGs. Produce concise structured JSON."

WORLD_GEN_USER_TEMPLATE = """Create a compact RPG world based on the user's idea:
{idea}

The user is writing in language: {lang}

Output JSON with keys:
- title
- summary
- 3_locations (list of dict: name, description)
- 3_characters (list of dict: name, role, short_desc)
- initial_hook

After the JSON, briefly provide creative notes (also in the same language).
"""


DM_SYSTEM = """
You are an imaginative RPG Dungeon Master.
Do NOT write "DM:" or "Player:" or any speaker labels.
Only write the narrative text and the 3 numbered options (if required).
Keep responses short and reference the world's facts.
"""



# --------- 构造 prompt 的 helper 函数 ---------

def build_world_prompt(idea, lang_ui):
    """构造世界生成的 user prompt"""
    return WORLD_GEN_USER_TEMPLATE.format(idea=idea, lang=lang_ui)


def build_opening_scene_prompt(world_obj, lang_ui):
    return f"""
Use {lang_ui}.
World facts: {json.dumps(world_obj, ensure_ascii=False)}
Generate an opening scene for a short adventure.
Provide 3 action options as:
1. ...
2. ...
3. ...
"""


def build_next_scene_prompt(world_obj, main_quest, recent_history, player_choice, lang_ui, is_final=False):
    final_text = ""
    if is_final:
        final_text = """
THIS IS THE FINAL ROUND.
End the adventure with a clear, satisfying conclusion.
Do NOT provide any action options.
"""
    else:
        final_text = """
After the scene, provide exactly 3 numbered action options:
1. ...
2. ...
3. ...
Do NOT use numbered lists anywhere else.
"""

    return f"""
Use {lang_ui}.

World Facts:
{json.dumps(world_obj, ensure_ascii=False)}

Main Quest:
{main_quest}

Recent Story:
{recent_history}

Player just chose:
{player_choice}

Continue the adventure. Keep tension and plot progression.

{final_text}
"""
