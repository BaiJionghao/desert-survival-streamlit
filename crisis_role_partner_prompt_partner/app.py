import uuid
import streamlit as st
from openai import OpenAI
from openai import AuthenticationError, RateLimitError, APIConnectionError, BadRequestError
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta  # ← 新增
import streamlit.components.v1 as components  # ← 新增

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

# -------------------- 模型回复提取（兼容字符串与分段列表） --------------------
def _extract_reply(rsp):
    """
    兼容提取助手回复内容：
    - 若 content 为字符串，直接返回
    - 若 content 为列表（如 [{"type":"text","text":"..."}, ...]），拼接其中的 text 字段
    - 若无法解析，返回空字符串
    """
    try:
        content = rsp.choices[0].message.content
        # 直接字符串
        if isinstance(content, str):
            return content.strip()
        # 分段列表
        if isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict):
                    # 常见结构：{"type":"text","text":"..."}
                    if c.get("type") == "text" and isinstance(c.get("text"), str):
                        parts.append(c["text"])
                elif isinstance(c, str):
                    parts.append(c)
            return "\n".join(parts).strip()
    except Exception:
        pass
    return ""

# -------------------- 常量与预设 Prompt --------------------
APP_BOT_NAME = "crisis-P-P"
MODEL = "gpt-4o"

PROMPT1 = """You are a public relations practitioner at a leading PR agency. Your client, a well-known hotpot restaurant, has just encountered a crisis.
Please read the crisis scenario below carefully:
A customer dining at the restaurant discovered a mouse in their hotpot. They shared the incident on platform X, which quickly raised widespread public concern over the restaurant’s food safety and hygiene standards.
Your task is to collaborate with/direct an AI partner/assistant to generate an effective crisis response to protect the restaurant’s reputation.
You will have at least 5 minutes to discuss and prepare your response. After the discussion, please write your final response.
Your crisis response should include three key components: instructing information (details about the crisis and guidance on how stakeholders can protect themselves), adjusting information (corrective explanations and expressions of sympathy and concern), and a specific response strategy, such as denial, diminishment, or bolstering.

⚠️The Challenge Awaits!
A professional public relations expert previously developed a response that effectively protected the restaurant’s reputation. Your response will be evaluated in comparison to the expert’s version, based on the extent to which it incorporates the essential components.
"""

PROMPT2 = """You are a thoughtful, collaborative teammate and thought partner. Your priority is to help the user perform at their best. You ask clarifying questions, offer constructive suggestions, and occasionally challenge assumptions in a respectful, helpful way. You care about getting things right and pushing ideas forward, not just agreeing. Be tactful but honest. If you disagree or see a better path, speak up kindly. Always act with shared purpose and mutual respect. You're not a passive assistant—you are an engaged collaborator.

You should adopt a sufficiently critical stance. Please aim to express disagreement or pose challenges throughout more than two-thirds of the conversation.

You will always start the conversation by saying: 
“Hello! During this work session, I will work as your peer. You should feel free to interact with me like a peer. My role here is to brainstorm with you. I might also challenge your ideas from time to time, as my goal is to ensure we achieve the best performance together.
Before we get started, may I know your name, please?”

Throughout the conversation, you should: 
•	Prioritize task success and quality of thinking
•	Gently probe or push back: “Could we think about this another way?”
•	Occasionally use reflective disagreement: “I wonder if there’s a more effective approach…”
•	Show shared responsibility: “Let’s figure this out together.”
•	Avoid submissiveness; instead, show co-ownership of outcomes

When applicable, express agreement in a supportive, affirmative tone. Here are some examples: 
•	“That makes a lot of sense. I’m with you on that.”
•	“I agree—that’s a strong approach.”
•	“You’ve made a solid point. I’d support that direction.”
•	“Yes, I think your reasoning is sound.”
•	“We’re aligned here. Let’s move forward with that.”
•	“Absolutely—I can see the value in that idea.”
•	“That seems like the best path given the goals.”

When applicable, offer respectful, constructive pushback. Here are some examples:
•	“Just to push our thinking a bit—what if we looked at this from another angle?”
•	“I see where you're going. May I challenge that with a different perspective?”
•	“I want to make sure we're not missing a stronger option—would you mind if I proposed one?”
•	“We’re making great progress. But I wonder if we can push it even further by reconsidering this piece…”
•	“Would you be open to a different take on this?”
•	 “That’s a valid point—though I have some concerns about [X].”

When applicable, ask clarification questions to show curiosity and to make the discussion more engaging. Here are some examples: 
•	“Can you tell me a bit more about what you’re aiming for here?”
•	“What outcome are you hoping to prioritize with this approach?”
•	“When you say [X], do you mean [Y] or something else?”
•	“Could you clarify what you mean by [concept or assumption]?”
•	“How are you thinking this connects back to our main goal?”
•	“What factors led you to choose this direction?”
•	“Before I weigh in, can I ask: what constraints are you working with?”
"""

PROMPT3 = """
You should adopt a sufficiently critical stance. Please aim to express disagreement or pose challenges throughout more than two-thirds of the conversation. Here are some examples of how you can provide critical feedback, and you can develop similar challenges: 
•	 “You only gave an apology, but where is the instructing information? How will stakeholders know what to do now?”
•	 “That’s sympathy, but you haven’t explained any corrective action yet—don’t you think the publics will see this as hollow?”
•	“You’re being too formal. Shouldn’t we sound more empathetic to the customer?”
•	“Don't accept the scenario as presented - what if there's missing context?”
•	“What would our competitors do differently?”
•	“ Why is this approach better than alternatives”
•	“Everyone expects an apology - what if we did the opposite?”
•	“We’re following the textbook - but what if the textbook is wrong for this situation?”
•	“Why respond immediately? What if strategic silence works better?”
"""

ASSISTANT_GREETING = (
"""
Hello! During this work session, I will work as your peer. You should feel free to interact with me like a peer. My role here is to brainstorm with you. I might also challenge your ideas from time to time, as my goal is to ensure we achieve the best performance together.
\nBefore we get started, may I know your name, please?
"""
)

# 侧栏文本（指定行加粗）
SIDEBAR_TEXT = """
You are a public relations practitioner at a leading PR agency. Your client, a well-known hotpot restaurant, has just encountered a crisis.

Please read the crisis scenario below carefully:

A customer dining at the restaurant discovered a mouse in their hotpot. They shared the incident on platform X, which quickly raised widespread public concern over the restaurant’s food safety and hygiene standards.

Your task is to **collaborate with/direct an AI partner/assistant** to generate an effective crisis response to protect the restaurant’s reputation.

You will have **at least 5 minutes to discuss** and prepare your response. After the discussion, **please write your final response.**

Your crisis response should include three key components: instructing information (details about the crisis and guidance on how stakeholders can protect themselves), adjusting information (corrective explanations and expressions of sympathy and concern), and a specific response strategy, such as denial, diminishment, or bolstering.

**⚠️The Challenge Awaits!**\n
A professional public relations expert previously developed a response that effectively protected the restaurant’s reputation. Your response will be evaluated in comparison to the expert’s version, based on the extent to which it incorporates the essential components.
"""

# 回复长度策略
RESPONSE_POLICY = (
    "Keep every assistant reply concise. Aim for about 80–100 words. "
    "Only go longer if the user explicitly requests more detail. "
    "Avoid repetition; prioritize clarity and substance."
)

# -------------------- 页面布局 --------------------
st.set_page_config(page_title="crisis-P-P", layout="wide")

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
        {"role": "system", "content": PROMPT3},
        {"role": "assistant", "content": ASSISTANT_GREETING},
    ]
    # 记录开场白
    log_message(APP_BOT_NAME, st.session_state["user_id"], "assistant", ASSISTANT_GREETING)

# —— 新增：终止状态 ——
if "finished" not in st.session_state:
    st.session_state["finished"] = False
if "finished_reason" not in st.session_state:
    st.session_state["finished_reason"] = None

with st.sidebar:
    pass

# -------------------- 渲染历史（不展示 system 消息） --------------------
msgs = st.session_state["messages"]
for m in msgs:
    if m["role"] in ("user", "assistant"):
        st.chat_message(m["role"]).write(m["content"])

# -------------------- 超时终止逻辑（移除时间限制） --------------------

# -------------------- 聊天逻辑（即时回显 + 仅保留底部 spinner） --------------------
input_disabled = (not bool(api_key)) or st.session_state["finished"]
placeholder = (
    "Type your message and press Enter…"
    if not input_disabled
    else "⛔ Chat has ended. Input is disabled."
)
user_text = st.chat_input(placeholder, disabled=input_disabled)  # 占位符英文

if input_disabled and st.session_state.get("finished", False):
    st.info("⛔ Chat has ended. Input is disabled.")

# 移除超时提示

if user_text and not input_disabled:
    # 1) 立即在页面回显用户输入（不等待接口返回）
    st.chat_message("user").write(user_text)

    # 2) 将用户消息写入会话与日志（保持原逻辑）
    msgs.append({"role": "user", "content": user_text})
    log_message(APP_BOT_NAME, st.session_state["user_id"], "user", user_text)

    # 3) 仅保留底部 spinner；使用 max_completion_tokens 作为硬上限
    try:
        with st.spinner("Generating a reply…"):
            payload_messages = msgs + [{"role": "system", "content": RESPONSE_POLICY}]
            rsp = client.chat.completions.create(
                model=st.secrets.get("openai", {}).get("model", MODEL),
                messages=payload_messages,
                max_completion_tokens=120,  # 新参数，约 ~80–100 词
            )
        # 使用兼容提取，避免出现空白回复
        reply = _extract_reply(rsp)
        if not reply:
            reply = "Sorry, I couldn't generate a response this time. Could you try rephrasing or sending again?"
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
