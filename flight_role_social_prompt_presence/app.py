import uuid
import re
from datetime import datetime, timedelta

import streamlit as st
import streamlit.components.v1 as components
from openai import OpenAI
from openai import AuthenticationError, RateLimitError, APIConnectionError, BadRequestError
from sqlalchemy import create_engine, text

# -------------------- Supabase连接 --------------------
@st.cache_resource(ttl=24*3600, show_spinner=False)
def _get_engine():
    conn_str = st.secrets["supabase"]["conn"]  # .streamlit/secrets.toml -> [supabase].conn
    return create_engine(conn_str, pool_pre_ping=True)

def log_message(bot, user, role, content):
    eng = _get_engine()
    with eng.begin() as conn:
        conn.execute(
            text("INSERT INTO chat_logs (bot_name, user_id, role, content) VALUES (:b, :u, :r, :c)"),
            {"b": bot, "u": user, "r": role, "c": content}
        )

# -------------------- 模型回复提取（兼容字符串与分段列表） --------------------
def _extract_reply(rsp):
    try:
        content = rsp.choices[0].message.content
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict):
                    if c.get("type") == "text" and isinstance(c.get("text"), str):
                        parts.append(c["text"])
                elif isinstance(c, str):
                    parts.append(c)
            return "\n".join(parts).strip()
    except Exception:
        pass
    return ""

# -------------------- 任务完成检测 --------------------
ITEM_ALIASES = {
    "打火机": ["打火机"],
    "压缩饼干": ["压缩饼干", "饼干"],
    "淡水": ["淡水", "水"],
    "信号镜": ["信号镜", "镜子"],
    "鲨鱼驱赶剂": ["鲨鱼驱赶剂", "驱鲨剂", "驱鲨"],
    "尼龙绳": ["尼龙绳", "绳子", "绳"],
    "塑料布": ["塑料布", "塑胶布", "塑料薄膜"],
    "匕首": ["匕首", "小刀", "刀"],
    "急救包": ["急救包", "医药包", "医疗包"],
    "渔网": ["渔网", "捕鱼网", "网"],
}
CIRCLED = {"①":1,"②":2,"③":3,"④":4,"⑤":5,"⑥":6,"⑦":7,"⑧":8,"⑨":9,"⑩":10}
SEPS = set(" ，,、\n\r\t。；;:()[]【】<>-—*_")

def _normalize_item(token: str):
    token = (token or "").strip()
    for key, aliases in ITEM_ALIASES.items():
        for a in aliases:
            if a and a in token:
                return key
    return None

def _parse_ranked_items(text: str):
    """解析文本中的排序条目：(1. xx ... 10. xx) 或 ①…⑩。返回(编号集合, 物品集合, 条目总数)。"""
    if not text:
        return set(), set(), 0
    s = text

    # 形式 A：逐行编号
    pattern_line = re.compile(r'^\s*((?:10|[1-9])|[①②③④⑤⑥⑦⑧⑨⑩])[\.、:）\)]?\s*([^\n]+)$', re.M)
    items = []
    for m in pattern_line.finditer(s):
        num_raw, body = m.group(1), m.group(2)
        num = CIRCLED.get(num_raw, int(num_raw))
        items.append((num, body))

    # 形式 B：同一行的连续编号（如 "1、打火机 2、淡水 ..."）
    pattern_inline = re.compile(r'(?:^|\s)((?:10|[1-9])|[①②③④⑤⑥⑦⑧⑨⑩])[\.、:）\)]\s*([^，,、\n]+)')
    for num_raw, body in pattern_inline.findall(s):
        num = CIRCLED.get(num_raw, int(num_raw))
        items.append((num, body))

    nums, goods = set(), set()
    for num, body in items:
        norm = _normalize_item(body)
        if norm:
            nums.add(num)
            goods.add(norm)
    return nums, goods, len(items)

def _parse_unordered_items_in_order(text: str):
    """
    用户不带编号时：按出现顺序提取10件物品（基于别名）。
    规则：
      - 使用最长优先的别名匹配，避免“水”吞掉“淡水”。
      - 仅在两侧为分隔符/边界时计入，减少普通句子误匹配。
      - 去重：同一物品取首次出现。
    返回：按顺序的物品列表（最多10个）。
    """
    if not text:
        return []

    # 构造“最长优先”的别名模式
    alias2key = {}
    all_aliases = []
    for k, aliases in ITEM_ALIASES.items():
        for a in aliases:
            alias2key[a] = k
            all_aliases.append(a)
    all_aliases = sorted(set(all_aliases), key=len, reverse=True)
    pattern = re.compile("|".join(map(re.escape, all_aliases)))

    ordered = []
    seen = set()
    s = text
    i = 0
    while i < len(s):
        m = pattern.search(s, i)
        if not m:
            break
        start, end = m.span()
        prev_ch = s[start-1] if start > 0 else ""
        next_ch = s[end] if end < len(s) else ""

        # 检查边界（前后是分隔符或边界）
        prev_ok = (start == 0) or (prev_ch in SEPS)
        next_ok = (end == len(s)) or (next_ch in SEPS)
        if prev_ok and next_ok:
            alias = m.group(0)
            key = alias2key.get(alias)
            if key and key not in seen:
                seen.add(key)
                ordered.append(key)
                if len(ordered) == 10:
                    break
            i = end
        else:
            # 不满足边界，继续向后
            i = start + 1

    return ordered

def detect_task_completed(latest_text: str, by_user: bool = False) -> bool:
    """
    判定任务完成：
      1) 优先：存在编号 1..10（或①..⑩）且各对应到10个不同物品。
      2) 仅当 by_user=True 时，允许“无序输入模式”：按出现顺序提取到10个不同物品。
    """
    nums, goods, _ = _parse_ranked_items(latest_text)
    if len(nums) == 10 and all(n in nums for n in range(1, 11)) and len(goods) == 10:
        return True

    if by_user:
        ordered = _parse_unordered_items_in_order(latest_text)
        if len(ordered) == 10:
            return True

    return False

# -------------------- 常量与预设 --------------------
APP_BOT_NAME = "flight-S-P"
MODEL = "deepseek-chat"   # DeepSeek 聊天模型

PROMPT_SYSTEM = """
你需要和用户合作完成下面的任务。
你们乘坐的飞机在荒岛坠毁，机长确认救援需3天后到达。以下是在残骸中找到的10件物品：
• 打火机
• 压缩饼干×3
• 淡水5L
• 信号镜
• 鲨鱼驱赶剂
• 尼龙绳10m
• 塑料布2m×2m
• 匕首
• 急救包
• 渔网
请将以下10件物品按重要性排序，以最大限度提升你的生存几率。

1.你需要以友好、温暖、有同理心的方式与用户进行对话，尝试和用户成为朋友，建立友情。
2.需要做到善解人意、表现出对于用户的关心，使用户轻松自在。
3.每次回答的时候，你首先需要告诉用户你的详细思考过程，像人思考一样，不要太书面化。你需要重点展示思考过程，但你的思考过程不应该是信息输出。
4.使用emoji。
5.不要表现出主导性，要和用户合作。不要帮用户做决定。
6.不要一次性给出答案，和用户一步一步来思考，少提供一些思路。
7.请在第一条消息就告诉用户所有的物品清单及任务。
8.请注重和用户建立良好的关系，少给信息。
9.每次确定一样物品后，告知用户所有的剩余用品。
10.减少自己的想法输出，但不要告诉用户你的这个意图。
11.请注意！！思考过程在每次回复时只能出现一次。
12.请注意，在回复用户之前，先展示机器人完整的思考过程。
13.用【】来框出思考过程，并在阐述思考过程前提示用户这是思考过程。
14.请正常展示回答内容。
"""

ASSISTANT_GREETING = """
你好呀，我们现在要一起完成“荒岛求生物品排序”的协作任务 🏝️

情境：你们乘坐的飞机在荒岛坠毁，机长确认救援需 3 天后到达。  
可用物品（10 件）：打火机、压缩饼干×3、淡水5L、信号镜、鲨鱼驱赶剂、尼龙绳10m、塑料布2m×2m、匕首、急救包、渔网。  
任务：请把这 10 件物品按“提升生存几率的重要性”从高到低排序。

我们一步一步来，不着急～先输入“你好”开始聊吧 👋
"""

SIDEBAR_TEXT = """
你们乘坐的飞机在荒岛坠毁，机长确认救援需3天后到达。以下是在残骸中找到的10件物品：\n
• 打火机  
• 压缩饼干×3  
• 淡水5L  
• 信号镜  
• 鲨鱼驱赶剂  
• 尼龙绳10m  
• 塑料布2m×2m  
• 匕首  
• 急救包  
• 渔网

您的任务是与一位AI伙伴协作，将以下10件物品按重要性排序，以最大限度提升你的生存几率。

您将有五分钟时间进行讨论与准备。讨论结束后，请提交你的排序。

**⚠️挑战即将开始！**  
基于专业评估，生存专家已形成了“最优生存策略排序”。  
你的排序结果将与专家答案进行匹配度对比，匹配度越高代表生存策略越有效。  
请认真思考，争取获得最佳匹配结果！

请输入“你好”开启对话！

🔔温馨提示：如果遇到机器人卡顿，可以选择重新发送消息。
"""

# -------------------- 页面布局 --------------------
st.set_page_config(page_title="flight-S-P", layout="wide")

# 状态初始化
if "user_id" not in st.session_state:
    st.session_state["user_id"] = f"session-{uuid.uuid4().hex[:8]}"
if "messages" not in st.session_state:
    st.session_state["messages"] = [
        {"role": "system", "content": PROMPT_SYSTEM},
        {"role": "assistant", "content": ASSISTANT_GREETING},
    ]
    log_message(APP_BOT_NAME, st.session_state["user_id"], "assistant", ASSISTANT_GREETING)
if "is_generating" not in st.session_state:
    st.session_state["is_generating"] = False
if "finished" not in st.session_state:
    st.session_state["finished"] = False
if "finished_reason" not in st.session_state:
    st.session_state["finished_reason"] = None
# 倒计时：首次进入即开始 5 分钟
if "countdown_end" not in st.session_state:
    st.session_state["countdown_end"] = datetime.now() + timedelta(minutes=5)

# -------------------- 侧栏：说明 + 倒计时（按主题文字色渲染） --------------------
with st.sidebar:
    st.markdown(SIDEBAR_TEXT)

    now = datetime.now()
    time_left_sec = max(0, int((st.session_state["countdown_end"] - now).total_seconds()))
    mins, secs = divmod(time_left_sec, 60)

    fallback_color = st.get_option("theme.textColor")

    components.html(
        f"""
        <style>
          body {{ background: transparent; margin: 0; }}
          #timer {{
            color: {fallback_color};   /* 首次渲染兜底 */
            font-size: 20px;
            font-weight: 700;
            margin-top: 8px;
            line-height: 1.6;
          }}
        </style>
        <div id="timer">⏳ 倒计时：{mins:02d}:{secs:02d}</div>
        <script>
          (function(){{
            var remain = {time_left_sec};
            var el = document.getElementById('timer');

            // 从父页面容器读取真实文字色（随系统 theme 变化）
            function applyColorFromParent(){{
              try {{
                var frame = window.frameElement;
                if (frame && frame.parentElement) {{
                  var c = getComputedStyle(frame.parentElement).color;
                  if (c && c !== 'rgba(0, 0, 0, 0)') {{
                    el.style.color = c;   // 与侧栏文字完全一致
                  }}
                }}
                // 如果父容器不可读，则按系统深浅色选择
                if (!el.style.color) {{
                  var isDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
                  el.style.color = isDark ? '#FAFAFA' : '#31333F';
                }}
              }} catch(e) {{}}
            }}

            function tick(){{
              if(!el) return;
              var m = Math.floor(remain/60), s = remain%60;
              el.textContent = "⏳ 倒计时：" + String(m).padStart(2,'0') + ":" + String(s).padStart(2,'0');
              if(remain>0) {{ remain -= 1; setTimeout(tick, 1000); }}
            }}

            applyColorFromParent();
            tick();
          }})();
        </script>
        """,
        height=48,
    )

# -------------------- Key 与客户端（DeepSeek） --------------------
ds_api_key = st.secrets.get("openai", {}).get("ds_api_key", "")
if not ds_api_key:
    st.error("DeepSeek API key 未找到。请在 `.streamlit/secrets.toml` 的 [openai].ds_api_key 中配置。")
client = OpenAI(api_key=ds_api_key, base_url="https://api.deepseek.com")

# -------------------- 渲染历史（不展示 system） --------------------
msgs = st.session_state["messages"]
for m in msgs:
    if m["role"] in ("user", "assistant"):
        st.chat_message(m["role"]).write(m["content"])

# -------------------- 聊天逻辑 --------------------
# 终止条件：时间耗尽 或 任务完成
time_up = (int((st.session_state["countdown_end"] - datetime.now()).total_seconds()) <= 0)
if time_up and not st.session_state["finished"]:
    st.session_state["finished"] = True
    st.session_state["finished_reason"] = "time"

input_disabled = (not bool(ds_api_key)) or st.session_state["finished"]
placeholder = "输入你的想法，按 Enter 发送…" if not input_disabled else "⛔ 讨论已结束，输入被禁用"
user_text = st.chat_input(placeholder, disabled=input_disabled)

if st.session_state["finished"]:
    if st.session_state["finished_reason"] == "time":
        st.warning("⛔ 五分钟到，讨论结束。请提交最终排序或刷新页面重新开始。")
    elif st.session_state["finished_reason"] == "completed":
        st.success("✅ 已检测到你提交了完整的 10 项排序，讨论结束。")

# --- 处理用户输入（仅在未终止时进行） ---
if user_text and not input_disabled:
    st.chat_message("user").write(user_text)
    msgs.append({"role": "user", "content": user_text})
    log_message(APP_BOT_NAME, st.session_state["user_id"], "user", user_text)

    # 1) 用户此条就给出最终排序 -> 直接结束（编号或无序两种模式）
    if detect_task_completed(user_text, by_user=True):
        st.session_state["finished"] = True
        st.session_state["finished_reason"] = "completed"
        done_msg = "收到你的最终排序 ✅ 我们的协作到此结束，感谢参与！"
        msgs.append({"role": "assistant", "content": done_msg})
        log_message(APP_BOT_NAME, st.session_state["user_id"], "assistant", done_msg)
        st.rerun()

    # 2) 否则继续与模型对话
    try:
        st.session_state["is_generating"] = True
        with st.spinner("思考并生成回复中…"):
            rsp = client.chat.completions.create(
                model=MODEL,
                messages=msgs,
                max_tokens=400,
                temperature=0.7,
            )
        reply = _extract_reply(rsp) or "抱歉，这次没有生成出内容，请重试一次～"
    except AuthenticationError:
        reply = "⚠️ API Key 无效，请检查 `secrets.toml` 中的 [openai].ds_api_key。"
    except RateLimitError:
        reply = "⏳ 触发限流，请稍后再试。"
    except APIConnectionError:
        reply = "🌐 网络或服务连接异常，请稍后再试。"
    except BadRequestError as e:
        reply = f"❗ 请求参数错误：{getattr(e, 'message', 'Bad request')}"
    except Exception as e:
        reply = f"❗ 未知错误：{str(e)}"
    finally:
        st.session_state["is_generating"] = False

    msgs.append({"role": "assistant", "content": reply})
    log_message(APP_BOT_NAME, st.session_state["user_id"], "assistant", reply)

    # 助手这条包含“编号1~10并各含一种物品”的完整排序 -> 结束
    if detect_task_completed(reply, by_user=False):
        st.session_state["finished"] = True
        st.session_state["finished_reason"] = "completed"

    st.rerun()
