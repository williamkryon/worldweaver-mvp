# adventure.py
import re
import json
from llm import (
    call_gpt,
    DM_SYSTEM,
    EVENT_SYSTEM,
    build_opening_scene_prompt,
    parse_action
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
    
    def build_event_prompt(self, world_obj, player_action, parsed_action):

        lang = world_obj.get("lang_ui")
        parsed = json.loads(parsed_action)
        action_type = parsed.get("action_type", "social")
        target = parsed.get("target", "")
        intent = parsed.get("intent", "")
        topic = parsed.get("topic", "")
        risk = parsed.get("risk", "low")

        world_state = world_obj.get("world_state", {})
        player_stats = world_obj.get("player_stats", {})
        characters = world_obj.get("characters", [])

        info_level = self.control_information_layer(parsed, world_obj)
        chapter = world_obj["adventure_state"].get("chapter", 0)

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

            ==================== 玩家行为（解析后，必须使用） ====================
            action_type: {action_type}
            target: {target}
            intent: {intent}
            topic: {topic}
            risk: {risk}
            完整解析：{parsed_action}

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

        with open("gpt_log.txt", "a", encoding="utf-8") as f:
            f.write("\n\n==================== HEALTH CHANGE ====================\n")
            f.write(str(new_hp) + "\n")
            f.write("==================================================\n")
        
        return world_obj

    # ----------- 正常/最终回合 -----------

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

    # 生成下一回合剧情（包括 final 回合判断）
    def next_round(self, player_action):
        # 每一回合开始时，世界自动呼吸一次
        self.update_world_state()

        # 1) 构建事件 prompt（事件 JSON）
        parsed = parse_action(player_action)
        parsed_action = json.dumps(parsed, ensure_ascii=False)
        prompt = self.build_event_prompt(self.world_obj, player_action, parsed_action)
        self.update_npc_by_player_action(parsed, self.world_obj)

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
        # ---- 推进主线进度 ----
        self.advance_story()

        adv = self.world_obj.get("adventure_state", {})

        progress = self.world_obj["adventure_state"]["story_progress"]
        chapter = self.get_chapter(progress)
        self.world_obj["adventure_state"]["chapter"] = chapter
        
        self.save_given_info(event, self.world_obj)
        
        # 6.1) 如果主线满了，触发终章剧情
        if adv.get("story_progress", 0) >= 100 and not adv.get("final_triggered", False):

            adv["final_triggered"] = True
            self.world_obj["adventure_state"] = adv

            final_prompt = f"""
                你是这个世界的 DM。
                主线任务达成，请生成【终章事件】。

                你必须严格输出以下 JSON，不得多字不得少字：

                {{
                "dm_text": "用 {self.lang_ui} 写 4~6 句故事，总结整个冒险，只能使用 adventure_history 和 info_given 中已出现的元素，不得创造新地点、新角色、新魔法，也不得加入世界中从未提及的内容。",
                "options": [],
                "health_change": 0,
                "world_state_change": {{}},
                "player_change": {{}},
                "npc_change": []
                }}
                """

            final_raw = call_gpt(EVENT_SYSTEM, final_prompt, max_tokens=800)
            final_event = extract_json(final_raw)

            if final_event:
                # 写入记录
                self.state["history"].append({
                    "player": "(final)",
                    "dm": final_event["dm_text"]
                })

                # 清空 options，冒险结束
                self.state["options"] = []
            return final_event

        # 6) 回合数 +1
        self.state["round"] += 1

        return event

