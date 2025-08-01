import streamlit as st
import scipy.stats as stats

EXPERT_RANK = [
    "a bottle of water",
    "a 20′×20′ piece of canvas",
    "a magnetic compass",
    "a map",
    "a knife",
]

def score_ranking(user_rank):
    idx_u = {item: i for i, item in enumerate(user_rank)}
    idx_e = {item: i for i, item in enumerate(EXPERT_RANK)}
    u = [idx_u[it] for it in EXPERT_RANK]
    e = [idx_e[it] for it in EXPERT_RANK]
    rho, _ = stats.spearmanr(u, e)
    return round((rho + 1) / 2, 3)  # 映射到 0~1

ROLE = "assistant"     # 固定角色

st.set_page_config(page_title="Desert Survival · Assistant", page_icon="🤖")
st.title("🏜️ Desert Survival Ranking Task · Assistant")

st.info("""
**Hello! I’m your assistant for today’s task.**  
During this work session, I will work as your assistant. Please let me know whenever you need my assistance. 
My role here is to follow your command. I will do whatever you say, as my goal here is to ensure 
you are supported in the way you prefer. 
""", icon="🤖")

items = [
    "a bottle of water",
    "a 20′×20′ piece of canvas",
    "a map",
    "a knife",
    "a magnetic compass",
]

rank = st.multiselect(
    "请按重要性顺序点击物品（先点=更重要）：",
    options=items,
    default=[],
)

if len(rank) == 5 and st.button("提交并评分"):
    st.success(f"你的得分：{score_ranking(rank)} / 1.0")
    st.balloons()
