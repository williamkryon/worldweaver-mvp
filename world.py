# world.py
import json
import re
import time
import random
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

def generate_world(idea, world_name, lang_ui):
    """
    生成完整世界：
    - GPT 生成世界内容（world_content）
    - GPT 生成世界逻辑（world_logic）
    - GPT 生成初始状态（initial_state）
    - 程序填充系统字段（system fields）
    """

    # ---------- 1) GPT：生成世界内容结构 ----------
    world_prompt = f"""
        根据玩家的创意构建一个完整的 RPG 世界。

        玩家创意：
        {idea}

        当前 UI 语言：{lang_ui}

        语言要求（非常重要）：
        - 如果 UI 语言是 "中文"，则除了 JSON 的 key（如 "title"）必须保持英文外，
        所有 value（标题、简介、地点名称与描述、角色名称与描述、initial_hook、
        world_logic 里的 culture 等等）都必须使用自然流畅的中文。
        - 如果 UI 语言是 "English"，则所有 value 都必须使用自然流畅的英文。

        请输出 JSON，字段如下：
        

        {{
        "title": "...",
        "summary": "...",
        "initial_hook": "...",
        "locations": [
            {{"name": "...", "description": "...", "tags": ["city","ruin"], "danger": 0-100}}
        ],
        "characters": [
            {{
                "name": "...",
                "role": "...",
                "short_desc": "...",
                "stats": {{
                    "trust": 0-100,
                    "fear": 0-100,
                    "health": 50-120,
                    "custom": {{}}
                }}
            }}
        ],

        "world_logic": {{
            "allow_magic": true/false,
            "tech_level": "stone_age | medieval | industrial | modern | sci_fi",
            "energy_system": "...",
            "physics_rules": "...",
            "culture": "...",
            "world_type": "desert | frost | volcanic | apocalypse | forest | ocean"
        }},

        "initial_state": {{
            "world_heat": 0-100,
            "tension": 0-100,
            "magic_density": 0-100,
            "corruption": 0-100,
            "radiation": 0-100
        }}
        }}

        要求：
        - 输出严格 JSON
        - 不要解释
        - 内容必须与玩家的创意一致
        - initial_state 的数值必须由世界逻辑推导
        """


    out = call_gpt(WORLD_GEN_SYSTEM, world_prompt, max_tokens=1800)
    data = extract_json(out)

    if data is None:
        # 最基础兜底，但一般不会触发
        data = {
            "title": world_name,
            "summary": out,
            "initial_hook": "",
            "locations": [],
            "characters": [],
            "world_logic": {},
            "initial_state": {}
        }


    # ---------- 2) GPT：生成主线一句话 ----------
    quest_prompt = f"""
        为这个世界写一句话主线任务（目标句子，不要剧情）。
        世界信息：
        {json.dumps(data, ensure_ascii=False)}
        只输出一句话。"""
    
    main_quest = call_gpt(WORLD_GEN_SYSTEM, quest_prompt, max_tokens=200)
    data["main_quest"] = main_quest.strip()

     # ---------- 2.5) GPT：生成玩家角色 ----------
    player_prompt = f"""
        根据以下世界内容，为这个世界生成一个“玩家角色”（主角）。

        世界信息：
        {json.dumps(data, ensure_ascii=False)}

        输出 JSON，字段如下：

        {{
        "player_profile": {{
            "name": "玩家名字（符合世界语言风格，用 {lang_ui}）",
            "background": "玩家的身世背景（2-3句话）",
            "profession": "职业 / 角色类别",
            "role_in_world": "外来者 | 被选中者 | 探险家 | 流民 | 学者 等",
            "traits": ["2~4 个个性特质"],
            "weakness": ["1~2 个弱点"]
        }},
        "player_stats": {{
            "health": 100,
            "sanity": 60~120,
            "mana": 0~100,           // 如果世界逻辑 allow_magic = false 则 mana = 0
            "custom": {{
                "力量": 1~10,
                "敏捷": 1~10,
                "智力": 1~10
            }}
        }}
        }}

        要求：
        - 所有字段必须符合世界逻辑 world_logic 中的 tech_level / allow_magic / energy_system
        - 名字、描述都必须使用语言：{lang_ui}
        - 只输出 JSON，不要解释
        """
    player_out = call_gpt(WORLD_GEN_SYSTEM, player_prompt, max_tokens=800)
    player_data = extract_json(player_out)

    if player_data is None:
        # 基础兜底
        player_data = {
            "player_profile": {
                "name": "无名旅人",
                "background": "一个没有明确过去的旅行者，刚刚来到这个世界。",
                "profession": "wanderer",
                "role_in_world": "outsider",
                "traits": ["好奇"],
                "weakness": ["天真"]
            },
            "player_stats": {
                "health": 100,
                "sanity": 100,
                "mana": 0,
                "custom": {"力量": 5, "敏捷": 5, "智力": 5}
            }
        }

    # ---------- 3) 构造 world_template（程序字段 + 内容字段容器） ----------
    world_template = {

        # --- 世界内容字段（GPT 覆盖） ---
        "title": "",
        "summary": "",
        "lang_ui": lang_ui,
        "initial_hook": "",
        "main_quest": "",
        "locations": [],
        "characters": [],
        "world_logic": {},
        "initial_state": {},

        # --- 系统字段（程序初始化，会随着游戏改变） ---
        "player_stats": {
            "health": 100,
            "mana": 0,
            "sanity": 100,
            "traits": [],
            "role": "outsider"
        },

        "companions": [],

        "inventory": {
            "resources": {},
            "items": [],
            "lore": []
        },

        # 动态世界状态（start = initial_state）
        "world_state": {},

        "memory": {
            "visited_locations": [],
            "met_characters": [],
            "events_triggered": [],
            "unlocked_lore": []
        },

        # 游戏规则
        "event_rules": {
            "max_choices": 5,
            "allow_free_input": True,
            "combat_enabled": False
        }
    }

    # ---------- 4) 覆盖世界内容字段（GPT → template） ----------
    world_template["title"] = data.get("title", world_name)
    world_template["summary"] = data.get("summary", "")
    world_template["initial_hook"] = data.get("initial_hook", "")
    world_template["main_quest"] = data.get("main_quest", "")

    # 地点
    if "locations" in data:
        world_template["locations"] = data["locations"]

    # 角色（GPT 已经生成 stats，无需程序加默认 stats）
    if "characters" in data:
        world_template["characters"] = data["characters"]

    # 世界逻辑
    world_template["world_logic"] = data.get("world_logic", {})

    # 世界初始状态
    world_template["initial_state"] = data.get("initial_state", {})

    # 初始 world_state = initial_state（动态）
    world_template["world_state"] = dict(world_template["initial_state"])

     # ---------- 4.1 合并玩家信息到 world_template ----------
    world_template["player_profile"] = player_data.get("player_profile", {})

    # 玩家 stats（如果世界没有魔法 → mana = 0）
    stats = player_data.get("player_stats", {})
    if not world_template["world_logic"].get("allow_magic", False):
        stats["mana"] = 0
    world_template["player_stats"] = stats

    # ---------- 5) 完成 ----------
    return world_template



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
