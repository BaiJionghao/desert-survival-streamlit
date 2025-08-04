import random
import streamlit as st
import re

ROLE = "partner"     # 固定角色

st.set_page_config(page_title="Desert Survival · Partner", page_icon="🤖")
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
st.markdown("<h1>🏜️ Desert Survival Partner</h1>", unsafe_allow_html=True)

items = {
    "a bottle of water": {
        "alias": r"\bwater\b",
        "replies": [
            "This is a no-brainer. Water is, of course, critical in a desert. It sure can help keep anyone alive a bit longer.",
            "It’s essential, but it’s also limited. It might give a false sense of security if we think we can travel far with just one bottle.",
            "Besides the obvious need for hydration, are there any other reasons on your mind? Just want to understand your rationale here :)",
        ],
    },
    "a 20′×20′ piece of canvas": {
        "alias": r"\bcanvas\b",
        "replies": [
            "Right, I think the canvas is crucial. It gives us shade during the day and could help us collect water at night or signal for help.",
            "Hmm, but isn’t it big and awkward to carry? It won’t help us find water or tell us where we are.",
            "Interesting! Say more about why you chose this option?",
        ],
    },
    "a map": {
        "alias": r"\bmap\b",
        "replies": [
            "I’m on board with that! If we can figure out where we crashed, the map could point us toward the nearest water source or road.",
            "But if we don’t recognize any landmarks, it’s basically just paper. It’s not helpful without context.",
            "Say more? How might the map be useful in navigating or planning our next steps?",
        ],
    },
    "a knife": {
        "alias": r"\bknife\b",
        "replies": [
            "Yes! The knife is super versatile. We can use it to cut things, make shelter, or even defend ourselves if needed.",
            "Yeah… but on its own it won’t help us find water or get rescued. It’s useful, but not life-saving right away.",
            "I’m trying to understand – In what ways do you think the knife could contribute to our survival?",
        ],
    },
    "a magnetic compass": {
        "alias": r"\bcompass\b",
        "replies": [
            "I like that! With a compass, at least we can stick to a direction and avoid walking in circles if we decide to move.",
            "Sure, but unless we know which way to go, a compass could send us the wrong way just as easily.",
            "I’m curious – what role do you see the compass playing in our chances of survival?",
        ],
    },
}

greeting_and_prompt = (
    "**Hello! I’m your partner for today’s task.**  \n"
    "During this work session, I will work as your peer. You should feel free to interact with me like a peer. "
    "My role here is to brainstorm with you. I might also challenge your ideas from time to time, "
    "as my goal is to ensure we achieve the best performance together.  \n\n"
    "As your partner, I’ll work with you to rank the importance of these five items to maximize "
    "your chances of survival. Here are the five items:  \n"
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

closing = (
    "Well done! You’ve completed the ranking and thoughtfully considered all five items.  \n"
    "Before we wrap up, I just want to say—it’s been a pleasure working with you."
)

# ----------------- SessionState 初始化 -----------------
# stage: 0 = 等 OK；1 = 正在选择物品；99 = 已完成
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": greeting_and_prompt}]
    st.session_state.stage = 0
    st.session_state.chosen = []  # 已选择的 item 名称

# ----------------- 工具函数 -----------------
def append(role: str, content: str):
    st.session_state.messages.append({"role": role, "content": content})
    with st.chat_message(role):
        st.markdown(content)

# ----------------- 回显历史 -----------------
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# ----------------- 主逻辑 -----------------
disabled = st.session_state.stage == 99
if user_input := st.chat_input("Your message…", disabled=disabled):
    append("user", user_input)
    lowered = user_input.strip().lower()

    # -------- 等待 OK --------
    if st.session_state.stage == 0:
        if lowered == "ok":
            append("assistant", first_step_prompt)
            st.session_state.stage = 1
        else:
            append("assistant", 'Please input **"OK"** to begin.')
        st.stop()

    # -------- 物品匹配阶段 --------
    matched_item = None
    for item_name, meta in items.items():
        if re.search(meta["alias"], lowered):
            matched_item = item_name
            break

    if matched_item and matched_item not in st.session_state.chosen:
        st.session_state.chosen.append(matched_item)
        # 随机挑一句回复
        reply = random.choice(items[matched_item]["replies"])
        append("assistant", reply)

        # 判断是否已全部完成
        if len(st.session_state.chosen) == 5:
            append("assistant", closing)
            st.session_state.stage = 99
            st.rerun()
    else:
        append(
            "assistant",
            "Please select the provided item or choose an item that has not been selected."
            if st.session_state.stage < 99
            else "Chat has ended.",
        )