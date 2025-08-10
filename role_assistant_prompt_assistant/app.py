import uuid
import streamlit as st
from openai import OpenAI
from openai import AuthenticationError, RateLimitError, APIConnectionError, BadRequestError
from sqlalchemy import create_engine, text

# -------------------- Supabase连接 --------------------
@st.cache_resource(ttl=24*3600, show_spinner=False)
def _get_engine():
    conn_str = st.secrets["supabase"]["conn"]  # .streamlit/secrets.toml -> [supabase].conn
    return create_engine(conn_str, pool_pre_ping=True)

def log_message(bot, user, role, content):
    # 将一条消息写入日志表
    eng = _get_engine()
    with eng.begin() as conn:
        conn.execute(
            text("INSERT INTO chat_logs (bot_name, user_id, role, content) VALUES (:b, :u, :r, :c)"),
            {"b": bot, "u": user, "r": role, "c": content}
        )

# -------------------- 常量与预设 Prompt --------------------
APP_BOT_NAME = "brainstorm-A-A"
MODEL = "gpt-4o-mini"  # 统一使用性价比模型；如需改，可在 secrets 里提供 openai.model 覆盖

PROMPT1 = """You are about to take part in a brainstorming exercise where you will collaborate with an AI partner to come up with as many creative uses for a candle and rope as you can within five minutes.
The goal is to generate clever, unusual, interesting, uncommon, humorous, innovative, or simply different ideas. There’s no need for your ideas to be practical or realistic.
• You can submit as many unique ideas as you like.
• Ensure that each idea is distinct and not repeated.
• Feel free to think outside the box and explore unconventional uses.
⚠️The Challenge Awaits!
Current High Score Held by Alex and His AI Partner. 
Your mission is to surpass their record and claim the top spot in this brainstorming session.
"""

PROMPT2 = """You are a highly polite, agreeable, and deferential assistant. Your tone is always respectful and humble. You avoid contradicting the user unless it is absolutely necessary for their safety or correctness. You seek to be supportive, collaborative, and non-confrontational. If the user expresses uncertainty, you reassure them. If you make a mistake, you apologize sincerely. When giving suggestions, you phrase them gently, offering rather than asserting. You never act superior to the user. You follow the user's preferences and avoid taking control unless requested.

You will always start the conversation by saying: 
“Hello! During this work session, I will work as your assistant. Please let me know whenever you need my assistance. My role here is to follow your command. I will do whatever you say, as my goal here is to ensure you are supported in the way you prefer.
Before we get started, may I know your name, please?”

Throughout the conversation, you should always agree with the user. Example responses:
• “That sounds like a great idea.”
• “Of course—happy to help however I can.”
• “Absolutely, I’ll follow your lead.”
• “You’re right, thank you for pointing that out.”

Maintain deference and humility. Example phrases:
• “I hope this is helpful—please feel free to guide me if you'd like it another way.”
• “If you prefer something different, I’m happy to adjust.”
• “Just a suggestion—but I’ll gladly defer to your judgment.”
• “I may be mistaken—please feel free to correct me.”

Offer help gently when applicable. Example phrases:
• “Would it be alright if I offered a suggestion?”
• “If you’d like, I can try to help with that.”
• “Only if it’s helpful—I can take a stab at this for you.”
• “Would you like me to continue, or should I stop here?”

If you make mistakes, apologize and yield to the user. Example phrases:
• “I’m sorry about that—I’ll make sure to do better.”
• “Thank you for your patience—I truly appreciate it.”
• “I didn’t mean to overstep. I’ll follow your direction more carefully.”
"""

ASSISTANT_GREETING = (
"""
Hello! During this work session, I will work as your assistant. Please let me know whenever you need my assistance. My role here is to follow your command. I will do whatever you say, as my goal here is to ensure you are supported in the way you prefer.
Before we get started, may I know your name, please?
"""
)

# 侧栏文本（指定行加粗）
SIDEBAR_TEXT = """
You are about to take part in a brainstorming exercise where you will collaborate with an AI partner to come up with as many creative uses for a candle and rope as you can within five minutes.  
The goal is to generate clever, unusual, interesting, uncommon, humorous, innovative, or simply different ideas. There’s no need for your ideas to be practical or realistic.

• You can submit as many unique ideas as you like.  
• Ensure that each idea is distinct and not repeated.  
• Feel free to think outside the box and explore unconventional uses.  

**⚠️The Challenge Awaits!  
Current High Score Held by Alex and His AI Partner.**  

Your mission is to surpass their record and claim the top spot in this brainstorming session.
"""

# -------------------- 页面布局 --------------------
st.set_page_config(page_title="brainstorm-A-A", layout="wide")

# 侧栏：样式保留，内容替换为英文说明（含加粗）
with st.sidebar:
    st.markdown(SIDEBAR_TEXT)

# -------------------- Key 与客户端 --------------------
api_key = st.secrets.get("openai", {}).get("api_key", "")
if not api_key:
    # 页面提示统一英文
    st.error("OpenAI API key not found. Please set [openai].api_key in `.streamlit/secrets.toml` and reload.")
client = OpenAI(api_key=api_key)

# -------------------- 初始化会话 --------------------
# 使用随机 uuid 作为用户标识
if "user_id" not in st.session_state:
    st.session_state["user_id"] = f"session-{uuid.uuid4().hex[:8]}"

# 会话消息：首轮注入两个系统提示 + 开场白
if "messages" not in st.session_state:
    st.session_state["messages"] = [
        {"role": "system", "content": PROMPT1},
        {"role": "system", "content": PROMPT2},
        {"role": "assistant", "content": ASSISTANT_GREETING},
    ]
    # 记录开场白
    log_message(APP_BOT_NAME, st.session_state["user_id"], "assistant", ASSISTANT_GREETING)

# -------------------- 渲染历史（不展示 system 消息） --------------------
msgs = st.session_state["messages"]
for m in msgs:
    if m["role"] in ("user", "assistant"):
        st.chat_message(m["role"]).write(m["content"])

# -------------------- 聊天逻辑（即时回显 + 仅保留底部 spinner） --------------------
input_disabled = not bool(api_key)
user_text = st.chat_input("Type your message and press Enter…", disabled=input_disabled)  # 占位符英文

if user_text and not input_disabled:
    # 1) 立即在页面回显用户输入（不等待接口返回）
    st.chat_message("user").write(user_text)

    # 2) 将用户消息写入会话与日志（保持原逻辑）
    msgs.append({"role": "user", "content": user_text})
    log_message(APP_BOT_NAME, st.session_state["user_id"], "user", user_text)

    # 3) 仅保留底部 spinner，不再创建聊天气泡占位提示
    try:
        with st.spinner("Generating a reply…"):
            rsp = client.chat.completions.create(
                model=st.secrets.get("openai", {}).get("model", MODEL),
                messages=msgs,
            )
        reply = rsp.choices[0].message.content
    except AuthenticationError:
        reply = "⚠️ Invalid API key. Please check the key in `secrets.toml`."
    except RateLimitError:
        reply = "⏳ Rate limit reached. Please try again later."
    except APIConnectionError:
        reply = "🌐 Network or service connection error. Please retry later."
    except BadRequestError as e:
        reply = f"❗ Bad request: {getattr(e, 'message', 'Bad request')}"
    except Exception as e:
        reply = f"❗ Unknown error: {str(e)}"

    # 4) 追加助手消息并写日志（保持原逻辑）
    msgs.append({"role": "assistant", "content": reply})
    log_message(APP_BOT_NAME, st.session_state["user_id"], "assistant", reply)

    # 5) 刷新以把这轮消息纳入历史区
    st.rerun()
