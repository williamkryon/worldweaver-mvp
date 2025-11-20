# app.py
import os
import json
import time
from io import BytesIO
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import re

import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, Text, Float
from sqlalchemy.orm import declarative_base, sessionmaker
from openai import OpenAI

# ---------- UI 文本（中英双语） ----------
TEXT = {
    "ui_language": {
        "中文": "语言 / Language",
        "English": "Language"
    },
    "title": {
        "中文": "WorldWeaver — MVP（构建 / 玩耍 / 导出画册）",
        "English": "WorldWeaver — MVP (Build / Play / Export Artbook)"
    },
    "intro": {
        "中文": "输入一个创意，让 AI 帮你生成一个小世界，然后在其中进行一次简短的冒险，并可以导出 PDF 画册。",
        "English": "Enter an idea and let AI generate a small world. Play a short adventure in it and export a PDF artbook."
    },
    "sidebar_create_title": {
        "中文": "1) 创建新世界",
        "English": "1) Create New World"
    },
    "input_idea": {
        "中文": "一句话概括你的世界（示例：被海水淹没的蒸汽城市）",
        "English": "Describe your world in one sentence (e.g. A steam city drowned by the sea)"
    },
    "world_name": {
        "中文": "给世界起个名字（英语优先）",
        "English": "Name your world (English preferred)"
    },
    "button_generate_world": {
        "中文": "生成世界",
        "English": "Generate World"
    },
    "generate_world_spinner": {
        "中文": "生成世界中……",
        "English": "Generating world…"
    },
    "generate_world_need_idea": {
        "中文": "先写一句话创意。",
        "English": "Please enter a one-line idea first."
    },
    "section_world": {
        "中文": "2) 你的世界",
        "English": "2) Your Worlds"
    },
    "choose_world": {
        "中文": "选择已有世界",
        "English": "Select an existing world"
    },
    "new_world_label": {
        "中文": "-- 新建 --",
        "English": "-- New --"
    },
    "no_world_yet": {
        "中文": "请先在左侧创建一个新世界。",
        "English": "Please create a new world from the sidebar first."
    },
    "world_summary": {
        "中文": "简介",
        "English": "Summary"
    },
    "world_locations": {
        "中文": "地点",
        "English": "Locations"
    },
    "world_characters": {
        "中文": "主要角色",
        "English": "Main Characters"
    },
    "world_hook": {
        "中文": "初始钩子",
        "English": "Initial Hook"
    },
    "section_adventure": {
        "中文": "3) 进入冒险（多回合）",
        "English": "3) Enter Adventure (Multi-round)"
    },
    "adventure_history": {
        "中文": "冒险记录",
        "English": "Adventure History"
    },
    "round_label": {
        "中文": "回合",
        "English": "Round"
    },
    "player_label": {
        "中文": "玩家",
        "English": "Player"
    },
    "dm_label": {
        "中文": "DM",
        "English": "DM"
    },
    "start_adventure": {
        "中文": "开始冒险",
        "English": "Start Adventure"
    },
    "choose_action": {
        "中文": "选择你的行动：",
        "English": "Choose your action:"
    },
    "section_export": {
        "中文": "4) 生成冒险总结与画册",
        "English": "4) Generate Adventure Summary & Artbook"
    },
    "generate_summary": {
        "中文": "生成冒险总结（文本）",
        "English": "Generate Adventure Summary (text)",
    },
    "summary_spinner": {
        "中文": "生成总结中……",
        "English": "Generating summary…"
    },
    "summary_box_label": {
        "中文": "冒险总结",
        "English": "Adventure Summary"
    },
    "generate_pdf": {
        "中文": "生成画册 (PDF)",
        "English": "Generate Artbook (PDF)"
    },
    "download_pdf": {
        "中文": "下载画册 (PDF)",
        "English": "Download Artbook (PDF)"
    },
    "no_world_for_export": {
        "中文": "请先选择一个已生成的世界，然后再导出画册。",
        "English": "Please select a generated world before exporting the artbook."
    }
}

# PDF 内部标签
PDF_LABELS = {
    "summary": {"中文": "世界简介", "English": "Summary"},
    "log": {"中文": "冒险记录", "English": "Adventure Log"},
    "player": {"中文": "玩家", "English": "Player"},
    "dm": {"中文": "DM", "English": "DM"},
}

# ---------- 配置 ----------
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.error("请在项目根目录创建 .env 文件并写入 OPENAI_API_KEY=你的key")
    st.stop()

client = OpenAI(api_key=OPENAI_API_KEY)
DB_PATH = "sqlite:///worlds.db"

Base = declarative_base()
engine = create_engine(DB_PATH, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)


# ---------- 数据模型 ----------
class World(Base):
    __tablename__ = "worlds"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), unique=True)
    data = Column(Text)  # 存 JSON 字符串
    created_at = Column(Float)


Base.metadata.create_all(bind=engine)


# ---------- 辅助函数：调用 LLM ----------
def call_gpt_system(system_prompt, user_prompt, max_tokens=600):
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.8,
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"调用 OpenAI 接口出错: {e}")
        return "（出错了，没能生成内容。）"


# 生成世界的 prompt 模板
WORLD_GEN_SYSTEM = "You are an expert worldbuilder for tabletop RPGs. Produce concise structured JSON."
WORLD_GEN_USER = """Create a compact RPG world based on the user's idea:
{idea}

The user is writing in language: {lang}
Output **all JSON fields in the same language as the user's idea**.

Output JSON with keys:
- title
- summary
- 3_locations (list of dict: name, description)
- 3_characters (list of dict: name, role, short_desc)
- initial_hook

After the JSON, briefly provide creative notes (also in the same language).
"""

DM_SYSTEM = "You are an imaginative RPG Dungeon Master. Keep responses short and reference the world's facts."


# ---------- 冒险状态初始化 ----------
if "adventure" not in st.session_state:
    st.session_state.adventure = {
        "history": [],  # 每回合剧情
        "round": 0,
        "options": []   # 当前回合选项
    }


# ---------- 页面设置 ----------
st.set_page_config(page_title="WorldWeaver MVP", layout="wide")

# ---------- 侧边栏：语言选择 + 创建世界 ----------
with st.sidebar:
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

                user_prompt = WORLD_GEN_USER.format(idea=idea, lang=lang_ui)   
                out = call_gpt_system(WORLD_GEN_SYSTEM, user_prompt, max_tokens=600)

                # 提取 JSON
                m = re.search(r"(\{[\s\S]*\})", out)
                json_text = m.group(1) if m else None

                if not json_text:
                    data = {"title": world_name, "summary": out}
                else:
                    try:
                        data = json.loads(json_text)
                    except Exception:
                        data = {"title": world_name, "summary": out}

                # --- 同名覆盖 ---
                session = SessionLocal()
                existing = session.query(World).filter_by(name=world_name).first()

                if existing:
                    existing.data = json.dumps(data, ensure_ascii=False)
                    existing.created_at = time.time()
                    
                else:
                    new_world = World(
                        name=world_name,
                        data=json.dumps(data, ensure_ascii=False),
                        created_at=time.time()
                    )
                    session.add(new_world)
                    
                session.commit()
                session.close()

                st.success("世界已生成（同名已覆盖）！" if lang_ui == "中文" 
                        else "World generated (existing world overwritten)!")


# ---------- 主区域：标题 & 简介 ----------
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

world_obj = None
if sel and sel != new_world_label:
    for w in worlds:
        if w.name == sel:
            world_obj = json.loads(w.data)
            break

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

    # 冒险入口 / 回合逻辑
    # 第一次点击生成开场剧情
    if st.session_state.adventure["round"] == 0:
        if st.button(TEXT["start_adventure"][lang_ui]):
            prompt = f"""World facts: {json.dumps(world_obj, ensure_ascii=False)}
Generate an opening scene for a short adventure. Provide 3 action options formatted like:
1. xxx
2. xxx
3. xxx
Do NOT use numbered lists (1., 2., etc.) anywhere else in the story except within these 3 action options lines."""
            
            with st.spinner("AI 生成中……" if lang_ui == "中文" else "AI thinking…"):
                dm_resp = call_gpt_system(DM_SYSTEM, prompt, max_tokens=400)

            # 提取选项
            options = re.findall(r"\d\.\s(.+)", dm_resp)
            if not options:
                if lang_ui == "中文":
                    options = ["继续探索", "调查角色", "前往未知地点"]
                else:
                    options = ["Keep exploring", "Investigate a character", "Head to an unknown place"]
            st.session_state.adventure["history"].append({"player": "(start)", "dm": dm_resp})
            st.session_state.adventure["options"] = options
            st.session_state.adventure["round"] += 1

    # 展示最近的冒险历史
    if st.session_state.adventure["history"]:
        st.markdown(f"### {TEXT['adventure_history'][lang_ui]}")
        for i, it in enumerate(st.session_state.adventure["history"][-10:]):
            st.markdown(f"**{TEXT['round_label'][lang_ui]} {i+1}**")
            st.write(f"{TEXT['player_label'][lang_ui]}：", it["player"])
            st.write(f"{TEXT['dm_label'][lang_ui]}：", it["dm"])
            st.markdown("---")

    # 显示当前选项按钮
    if st.session_state.adventure["options"]:
        st.write(TEXT["choose_action"][lang_ui])
        for idx, opt in enumerate(st.session_state.adventure["options"]):
            if st.button(opt):
                player_choice = opt
                last_dm = st.session_state.adventure["history"][-1]["dm"]

                prompt = f"""Use {lang_ui}: World facts: {json.dumps(world_obj, ensure_ascii=False)}
Previous story: {last_dm}
Player chose: {player_choice}
Generate the next scene with 3 action options formatted like:
1. xxx
2. xxx
3. xxx
Do NOT use numbered lists (1., 2., etc.) anywhere else in the story except within these 3 action options lines."""
                
                with st.spinner("AI 生成中……" if lang_ui == "中文" else "AI thinking…"):
                    dm_resp = call_gpt_system(DM_SYSTEM, prompt, max_tokens=400)
                options = re.findall(r"\d\.\s(.+)", dm_resp)
                if not options:
                    options = ["继续探索", "调查角色", "前往未知地点"] if lang_ui == "中文" else [
                        "Keep exploring", "Investigate a character", "Head to an unknown place"
                    ]
                st.session_state.adventure["history"].append({"player": player_choice, "dm": dm_resp})
                st.session_state.adventure["options"] = options
                st.session_state.adventure["round"] += 1
                st.rerun()

else:
    st.info(TEXT["no_world_yet"][lang_ui])

# ---------- 4) 生成总结与画册 ----------
st.markdown("---")
st.subheader(TEXT["section_export"][lang_ui])


def split_into_paragraphs(text: str):
    """根据空行和 1./2./3. 分段，保持原来的语义顺序。"""
    lines = text.split("\n")

    paragraphs = []
    buffer = []

    for line in lines:
        stripped = line.strip()

        # 空行 → 结束当前段
        if stripped == "":
            if buffer:
                paragraphs.append(" ".join(buffer))
                buffer = []
            continue

        # 列表项（如 1. xxx / 2. xxx）
        if re.match(r"^\d+\.\s", stripped):
            if buffer:
                paragraphs.append(" ".join(buffer))
                buffer = []
            paragraphs.append(stripped)
            continue

        buffer.append(stripped)

    if buffer:
        paragraphs.append(" ".join(buffer))

    return paragraphs


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
            summary = call_gpt_system(
                "You are an expert RPG chronicler who writes evocative summaries.",
                summary_prompt,
                max_tokens=400
            )
        st.text_area(TEXT["summary_box_label"][lang_ui], value=summary, height=200)


# PDF 画册导出
if st.button(TEXT["generate_pdf"][lang_ui]):
    if not world_obj:
        st.warning(TEXT["no_world_for_export"][lang_ui])
    else:
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfbase import pdfmetrics
        from reportlab.lib.units import mm

        # 注册中文字体
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm
        )

        styles = getSampleStyleSheet()
        normal = styles["Normal"]
        normal.fontName = "STSong-Light"
        title_style = styles["Title"]
        title_style.fontName = "STSong-Light"

        story = []

        # 标题
        story.append(Paragraph(world_obj.get("title", "Untitled World"), title_style))
        story.append(Spacer(1, 10))

        # 世界简介
        story.append(Paragraph(f"<b>{PDF_LABELS['summary'][lang_ui]}</b>", normal))
        story.append(Paragraph(world_obj.get("summary", ""), normal))
        story.append(Spacer(1, 12))

        # 冒险记录
        story.append(Paragraph(f"<b>{PDF_LABELS['log'][lang_ui]}</b>", normal))
        story.append(Spacer(1, 8))

        for it in st.session_state.adventure["history"]:
            # Player 段落
            story.append(Paragraph(f"<b>{PDF_LABELS['player'][lang_ui]}:</b>", normal))
            player_paras = split_into_paragraphs(str(it["player"]))
            for p in player_paras:
                story.append(Paragraph(p, normal))
                story.append(Spacer(1, 4))

            # DM 段落
            story.append(Paragraph(f"<b>{PDF_LABELS['dm'][lang_ui]}:</b>", normal))
            dm_paras = split_into_paragraphs(str(it["dm"]))
            for p in dm_paras:
                story.append(Paragraph(p, normal))
                story.append(Spacer(1, 4))

            story.append(Spacer(1, 8))

        doc.build(story)
        buffer.seek(0)

        st.download_button(
            TEXT["download_pdf"][lang_ui],
            data=buffer,
            file_name=f"{world_obj.get('title','world')}_book.pdf",
            mime="application/pdf"
        )

session.close()
