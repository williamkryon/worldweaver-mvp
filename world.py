# world.py
import json
import re
import time
from db import SessionLocal, World
from llm import call_gpt, WORLD_GEN_SYSTEM, build_world_prompt

# 从 GPT 输出中提取 JSON
def extract_json(text):
    m = re.search(r"(\{[\s\S]*\})", text)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except:
        return None

# 输入一句话创意，生成世界 JSON + main_quest。返回 world_obj 字典。
def generate_world(idea, world_name, lang_ui):

    # --- 生成世界世界 ---
    user_prompt = build_world_prompt(idea, lang_ui)
    out = call_gpt(WORLD_GEN_SYSTEM, user_prompt, max_tokens=1200)

    # 提取 JSON
    data = extract_json(out)
    if data is None:
        # JSON 提取失败 → 用 summary 输出兜底
        data = {"title": world_name, "summary": out}

    # --- 生成主线任务 ---
    quest_prompt = f"""为这个世界设计一个清晰的主线任务，用一句话概括。
    世界信息：
    {json.dumps(data, ensure_ascii=False)}
    要求：
    - 中文用中文一句话，英文用英文一句话
    - 不要太长，不要剧情摘要，只要“任务目标”
    """

    main_quest = call_gpt(WORLD_GEN_SYSTEM, quest_prompt, max_tokens=600)
    data["main_quest"] = main_quest.strip()

    return data

# 保存世界到数据库（同名覆盖）
def save_world_to_db(world_name, world_obj):

    session = SessionLocal()
    existing = session.query(World).filter_by(name=world_name).first()

    if existing:
        existing.data = json.dumps(world_obj, ensure_ascii=False)
        existing.created_at = time.time()
    else:
        new_world = World(
            name=world_name,
            data=json.dumps(world_obj, ensure_ascii=False),
            created_at=time.time()
        )
        session.add(new_world)

    session.commit()
    session.close()
