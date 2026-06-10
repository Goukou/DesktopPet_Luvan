import pygame
import sys
import os
import math
import time
import threading
import requests
import re

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
    必须在 pygame.display.set_mode() 后调用，否则可能出现：
    No video mode has been set
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

    # 关键修复：
    # 先 set_mode，再 set_icon。
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
        text = "啊？我卡了"

    return text


def set_bubble(text, duration=BUBBLE_DURATION):
    global bubble_text, bubble_show_until

    bubble_text = text
    bubble_show_until = time.time() + duration


def ask_deepseek(user_text):
    global conversation_history

    api_key = DEEPSEEK_API_KEY.strip()

    if not api_key or api_key == "在这里填你的DeepSeek API Key":
        return "API Key还没填"

    messages = [
        {
            "role": "system",
            "content": LUWAN_SYSTEM_PROMPT
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

    try:
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

        return reply

    except requests.exceptions.Timeout:
        return "网卡了，绷不住"
    except requests.exceptions.HTTPError as e:
        try:
            code = e.response.status_code
            err_text = e.response.text
            print("HTTP error:", code, err_text)
            write_error_log(f"HTTP error: {code}\n{err_text}")
            return f"API炸了:{code}"
        except Exception:
            return "API炸了"
    except Exception as e:
        print("DeepSeek error:", e)
        write_error_log(f"DeepSeek error: {repr(e)}")
        return "出错了，已老实"


def start_ai_chat(user_text):
    global is_waiting_ai

    if is_waiting_ai:
        return

    is_waiting_ai = True
    set_bubble("思考中...", 30)

    def worker():
        global is_waiting_ai

        try:
            reply = ask_deepseek(user_text)
            set_bubble(reply, BUBBLE_DURATION)
        except Exception as e:
            print("AI线程错误:", e)
            write_error_log(f"AI线程错误: {repr(e)}")
            set_bubble("我刚刚卡住了", BUBBLE_DURATION)
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


def is_ctrl_k(event):
    """
    判断 Ctrl + K。
    """
    keys = pygame.key.get_pressed()
    ctrl_down = keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL]
    return ctrl_down and event.key == pygame.K_k


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


def draw_input_box(screen, text, composition, x, y, font):
    """
    绘制输入框、中文输入预编辑文本、闪烁光标。
    """
    padding = 10
    width = 380
    height = 48

    rect = pygame.Rect(
        x - width // 2,
        y - height,
        width,
        height
    )

    rect.x = clamp(rect.x, 10, WINDOW_W - width - 10)
    rect.y = clamp(rect.y, 10, WINDOW_H - height - 10)

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

    inner_w = width - padding * 2
    cursor_visible = (int(time.time() * 2) % 2) == 0

    text_x = rect.x + padding
    text_y = rect.y + 13

    placeholder = "输入内容，按 Enter 发送..."

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
        display_text = placeholder
        display_color = PLACEHOLDER_COLOR

    text_surface = font.render(display_text, True, display_color)
    screen.blit(text_surface, (text_x, text_y))

    text_width = font.size(display_text)[0]

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
        cursor_x = text_x + text_width + 4

        if text or composition:
            cursor_x = text_x + text_width + 2
        else:
            cursor_x = text_x + text_width + 4

        if cursor_x > rect.right - padding:
            cursor_x = rect.right - padding

        cursor_y1 = rect.y + 11
        cursor_y2 = rect.y + height - 11

        pygame.draw.line(
            screen,
            CURSOR_COLOR,
            (cursor_x, cursor_y1),
            (cursor_x, cursor_y2),
            2
        )

    ime_rect = pygame.Rect(
        text_x,
        rect.y + height,
        max(80, inner_w),
        32
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

    # ============================================================
    # 创建窗口
    # ============================================================

    screen = create_window()
    clock = pygame.time.Clock()

    font = load_font(18)

    # ============================================================
    # 加载图片
    # ============================================================

    check_resource_or_exit(BODY_PATH, "body.png")
    check_resource_or_exit(LEFT_EYE_PATH, "left_eye.png")
    check_resource_or_exit(RIGHT_EYE_PATH, "right_eye.png")

    body_original = pygame.image.load(BODY_PATH).convert_alpha()
    left_eye_original = pygame.image.load(LEFT_EYE_PATH).convert_alpha()
    right_eye_original = pygame.image.load(RIGHT_EYE_PATH).convert_alpha()

    body_w, body_h = body_original.get_size()

    # ============================================================
    # 缩放角色图
    # ============================================================

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

    # ============================================================
    # 角色初始位置
    # ============================================================

    body_x = (WINDOW_W - draw_w) // 2
    body_y = (WINDOW_H - draw_h) // 2

    # ============================================================
    # 眼仁位置参数
    # ============================================================

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

    # ============================================================
    # 主循环
    # ============================================================

    running = True

    while running:
        clock.tick(FPS)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            # Ctrl + K 退出
            if event.type == pygame.KEYDOWN:
                if is_ctrl_k(event):
                    running = False

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

            # 中文输入法正在组词
            if event.type == pygame.TEXTEDITING:
                if input_active:
                    composition_text = event.text

            # 中文输入法确认输入
            if event.type == pygame.TEXTINPUT:
                if input_active:
                    if len(input_text) + len(event.text) <= MAX_INPUT_LENGTH:
                        input_text += event.text

                    composition_text = ""

                    if input_text.strip():
                        input_show_until = 0

            # 鼠标按下
            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    mouse_global = get_global_mouse_pos()

                    if is_mouse_on_body(mouse_global, body, body_x, body_y, draw_w, draw_h):
                        # 点击中心：打开聊天输入框
                        if is_mouse_on_center(mouse_global, body_x, body_y, draw_w, draw_h):
                            if not is_waiting_ai:
                                input_active = True
                                input_text = ""
                                composition_text = ""
                                input_show_until = time.time() + INPUT_IDLE_DURATION
                                enable_text_input()
                        else:
                            dragging = True
                            drag_start_mouse = mouse_global
                            drag_start_body = (body_x, body_y)

            # 鼠标松开
            if event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    dragging = False

            if event.type == pygame.WINDOWLEAVE:
                dragging = False

        # 获取全屏鼠标坐标
        mouse = get_global_mouse_pos()

        # 输入框为空时，5 秒后自动消失
        if input_active and not input_text.strip() and not composition_text.strip() and input_show_until > 0:
            if time.time() >= input_show_until:
                input_active = False
                input_text = ""
                composition_text = ""
                input_show_until = 0
                disable_text_input()

        # 拖动角色
        if dragging:
            current_mouse = mouse

            dx = current_mouse[0] - drag_start_mouse[0]
            dy = current_mouse[1] - drag_start_mouse[1]

            body_x = drag_start_body[0] + dx
            body_y = drag_start_body[1] + dy

            body_x, body_y = clamp_body_position(body_x, body_y, draw_w, draw_h)

        # 每帧填透明背景色
        screen.fill(TRANSPARENT_COLOR)

        # 先画白色外轮廓
        screen.blit(body_outline, (body_x, body_y))

        # 再画角色本体
        screen.blit(body, (body_x, body_y))

        # 左右眼在屏幕里的中心位置
        left_screen_center = (
            body_x + left_eye_center[0],
            body_y + left_eye_center[1]
        )

        right_screen_center = (
            body_x + right_eye_center[0],
            body_y + right_eye_center[1]
        )

        # 计算眼仁偏移
        left_offset = get_eye_offset(mouse, left_screen_center, max_move)
        right_offset = get_eye_offset(mouse, right_screen_center, max_move)

        # 绘制左眼仁
        screen.blit(
            left_eye_img,
            (
                left_screen_center[0] - left_eye_w // 2 + left_offset[0],
                left_screen_center[1] - left_eye_h // 2 + left_offset[1]
            )
        )

        # 绘制右眼仁
        screen.blit(
            right_eye_img,
            (
                right_screen_center[0] - right_eye_w // 2 + right_offset[0],
                right_screen_center[1] - right_eye_h // 2 + right_offset[1]
            )
        )

        # 头顶气泡位置
        bubble_x = body_x + draw_w // 2
        bubble_y = body_y + int(draw_h * BUBBLE_Y_OFFSET_RATIO)

        now = time.time()

        if bubble_text and now < bubble_show_until:
            draw_bubble(screen, bubble_text, bubble_x, bubble_y, font)
        else:
            bubble_text = ""

        # 输入框
        if input_active:
            draw_input_box(
                screen,
                input_text,
                composition_text,
                bubble_x,
                bubble_y - 8,
                font
            )

        # 调试显示眼睛中心和点击中心范围
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

        pygame.display.flip()

    disable_text_input()
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
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