# adventure.py
import re
import json
from llm import (
    call_gpt,
    DM_SYSTEM,
    build_opening_scene_prompt,
    build_next_scene_prompt
)

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

    # ----------- 开场回合 -----------

    # 开始冒险 → 生成开场剧情
    def start_adventure(self):
        prompt = build_opening_scene_prompt(self.world_obj, self.lang_ui)
        dm_resp = call_gpt(DM_SYSTEM, prompt, max_tokens=1200)

        options = self.extract_options(dm_resp)
        if not options:
            if self.lang_ui == "中文":
                options = ["继续探索", "调查角色", "前往未知地点"]
            else:
                options = ["Keep exploring", "Investigate a character", "Head to an unknown place"]

        self.state["history"].append({"player": "(start)", "dm": dm_resp})
        self.state["options"] = options
        self.state["round"] += 1

    # ----------- 正常/最终回合 -----------

    # 生成下一回合剧情（包括 final 回合判断）
    def next_round(self, player_choice):

        main_quest = self.world_obj.get("main_quest", "")
        history_text = self.recent_history_text()

        # 是否为最终回合（可以改回合数）
        is_final = (self.state["round"] == 4)

        prompt = build_next_scene_prompt(
            self.world_obj,
            main_quest,
            history_text,
            player_choice,
            self.lang_ui,
            is_final=is_final
        )

        dm_resp = call_gpt(DM_SYSTEM, prompt, max_tokens=1200)
        options = self.extract_options(dm_resp)

        if is_final:
            options = []

        # 更新状态
        self.state["history"].append({"player": player_choice, "dm": dm_resp})
        self.state["options"] = options
        self.state["round"] += 1

