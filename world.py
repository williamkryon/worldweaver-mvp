# world.py
import json
import re
import time
import random
from db import SessionLocal, World
from llm import call_gpt, WORLD_GEN_SYSTEM
from utils import extract_json

def safe_get(d, key, default):
    """安全取值，避免 None、空字符串、缺失 key 的问题"""
    if not isinstance(d, dict):
        return default
    val = d.get(key, default)
    if val in [None, ""]:
        return default
    return val


def generate_world(idea, world_name, lang_ui):
    """
    优化后的世界生成流程：
    1) GPT 生成世界结构（世界 + 角色 + 地点 + initial_state）
    2) GPT 生成 main_quest
    3) GPT 生成玩家角色（player_profile + player_stats）
    4) 合并成 world_template 并初始化系统字段
    """

    # ------------------------------
    # 1. GPT：生成世界基础结构
    # ------------------------------
    world_prompt = f"""
        根据玩家的创意构建一个完整的 RPG 世界。

        玩家创意：
        {idea}

        当前 UI 语言：{lang_ui}

        语言要求：
        - UI 为中文 → 所有 value 用自然中文（JSON key 保持英文）
        - UI 为英文 → 所有 value 用自然英文

        输出严格 JSON，不要解释：

        {{
        "title": "...",
        "summary": "...",
        "initial_hook": "...",
        "locations": [
            {{
                "name": "...",
                "description": "...",
                "tags": ["city","ruin"],
                "danger": 0
            }}
        ],
        "characters": [
            {{
                "name": "...",
                "role": "...",
                "short_desc": "...",
                "stats": {{
                    "trust": 0,
                    "fear": 0,
                    "health": 100,
                    "custom": {{}}
                }}
            }}
        ],

        "world_logic": {{
            "allow_magic": true,
            "tech_level": "medieval",
            "energy_system": "...",
            "physics_rules": "...",
            "culture": "...",
            "world_type": "forest"
        }},

        "initial_state": {{
            "tension": 10,
            "magic_density": 5,
            "corruption": 2,
            "radiation": 0
        }}
        }}
    """

    out = call_gpt(WORLD_GEN_SYSTEM, world_prompt, max_tokens=1600)
    data = extract_json(out)

    # 兜底（极少情况）
    if not data:
        data = {
            "title": world_name,
            "summary": out,
            "initial_hook": "",
            "locations": [],
            "characters": [],
            "world_logic": {},
            "initial_state": {}
        }

    # ------------------------------
    # 2. GPT：一句话主线
    # ------------------------------
    quest_prompt = f"""
        根据以下世界内容写一句话主线任务，不要剧情，只要任务目标：

        {json.dumps(data, ensure_ascii=False)}

        只输出一句话。
    """
    main_quest = call_gpt(WORLD_GEN_SYSTEM, quest_prompt, max_tokens=60).strip()
    data["main_quest"] = main_quest

    # ------------------------------
    # 2.5 GPT：生成六段剧情节点 story_nodes
    # ------------------------------
    node_prompt = f"""
        你需要为一个短篇冒险生成 6 个固定剧情节点，用于推动完整故事。
        必须输出严格 JSON，不得换行于 summary 内，不得包含任何回车符或多行文本。
        每个 summary 必须是单行句子。

        要求：
        - summary 必须是一句话（不能包含换行、不能包含引号）
        - options 必须是数组，格式为：{{"text": "xxxx", "goto": "xxxx"}}
        - 剧情跳转规则必须遵守：
        setup → first_clue
        first_clue → twist
        twist → crisis
        crisis → pre_finale
        pre_finale → finale
        finale → options = []

        世界信息如下：
        {json.dumps(data, ensure_ascii=False)}

        输出严格 JSON：

        {{
        "setup": {{
            "summary": "一句话，不可换行",
            "options": [{{"text": "选项一句话", "goto": "first_clue"}}]
        }},
        "first_clue": {{
            "summary": "一句话，不可换行",
            "options": [{{"text": "选项一句话", "goto": "twist"}}]
        }},
        "twist": {{
            "summary": "一句话，不可换行",
            "options": [{{"text": "选项一句话", "goto": "crisis"}}]
        }},
        "crisis": {{
            "summary": "一句话，不可换行",
            "options": [{{"text": "选项一句话", "goto": "pre_finale"}}]
        }},
        "pre_finale": {{
            "summary": "一句话，不可换行",
            "options": [{{"text": "选项一句话", "goto": "finale"}}]
        }},
        "finale": {{
            "summary": "一句话，不可换行",
            "options": []
        }}
        }}
        """

    node_raw = call_gpt(WORLD_GEN_SYSTEM, node_prompt, max_tokens=800)
    story_nodes = extract_json(node_raw) or {}

    if not story_nodes or "setup" not in story_nodes:
        story_nodes = {
            "setup": {"summary": "故事开始于玩家进入此世界。", "options": [{"text": "继续前进", "goto": "first_clue"}]},
            "first_clue": {"summary": "玩家发现一个神秘的线索。", "options": [{"text": "继续调查", "goto": "twist"}]},
            "twist": {"summary": "玩家发现一个隐藏的真相。", "options": [{"text": "面对真相", "goto": "crisis"}]},
            "crisis": {"summary": "危机加深，风险上升。", "options": [{"text": "寻找突破口", "goto": "pre_finale"}]},
            "pre_finale": {"summary": "最终决战前的准备。", "options": [{"text": "进入最终地点", "goto": "finale"}]},
            "finale": {"summary": "故事的结局揭晓。", "options": []}
        }

    data["story_nodes"] = story_nodes

    # ------------------------------
    # 3. GPT：生成玩家角色
    # ------------------------------
    player_prompt = f"""
        根据以下世界内容，为这个世界生成一个玩家角色。

        世界信息：
        {json.dumps(data, ensure_ascii=False)}

        输出严格 JSON：

        {{
        "player_profile": {{
            "name": "玩家名字 ({lang_ui})",
            "background": "2-3 句背景",
            "profession": "...",
            "role_in_world": "...",
            "traits": ["..."],
            "weakness": ["..."]
        }},
        "player_stats": {{
            "health": 100,
            "sanity": 80,
            "mana": 0,
            "custom": {{
                "力量": 5,
                "敏捷": 5,
                "智力": 5
            }}
        }}
        }}
    """

    player_out = call_gpt(WORLD_GEN_SYSTEM, player_prompt, max_tokens=800)
    player_data = extract_json(player_out)

    # 玩家角色兜底
    if not player_data:
        player_data = {
            "player_profile": {
                "name": "无名旅人" if lang_ui == "中文" else "Nameless Wanderer",
                "background": "一个没有明确过去的旅人。",
                "profession": "wanderer",
                "role_in_world": "outsider",
                "traits": ["curious"],
                "weakness": ["naive"]
            },
            "player_stats": {
                "health": 100,
                "sanity": 100,
                "mana": 0,
                "custom": {"力量": 5, "敏捷": 5, "智力": 5}
            }
        }

    # ------------------------------
    # 4. 构造最终 world_template（无重复字段）
    # ------------------------------
    initial_state = safe_get(data, "initial_state", {})

    world_template = {
        # --- GPT world data ---
        "title": safe_get(data, "title", world_name),
        "summary": safe_get(data, "summary", ""),
        "initial_hook": safe_get(data, "initial_hook", ""),
        "main_quest": safe_get(data, "main_quest", ""),
        "story_nodes": safe_get(data, "story_nodes", {}),
        "lang_ui": lang_ui,

        "locations": safe_get(data, "locations", []),
        "characters": safe_get(data, "characters", []),
        "world_logic": safe_get(data, "world_logic", {}),

        "story_nodes": safe_get(data, "story_nodes", {}),

        # --- initial & world_state 分离 ---
        "initial_state": initial_state,
        "world_state": {
            "tension": initial_state.get("tension", 10),
            "magic_density": initial_state.get("magic_density", 5),
            "corruption": initial_state.get("corruption", 0),
            "radiation": initial_state.get("radiation", 0),
            "time_of_day": 0,
            "weather": "clear"
        },

        # --- player data ---
        "player_profile": safe_get(player_data, "player_profile", {}),
        "player_stats": player_data.get("player_stats", {}),

        # --- story ---
        "story_beats": data.get("story_beats", {}),

        # --- inventory ---
        "inventory": {"resources": {}, "items": [], "lore": []},

        # --- adventure / memory ---
        "memory": {
            "visited_locations": [],
            "met_characters": [],
            "events_triggered": [],
            "unlocked_lore": [],
            "info_given": [],
            "key_clues": []
        },

        "adventure_state": {
            "story_progress": 0,
            "chapter": 0,
            "final_triggered": False
        },

        # 系统字段：同伴
        "companions": []
    }

    # 如果世界没有魔法，强制 mana = 0
    if not world_template["world_logic"].get("allow_magic", False):
        world_template["player_stats"]["mana"] = 0

    with open("gpt_log.txt", "a", encoding="utf-8") as f:
        f.write("\n\n==================== FIRST CHECK ====================\n")
        f.write(json.dumps(data["story_nodes"], ensure_ascii=False, indent=2))
        f.write("\n==================================================\n")
        f.write(json.dumps(world_template["story_nodes"], ensure_ascii=False, indent=2))
        f.write("\n==================================================\n")

    return world_template



def enrich_npc_personality(npc):
    """根据角色 role 和 desc 自动扩展 NPC 性格（智能补全层）"""

    role = npc.get("role", "")
    desc = npc.get("desc", "")
    traits = npc.get("base_traits", [])[:]    # 复制 GPT 的基础性格
    speech_style = npc.get("speech_style", "")

    # ---- 职业原型扩展（极少规则，但覆盖99%的情况） ----
    if any(key in role for key in ["战士", "斗士", "护卫", "勇士"]):
        traits += ["勇猛", "直接"]
        speech_style = speech_style or "声音洪亮，直截了当"

    if any(key in role for key in ["刺客", "影", "潜行", "追踪"]):
        traits += ["冷静", "隐秘"]
        speech_style = speech_style or "低声、短句、不愿多说"

    if any(key in role for key in ["法师", "巫师", "魔法"]):
        traits += ["理性", "神秘"]
        speech_style = speech_style or "语气平淡，带讲解性质"

    if any(key in role for key in ["商人", "交易", "经纪"]):
        traits += ["圆滑", "机敏"]
        speech_style = speech_style or "客套、谨慎、观察对方反应"

    if any(key in role for key in ["领袖", "国王", "指挥", "将军"]):
        traits += ["权威", "果断"]
        speech_style = speech_style or "稳重、有命令感"

    # ---- 根据描述自动填词 ----
    if "阴影" in desc or "黑暗" in desc:
        traits += ["神秘", "危险"]

    if "善良" in desc:
        traits += ["温和"]

    if "愤怒" in desc or "暴躁" in desc:
        traits += ["冲动"]

    # ---- 安全兜底 ----
    if len(traits) < 2:
        traits.append("中性")

    npc["personality"] = {
        "traits": list(set(traits)),
        "speech_style": speech_style or "正常语速、普通语气",
    }
    return npc


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
