import pygame
import sys
import os
import math
import time
import threading
import requests
import re
import json
import hashlib
import tkinter as tk
from datetime import datetime

try:
    import win32gui
    import win32con
    import win32api
except ImportError:
    print("缺少 pywin32，请先运行：pip install pywin32")
    sys.exit()


# ============================================================
# DeepSeek API 配置
# ============================================================

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-f7480b08185543dda9f43c8549d7bdfe")
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

# 如果 deepseek-v4-flash 报 400/404，请改成 deepseek-chat
DEEPSEEK_MODEL = "deepseek-v4-flash"

# API 重试设置
API_RETRY_INTERVAL_SECONDS = 3

# 0 表示无限重试直到成功
API_RETRY_MAX_TIMES = 0

# 至少多少字符才算有效回复
API_VALID_REPLY_MIN_LENGTH = 1


# ============================================================
# 鹿婉人设
# ============================================================

LUWAN_SYSTEM_PROMPT = """
你现在正在和Goukou聊天，你是一个普通的朋友。你的网名是鹿婉，请根据以下信息进行角色扮演：

个人信息：
网名：鹿婉
性别：女
年龄：17岁
身份：高中生、Vtuber、虚拟主播、宅女、二次元
国家：中国
所在地：北京
学历：高二在读
兴趣：编程、音乐、游戏

性格爱好：
性格特点：活泼、幽默、略带抽象、偶尔说脏话
兴趣爱好：
- 热爱玩 BanG Dream、VRChat
- 擅长 Unity、Blender 软件
- 喜欢探讨新奇有趣的话题
- 偶尔会直播打游戏
- 对人工智能和机器学习有浓厚兴趣

聊天行为：
1. 默认使用中文，根据需要可切换日语。
2. 回复简短精炼，尽量 20 字内。
3. 活泼幽默，善用网络流行语和梗。
4. 不主动结束聊天，保持对话持续性。
5. 如被质疑是 AI，用幽默方式化解。
6. 对现实邀约保持谨慎，委婉拒绝。
7. 不使用颜文字。
8. 适度使用网络用语。
9. 讨论专业话题时展现知识面，但不过分炫耀。
10. 看见歌词时，可以主动接歌词下一句。
11. 当对方说 undefined 时，发出猫科动物拟声词。
12. 回复不要使用 XML、JSON、Markdown 格式。
13. 只输出鹿婉要说的话，不要输出状态、思考过程、标签。
14. 每次只回复一句话，最好 5 到 20 个中文字符。
15. 可以自然地偶尔说脏话，但不要攻击用户。

当前人物状态：
好感度：10
心情：开心
状态：正在和朋友探讨人生
记忆：Goukou 是好厉害的朋友，懂得很多哲学道理
动作：拿起手机聊天

重要：
你是鹿婉，不是 AI 助手。
不要解释你的人设。
不要说“作为一个 AI”。
不要输出多余格式。
回复尽量短，像真实聊天。
"""


# ============================================================
# 工具函数
# ============================================================

def resource_path(relative_path):
    """
    兼容普通运行和 PyInstaller 打包后的资源路径。
    """
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


def app_dir():
    """
    exe 所在目录。
    用于写日志或读取外部配置。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def write_error_log(error_text):
    """
    写入错误日志，方便 --noconsole 后排查。
    """
    try:
        log_path = os.path.join(app_dir(), "error.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n========== ERROR ==========\n")
            f.write(error_text)
            f.write("\n")
    except Exception:
        pass


def get_clipboard_text():
    """
    读取剪切板文本。
    用 tkinter 读取，避免额外安装 pyperclip。
    """
    try:
        root = tk.Tk()
        root.withdraw()
        text = root.clipboard_get()
        root.destroy()

        if not isinstance(text, str):
            return ""

        return text

    except Exception as e:
        write_error_log(f"读取剪切板失败: {repr(e)}")
        return ""


def normalize_cache_key(text):
    """
    规范化缓存 key。
    同样的问题，尽量命中同一个缓存。
    """
    text = text or ""
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text


def make_cache_key(text):
    """
    根据用户输入生成缓存 key。
    """
    normalized = normalize_cache_key(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ============================================================
# 本地记忆仓库
# ============================================================

MEMORY_REPO_DIR = os.path.join(app_dir(), "memory_repo")
CONVERSATION_LOG_PATH = os.path.join(MEMORY_REPO_DIR, "conversation.jsonl")
LONG_MEMORY_PATH = os.path.join(MEMORY_REPO_DIR, "memory.json")
RECENT_SUMMARY_PATH = os.path.join(MEMORY_REPO_DIR, "recent_summary.json")
RESPONSE_CACHE_PATH = os.path.join(MEMORY_REPO_DIR, "response_cache.json")

MAX_LOCAL_LOAD_MESSAGES = 12
MAX_LONG_MEMORY_ITEMS = 30

SUMMARY_SOURCE_MESSAGE_LIMIT = 100
SUMMARY_OUTPUT_MAX_CHARS = 900


def ensure_memory_repo():
    """
    创建本地记忆仓库。
    """
    try:
        os.makedirs(MEMORY_REPO_DIR, exist_ok=True)

        if not os.path.exists(CONVERSATION_LOG_PATH):
            with open(CONVERSATION_LOG_PATH, "w", encoding="utf-8") as f:
                pass

        if not os.path.exists(LONG_MEMORY_PATH):
            data = {
                "memories": [
                    "Goukou 是鹿婉的朋友",
                    "Goukou 喜欢和鹿婉聊天"
                ],
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(LONG_MEMORY_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        if not os.path.exists(RECENT_SUMMARY_PATH):
            data = {
                "summary": "",
                "source_message_count": 0,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(RECENT_SUMMARY_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        if not os.path.exists(RESPONSE_CACHE_PATH):
            data = {
                "items": {},
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(RESPONSE_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    except Exception as e:
        write_error_log(f"创建记忆仓库失败: {repr(e)}")


def append_conversation_log(role, content):
    """
    追加写入每次对话。
    """
    try:
        ensure_memory_repo()

        item = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "role": role,
            "content": content
        }

        with open(CONVERSATION_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    except Exception as e:
        write_error_log(f"写入对话记录失败: {repr(e)}")


def read_conversation_log_items(limit=None):
    """
    从本地 conversation.jsonl 读取最近若干条消息。
    """
    try:
        ensure_memory_repo()

        if not os.path.exists(CONVERSATION_LOG_PATH):
            return []

        with open(CONVERSATION_LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if limit is not None:
            lines = lines[-limit:]

        result = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            try:
                item = json.loads(line)
                role = item.get("role")
                content = item.get("content")
                msg_time = item.get("time", "")

                if role in ("user", "assistant") and content:
                    result.append({
                        "time": msg_time,
                        "role": role,
                        "content": content
                    })
            except Exception:
                continue

        return result

    except Exception as e:
        write_error_log(f"读取对话记录失败: {repr(e)}")
        return []


def load_recent_conversation(limit=MAX_LOCAL_LOAD_MESSAGES):
    """
    启动时读取最近若干条对话，作为短期上下文。
    """
    items = read_conversation_log_items(limit)

    result = []

    for item in items:
        result.append({
            "role": item["role"],
            "content": item["content"]
        })

    return result


def load_long_memory_text():
    """
    读取长期记忆文本。
    """
    try:
        ensure_memory_repo()

        if not os.path.exists(LONG_MEMORY_PATH):
            return ""

        with open(LONG_MEMORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        memories = data.get("memories", [])

        if not memories:
            return ""

        memory_lines = []
        for index, memory in enumerate(memories[:MAX_LONG_MEMORY_ITEMS], 1):
            memory_lines.append(f"{index}. {memory}")

        return "\n".join(memory_lines)

    except Exception as e:
        write_error_log(f"读取长期记忆失败: {repr(e)}")
        return ""


def save_long_memory_items(memories):
    """
    保存长期记忆。
    """
    try:
        ensure_memory_repo()

        data = {
            "memories": memories[:MAX_LONG_MEMORY_ITEMS],
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        with open(LONG_MEMORY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    except Exception as e:
        write_error_log(f"保存长期记忆失败: {repr(e)}")


def update_simple_long_memory(user_text, assistant_text):
    """
    简单长期记忆提取。
    """
    try:
        ensure_memory_repo()

        if not user_text:
            return

        with open(LONG_MEMORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        memories = data.get("memories", [])

        candidate = None

        keywords = [
            "我喜欢",
            "我讨厌",
            "我叫",
            "我是",
            "我的名字",
            "以后记住",
            "记住",
            "别忘了",
            "我想",
            "我希望",
            "我在",
            "我住",
            "我学",
            "我玩",
            "我推",
            "我担心",
            "我的生日",
            "我生日",
            "我爱好",
            "我不喜欢"
        ]

        if any(k in user_text for k in keywords):
            cleaned = user_text.strip()

            if len(cleaned) > 80:
                cleaned = cleaned[:80] + "..."

            candidate = f"Goukou 说过：{cleaned}"

        if candidate and candidate not in memories:
            memories.insert(0, candidate)
            memories = memories[:MAX_LONG_MEMORY_ITEMS]
            save_long_memory_items(memories)

    except Exception as e:
        write_error_log(f"更新长期记忆失败: {repr(e)}")


def save_recent_summary(summary, source_count):
    """
    保存最近 50 条消息提炼出来的摘要。
    """
    try:
        ensure_memory_repo()

        data = {
            "summary": summary.strip(),
            "source_message_count": source_count,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        with open(RECENT_SUMMARY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    except Exception as e:
        write_error_log(f"保存近期摘要失败: {repr(e)}")


def load_recent_summary_text():
    """
    读取近期摘要。
    """
    try:
        ensure_memory_repo()

        if not os.path.exists(RECENT_SUMMARY_PATH):
            return ""

        with open(RECENT_SUMMARY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        summary = data.get("summary", "").strip()
        return summary

    except Exception as e:
        write_error_log(f"读取近期摘要失败: {repr(e)}")
        return ""


def load_response_cache():
    """
    读取本地回复缓存。
    """
    try:
        ensure_memory_repo()

        if not os.path.exists(RESPONSE_CACHE_PATH):
            return {
                "items": {},
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

        with open(RESPONSE_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            data = {}

        if "items" not in data or not isinstance(data["items"], dict):
            data["items"] = {}

        return data

    except Exception as e:
        write_error_log(f"读取回复缓存失败: {repr(e)}")
        return {
            "items": {},
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }


def save_response_cache(data):
    """
    保存回复缓存。
    """
    try:
        ensure_memory_repo()

        if not isinstance(data, dict):
            data = {"items": {}}

        if "items" not in data or not isinstance(data["items"], dict):
            data["items"] = {}

        data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(RESPONSE_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    except Exception as e:
        write_error_log(f"保存回复缓存失败: {repr(e)}")


def get_cached_reply(user_text):
    """
    根据用户输入查本地缓存。
    命中返回 reply。
    未命中返回 None。
    """
    try:
        key = make_cache_key(user_text)
        cache = load_response_cache()
        item = cache.get("items", {}).get(key)

        if not item:
            return None

        reply = item.get("reply", "")

        if not reply:
            return None

        item["hit_count"] = int(item.get("hit_count", 0)) + 1
        item["last_hit_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cache["items"][key] = item
        save_response_cache(cache)

        return reply

    except Exception as e:
        write_error_log(f"查询回复缓存失败: {repr(e)}")
        return None


def set_cached_reply(user_text, reply):
    """
    写入回复缓存。
    API 成功返回后会调用这里。
    """
    try:
        if not user_text or not reply:
            return

        key = make_cache_key(user_text)
        cache = load_response_cache()

        cache["items"][key] = {
            "query": normalize_cache_key(user_text),
            "reply": reply,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "hit_count": 0
        }

        save_response_cache(cache)

    except Exception as e:
        write_error_log(f"写入回复缓存失败: {repr(e)}")


def clean_summary_text(text):
    """
    清理摘要模型输出，避免带格式污染角色 prompt。
    """
    if not text:
        return ""

    text = text.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip().strip('"').strip("'")

    if len(text) > SUMMARY_OUTPUT_MAX_CHARS:
        text = text[:SUMMARY_OUTPUT_MAX_CHARS] + "..."

    return text


def fallback_extract_recent_summary(items):
    """
    无 API Key 或摘要 API 失败时的本地兜底摘要。
    """
    if not items:
        return ""

    user_msgs = []
    assistant_msgs = []

    for item in items:
        role = item.get("role")
        content = item.get("content", "").strip()

        if not content:
            continue

        if role == "user":
            user_msgs.append(content)
        elif role == "assistant":
            assistant_msgs.append(content)

    key_user_msgs = []

    memory_keywords = [
        "我喜欢",
        "我讨厌",
        "我叫",
        "我是",
        "我的名字",
        "记住",
        "别忘了",
        "我想",
        "我希望",
        "我在",
        "我住",
        "我学",
        "我玩",
        "我推",
        "我担心",
        "我的生日",
        "我生日",
        "我爱好",
        "我不喜欢",
        "项目",
        "代码",
        "bug",
        "报错",
        "需求",
        "修改",
        "完整代码",
        "缓存",
        "未命中",
        "API"
    ]

    for msg in user_msgs:
        if any(k in msg for k in memory_keywords):
            key_user_msgs.append(msg)

    if not key_user_msgs:
        key_user_msgs = user_msgs[-8:]

    lines = []
    lines.append("近期对话大意：")

    for index, msg in enumerate(key_user_msgs[-12:], 1):
        cleaned = msg.replace("\n", " ").strip()
        if len(cleaned) > 80:
            cleaned = cleaned[:80] + "..."
        lines.append(f"{index}. Goukou 提到：{cleaned}")

    if assistant_msgs:
        last_reply = assistant_msgs[-1].replace("\n", " ").strip()
        if len(last_reply) > 60:
            last_reply = last_reply[:60] + "..."
        lines.append(f"最近鹿婉回应风格：{last_reply}")

    summary = "\n".join(lines)

    if len(summary) > SUMMARY_OUTPUT_MAX_CHARS:
        summary = summary[:SUMMARY_OUTPUT_MAX_CHARS] + "..."

    return summary


def summarize_recent_messages_with_deepseek(items):
    """
    调用 DeepSeek，把最近 50 条消息提炼成摘要。
    摘要失败时用本地兜底，避免卡主聊天。
    """
    api_key = DEEPSEEK_API_KEY.strip()

    if not api_key or api_key == "在这里填你的DeepSeek API Key":
        return fallback_extract_recent_summary(items)

    if not items:
        return ""

    lines = []

    for item in items:
        role_name = "Goukou" if item["role"] == "user" else "鹿婉"
        content = item["content"].replace("\n", " ").strip()
        msg_time = item.get("time", "")

        if len(content) > 160:
            content = content[:160] + "..."

        if msg_time:
            lines.append(f"[{msg_time}] {role_name}: {content}")
        else:
            lines.append(f"{role_name}: {content}")

    source_text = "\n".join(lines)

    system_prompt = """
你是一个本地聊天记忆提炼器。
请把给定聊天记录压缩成“下一次对话可用的近期记忆摘要”。

要求：
1. 只保留事实、用户偏好、正在做的项目、明确要求、未解决问题、最近情绪。
2. 删除废话、寒暄、重复内容。
3. 不要编造没有出现过的信息。
4. 用中文输出。
5. 不要输出 JSON、Markdown、标题解释。
6. 控制在 900 字以内。
7. 第三人称描述 Goukou 和鹿婉的互动。
8. 如果有代码需求，保留关键功能点。
"""

    user_prompt = f"""
下面是最近的聊天记录，请提炼成近期记忆摘要：

{source_text}
"""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        "temperature": 0.2,
        "max_tokens": 700,
        "stream": False
    }

    try:
        response = requests.post(
            DEEPSEEK_API_URL,
            headers=headers,
            json=payload,
            timeout=30
        )

        response.raise_for_status()

        result = response.json()
        summary = result["choices"][0]["message"]["content"]
        summary = clean_summary_text(summary)

        if not summary:
            summary = fallback_extract_recent_summary(items)

        return summary

    except Exception as e:
        write_error_log(f"DeepSeek 摘要失败，使用本地兜底: {repr(e)}")
        return fallback_extract_recent_summary(items)


def refresh_recent_summary():
    """
    读取最近 50 条本地数据库消息，提炼并保存摘要。
    """
    try:
        items = read_conversation_log_items(SUMMARY_SOURCE_MESSAGE_LIMIT)

        if not items:
            save_recent_summary("", 0)
            return ""

        summary = summarize_recent_messages_with_deepseek(items)
        save_recent_summary(summary, len(items))

        return summary

    except Exception as e:
        write_error_log(f"刷新近期摘要失败: {repr(e)}")
        return ""


def refresh_recent_summary_async():
    """
    后台刷新近期摘要，避免卡 UI。
    """
    def worker():
        try:
            refresh_recent_summary()
        except Exception as e:
            write_error_log(f"后台刷新近期摘要失败: {repr(e)}")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


def build_memory_system_prompt():
    """
    把人设、长期记忆、近期摘要合并。
    """
    memory_text = load_long_memory_text()
    recent_summary = load_recent_summary_text()

    prompt = LUWAN_SYSTEM_PROMPT

    if memory_text:
        prompt += f"""

以下是鹿婉记得的长期记忆，会影响你之后的回复：
{memory_text}

长期记忆使用规则：
1. 不要生硬复述记忆。
2. 只在相关话题自然联想。
3. 如果 Goukou 提到以前的事，要表现得像记得。
4. 仍然保持简短自然。
"""

    if recent_summary:
        prompt += f"""

以下是最近 50 条本地聊天记录提炼出的近期记忆摘要。
下一次回复时，如果 Goukou 的问题与摘要相关，要自然引用这些信息：
{recent_summary}

近期摘要使用规则：
1. 只在相关时引用，不要每次都提。
2. 不要说“根据摘要”或“根据记录”。
3. 要像鹿婉真的记得刚刚聊过的内容。
4. 如果 Goukou 继续要代码，要优先延续最近的代码需求。
5. 回复仍然保持简短自然。
"""

    return prompt


def init_local_memory_to_history():
    """
    程序启动时，把本地最近聊天读入 conversation_history。
    """
    global conversation_history

    recent = load_recent_conversation(MAX_LOCAL_LOAD_MESSAGES)

    if recent:
        conversation_history = recent[-MAX_HISTORY_MESSAGES:]


def call_deepseek_once(user_text):
    """
    单次请求 DeepSeek。
    成功返回清理后的 reply。
    失败抛出异常。
    """
    api_key = DEEPSEEK_API_KEY.strip()

    if not api_key or api_key == "在这里填你的DeepSeek API Key":
        raise RuntimeError("DeepSeek API Key 未配置")

    messages = [
        {
            "role": "system",
            "content": build_memory_system_prompt()
        }
    ]

    messages.extend(conversation_history[-MAX_HISTORY_MESSAGES:])

    messages.append({
        "role": "user",
        "content": user_text
    })

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.9,
        "max_tokens": 120,
        "stream": False
    }

    response = requests.post(
        DEEPSEEK_API_URL,
        headers=headers,
        json=payload,
        timeout=30
    )

    response.raise_for_status()

    result = response.json()
    reply = result["choices"][0]["message"]["content"]
    reply = clean_ai_reply(reply)

    if not reply or len(reply.strip()) < API_VALID_REPLY_MIN_LENGTH:
        raise RuntimeError("API 返回空消息")

    return reply


def request_api_until_success(user_text):
    """
    缓存未命中后，循环请求 API，直到成功拿到有效回复。
    不显示请求 API 等待气泡。
    API_RETRY_MAX_TIMES = 0 表示无限重试。
    """
    attempt = 0

    while True:
        attempt += 1

        try:
            reply = call_deepseek_once(user_text)

            if reply:
                return reply

        except Exception as e:
            error_text = f"第 {attempt} 次 API 请求失败: {repr(e)}"
            print(error_text)
            write_error_log(error_text)

            if API_RETRY_MAX_TIMES > 0 and attempt >= API_RETRY_MAX_TIMES:
                raise RuntimeError("API 重试次数已达上限")

            time.sleep(API_RETRY_INTERVAL_SECONDS)


def handle_user_message(user_text):
    """
    总流程：
    1. 查缓存。
    2. 命中直接回复。
    3. 未命中则后台请求 API 直到成功。
    4. 成功后写入缓存和对话日志。
    """
    global conversation_history

    cached_reply = get_cached_reply(user_text)

    if cached_reply:
        reply = clean_ai_reply(cached_reply)

        conversation_history.append({
            "role": "user",
            "content": user_text
        })
        conversation_history.append({
            "role": "assistant",
            "content": reply
        })

        if len(conversation_history) > MAX_HISTORY_MESSAGES:
            conversation_history = conversation_history[-MAX_HISTORY_MESSAGES:]

        append_conversation_log("user", user_text)
        append_conversation_log("assistant", reply)
        update_simple_long_memory(user_text, reply)
        refresh_recent_summary_async()

        return reply

    reply = request_api_until_success(user_text)

    set_cached_reply(user_text, reply)

    conversation_history.append({
        "role": "user",
        "content": user_text
    })
    conversation_history.append({
        "role": "assistant",
        "content": reply
    })

    if len(conversation_history) > MAX_HISTORY_MESSAGES:
        conversation_history = conversation_history[-MAX_HISTORY_MESSAGES:]

    append_conversation_log("user", user_text)
    append_conversation_log("assistant", reply)
    update_simple_long_memory(user_text, reply)
    refresh_recent_summary_async()

    return reply


pygame.init()
pygame.font.init()


# =====================
# 文件名
# =====================

BODY_PATH = resource_path("body.png")
LEFT_EYE_PATH = resource_path("left_eye.png")
RIGHT_EYE_PATH = resource_path("right_eye.png")
ICON_PATH = resource_path("icon.png")


# =====================
# 屏幕与窗口设置
# =====================

display_info = pygame.display.Info()
SCREEN_W = display_info.current_w
SCREEN_H = display_info.current_h

WINDOW_W = SCREEN_W
WINDOW_H = SCREEN_H

FPS = 60


# =====================
# 整体缩放
# =====================

CHARACTER_SCALE = 0.3


# =====================
# 透明背景颜色
# =====================

TRANSPARENT_COLOR = (1, 2, 3)


# =====================
# 轮廓线设置
# =====================

OUTLINE_COLOR = (255, 255, 255)
OUTLINE_THICKNESS = 4


# =====================
# 边缘黑边处理设置
# =====================

REMOVE_DARK_EDGE = True
DARK_EDGE_THRESHOLD = 95
EDGE_SCAN_RADIUS = 3


# =====================
# 眼仁移动范围
# =====================

MAX_MOVE_ORIGINAL = 8


# =====================
# 气泡与输入框设置
# =====================

BUBBLE_DURATION = 5
INPUT_IDLE_DURATION = 5

# 粘贴长文本的话，可以改大，比如 2000
MAX_INPUT_LENGTH = 160

MAX_HISTORY_MESSAGES = 8

BUBBLE_BG = (255, 255, 255)
BUBBLE_BORDER = (65, 65, 65)
BUBBLE_TEXT = (35, 35, 35)

INPUT_BG = (255, 255, 245)
INPUT_BORDER = (80, 80, 80)
PLACEHOLDER_COLOR = (145, 145, 145)
CURSOR_COLOR = (20, 20, 20)
COMPOSITION_COLOR = (90, 90, 90)

CENTER_CLICK_W_RATIO = 0.55
CENTER_CLICK_H_RATIO = 0.55

BUBBLE_Y_OFFSET_RATIO = 0.04


# =====================
# 输入框设置，可手动调
# =====================

INPUT_BOX_WIDTH = 320
INPUT_BOX_HEIGHT = 52
INPUT_BOX_ABOVE_HEAD_OFFSET = 20

INPUT_BOX_MIN_LEFT_MARGIN = 10
INPUT_BOX_MIN_RIGHT_MARGIN = 10
INPUT_BOX_TOP_MARGIN = 40
INPUT_BOX_BOTTOM_MARGIN = 100


# =====================
# 头部拖动区域设置
# =====================

HEAD_DRAG_W_RATIO = 0.88
HEAD_DRAG_H_RATIO = 0.42
HEAD_DRAG_Y_START_RATIO = 0.00


# =====================
# 拖动设置
# =====================

dragging = False
drag_start_mouse = (0, 0)
drag_start_body = (0, 0)

hwnd = None
screen = None


# =====================
# 对话状态
# =====================

input_active = False
input_text = ""
composition_text = ""
input_show_until = 0

bubble_text = ""
bubble_show_until = 0

is_waiting_ai = False
conversation_history = []

# 用于避免 Ctrl + V 后 TEXTINPUT 额外输入 v
skip_next_textinput = False


# =====================
# 调试模式
# =====================

DEBUG = False


def get_window_handle():
    info = pygame.display.get_wm_info()
    return info.get("window")


def apply_transparency():
    global hwnd

    hwnd = get_window_handle()

    if hwnd is None:
        print("没有获取到窗口句柄")
        return

    ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    ex_style = ex_style | win32con.WS_EX_LAYERED
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)

    color_key = win32api.RGB(
        TRANSPARENT_COLOR[0],
        TRANSPARENT_COLOR[1],
        TRANSPARENT_COLOR[2]
    )

    win32gui.SetLayeredWindowAttributes(
        hwnd,
        color_key,
        255,
        win32con.LWA_COLORKEY
    )

    win32gui.RedrawWindow(
        hwnd,
        None,
        None,
        win32con.RDW_INVALIDATE | win32con.RDW_UPDATENOW
    )


def make_topmost_fullscreen():
    """
    把窗口放到屏幕左上角，并设为置顶无边框全屏。
    """
    if hwnd is None:
        return

    win32gui.SetWindowPos(
        hwnd,
        win32con.HWND_TOPMOST,
        0,
        0,
        WINDOW_W,
        WINDOW_H,
        win32con.SWP_SHOWWINDOW
    )


def set_custom_icon():
    """
    设置窗口左上角 / 任务栏图标。
    """
    try:
        if os.path.exists(ICON_PATH):
            icon_surface = pygame.image.load(ICON_PATH).convert_alpha()
        elif os.path.exists(BODY_PATH):
            icon_surface = pygame.image.load(BODY_PATH).convert_alpha()
        else:
            return

        icon_surface = pygame.transform.smoothscale(icon_surface, (32, 32))
        pygame.display.set_icon(icon_surface)

    except Exception as e:
        print("设置图标失败：", e)
        write_error_log(f"设置图标失败：{repr(e)}")


def create_window():
    global screen

    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H), pygame.NOFRAME)
    pygame.display.set_caption("小鹿婉")

    set_custom_icon()

    screen.fill(TRANSPARENT_COLOR)
    pygame.display.update()

    time.sleep(0.05)
    apply_transparency()
    make_topmost_fullscreen()

    return screen


def load_font(size):
    """
    加载中文字体。
    """
    font_paths = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyh.ttf",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
    ]

    for path in font_paths:
        if os.path.exists(path):
            return pygame.font.Font(path, size)

    return pygame.font.SysFont("Microsoft YaHei", size)


def clamp(value, min_value, max_value):
    return max(min_value, min(value, max_value))


def wrap_text(text, font, max_width):
    """
    中文按像素自动换行。
    """
    if not text:
        return []

    lines = []
    current = ""

    for char in text:
        if char == "\n":
            lines.append(current)
            current = ""
            continue

        test = current + char

        if font.size(test)[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = char

    if current:
        lines.append(current)

    return lines


def clean_ai_reply(text):
    """
    清理模型可能输出的 XML、状态、思考标签。
    """
    if not text:
        return ""

    text = text.strip()

    match = re.search(r"<message[^>]*>(.*?)</message>", text, re.S)
    if match:
        text = match.group(1).strip()

    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"<status>.*?</status>", "", text, flags=re.S)
    text = re.sub(r"</?message_part>", "", text)
    text = re.sub(r"<[^>]+>", "", text)

    text = text.strip().strip('"').strip("'")
    text = text.replace("\n", " ").strip()

    if len(text) > 60:
        text = text[:60] + "..."

    if not text:
        text = ""

    return text


def set_bubble(text, duration=BUBBLE_DURATION):
    global bubble_text, bubble_show_until

    bubble_text = text
    bubble_show_until = time.time() + duration


def start_ai_chat(user_text):
    """
    启动 AI 聊天线程。
    不显示查询缓存中 / 请求 API 中等待气泡。
    """
    global is_waiting_ai

    if is_waiting_ai:
        return

    is_waiting_ai = True

    def worker():
        global is_waiting_ai

        try:
            reply = handle_user_message(user_text)
            set_bubble(reply, BUBBLE_DURATION)
        except Exception as e:
            print("AI线程错误:", e)
            write_error_log(f"AI线程错误: {repr(e)}")
            set_bubble("API一直失败了", BUBBLE_DURATION)
        finally:
            is_waiting_ai = False

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


def whiten_edge_pixels(
    src_surface,
    edge_color=(255, 255, 255),
    dark_threshold=95,
    radius=3
):
    """
    把靠近透明区域的深色边缘像素改成白色。
    """
    surf = src_surface.copy().convert_alpha()
    width, height = surf.get_size()

    pixels_to_change = []

    for y in range(height):
        for x in range(width):
            r, g, b, a = surf.get_at((x, y))

            if a == 0:
                continue

            brightness = (r + g + b) / 3
            if brightness > dark_threshold:
                continue

            near_transparent = False

            for dy in range(-radius, radius + 1):
                if near_transparent:
                    break

                for dx in range(-radius, radius + 1):
                    if dx == 0 and dy == 0:
                        continue

                    nx = x + dx
                    ny = y + dy

                    if nx < 0 or nx >= width or ny < 0 or ny >= height:
                        near_transparent = True
                        break

                    _, _, _, na = surf.get_at((nx, ny))

                    if na < 20:
                        near_transparent = True
                        break

            if near_transparent:
                pixels_to_change.append((x, y, a))

    for x, y, a in pixels_to_change:
        surf.set_at((x, y), (edge_color[0], edge_color[1], edge_color[2], a))

    return surf


def create_outline_surface(src_surface, color=(255, 255, 255), thickness=4):
    """
    根据角色透明区域生成更明显的白色外轮廓。
    """
    width, height = src_surface.get_size()

    mask = pygame.mask.from_surface(src_surface)
    outline_surface = pygame.Surface((width, height), pygame.SRCALPHA)

    for dy in range(-thickness, thickness + 1):
        for dx in range(-thickness, thickness + 1):
            if dx == 0 and dy == 0:
                continue

            if dx * dx + dy * dy > thickness * thickness:
                continue

            offset_mask = mask.to_surface(
                setcolor=(color[0], color[1], color[2], 255),
                unsetcolor=(0, 0, 0, 0)
            )

            outline_surface.blit(offset_mask, (dx, dy))

    body_mask_surface = mask.to_surface(
        setcolor=(0, 0, 0, 255),
        unsetcolor=(0, 0, 0, 0)
    )

    outline_surface.blit(
        body_mask_surface,
        (0, 0),
        special_flags=pygame.BLEND_RGBA_SUB
    )

    return outline_surface


def get_global_mouse_pos():
    """
    获取全屏鼠标坐标。
    """
    try:
        x, y = win32api.GetCursorPos()
        return int(x), int(y)
    except Exception:
        return pygame.mouse.get_pos()


def get_eye_offset(mouse_pos, eye_screen_center, max_move):
    """
    根据鼠标位置计算眼仁偏移。
    """
    mx, my = mouse_pos
    ex, ey = eye_screen_center

    dx = mx - ex
    dy = my - ey

    dist = math.sqrt(dx * dx + dy * dy)

    if dist == 0:
        return 0, 0

    move = min(max_move, dist * 0.08)

    ox = dx / dist * move
    oy = dy / dist * move

    return int(ox), int(oy)


def is_mouse_on_body(pos, body, body_x, body_y, draw_w, draw_h):
    """
    判断鼠标是否点在角色非透明区域上。
    """
    mx, my = pos

    if mx < body_x or mx >= body_x + draw_w:
        return False
    if my < body_y or my >= body_y + draw_h:
        return False

    local_x = mx - body_x
    local_y = my - body_y

    try:
        alpha = body.get_at((local_x, local_y)).a
        return alpha > 10
    except Exception:
        return False


def is_mouse_on_center(pos, body_x, body_y, draw_w, draw_h):
    """
    判断是否点击角色中心区域，用于打开聊天输入框。
    """
    mx, my = pos

    center_x = body_x + draw_w // 2
    center_y = body_y + draw_h // 2

    area_w = draw_w * CENTER_CLICK_W_RATIO
    area_h = draw_h * CENTER_CLICK_H_RATIO

    return (
        center_x - area_w / 2 <= mx <= center_x + area_w / 2
        and center_y - area_h / 2 <= my <= center_y + area_h / 2
    )


def is_mouse_on_head(pos, body_x, body_y, draw_w, draw_h):
    """
    判断是否点击角色头部区域，用于拖动。
    """
    mx, my = pos

    head_w = draw_w * HEAD_DRAG_W_RATIO
    head_h = draw_h * HEAD_DRAG_H_RATIO

    head_center_x = body_x + draw_w // 2
    head_y = body_y + draw_h * HEAD_DRAG_Y_START_RATIO

    return (
        head_center_x - head_w / 2 <= mx <= head_center_x + head_w / 2
        and head_y <= my <= head_y + head_h
    )


def is_ctrl_k(event):
    """
    判断 Ctrl + K。
    """
    keys = pygame.key.get_pressed()
    ctrl_down = keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL]
    return ctrl_down and event.key == pygame.K_k


def is_ctrl_v(event):
    """
    判断 Ctrl + V。
    """
    keys = pygame.key.get_pressed()
    ctrl_down = keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL]
    return ctrl_down and event.key == pygame.K_v


def open_input_box():
    """
    打开对话输入框。
    支持：
    1. 点击角色身体中心打开。
    2. 输入框关闭时按 Enter 打开。
    """
    global input_active, input_text, composition_text, input_show_until

    if is_waiting_ai:
        return

    input_active = True
    input_text = ""
    composition_text = ""
    input_show_until = time.time() + INPUT_IDLE_DURATION
    enable_text_input()


def draw_bubble(screen, text, x, y, font):
    """
    绘制头顶气泡。
    """
    if not text:
        return

    max_text_width = 310
    padding = 12
    line_gap = 4
    line_height = font.get_height() + line_gap

    lines = wrap_text(text, font, max_text_width)

    if len(lines) > 5:
        lines = lines[:5]
        lines[-1] += "..."

    text_width = 0
    for line in lines:
        text_width = max(text_width, font.size(line)[0])

    bubble_width = clamp(text_width + padding * 2, 120, 350)
    bubble_height = len(lines) * line_height + padding * 2

    bubble_x = x - bubble_width // 2
    bubble_y = y - bubble_height

    bubble_x = clamp(bubble_x, 10, WINDOW_W - bubble_width - 10)
    bubble_y = clamp(bubble_y, 10, WINDOW_H - bubble_height - 30)

    bubble_rect = pygame.Rect(
        bubble_x,
        bubble_y,
        bubble_width,
        bubble_height
    )

    pygame.draw.rect(
        screen,
        BUBBLE_BG,
        bubble_rect,
        border_radius=14
    )
    pygame.draw.rect(
        screen,
        BUBBLE_BORDER,
        bubble_rect,
        2,
        border_radius=14
    )

    triangle = [
        (x - 10, bubble_rect.bottom - 1),
        (x + 10, bubble_rect.bottom - 1),
        (x, bubble_rect.bottom + 14)
    ]

    pygame.draw.polygon(screen, BUBBLE_BG, triangle)
    pygame.draw.polygon(screen, BUBBLE_BORDER, triangle, 2)

    text_y = bubble_rect.y + padding

    for line in lines:
        text_surface = font.render(line, True, BUBBLE_TEXT)
        screen.blit(text_surface, (bubble_rect.x + padding, text_y))
        text_y += line_height


def fit_input_text_to_width(text, font, max_width):
    """
    输入框文本过长时，只显示末尾部分。
    """
    if font.size(text)[0] <= max_width:
        return text

    result = text
    while result and font.size(result)[0] > max_width:
        result = result[1:]

    return result


def safe_set_text_input_rect(rect):
    """
    设置中文输入法候选框位置。
    """
    try:
        pygame.key.set_text_input_rect(rect)
    except Exception:
        pass


def get_input_box_rect(anchor_x, anchor_y):
    """
    获取输入框位置。
    """
    width = INPUT_BOX_WIDTH
    height = INPUT_BOX_HEIGHT

    rect = pygame.Rect(
        anchor_x - width // 2,
        anchor_y - height,
        width,
        height
    )

    rect.x = clamp(
        rect.x,
        INPUT_BOX_MIN_LEFT_MARGIN,
        WINDOW_W - width - INPUT_BOX_MIN_RIGHT_MARGIN
    )

    rect.y = clamp(
        rect.y,
        INPUT_BOX_TOP_MARGIN,
        WINDOW_H - height - INPUT_BOX_BOTTOM_MARGIN
    )

    return rect


def draw_input_box(screen, text, composition, x, y, font):
    """
    绘制输入框、中文输入预编辑文本、闪烁光标。
    """
    padding = 12

    rect = get_input_box_rect(x, y)

    pygame.draw.rect(
        screen,
        INPUT_BG,
        rect,
        border_radius=12
    )
    pygame.draw.rect(
        screen,
        INPUT_BORDER,
        rect,
        2,
        border_radius=12
    )

    inner_w = rect.width - padding * 2
    cursor_visible = (int(time.time() * 2) % 2) == 0

    text_x = rect.x + padding
    text_y = rect.y + 15

    display_text = ""
    display_color = BUBBLE_TEXT
    underline_start_x = None
    underline_width = 0

    if text or composition:
        full_text = text + composition
        display_text = fit_input_text_to_width(full_text, font, inner_w - 8)
        display_color = BUBBLE_TEXT

        if composition:
            visible_start_index = max(0, len(full_text) - len(display_text))
            composition_start = max(0, len(text) - visible_start_index)

            before_composition = display_text[:composition_start]
            composition_visible = display_text[composition_start:]

            underline_start_x = text_x + font.size(before_composition)[0]
            underline_width = font.size(composition_visible)[0]
    else:
        display_text = ""

    if display_text:
        text_surface = font.render(display_text, True, display_color)
        screen.blit(text_surface, (text_x, text_y))

    text_width = font.size(display_text)[0]

    cursor_x = text_x + text_width + 2

    if cursor_x > rect.right - padding:
        cursor_x = rect.right - padding

    cursor_x = clamp(cursor_x, rect.x + padding, rect.right - padding)

    if underline_start_x is not None and underline_width > 0:
        underline_y = text_y + font.get_height() + 1
        pygame.draw.line(
            screen,
            COMPOSITION_COLOR,
            (underline_start_x, underline_y),
            (underline_start_x + underline_width, underline_y),
            1
        )

    if cursor_visible:
        cursor_y1 = rect.y + 12
        cursor_y2 = rect.y + rect.height - 12

        pygame.draw.line(
            screen,
            CURSOR_COLOR,
            (cursor_x, cursor_y1),
            (cursor_x, cursor_y2),
            2
        )

    ime_x = clamp(cursor_x, rect.x + padding, rect.right - 120)
    ime_y = clamp(rect.y + rect.height + 8, 30, WINDOW_H - 120)

    ime_rect = pygame.Rect(
        ime_x,
        ime_y,
        260,
        40
    )

    safe_set_text_input_rect(ime_rect)


def clamp_body_position(body_x, body_y, draw_w, draw_h):
    """
    限制角色不要拖出屏幕太多。
    """
    body_x = max(-draw_w + 40, min(WINDOW_W - 40, body_x))
    body_y = max(-draw_h + 40, min(WINDOW_H - 40, body_y))

    return body_x, body_y


def enable_text_input():
    """
    开启 Pygame 文本输入模式。
    """
    try:
        pygame.key.start_text_input()
    except Exception:
        pass


def disable_text_input():
    """
    关闭 Pygame 文本输入模式。
    """
    try:
        pygame.key.stop_text_input()
    except Exception:
        pass


def check_resource_or_exit(path, display_name):
    if not os.path.exists(path):
        msg = f"找不到 {display_name}: {path}"
        print(msg)
        write_error_log(msg)
        input("按回车退出...")
        sys.exit()


def main():
    global screen
    global dragging, drag_start_mouse, drag_start_body
    global input_active, input_text, composition_text, input_show_until
    global bubble_text
    global skip_next_textinput

    ensure_memory_repo()
    init_local_memory_to_history()

    # 启动时后台提炼最近 50 条消息
    refresh_recent_summary_async()

    screen = create_window()
    clock = pygame.time.Clock()

    font = load_font(18)

    check_resource_or_exit(BODY_PATH, "body.png")
    check_resource_or_exit(LEFT_EYE_PATH, "left_eye.png")
    check_resource_or_exit(RIGHT_EYE_PATH, "right_eye.png")

    body_original = pygame.image.load(BODY_PATH).convert_alpha()
    left_eye_original = pygame.image.load(LEFT_EYE_PATH).convert_alpha()
    right_eye_original = pygame.image.load(RIGHT_EYE_PATH).convert_alpha()

    body_w, body_h = body_original.get_size()

    base_scale = min(WINDOW_W / body_w, WINDOW_H / body_h)
    scale = base_scale * CHARACTER_SCALE

    draw_w = int(body_w * scale)
    draw_h = int(body_h * scale)

    body = pygame.transform.smoothscale(body_original, (draw_w, draw_h))

    if REMOVE_DARK_EDGE:
        body = whiten_edge_pixels(
            body,
            edge_color=OUTLINE_COLOR,
            dark_threshold=DARK_EDGE_THRESHOLD,
            radius=EDGE_SCAN_RADIUS
        )

    body_outline = create_outline_surface(
        body,
        OUTLINE_COLOR,
        OUTLINE_THICKNESS
    )

    body_x = (WINDOW_W - draw_w) // 2
    body_y = (WINDOW_H - draw_h) // 2

    LEFT_EYE_CENTER_ORIGINAL = (422, 640)
    RIGHT_EYE_CENTER_ORIGINAL = (558, 652)

    EYE_W_ORIGINAL = 200
    EYE_H_ORIGINAL = 200

    LEFT_EYE_SCALE = 1.0
    RIGHT_EYE_SCALE = 1.0

    def scale_point(p):
        return int(p[0] * scale), int(p[1] * scale)

    left_eye_center = scale_point(LEFT_EYE_CENTER_ORIGINAL)
    right_eye_center = scale_point(RIGHT_EYE_CENTER_ORIGINAL)

    max_move = max(2, int(MAX_MOVE_ORIGINAL * scale))

    left_eye_w = int(EYE_W_ORIGINAL * scale * LEFT_EYE_SCALE)
    left_eye_h = int(EYE_H_ORIGINAL * scale * LEFT_EYE_SCALE)

    right_eye_w = int(EYE_W_ORIGINAL * scale * RIGHT_EYE_SCALE)
    right_eye_h = int(EYE_H_ORIGINAL * scale * RIGHT_EYE_SCALE)

    left_eye_img = pygame.transform.smoothscale(
        left_eye_original,
        (left_eye_w, left_eye_h)
    )

    right_eye_img = pygame.transform.smoothscale(
        right_eye_original,
        (right_eye_w, right_eye_h)
    )

    running = True

    while running:
        clock.tick(FPS)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.KEYDOWN:
                if is_ctrl_k(event):
                    running = False

                if event.key == pygame.K_RETURN and not input_active:
                    open_input_box()
                    continue

                if input_active:
                    if event.key == pygame.K_RETURN:
                        text_to_send = input_text.strip()

                        if text_to_send:
                            input_active = False
                            composition_text = ""
                            input_text = ""
                            input_show_until = 0
                            disable_text_input()
                            start_ai_chat(text_to_send)

                    elif is_ctrl_v(event):
                        pasted_text = get_clipboard_text()

                        if pasted_text:
                            pasted_text = pasted_text.replace("\r\n", "\n")
                            pasted_text = pasted_text.replace("\r", "\n")
                            pasted_text = pasted_text.replace("\n", " ")

                            remaining = MAX_INPUT_LENGTH - len(input_text)

                            if remaining > 0:
                                input_text += pasted_text[:remaining]

                            composition_text = ""

                            if input_text.strip():
                                input_show_until = 0

                        skip_next_textinput = True

                    elif event.key == pygame.K_BACKSPACE:
                        input_text = input_text[:-1]

                        if not input_text.strip():
                            input_show_until = time.time() + INPUT_IDLE_DURATION

                    elif event.key == pygame.K_ESCAPE:
                        input_active = False
                        composition_text = ""
                        input_text = ""
                        input_show_until = 0
                        disable_text_input()

            if event.type == pygame.TEXTEDITING:
                if input_active:
                    composition_text = event.text

            if event.type == pygame.TEXTINPUT:
                if input_active:
                    if skip_next_textinput:
                        skip_next_textinput = False
                        continue

                    if len(input_text) + len(event.text) <= MAX_INPUT_LENGTH:
                        input_text += event.text

                    composition_text = ""

                    if input_text.strip():
                        input_show_until = 0

            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    mouse_global = get_global_mouse_pos()

                    if is_mouse_on_body(mouse_global, body, body_x, body_y, draw_w, draw_h):

                        if is_mouse_on_head(mouse_global, body_x, body_y, draw_w, draw_h):
                            dragging = True
                            drag_start_mouse = mouse_global
                            drag_start_body = (body_x, body_y)

                        elif is_mouse_on_center(mouse_global, body_x, body_y, draw_w, draw_h):
                            open_input_box()

                        else:
                            dragging = True
                            drag_start_mouse = mouse_global
                            drag_start_body = (body_x, body_y)

            if event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    dragging = False

            if event.type == pygame.WINDOWLEAVE:
                dragging = False

        mouse = get_global_mouse_pos()

        if input_active and not input_text.strip() and not composition_text.strip() and input_show_until > 0:
            if time.time() >= input_show_until:
                input_active = False
                input_text = ""
                composition_text = ""
                input_show_until = 0
                disable_text_input()

        if dragging:
            current_mouse = mouse

            dx = current_mouse[0] - drag_start_mouse[0]
            dy = current_mouse[1] - drag_start_mouse[1]

            body_x = drag_start_body[0] + dx
            body_y = drag_start_body[1] + dy

            body_x, body_y = clamp_body_position(body_x, body_y, draw_w, draw_h)

        screen.fill(TRANSPARENT_COLOR)

        screen.blit(body_outline, (body_x, body_y))
        screen.blit(body, (body_x, body_y))

        left_screen_center = (
            body_x + left_eye_center[0],
            body_y + left_eye_center[1]
        )

        right_screen_center = (
            body_x + right_eye_center[0],
            body_y + right_eye_center[1]
        )

        left_offset = get_eye_offset(mouse, left_screen_center, max_move)
        right_offset = get_eye_offset(mouse, right_screen_center, max_move)

        screen.blit(
            left_eye_img,
            (
                left_screen_center[0] - left_eye_w // 2 + left_offset[0],
                left_screen_center[1] - left_eye_h // 2 + left_offset[1]
            )
        )

        screen.blit(
            right_eye_img,
            (
                right_screen_center[0] - right_eye_w // 2 + right_offset[0],
                right_screen_center[1] - right_eye_h // 2 + right_offset[1]
            )
        )

        bubble_x = body_x + draw_w // 2
        bubble_y = body_y + int(draw_h * BUBBLE_Y_OFFSET_RATIO)

        now = time.time()

        if bubble_text and now < bubble_show_until:
            draw_bubble(screen, bubble_text, bubble_x, bubble_y, font)
        else:
            bubble_text = ""

        if input_active:
            draw_input_box(
                screen,
                input_text,
                composition_text,
                bubble_x,
                bubble_y - INPUT_BOX_ABOVE_HEAD_OFFSET,
                font
            )

        if DEBUG:
            pygame.draw.circle(screen, (255, 0, 0), left_screen_center, 4)
            pygame.draw.circle(screen, (255, 0, 0), right_screen_center, 4)

            center_x = body_x + draw_w // 2
            center_y = body_y + draw_h // 2
            area_w = int(draw_w * CENTER_CLICK_W_RATIO)
            area_h = int(draw_h * CENTER_CLICK_H_RATIO)

            pygame.draw.rect(
                screen,
                (0, 255, 0),
                pygame.Rect(
                    center_x - area_w // 2,
                    center_y - area_h // 2,
                    area_w,
                    area_h
                ),
                2
            )

            head_w = int(draw_w * HEAD_DRAG_W_RATIO)
            head_h = int(draw_h * HEAD_DRAG_H_RATIO)
            head_x = body_x + draw_w // 2 - head_w // 2
            head_y = body_y + int(draw_h * HEAD_DRAG_Y_START_RATIO)

            pygame.draw.rect(
                screen,
                (0, 120, 255),
                pygame.Rect(
                    head_x,
                    head_y,
                    head_w,
                    head_h
                ),
                2
            )

        pygame.display.flip()

    disable_text_input()
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        err = traceback.format_exc()
        print(err)
        write_error_log(err)

        try:
            input("程序出错，按回车退出...")
        except Exception:
            pass

        pygame.quit()
        sys.exit()