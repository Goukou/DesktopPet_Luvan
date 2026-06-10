import pygame
import sys
import os
import math
import time

try:
    import win32gui
    import win32con
    import win32api
except ImportError:
    print("缺少 pywin32，请先运行：pip install pywin32")
    sys.exit()


def resource_path(relative_path):
    """
    兼容普通运行和 PyInstaller 打包后的资源路径。

    普通运行时：
        从当前项目目录读取资源。

    PyInstaller 打包后：
        从临时解压目录 sys._MEIPASS 读取资源。
    """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


pygame.init()

# =====================
# 文件名
# =====================
BODY_PATH = resource_path("body.png")
LEFT_EYE_PATH = resource_path("left_eye.png")
RIGHT_EYE_PATH = resource_path("right_eye.png")

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
# 1.0 = 原大小
# 0.8 = 缩小到 80%
# 1.2 = 放大到 120%
# =====================
CHARACTER_SCALE = 0.3

# =====================
# 透明背景颜色
# 不要用黑色或白色，避免和轮廓/角色颜色冲突
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

# 黑边判定阈值
# 越大，越容易把深色边缘改白
# 如果误伤角色内部深色线条，可以调低，比如 50
DARK_EDGE_THRESHOLD = 95

# 只处理靠近透明区域的边缘像素
# 数值越大，处理范围越宽
EDGE_SCAN_RADIUS = 3

# =====================
# 拖动设置
# =====================
dragging = False
drag_start_mouse = (0, 0)
drag_start_body = (0, 0)

hwnd = None


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


def create_window():
    global screen

    # 无边框全屏透明窗口
    # 不使用 pygame.FULLSCREEN，避免独占全屏影响透明桌宠效果
    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H), pygame.NOFRAME)
    pygame.display.set_caption("小鹿婉")

    screen.fill(TRANSPARENT_COLOR)
    pygame.display.update()

    time.sleep(0.05)
    apply_transparency()
    make_topmost_fullscreen()

    return screen


screen = create_window()
clock = pygame.time.Clock()

# =====================
# 加载图片
# =====================
body_original = pygame.image.load(BODY_PATH).convert_alpha()
left_eye_original = pygame.image.load(LEFT_EYE_PATH).convert_alpha()
right_eye_original = pygame.image.load(RIGHT_EYE_PATH).convert_alpha()

body_w, body_h = body_original.get_size()

# =====================
# 缩放角色图
# =====================
base_scale = min(WINDOW_W / body_w, WINDOW_H / body_h)
scale = base_scale * CHARACTER_SCALE

draw_w = int(body_w * scale)
draw_h = int(body_h * scale)

body = pygame.transform.smoothscale(body_original, (draw_w, draw_h))


def whiten_edge_pixels(
    src_surface,
    edge_color=(255, 255, 255),
    dark_threshold=95,
    radius=3
):
    """
    把靠近透明区域的深色边缘像素改成白色。

    用途：
        如果 body.png 原图边缘自带黑色/深色抗锯齿，
        单纯画白色外轮廓无法覆盖这些黑边。
        这个函数会检测角色边缘附近的深色像素，并把它们改为白色。

    注意：
        只处理 alpha > 0 的角色像素。
        只处理靠近透明区域的边缘像素。
    """
    surf = src_surface.copy().convert_alpha()
    width, height = surf.get_size()

    pixels_to_change = []

    for y in range(height):
        for x in range(width):
            r, g, b, a = surf.get_at((x, y))

            # 完全透明的不处理
            if a == 0:
                continue

            # 判断是不是深色像素
            brightness = (r + g + b) / 3
            if brightness > dark_threshold:
                continue

            near_transparent = False

            # 检查周围 radius 范围内是否有透明像素
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

                    # 透明或半透明，都认为是边缘附近
                    if na < 20:
                        near_transparent = True
                        break

            if near_transparent:
                pixels_to_change.append((x, y, a))

    for x, y, a in pixels_to_change:
        surf.set_at((x, y), (edge_color[0], edge_color[1], edge_color[2], a))

    return surf


if REMOVE_DARK_EDGE:
    body = whiten_edge_pixels(
        body,
        edge_color=OUTLINE_COLOR,
        dark_threshold=DARK_EDGE_THRESHOLD,
        radius=EDGE_SCAN_RADIUS
    )

# =====================
# 角色初始位置
# 默认居中
# =====================
body_x = (WINDOW_W - draw_w) // 2
body_y = (WINDOW_H - draw_h) // 2

# 如果你想默认在右下角，注释上面两行，启用下面两行：
# body_x = WINDOW_W - draw_w - 80
# body_y = WINDOW_H - draw_h - 80

# =====================
# 眼仁位置参数
# 这些坐标是基于 body.png 原图尺寸的坐标
# =====================
LEFT_EYE_CENTER_ORIGINAL = (420, 640)
RIGHT_EYE_CENTER_ORIGINAL = (552, 670)

# =====================
# 眼仁大小
# =====================
EYE_W_ORIGINAL = 200
EYE_H_ORIGINAL = 200

LEFT_EYE_SCALE = 1.0
RIGHT_EYE_SCALE = 1.0

# =====================
# 眼仁移动范围
# 数值越大，眼睛移动幅度越大
# =====================
MAX_MOVE_ORIGINAL = 16

# =====================
# 调试模式
# True 会显示眼睛中心点
# =====================
DEBUG = False


def scale_point(p):
    return int(p[0] * scale), int(p[1] * scale)


left_eye_center = scale_point(LEFT_EYE_CENTER_ORIGINAL)
right_eye_center = scale_point(RIGHT_EYE_CENTER_ORIGINAL)

max_move = int(MAX_MOVE_ORIGINAL * scale)

# =====================
# 缩放眼仁图片
# =====================
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


def create_outline_surface(src_surface, color=(255, 255, 255), thickness=4):
    """
    根据角色透明区域生成更明显的白色外轮廓。

    这个版本不是只画 mask.outline() 单线，
    而是把角色 alpha mask 向四周扩张，得到更厚的外描边。
    """
    width, height = src_surface.get_size()

    mask = pygame.mask.from_surface(src_surface)

    outline_surface = pygame.Surface((width, height), pygame.SRCALPHA)

    # 用多个方向偏移来制造厚轮廓
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

    # 挖掉角色本体区域，只保留外侧轮廓
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


body_outline = create_outline_surface(
    body,
    OUTLINE_COLOR,
    OUTLINE_THICKNESS
)


def get_global_mouse_pos():
    """
    获取全屏鼠标坐标。

    使用 win32api.GetCursorPos() 进行全屏追踪。
    这样即使 pygame 窗口没有鼠标焦点，眼球也可以继续追踪整个屏幕。

    如果极少数情况下失败，则退回 pygame.mouse.get_pos()。
    """
    try:
        x, y = win32api.GetCursorPos()
        return int(x), int(y)
    except Exception:
        return pygame.mouse.get_pos()


def get_eye_offset(mouse_pos, eye_screen_center):
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

    move = min(max_move, dist * 0.05)

    ox = dx / dist * move
    oy = dy / dist * move

    return int(ox), int(oy)


def is_mouse_on_body(pos):
    """
    判断鼠标是否点在角色非透明区域上。
    用于拖动角色。
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


def is_ctrl_k(event):
    """
    判断 Ctrl + K。
    """
    keys = pygame.key.get_pressed()
    ctrl_down = keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL]
    return ctrl_down and event.key == pygame.K_k


def clamp_body_position():
    """
    限制角色不要拖出屏幕太多。
    """
    global body_x, body_y

    body_x = max(-draw_w + 40, min(WINDOW_W - 40, body_x))
    body_y = max(-draw_h + 40, min(WINDOW_H - 40, body_y))


# =====================
# 主循环
# =====================
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

        # 鼠标按下：拖动角色
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                mouse_global = get_global_mouse_pos()

                if is_mouse_on_body(mouse_global):
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

    # 拖动角色
    if dragging:
        current_mouse = mouse

        dx = current_mouse[0] - drag_start_mouse[0]
        dy = current_mouse[1] - drag_start_mouse[1]

        body_x = drag_start_body[0] + dx
        body_y = drag_start_body[1] + dy

        clamp_body_position()

    # 每帧填透明背景色
    screen.fill(TRANSPARENT_COLOR)

    # 先画白色外轮廓
    screen.blit(body_outline, (body_x, body_y))

    # 再画处理过黑边的角色本体
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
    left_offset = get_eye_offset(mouse, left_screen_center)
    right_offset = get_eye_offset(mouse, right_screen_center)

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

    # 调试显示眼睛中心
    if DEBUG:
        pygame.draw.circle(screen, (255, 0, 0), left_screen_center, 4)
        pygame.draw.circle(screen, (255, 0, 0), right_screen_center, 4)

    pygame.display.flip()

pygame.quit()
sys.exit()