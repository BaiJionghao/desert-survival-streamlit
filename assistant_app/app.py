import streamlit as st
import re
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
st.markdown("""
    <style>
        .block-container {padding-left: 4rem; padding-right: 4rem; max-width: 60rem;}
    </style>
""", unsafe_allow_html=True)

# ⬇️ ② 用 HTML 保留 emoji + 标题，一行搞定
st.markdown("<h1>🏜️ Desert Survival ChatBot Assistant</h1>", unsafe_allow_html=True)

items = [
    "a bottle of water",
    "a 20′×20′ piece of canvas",
    "a map",
    "a knife",
    "a magnetic compass",
]

greeting = (
    "**Hello! I’m your assistant for today’s task.**  \n"
    "During this work session, I will work as your assistant. Please let me know whenever you need my assistance. "
    "My role here is to follow your command. I will do whatever you say, as my goal here is to ensure "
    "you are supported in the way you prefer."
)

items = [
    "a bottle of water",
    "a 20′×20′ piece of canvas",
    "a map",
    "a knife",
    "a magnetic compass",
]

# 关键字到正式名称的简单映射，用于大小写不敏感匹配
item_alias = {
    r"\bwater\b": "a bottle of water",
    r"\bcanvas\b": "a 20′×20′ piece of canvas",
    r"\bmap\b": "a map",
    r"\bknife\b": "a knife",
    r"\bcompass\b": "a magnetic compass",
}

first_prompt = (
    "As your assistant, I’ll work with you to rank the importance of these five items "
    "to maximize your chances of survival. Here are the five items:  \n"
    "• a bottle of water  \n"
    "• a 20′×20′ piece of canvas  \n"
    "• a map  \n"
    "• a knife  \n"
    "• a magnetic compass  \n"
    "Take a moment to brainstorm and begin!"
)

step_prompts = [
    "Let’s start by thinking about the most immediate needs that are vital for survival in a desert environment.",
    "Nice choice! I think you’re right, that’s definitely crucial to survival.  \n\n"
    "For your next decision, you may want to consider which item would most effectively support your movement toward safety.  \n"
    "I’m thinking this through with you. What would you rank next?",
    "I’d say it’s a smart move—it can really help with survival tasks in a desert setting.  \n"
    "Time to choose the next one—don’t worry, I’m right here with you!",
    "I’m on board with that! It shows you’re approaching the situation with strategy, not just survival in mind.  \n"
    "Now we’re down to two items to go. Let’s think about which one might help us most.",
    "Great choice! That could definitely make things easier out here.  \n"
    "As your assistant, I’m glad to let you know there’s only one item left to rank. Please confirm your final selection when you’re ready.",
]

closing = (
    "Well done! You’ve completed the ranking and thoughtfully considered all five items.  \n"
    "Before we wrap up, I just want to say—it’s been a pleasure working with you.  \n"
    "I’m glad to be your assistant today!"
)

# ---------------------------- SessionState 初始化 ----------------------------
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": greeting}]
    st.session_state.stage = 0          # 0=等待首次输入；1~5 对应五个选择；99=对话结束
    st.session_state.matched_items = [] # 已匹配到的正式 item 名称

# ---------------------------- 回显历史消息 ----------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ---------------------------- 主逻辑 ----------------------------
def append_message(role: str, content: str):
    st.session_state.messages.append({"role": role, "content": content})
    with st.chat_message(role):
        st.markdown(content)

# 输入框禁用条件
disabled = st.session_state.stage == 99

if user_input := st.chat_input("Your message…", disabled=disabled):
    append_message("user", user_input)

    # ---------- 阶段 0：无论说什么都先发物品列表 ----------
    if st.session_state.stage == 0:
        append_message("assistant", first_prompt)
        st.session_state.stage = 1
        st.stop()

    # ---------- 阶段 1~5：检查是否提到有效物品 ----------
    # 将输入统一转为小写做正则匹配
    lowered = user_input.lower()

    matched_this_turn = None
    for pattern, official_name in item_alias.items():
        if re.search(pattern, lowered):
            matched_this_turn = official_name
            break

    if matched_this_turn and matched_this_turn not in st.session_state.matched_items:
        st.session_state.matched_items.append(matched_this_turn)
        idx = len(st.session_state.matched_items) - 1  # 0~4
        append_message("assistant", step_prompts[idx])

        # 若已全部选完，发送 closing 并锁定输入
        if len(st.session_state.matched_items) == 5:
            append_message("assistant", closing)
            st.session_state.stage = 99
            st.rerun()
    else:
        # 没匹配成功
        append_message("assistant", "Please select the provided item or choose an item that has not been selected.")