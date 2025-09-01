import streamlit as st
import re
import time
import random

ROLE = "assistant"     # 固定角色

st.set_page_config(page_title="Desert Survival · Assistant", page_icon="🤖")
st.markdown(
    """
    <style>
        /* 页面宽度 */
        .block-container {padding-left:4rem; padding-right:4rem; max-width:60rem;}

        /* --- 用户整行容器：外层 stChatMessage 有 user-avatar 时翻转 --- */
        [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
            flex-direction: row-reverse !important;          /* 头像在右，气泡在左 */
        }

        /* --- 用户头像+气泡的里层容器 --- */
        [data-testid="stChatMessageAvatarUser"] {
            align-items: center !important;                  /* 头像垂直居中 ✔️ */
        }

        /* --- 用户文字气泡 --- */
        [data-testid="stChatMessageAvatarUser"] .stMarkdown {
            border-radius: .5rem !important;
            padding: .5rem .75rem !important;
            text-align: right !important;
        }

        /* --- 头像左右留缝隙 --- */
        [data-testid="stChatMessageAvatarUser"] img {
            margin-left: .5rem !important;
            margin-right: 0 !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# ⬇️ ② 用 HTML 保留 emoji + 标题，一行搞定
st.markdown("<h1>🏜️ Desert Survival Assistant</h1>", unsafe_allow_html=True)

items = [
    "a bottle of water",
    "a 20′×20′ piece of canvas",
    "a map",
    "a knife",
    "a magnetic compass",
]

item_alias = {
    r"\bwater\b": "a bottle of water",
    r"\bcanvas\b": "a 20′×20′ piece of canvas",
    r"\bmap\b": "a map",
    r"\bknife\b": "a knife",
    r"\bcompass\b": "a magnetic compass",
}

greeting_and_prompt = (
    "**Hello! I’m your assistant for today’s task.**  \n"
    "During this work session, I will work as your assistant. Please let me know whenever you need my assistance. "
    "My role here is to follow your command. I will do whatever you say, as my goal here is to ensure "
    "you are supported in the way you prefer.  \n\n"
    "As your assistant, I’ll work with you to rank the importance of these five items "
    "to maximize your chances of survival. Here are the five items:  \n"
    "• a bottle of water  \n"
    "• a 20′×20′ piece of canvas  \n"
    "• a map  \n"
    "• a knife  \n"
    "• a magnetic compass  \n"
    "Take a moment to brainstorm and say **“OK”** to begin!"
)

first_step_prompt = (
    "Let’s start by thinking about the most immediate needs that are vital for survival in a desert environment."
)

step_prompts = [
    "Nice choice! I think you’re right, that’s definitely crucial to survival.  \n"
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
    "Before we wrap up, I just want to say—it’s been a pleasure working with you."
)

# ---------------------------- SessionState 初始化 ----------------------------
# stage: 0=等待 OK；1~5=已成功选择 n 个物品；99=结尾
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": greeting_and_prompt}]
    st.session_state.stage = 0
    st.session_state.matched_items = []
# ⬇️ 新增：启动时间与超时标记（只初始化一次）
if "start_time" not in st.session_state:
    st.session_state.start_time = time.time()
if "time_up" not in st.session_state:
    st.session_state.time_up = False

# ⬇️ 新增：每次刷新检查是否超时（未完成对话且超过5分钟）
if (not st.session_state.time_up) and (st.session_state.stage != 99):
    elapsed = time.time() - st.session_state.start_time
    if elapsed >= 300:
        st.session_state.time_up = True

# ---------------------------- 工具函数 ----------------------------
def append_message(role: str, content: str):
    # 在“新生成的助手回复”前显示随机 3-5 秒的加载动画（历史回显不走这个函数）
    if role == "assistant":
        with st.spinner("Generating a reply..."):
            time.sleep(random.uniform(3, 5))
    st.session_state.messages.append({"role": role, "content": content})
    with st.chat_message(role):
        st.markdown(content)

# ---------------------------- 回显历史 ----------------------------
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# ⬇️ 新增：若已到时间且未完成，直接在页面输出提示
if st.session_state.time_up and st.session_state.stage != 99:
    st.warning(
        "⛔ The time limit has ended. Please enter the final ranking in the text box below."
    )

# ---------------------------- 主逻辑 ----------------------------
# ⬇️ 修改：超时也会禁用输入框
disabled = (st.session_state.stage == 99) or st.session_state.get("time_up", False)

if user_input := st.chat_input("Your message…", disabled=disabled):
    append_message("user", user_input)
    lowered = user_input.strip().lower()

    # 若已超时则不再处理任何逻辑（防御性判断，通常不会触发，因为已禁用输入框）
    if st.session_state.get("time_up", False):
        st.stop()

    # ---------- 阶段 0：等待 “ok” ----------
    if st.session_state.stage == 0:
        if lowered == "ok":
            append_message("assistant", first_step_prompt)
            st.session_state.stage = 1
        else:
            append_message("assistant", 'Please input **"OK"** to begin.')
        st.stop()

    # ---------- 阶段 1~5：物品匹配 ----------
    matched_item = None
    for pat, official in item_alias.items():
        if re.search(pat, lowered):
            matched_item = official
            break

    if (
        matched_item
        and matched_item not in st.session_state.matched_items
        and st.session_state.stage <= 5
    ):
        st.session_state.matched_items.append(matched_item)
        # len==1 对应 step_prompts[0]，以此类推
        idx = len(st.session_state.matched_items) - 1
        if idx < 4:  # 前四次
            append_message("assistant", step_prompts[idx])
        else:        # 第五次直接结束
            append_message("assistant", closing)
            st.session_state.stage = 99
            st.rerun()
        st.session_state.stage += 1
    else:
        append_message(
            "assistant",
            "Please select the provided item or choose an item that has not been selected."
            if st.session_state.stage < 99
            else "Chat has ended.",
        )
