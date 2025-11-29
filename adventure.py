# adventure.py
import re
import json
from llm import (
    call_gpt,
    DM_SYSTEM,
    EVENT_SYSTEM,
    build_opening_scene_prompt,
    parse_action,
    build_event_prompt
)
from utils import extract_json
from world import enrich_npc_personality
import random

# 管理冒险状态（history / round / options）
class AdventureManager:
    def __init__(self, world_obj, lang_ui, session_state):
        self.world_obj = world_obj
        self.lang_ui = lang_ui

        # ---------- NPC 性格扩展（只执行一次） ----------
        for npc in self.world_obj.get("characters", []):
            enrich_npc_personality(npc)

        self.state = session_state["adventure"]
        # ---------- 节点故事引擎初始化 ----------
        adv = self.world_obj.get("adventure_state", {})
        if "current_node" not in adv:
            adv["current_node"] = "setup"
        if "node_round_count" not in adv:
            adv["node_round_count"] = 0
        self.world_obj["adventure_state"] = adv

    # ----------- 辅助函数 -----------

    # 从 GPT 输出中提取 1. 2. 3. 的选项
    def extract_options(self, dm_resp):
        opts = re.findall(r"\d\.\s(.+)", dm_resp)
        return opts

    def recent_history_text(self, n=3, full=False):
        """
        返回最近 n 回合 或 全部历史
        """
        history = self.state["history"]
        
        if full:
            selected = history
        else:
            selected = history[-n:]

        return "".join([f"Player: {h['player']}\nDM: {h['dm']}\n\n" for h in selected])
    
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

    def apply_event(self, world_obj, event):
        """
        只处理 health_change 的最简化版本
        """

        # ---- 获取当前 HP ----
        ps = world_obj.get("player_stats", {})
        hp = ps.get("health", 100)

        # ---- 获取变化量，并转换为数字 ----
        delta = self._to_number(event.get("health_change", 0))

        # ---- 应用变化 ----
        new_hp = hp + delta

        # ---- 边界保护 ----
        new_hp = max(0, min(new_hp, 100))

        # ---- 写回世界数据 ----
        ps["health"] = new_hp
        world_obj["player_stats"] = ps

        # with open("gpt_log.txt", "a", encoding="utf-8") as f:
        #     f.write("\n\n==================== HEALTH CHANGE ====================\n")
        #     f.write(str(new_hp) + "\n")
        #     f.write("==================================================\n")
        
        return world_obj

    # ----------- 正常/最终回合 -----------
    def render_node_round(self, node_summary, player_action):
        prompt = f"""
        你是这个故事的叙述者。根据以下信息写出【本回合发生的事件】，共 3~4 句。

        规则：
        - 本回合必须体现玩家刚才的动作所带来的影响
        - 必须推动故事朝节点摘要方向推进，但不能重复上回合文字
        - 必须加入新的细节：线索 / 新角色出现 / 冲突 / 环境变化（二选一）
        - 保持语言自然，不要模板化，不要重复相同句式

        节点摘要（剧情方向）：
        {node_summary}

        玩家动作（必须融入叙述）：
        {player_action}
        """

        dm_text = call_gpt(DM_SYSTEM, prompt, max_tokens=250)
        return dm_text




    # ---------- 世界状态自动呼吸 ----------
    def update_world_state(self):
        ws = self.world_obj.get("world_state", {})

        # 轻微波动：让世界“活着”
        for key in ["tension", "corruption", "magic_density", "radiation"]:
            if key in ws and isinstance(ws[key], (int, float)):
                ws[key] += random.randint(-2, 3)   # 小范围波动
                ws[key] = max(0, min(100, ws[key]))

        # 昼夜循环 0=白天 1=黄昏 2=夜晚
        if "time_of_day" in ws:
            ws["time_of_day"] = (ws["time_of_day"] + 1) % 3

        # 天气系统（随机变化，低概率变化）
        if "weather" in ws:
            if random.random() < 0.2:  # 20% 概率改变
                ws["weather"] = random.choice(["clear", "cloudy", "fog", "rain", "storm", "snow"])

        # 写回
        self.world_obj["world_state"] = ws
    
    # ---------- 主线剧情推进 ----------
    def advance_story(self):
        adv = self.world_obj.get("adventure_state", {})

        # 如果已经触发了终章就不要再推进
        if adv.get("final_triggered"):
            return

        # 每回合推进主线（3~8% 随机，避免跳太快）
        increment = random.randint(3, 8)
        adv["story_progress"] = min(100, adv.get("story_progress", 0) + increment)

        # 写回
        self.world_obj["adventure_state"] = adv

    def update_npc_by_player_action(self, parsed, world):
        target = parsed.get("target", "")
        intent = parsed.get("intent", "")
        action_type = parsed.get("action_type", "")

        for npc in world.get("characters", []):
            if npc["name"] != target:
                continue

            # 社交提升信任
            if action_type == "social":
                npc["stats"]["trust"] += 1

            # 攻击同一敌人 → 战斗友情增强
            if action_type == "combat":
                npc["stats"]["trust"] += 2
                npc["stats"]["fear"] -= 1

            # 威胁/挑衅
            if intent in ["威胁", "挑衅"]:
                npc["stats"]["trust"] -= 3
                npc["stats"]["fear"] += 2

    def control_information_layer(self, parsed, world):
        """控制 NPC 本回合允许透露的信息层级"""

        memory = world.setdefault("memory", {})
        info_history = memory.setdefault("info_given", [])
        progress = world["adventure_state"]["story_progress"]
        chapter = world["adventure_state"].get("chapter", 0)
        topic = parsed.get("topic", "")
        action_type = parsed.get("action_type", "")

        # --- 战斗/移动/潜行等事件不应提供信息 ---
        if action_type not in ["social", "exploration"]:
            return "no_information"

        # --- 若已给过同主题信息：仅提供更深细节，不重复 ---
        if topic and any(topic in info for info in info_history):
            return "deepening"

        # --- 按章节决定最大信息深度 ---
        if chapter == 0:
            return "shallow"            # 序章 → 小线索
        elif chapter == 1:
            return "medium"             # 线索阶段 → 中线索
        elif chapter == 2:
            return "major"              # 冲突阶段 → 大线索
        elif chapter == 3:
            return "major"              # 危机逼近 → 大线索 + 强暗示
        elif chapter == 4:
            return "major"              # 终章前夕 → 大线索但保留关键
        elif chapter >= 5:
            return "reveal"             # 最终章 → 大揭露

        # 安全兜底
        return "shallow"
    
    def save_given_info(self, event, world):
        text = event["dm_text"]
        memory = world.setdefault("memory", {})
        info_history = memory.setdefault("info_given", [])

        # 捕捉 NPC 提供的重要信息（简单关键词提取）
        keywords = ["魔法阵", "失踪", "女巫", "黑暗力量", "仪式", "水晶"]

        for kw in keywords:
            if kw in text and kw not in info_history:
                info_history.append(kw)

    
    def get_chapter(self, progress):
        if progress < 10:
            return 0  # 序章
        if progress < 30:
            return 1  # 线索阶段
        if progress < 60:
            return 2  # 冲突阶段
        if progress < 80:
            return 3  # 危机逼近
        if progress < 100:
            return 4  # 终章前夕
        return 5        # 最终章

    def next_round(self, player_action):

        adv = self.world_obj["adventure_state"]
        nodes = self.world_obj.get("story_nodes", {})
        node_id = adv["current_node"]
        node_round = adv["node_round_count"]

        current_node = nodes.get(node_id, None)

        # 4) 如果玩家选了剧情跳转选项
        if adv.get("ready_for_node_jump"):
            chosen_text = player_action
            for opt in current_node["options"]:
                if opt["text"] == chosen_text:
                    next_id = opt["goto"]
                    adv["current_node"] = next_id
                    adv["node_round_count"] = 0  # 重置下一章节回合计数
                    adv["ready_for_node_jump"] = False
                    self.world_obj["adventure_state"] = adv
                    break

        # 跳完节点后：更新 node_id / node_round / current_node
        with open("gpt_log.txt", "a", encoding="utf-8") as f:
            f.write("\n\n==================== node id ====================\n")
            f.write(adv["current_node"] + "\n")
            f.write("\n==================================================\n")
            f.write(json.dumps(current_node, ensure_ascii=False, indent=2))
            f.write("\n==================================================\n")
            f.write(node_id + "\n")
            f.write("\n==================================================\n")
            f.write(json.dumps(nodes, ensure_ascii=False, indent=2))
            f.write("\n==================================================\n")

        node_id = adv["current_node"]
        node_round = adv["node_round_count"]
        current_node = nodes[node_id]


        # 1) 是否到达最终章？
        if node_id == "finale":
            dm_text = self.render_node_round(current_node["summary"], player_action)
            self.state["history"].append({"player": player_action, "dm": dm_text})
            self.state["options"] = []
            return {"dm_text": dm_text, "options": []}

        # 2) 每个节点允许 2~4 回合（可调）
        if node_round < 2:
            # 普通回合（GPT 生成内部选项）
            dm_text = self.render_node_round(current_node["summary"], player_action)

            # 简单内部选项（不跳节点）
            options = [
                "继续观察周围",
                "和附近的角色互动",
                "尝试前往另一个角落"
            ]

            self.state["history"].append({"player": player_action, "dm": dm_text})
            self.state["options"] = options

            adv["node_round_count"] += 1
            self.world_obj["adventure_state"] = adv
            return {"dm_text": dm_text, "options": options}

        # 3) 第 3 回合：给剧情节点选项（决定跳转）
        else:
            dm_text = self.render_node_round(current_node["summary"], player_action)


            story_options = current_node["options"]  # 固定剧情跳转
            options_texts = [opt["text"] for opt in story_options]

            # 写入记录
            self.state["history"].append({"player": player_action, "dm": dm_text})
            self.state["options"] = options_texts

            # 玩家选择会触发 goto
            adv["ready_for_node_jump"] = True
            self.world_obj["adventure_state"] = adv

            return {"dm_text": dm_text, "options": options_texts}
    



