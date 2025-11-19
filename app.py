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
# import openai
from sqlalchemy import create_engine, Column, Integer, String, Text, Float
from sqlalchemy.orm import declarative_base, sessionmaker
from openai import OpenAI

# ---------- 配置 ----------
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.error("请在项目根目录创建 .env 文件并写入 OPENAI_API_KEY=你的key")
    st.stop()
# openai.api_key = OPENAI_API_KEY
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
            model="gpt-4o-mini",  # 或 "gpt-4o" / "gpt-4-turbo" 看你的key支持哪个
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.8,
        )
        return completion.choices[0].message.content.strip()

    except Exception as e:
        # Streamlit显示错误信息
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


# 初始化 session_state
if "adventure" not in st.session_state:
    st.session_state.adventure = {
        "history": [],  # 每回合剧情
        "round": 0,
        "options": []   # 当前回合选项
    }

# ---------- UI ----------
st.set_page_config(page_title="WorldWeaver MVP", layout="wide")
st.title("WorldWeaver — MVP（构建 / 玩耍 / 导出画册）")
st.markdown("输入一个创意，让 AI 帮你生成一个小世界，然后可以在其中进行一次简短的冒险并导出画册。")

# 左侧：创建世界
with st.sidebar:
    st.header("1) 创建新世界")
    idea = st.text_area(
        "一句话概括你的世界（示例：被海水淹没的蒸汽城市）",
        height=80
    )

    # 检测语言
    from langdetect import detect
    idea_stripped = idea.strip()
    if idea_stripped:
        try:
            lang = detect(idea_stripped)
        except:
            lang = "zh"  # 默认中文，如果检测失败
    else:
        lang = "zh"  # 没输入内容时默认中文
    world_name = st.text_input("给世界起个名字（英语优先）", value="MyWorld")
    if st.button("生成世界"):
        if not idea.strip():
            st.sidebar.error("先写一句话创意。")
        else:
            with st.spinner("生成中……"):
                user_prompt = WORLD_GEN_USER.format(idea=idea, lang=lang)
                out = call_gpt_system(WORLD_GEN_SYSTEM, user_prompt, max_tokens=600)
                # 尝试从文本中提取第一个 JSON 块
                m = re.search(r"(\{[\s\S]*\})", out)
                json_text = m.group(1) if m else None
                if not json_text:
                    # 直接包成一个简单结构
                    data = {"title": world_name, "summary": out}
                else:
                    try:
                        data = json.loads(json_text)
                    except Exception as e:
                        data = {"title": world_name, "summary": out}
                # 存 DB
                session = SessionLocal()
                w = World(name=world_name, data=json.dumps(data, ensure_ascii=False), created_at=time.time())
                session.add(w)
                session.commit()
                session.close()
                st.sidebar.success("世界已生成并保存！")

# 中间：选择世界 & 展示
st.header("2) 你的世界")
session = SessionLocal()
worlds = session.query(World).all()
world_names = [w.name for w in worlds]
sel = st.selectbox("选择已有世界", ["-- 新建 --"] + world_names)
world_obj = None
if sel and sel != "-- 新建 --":
    for w in worlds:
        if w.name == sel:
            world_obj = json.loads(w.data)
            break
if world_obj:
    st.subheader(world_obj.get("title", sel))
    st.write("**简介**：", world_obj.get("summary",""))

    st.write("**地点**：")
    for loc in world_obj.get("3_locations", []):
        st.write(f"- {loc.get('name','')} — {loc.get('description','')}")

    st.write("**主要角色**：")
    for ch in world_obj.get("3_characters", []):
        st.write(f"- {ch.get('name','')} — {ch.get('role','')} — {ch.get('short_desc','')}")

    st.write("**初始钩子**：", world_obj.get("initial_hook",""))

    # 交互冒险：简易对话轮次
    st.markdown("---")
    st.subheader("3) 进入冒险（多回合）")

    # 展示历史
    for i, it in enumerate(st.session_state.adventure["history"][-10:]):
        st.markdown(f"**回合 {i+1}**")
        st.write("玩家：", it["player"])
        st.write("DM：", it["dm"])

    # 第一次点击生成开场剧情
    if st.session_state.adventure["round"] == 0:
        if st.button("开始冒险"):
            prompt = f"""World facts: {json.dumps(world_obj, ensure_ascii=False)}
    Generate an opening scene for a short adventure. Provide 3 action options formatted like:
    1. xxx
    2. xxx
    3. xxx"""
            with st.spinner("AI 生成中……"):
                dm_resp = call_gpt_system(DM_SYSTEM, prompt, max_tokens=400)
            # 提取选项
            options = re.findall(r"\d\.\s(.+)", dm_resp)
            if not options:
                options = ["继续探索", "调查角色", "前往未知地点"]  # 兜底选项
            st.session_state.adventure["history"].append({"player":"(start)", "dm":dm_resp})
            st.session_state.adventure["options"] = options
            st.session_state.adventure["round"] += 1

    # 显示当前选项
    if st.session_state.adventure["options"]:
        st.write("选择你的行动：")
        for idx, opt in enumerate(st.session_state.adventure["options"]):
            if st.button(opt):
                player_choice = opt
                last_dm = st.session_state.adventure["history"][-1]["dm"]
                # 生成下一回合剧情
                prompt = f"""Use the language of this world ({lang}): World facts: {json.dumps(world_obj, ensure_ascii=False)}
    Previous story: {last_dm}
    Player chose: {player_choice}
    Generate the next scene with 3 action options formatted like:
    1. xxx
    2. xxx
    3. xxx"""
                with st.spinner("AI 生成中……"):
                    dm_resp = call_gpt_system(DM_SYSTEM, prompt, max_tokens=400)
                options = re.findall(r"\d\.\s(.+)", dm_resp)
                if not options:
                    options = ["继续探索", "调查角色", "前往未知地点"]
                st.session_state.adventure["history"].append({"player":player_choice, "dm":dm_resp})
                st.session_state.adventure["options"] = options
                st.session_state.adventure["round"] += 1

# ---------- 展示历史 ----------
if st.session_state.adventure["history"]:
    st.subheader("冒险记录")
    for i, it in enumerate(st.session_state.adventure["history"][-10:]):
        st.markdown(f"**回合 {i+1}**")
        st.write("玩家：", it["player"])
        st.write("DM：", it["dm"])

# ---------- 生成总结与画册 ----------
st.markdown("---")
st.subheader("4) 生成冒险总结与画册")

if st.button("生成冒险总结（文本）"):
    history_text = "\n".join([f"Player: {h['player']}\nDM: {h['dm']}" for h in st.session_state.adventure["history"]])
    summary_prompt = f"请总结以下冒险为一段叙述风格的冒险回顾，突出情节要点和关键角色：\n\n{history_text}"
    with st.spinner("生成总结中……"):
        summary = call_gpt_system("You are an expert RPG chronicler who writes evocative summaries.", summary_prompt, max_tokens=400)
    st.text_area("冒险总结", value=summary, height=200)

if st.button("生成并下载画册 (PDF)"):
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase import pdfmetrics

    # 注册中文字体
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    w, h = A4

    # 标题字体
    c.setFont("STSong-Light", 20)
    c.drawCentredString(w/2, h-80, world_obj.get("title","Untitled World"))

    c.setFont("STSong-Light", 12)

    # 世界 summary
    c.drawString(50, h-120, "Summary:")
    summary_lines = simpleSplit(world_obj.get("summary",""), "STSong-Light", 12, w-100)
    y = h-140
    for line in summary_lines:
        c.drawString(50, y, line)
        y -= 14

    # 冒险记录
    c.drawString(50, y-20, "Adventure Log:")
    y -= 40
    for it in st.session_state.adventure["history"][-10:]:
        for prefix, txt in [("Player: ", it["player"]), ("DM: ", it["dm"])]:
            lines = simpleSplit(txt, "STSong-Light", 12, w-100)
            for line in lines:
                if y < 50:
                    c.showPage()
                    c.setFont("STSong-Light", 12)
                    y = h-50
                c.drawString(50, y, prefix + line)
                prefix = ""  # 只有第一行加前缀
                y -= 14
        y -= 10

    c.showPage()
    c.save()
    buffer.seek(0)
    st.download_button(
        "下载画册 PDF",
        data=buffer,
        file_name=f"{world_obj.get('title','world')}_book.pdf",
        mime="application/pdf"
    )


else:
    st.info("先在左侧创建一个新世界（Create），然后回到这里选择。")

session.close()
