# app.py
import os
import json
import time
from PIL import Image
import re

import streamlit as st
from ui.right_panel import render_right_panel

from db import SessionLocal, World, init_db
from llm import call_gpt
from world import generate_world, save_world_to_db
from text import TEXT, PDF_LABELS
from pdf_export import generate_pdf
from adventure import AdventureManager

# ---------- 冒险状态初始化 ----------
if "adventure" not in st.session_state:
    st.session_state.adventure = {
        "history": [],  # 每回合剧情
        "round": 0,
        "options": []   # 当前回合选项
    }


# ---------- 数据库设置 ----------
init_db()

# ---------- 页面设置 ----------
st.set_page_config(page_title="WorldWeaver MVP", layout="wide")

# ----- 初始化 session_state -----
if "world_obj" not in st.session_state:
    st.session_state.world_obj = None

if "adventure" not in st.session_state:
    st.session_state.adventure = {
        "history": [],
        "options": [],
        "round": 0
    }

# ---------- 主区域布局：左主区 + 右侧栏 ----------
col_main, col_right = st.columns([3,1])
# ---------- 固定右侧栏 ----------
with col_right:
    # UI 语言选择
    lang_ui = st.selectbox(
        TEXT["ui_language"]["中文"],
        ["中文", "English"]
    )

    st.markdown("---")
    st.header(TEXT["sidebar_create_title"][lang_ui])

    idea = st.text_area(
        TEXT["input_idea"][lang_ui],
        height=80
    )

    world_name = st.text_input(TEXT["world_name"][lang_ui], value="MyWorld")
    
    if st.button(TEXT["button_generate_world"][lang_ui]):
        if not idea.strip():
            st.error(TEXT["generate_world_need_idea"][lang_ui])
        else:
            with st.spinner(TEXT["generate_world_spinner"][lang_ui]):
                with st.spinner(TEXT["generate_world_spinner"][lang_ui]):
                    world_obj = generate_world(idea, world_name, lang_ui)
                    save_world_to_db(world_name, world_obj)

                st.success("世界已生成（同名已覆盖）！" if lang_ui == "中文" 
                        else "World generated (existing world overwritten)!")


# ---------- 主区域：标题 & 简介 ----------
with col_main: 
    st.title(TEXT["title"][lang_ui])
    st.markdown(TEXT["intro"][lang_ui])
    st.markdown("---")

    # ---------- 2) 世界选择与展示 ----------
    st.header(TEXT["section_world"][lang_ui])

    session = SessionLocal()
    worlds = session.query(World).all()
    world_names = [w.name for w in worlds]

    new_world_label = TEXT["new_world_label"][lang_ui]
    sel = st.selectbox(TEXT["choose_world"][lang_ui], [new_world_label] + world_names)


    # --------- 世界选择逻辑（最终正确版本） ---------

    # 如果用户选择了一个世界
    if sel and sel != new_world_label:
        # 如果这是第一次选择 或 切换世界
        if st.session_state.get("last_world") != sel:
            # 从数据库读取一次
            for w in worlds:
                if w.name == sel:
                    st.session_state.world_obj = json.loads(w.data)
                    break

            # 重置冒险状态
            st.session_state.adventure = {
                "history": [],
                "round": 0,
                "options": []
            }
            st.session_state.last_world = sel

    # 如果界面需要 world_obj 就从 session_state 拿
    world_obj = st.session_state.world_obj

    if world_obj:        
        # 世界信息展示
        st.subheader(world_obj.get("title", sel))

        # 删除世界按钮
        if st.button("删除这个世界" if lang_ui == "中文" else "Delete this world"):
            session = SessionLocal()
            session.query(World).filter_by(name=sel).delete()
            session.commit()
            session.close()
            st.success("已删除。" if lang_ui == "中文" else "Deleted.")
            st.rerun()

        # 简介
        st.markdown(f"**{TEXT['world_summary'][lang_ui]}**")
        st.write(world_obj.get("summary", ""))

        # 地点
        locations = world_obj.get("3_locations", [])
        if locations:
            st.markdown(f"**{TEXT['world_locations'][lang_ui]}**")
            for loc in locations:
                st.write(f"- {loc.get('name','')} — {loc.get('description','')}")

        # 角色
        characters = world_obj.get("3_characters", [])
        if characters:
            st.markdown(f"**{TEXT['world_characters'][lang_ui]}**")
            for ch in characters:
                st.write(f"- {ch.get('name','')} — {ch.get('role','')} — {ch.get('short_desc','')}")

        # 初始钩子
        st.markdown(f"**{TEXT['world_hook'][lang_ui]}**")
        st.write(world_obj.get("initial_hook", ""))

        st.markdown("---")
        st.subheader(TEXT["section_adventure"][lang_ui])


        # ---- 构造 recent history（给 DM prompt 使用） ----
        history = st.session_state.adventure["history"]
        
        adv = AdventureManager(world_obj, lang_ui, st.session_state)

        recent = history[-3:]  # 最近三回合。可改成 history 全部
        history_text = ""
        for h in recent:
            history_text += f"Player: {h['player']}\nDM: {h['dm']}\n\n"

        # 冒险入口 / 回合逻辑
        # 第一次点击生成开场剧情
        if st.session_state.adventure["round"] == 0:
            if st.button(TEXT["start_adventure"][lang_ui]):
                adv.start_adventure()
                st.rerun()

        # 展示最近的冒险历史

        history = st.session_state.adventure["history"]
        total_rounds = len(history)

        if total_rounds:
            st.markdown(f"### {TEXT['adventure_history'][lang_ui]}")

            # 只显示最近 10 条，但保留真实回合号
            start_index = max(0, total_rounds - 10)

            for idx in range(start_index, total_rounds):
                it = history[idx]
                round_no = idx + 1  # 真正的第几回合（从 1 开始）

                st.markdown(f"**{TEXT['round_label'][lang_ui]} {round_no}**")
                st.write(f"{TEXT['player_label'][lang_ui]}：", it["player"])
                st.write(f"{TEXT['dm_label'][lang_ui]}：", it["dm"])
                st.markdown("---")

        # 显示当前选项按钮
    if st.session_state.adventure["options"]:
        # ---------- 显示按钮 ----------
        st.write(TEXT["choose_action"][lang_ui])
        for opt in st.session_state.adventure["options"]:
            if st.button(opt):
                event, updated_world = adv.next_round(opt)
                # 更新世界数据（侧栏需要）
                st.session_state.world_obj = updated_world
                with open("gpt_log.txt", "a", encoding="utf-8") as f:
                    f.write("\n\n==================== HEALTH CHANGE ====================\n")
                    f.write(str(updated_world["player_stats"]["health"]) + "\n")
                    f.write(str(world_obj["player_stats"]["health"]) + "\n")
                    f.write(str(st.session_state.world_obj["player_stats"]["health"]) + "\n")
                    f.write("==================================================\n")
                st.session_state.world_obj['player_stats']["health"] = world_obj["player_stats"]["health"]
                st.session_state.adventure["history"] = adv.state["history"]
                st.session_state.adventure["options"] = adv.state["options"]
                st.session_state.adventure["round"] = adv.state["round"]
                st.rerun()


    else:
        st.info(TEXT["no_world_yet"][lang_ui])

    # ---------- 4) 生成总结与画册 ----------
    st.markdown("---")
    st.subheader(TEXT["section_export"][lang_ui])

    # 文本总结
    if st.button(TEXT["generate_summary"][lang_ui]):
        if not st.session_state.adventure["history"]:
            msg = "还没有任何冒险记录可以总结。" if lang_ui == "中文" else "There is no adventure history to summarize yet."
            st.warning(msg)
        else:
            history_text = "\n".join([f"Player: {h['player']}\nDM: {h['dm']}" for h in st.session_state.adventure["history"]])
            if lang_ui == "中文":
                summary_prompt = f"请总结以下冒险为一段叙述风格的冒险回顾，突出情节要点和关键角色：\n\n{history_text}"
            else:
                summary_prompt = f"Summarize the following adventure as a narrative recap, highlighting key plot points and important characters:\n\n{history_text}"

            with st.spinner(TEXT["summary_spinner"][lang_ui]):
                summary = call_gpt(
                    "You are an expert RPG chronicler who writes evocative summaries.",
                    summary_prompt,
                    max_tokens=1200
                )
            st.text_area(TEXT["summary_box_label"][lang_ui], value=summary, height=200)


    # PDF 画册导出
    if st.button(TEXT["generate_pdf"][lang_ui]):
        if not world_obj:
            st.warning(TEXT["no_world_for_export"][lang_ui])
        else:
            buffer = generate_pdf(
                world_obj,
                st.session_state.adventure["history"],
                PDF_LABELS,
                lang_ui
            )

            st.download_button(
                TEXT["download_pdf"][lang_ui],
                data=buffer,
                file_name=f"{world_obj.get('title','world')}_book.pdf",
                mime="application/pdf"
            )

# ---------- 侧边栏：属性和物品栏 ----------
with st.sidebar:
    if st.session_state.world_obj:
        st.subheader("玩家属性")
        st.write(f"Health: {st.session_state.world_obj['player_stats'].get('health', 100)}")

session.close()
