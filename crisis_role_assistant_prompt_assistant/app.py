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
APP_BOT_NAME = "crisis-A-A"
MODEL = "gpt-4o"

PROMPT1 = """You are a public relations practitioner at a leading PR agency. Your client, a well-known hotpot restaurant, has just encountered a crisis.
Please read the crisis scenario below carefully:
A customer dining at the restaurant discovered a mouse in their hotpot. They shared the incident on platform X, which quickly raised widespread public concern over the restaurant’s food safety and hygiene standards.
Your task is to collaborate with/direct an AI partner/assistant to generate an effective crisis response to protect the restaurant’s reputation.
You will have five minutes to discuss and prepare your response. After the discussion, please write your final response.
Your crisis response should include three key components: instructing information (details about the crisis and guidance on how stakeholders can protect themselves), adjusting information (corrective explanations and expressions of sympathy and concern), and a specific response strategy, such as denial, diminishment, or bolstering.

⚠️The Challenge Awaits!
A professional public relations expert previously developed a response that effectively protected the restaurant’s reputation. Your response will be evaluated in comparison to the expert’s version, based on the extent to which it incorporates the essential components.
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
Hello! During this work session, I will work as your assistant.\n
Please let me know whenever you need my assistance. My role here is to follow your command. I will do whatever you say, as my goal here is to ensure you are supported in the way you prefer.\n
Before we get started, may I know your name, please?
"""
)

# 侧栏文本（指定行加粗）
SIDEBAR_TEXT = """
You are a public relations practitioner at a leading PR agency. Your client, a well-known hotpot restaurant, has just encountered a crisis.

Please read the crisis scenario below carefully:

A customer dining at the restaurant discovered a mouse in their hotpot. They shared the incident on platform X, which quickly raised widespread public concern over the restaurant’s food safety and hygiene standards.

Your task is to **collaborate with/direct an AI partner/assistant** to generate an effective crisis response to protect the restaurant’s reputation.

You will have **five minutes to discuss** and prepare your response. After the discussion, **please write your final response.**

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
st.set_page_config(page_title="crisis-A-A", layout="wide")

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

# —— 新增：终止状态与倒计时结束时间（7分钟） ——
if "finished" not in st.session_state:
    st.session_state["finished"] = False
if "finished_reason" not in st.session_state:
    st.session_state["finished_reason"] = None
if "countdown_end" not in st.session_state:
    st.session_state["countdown_end"] = datetime.now() + timedelta(minutes=7)  # 7 分钟

# —— 侧边栏倒计时显示（HTML/JS，与模板一致） ——
with st.sidebar:
    now = datetime.now()
    time_left_sec = max(0, int((st.session_state["countdown_end"] - now).total_seconds()))
    mins, secs = divmod(time_left_sec, 60)
    fallback_color = st.get_option("theme.textColor")

    components.html(
        f"""
        <style>
          body {{ background: transparent; margin: 0; }}
          #timer {{
            color: {fallback_color};
            font-size: 20px;
            font-weight: 700;
            margin-top: 8px;
            line-height: 1.6;
          }}
        </style>
        <div id="timer">⏳ Timer: {mins:02d}:{secs:02d}</div>
        <script>
          (function(){{
            var remain = {time_left_sec};
            var el = document.getElementById('timer');

            function applyColorFromParent(){{
              try {{
                var frame = window.frameElement;
                if (frame && frame.parentElement) {{
                  var c = getComputedStyle(frame.parentElement).color;
                  if (c && c !== 'rgba(0, 0, 0, 0)') {{
                    el.style.color = c;
                  }}
                }}
                if (!el.style.color) {{
                  var isDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
                  el.style.color = isDark ? '#FAFAFA' : '#31333F';
                }}
              }} catch(e) {{}}
            }}

            function tick(){{
              if(!el) return;
              var m = Math.floor(remain/60), s = remain%60;
              el.textContent = "⏳ Timer: " + String(m).padStart(2,'0') + ":" + String(s).padStart(2,'0');
              if(remain>0) {{ remain -= 1; setTimeout(tick, 1000); }}
            }}

            applyColorFromParent();
            tick();
          }})();
        </script>
        """,
        height=48,
    )

# -------------------- 渲染历史（不展示 system 消息） --------------------
msgs = st.session_state["messages"]
for m in msgs:
    if m["role"] in ("user", "assistant"):
        st.chat_message(m["role"]).write(m["content"])

# -------------------- 超时终止逻辑（模板同思路） --------------------
time_up = (int((st.session_state["countdown_end"] - datetime.now()).total_seconds()) <= 0)
if time_up and not st.session_state["finished"]:
    st.session_state["finished"] = True
    st.session_state["finished_reason"] = "time"

# -------------------- 聊天逻辑（即时回显 + 仅保留底部 spinner） --------------------
input_disabled = (not bool(api_key)) or st.session_state["finished"]
user_text = st.chat_input("Type your message and press Enter…", disabled=input_disabled)  # 占位符英文

# 若因超时结束，给出明确提示（按你要求的英文）
if st.session_state["finished"] and st.session_state["finished_reason"] == "time":
    st.warning("⛔ The time limit has ended. Please enter the crisis response in the text box below.")

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
