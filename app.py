# app.py
import os
import json
import time
from io import BytesIO
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

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
# def call_gpt_system(system_prompt, user_prompt, max_tokens=500):
#     # 这里使用 gpt-4o 或 gpt-4-turbo 在你的 key 支持下，这里示例使用 gpt-3.5-turbo 兼容写法
#     resp = openai.ChatCompletion.create(
#         model="gpt-4o-mini" if "gpt-4o-mini" in openai.Model.list() else "gpt-3.5-turbo",
#         messages=[
#             {"role":"system","content":system_prompt},
#             {"role":"user","content":user_prompt}
#         ],
#         max_tokens=max_tokens,
#         temperature=0.8,
#     )
#     return resp["choices"][0]["message"]["content"].strip()

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
WORLD_GEN_USER = """Create a compact RPG world given this user idea:
{idea}

Output JSON with keys: title, summary, 3_locations (list), 3_characters (list of dict name+role+short_desc), initial_hook.
Provide brief creative notes after JSON.
"""

DM_SYSTEM = "You are an imaginative RPG Dungeon Master. Keep responses short and reference the world's facts."

# ---------- UI ----------
st.set_page_config(page_title="WorldWeaver MVP", layout="wide")
st.title("WorldWeaver — MVP（构建 / 玩耍 / 导出画册）")
st.markdown("输入一个创意，让 AI 帮你生成一个小世界，然后可以在其中进行一次简短的冒险并导出画册。")

# 左侧：创建世界
with st.sidebar:
    st.header("1) 创建新世界")
    idea = st.text_area("一句话概括你的世界（示例：被海水淹没的蒸汽城市）", height=80)
    world_name = st.text_input("给世界起个名字（英语优先）", value="MyWorld")
    if st.button("生成世界"):
        if not idea.strip():
            st.sidebar.error("先写一句话创意。")
        else:
            with st.spinner("生成中……"):
                user_prompt = WORLD_GEN_USER.format(idea=idea)
                out = call_gpt_system(WORLD_GEN_SYSTEM, user_prompt, max_tokens=600)
                # 尝试从文本中提取第一个 JSON 块
                import re
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
        st.write("-", loc)
    st.write("**主要角色**：")
    for ch in world_obj.get("3_characters", []):
        st.write("-", f"{ch.get('name')} — {ch.get('role')} — {ch.get('short_desc')}")
    st.write("**初始钩子**：", world_obj.get("initial_hook",""))

    # 交互冒险：简易对话轮次
    st.markdown("---")
    st.subheader("3) 进入冒险（一次短篇）")
    if "session_history" not in st.session_state:
        st.session_state.session_history = []
    player_input = st.text_input("你要做什么？（例如：我去港口调查白色号角）")
    if st.button("行动"):
        if not player_input.strip():
            st.warning("写点啥行动吧。")
        else:
            # 构造 prompt：把世界关键点带入
            world_text = json.dumps(world_obj, ensure_ascii=False)
            dm_prompt = f"""World facts: {world_text}

Player action: {player_input}

Respond as a Dungeon Master. Keep it immersive and update what happened. Also produce a short 'log' entry JSON with keys: event_summary, new_characters (list), new_locations (list)."""
            with st.spinner("AI 生成中……"):
                dm_resp = call_gpt_system(DM_SYSTEM, dm_prompt, max_tokens=400)
                st.markdown("**DM:**")
                st.write(dm_resp)
                # 把对话存到 session_state
                st.session_state.session_history.append({"player":player_input,"dm":dm_resp})
    # 展示历史
    if st.session_state.session_history:
        st.subheader("冒险记录")
        for i, it in enumerate(st.session_state.session_history[-10:]):
            st.markdown(f"**回合 {i+1}**")
            st.write("玩家：", it["player"])
            st.write("DM：", it["dm"])

    # 生成总结与画册
    st.markdown("---")
    st.subheader("4) 生成冒险总结与画册")
    if st.button("生成冒险总结（文本）"):
        history_text = "\n".join([f"Player: {h['player']}\nDM: {h['dm']}" for h in st.session_state.session_history])
        summary_prompt = f"请以英文为主，总结以下冒险为一段叙述风格的冒险回顾，突出情节要点和关键角色：\n\n{history_text}"
        with st.spinner("生成总结中……"):
            summary = call_gpt_system("You are an expert RPG chronicler who writes evocative summaries.", summary_prompt, max_tokens=400)
            st.text_area("冒险总结", value=summary, height=200)

    if st.button("生成并下载画册 (PDF)"):
        # 简易画册：封面 + 世界 summary + 并把图片占位
        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        w, h = A4
        c.setFont("Helvetica-Bold", 20)
        c.drawCentredString(w/2, h-80, world_obj.get("title","Untitled World"))
        c.setFont("Helvetica", 12)
        c.drawString(50, h-120, "Summary:")
        c.drawString(50, h-140, world_obj.get("summary",""))

        # 把冒险记录加入
        c.drawString(50, h-200, "Adventure Log:")
        y = h-220
        for it in st.session_state.session_history[-10:]:
            txt = f"Player: {it['player']}"
            c.drawString(55, y, txt[:80])
            y -= 14
            txt2 = f"DM: {it['dm']}"
            c.drawString(65, y, txt2[:80])
            y -= 18
            if y < 100:
                c.showPage()
                y = h-80
        c.showPage()
        c.save()
        buffer.seek(0)
        st.download_button("下载画册 PDF", data=buffer, file_name=f"{world_obj.get('title','world')}_book.pdf", mime="application/pdf")

else:
    st.info("先在左侧创建一个新世界（Create），然后回到这里选择。")

session.close()
