# adventure.py
import re
import json
from llm import (
    call_gpt,
    DM_SYSTEM,
    EVENT_SYSTEM,
    build_opening_scene_prompt
)
from world import extract_json

# 管理冒险状态（history / round / options）
class AdventureManager:
    def __init__(self, world_obj, lang_ui, session_state):
        self.world_obj = world_obj
        self.lang_ui = lang_ui
        self.state = session_state["adventure"]

    # ----------- 辅助函数 -----------

    # 从 GPT 输出中提取 1. 2. 3. 的选项
    def extract_options(self, dm_resp):
        opts = re.findall(r"\d\.\s(.+)", dm_resp)
        return opts

    # 构造最近 3 回合的历史文本供 GPT 使用
    def recent_history_text(self):
        history = self.state["history"]
        recent = history[-3:]
        text = ""
        for h in recent:
            text += f"Player: {h['player']}\nDM: {h['dm']}\n\n"
        return text
    
    def _to_number(self, x):
        if isinstance(x, (int, float)):
            return x
        if isinstance(x, str):
            x = x.strip()
            if x.startswith("+"):
                x = x[1:]
            try:
                return float(x)
            except:
                return 0
        return 0

    # ----------- 开场回合 -----------

    # 开始冒险 → 生成开场剧情
    def start_adventure(self):
        prompt = build_opening_scene_prompt(self.world_obj, self.lang_ui)
        dm_resp = call_gpt(DM_SYSTEM, prompt, max_tokens=1000)

        options = self.extract_options(dm_resp)
        if not options:
            if self.lang_ui == "中文":
                options = ["继续探索", "调查角色", "前往未知地点"]
            else:
                options = ["Keep exploring", "Investigate a character", "Head to an unknown place"]

        self.state["history"].append({"player": "(start)", "dm": dm_resp})
        self.state["options"] = options
        self.state["round"] += 1
    
    def build_event_prompt(self, world_obj, player_action):
        lang = world_obj.get("lang_ui")

        return f"""
            你是这个世界的 DM。根据世界信息与玩家行为生成下一回合事件。

            世界信息：
            {json.dumps(world_obj, ensure_ascii=False)}

            玩家行为：
            "{player_action}"

            语言要求：
            - 所有叙事文本必须使用 {lang}
            - JSON 的 key 使用英文
            - 只输出 JSON

            请严格输出以下结构：

            {{
            "dm_text": "NARRATIVE_HERE",
            "options": ["OP1","OP2","OP3","OP4","OP5"],
            "health_change": CHANGE_VALUE
            }}

            规则：
            - health_change 必须是整数（如 -10, -3, +5）
            - health_change 不能始终为 0，必须反映事件内容
            - 如果叙事中玩家受伤 → health_change 必须为负数
            - 如果叙事中玩家恢复 → health_change 为正数
            - 如果只是轻微动作 → health_change 可为 -1 ~ -3
            - 不要重复上回合事件
            - 必须推动剧情
            - 返回严格 JSON
            """
    
    def _to_number(self, x):
        if isinstance(x, (int, float)):
            return x
        if isinstance(x, str):
            x = x.strip()
            if x.startswith("+"):
                x = x[1:]
            try:
                return float(x)
            except:
                return 0
        return 0


    def apply_event(self, world_obj, event):
        """
        只处理 health_change 的最简化版本
        """

        # ---- 获取当前 HP ----
        ps = world_obj.get("player_stats", {})
        hp = ps.get("health", 100)

        # ---- 获取变化量 ----
        delta = event.get("health_change", 0)

        # ---- 强制转换为数字 ----
        try:
            if isinstance(delta, str):
                delta = delta.strip()
                if delta.startswith("+"):
                    delta = delta[1:]
                delta = float(delta)
        except:
            delta = 0

        # ---- 应用变化 ----
        new_hp = hp + delta

        # ---- 边界保护 ----
        new_hp = max(0, min(new_hp, 100))

        # ---- 写回世界数据 ----
        ps["health"] = new_hp
        world_obj["player_stats"] = ps

        with open("gpt_log.txt", "a", encoding="utf-8") as f:
            f.write("\n\n==================== HEALTH CHANGE ====================\n")
            f.write(str(new_hp) + "\n")
            f.write("==================================================\n")
        
        return world_obj

    # ----------- 正常/最终回合 -----------

    # 生成下一回合剧情（包括 final 回合判断）
    def next_round(self, player_action):
        # 1) 构建事件 prompt（事件 JSON）
        prompt = self.build_event_prompt(self.world_obj, player_action)

        # 2) 调用 GPT 生成事件 JSON
        out = call_gpt(EVENT_SYSTEM, prompt, max_tokens=800)
        event = extract_json(out)

        if event is None:
            # 兜底：最小事件
            event = {
                "dm_text": "事件生成失败，但冒险仍在继续。",
                "options": ["继续探索", "环顾四周", "保持警惕", "记日记", "休息一下"],
                "world_state_change": {},
                "player_stats_change": {},
                "inventory_change": {},
                "memory_update": {},
                "companions_change": {}
            }

        # 3) 应用事件 → 更新世界状态
        updated_world = self.apply_event(self.world_obj, event)
        self.world_obj = updated_world

        # 4) 写入冒险记录
        self.state["history"].append({
            "player": player_action,
            "dm": event["dm_text"]
        })

        # 5) 更新本回合选项
        self.state["options"] = event["options"]
        
        # 6) 回合数 +1
        self.state["round"] += 1

        return event, self.world_obj

