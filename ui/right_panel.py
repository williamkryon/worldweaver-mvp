import streamlit as st

def render_right_panel(world_obj, session_state):
    # 根据 UI 语言选择标题
    lang = world_obj.get("lang_ui", "English")
    inv_label = "物品栏" if lang == "中文" else "Inventory"
    st.subheader(inv_label)
    inv = world_obj.get("inventory", {})

    with st.expander("资源" if lang == "中文" else "Resources"):
        for k, v in inv.get("resources", {}).items():
            st.write(f"{k}: {v}")

    with st.expander("道具" if lang == "中文" else "Items"):
        for item in inv.get("items", []):
            st.write(f"- {item.get('name', '')}: {item.get('desc', '')}")

    with st.expander("世界碎片" if lang == "中文" else "Lore Fragments"):
        for lore in inv.get("lore", []):
            st.write(f"**{lore.get('title','')}**")
            st.write(lore.get("text", ""))
            st.markdown("---")

    player_label = "玩家属性" if lang == "中文" else "Player Stats"
    st.subheader(player_label)
    stats = world_obj.get("player_stats", {})
    logic = world_obj.get("world_logic", {})

    # 如果没有魔法，则不显示 mana
    for k, v in stats.items():
        if k == "mana" and not logic.get("allow_magic", False):
            continue
        st.write(f"{k}: {v}")

    comp_label = "同伴" if lang == "中文" else "Companions"
    st.subheader(comp_label)
    for ch in world_obj.get("characters", []):
            st.write(f"{ch.get('name','')} — trust {ch.get('stats',{}).get('trust','?')}, health {ch.get('stats',{}).get('health','?')}")
