# -*- coding: utf-8 -*-
"""
《糖果屋之後》｜第一天：夜晚（第一幕）- Day 1 Night, Act 1
=================================================================
延續 candy_house_day1_daytime.py 第一幕的構圖（兄妹背對村民、村民圍成一圈），
背景改成夜晚。與其他檔案共用同一套標準：
    - 480x270 邏輯畫布、SCALE=2 → 視窗 960x640
    - 同一組色票 + 夜晚新增的黑紫色調（沿用序幕版的近黑紫語彙，不是新配色）
    - aacircle 反鋸齒圓形、深色描邊、smoothscale 放大、暗角只蓋動畫不蓋字幕
    - 所有角色腳底統一貼齊 GROUND_Y（跟房子底部同一條線）
    - 頭部一律用 draw_head_with_hair（大髮色圓＋偏小臉部圓），不會光頭
    - 字幕：滑鼠左鍵推進，提示文字貼字幕框正上方，ACTS 裡每一行字串都要有逗號分隔
    - 結尾文字不加括號

第一幕字幕與動畫觸發點：
    第1句：好奇的村民來到兄妹附近觀察。                       → 村民正常（昏暗）站著
    第2句：黑暗中，村民的身影逐漸扭曲。                       → 跑到這句時，村民開始扭曲
    第3句：糖果史萊姆出現，緩慢爬過道路，不斷分裂。           → 跑到這句時，村民變成粉色史萊姆
    第4句：漢賽爾第一次揮起提燈，也第一次用書上學來的招式擊退敵人。→ 漢賽爾轉身舉燈迎敵

目前只有第一幕（後續幕次之後補上，可以直接接在同一個 ACTS 清單後面延伸）。
操作：滑鼠左鍵推進字幕，ESC 離開。
    pip install pygame
    python candy_house_day1_night_act1.py
"""

import math
import random
import sys

import pygame
import pygame.gfxdraw

# ------------------------------------------------------------------
# 視窗規格（與前兩支檔案完全一致）
# ------------------------------------------------------------------
INTERNAL_W, INTERNAL_H = 480, 270
SCALE = 2
SUBTITLE_LOGICAL_H = 50
SCENE_H_PX = INTERNAL_H * SCALE
SUBTITLE_H_PX = SUBTITLE_LOGICAL_H * SCALE
WINDOW_W = INTERNAL_W * SCALE
WINDOW_H = SCENE_H_PX + SUBTITLE_H_PX
FPS = 60
OUTLINE = (12, 9, 18)

pygame.init()
screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
pygame.display.set_caption("糖果屋之後｜第一天 夜晚（第一幕）")
canvas = pygame.Surface((INTERNAL_W, INTERNAL_H))
glow_layer = pygame.Surface((INTERNAL_W, INTERNAL_H), pygame.SRCALPHA)
clock = pygame.time.Clock()


def aacircle(surf, color, center, radius):
    cx, cy, r = int(center[0]), int(center[1]), max(1, int(radius))
    pygame.gfxdraw.filled_circle(surf, cx, cy, r, color)
    pygame.gfxdraw.aacircle(surf, cx, cy, r, color)


def outline_rect(surf, rect, color=OUTLINE, width=1):
    pygame.draw.rect(surf, color, rect, width)


def outline_polygon(surf, points, color=OUTLINE, width=1):
    pygame.draw.polygon(surf, color, points, width)


def build_vignette():
    vg = pygame.Surface((INTERNAL_W, INTERNAL_H), pygame.SRCALPHA)
    cx, cy = INTERNAL_W / 2, INTERNAL_H / 2
    max_r = math.hypot(cx, cy)
    max_alpha = 100
    vg.fill((0, 0, 0, max_alpha))
    steps = 28
    for i in range(steps, -1, -1):
        r = max_r * i / steps
        a = int(max_alpha * (i / steps) ** 1.6)
        pygame.draw.circle(vg, (0, 0, 0, a), (int(cx), int(cy)), int(r))
    return vg


# ------------------------------------------------------------------
# 色票：與前兩支檔案同一組，夜晚用序幕版本來就有的近黑紫語彙
# ------------------------------------------------------------------
COL_BG_TOP     = (10, 8, 20)
COL_BG_BOTTOM  = (22, 15, 34)
COL_SILHOUETTE = (16, 12, 24)
COL_AMBER      = (255, 190, 96)
COL_AMBER_DIM  = (150, 96, 40)
COL_BONE       = (235, 228, 210)
COL_BLOOD      = (198, 40, 46)
COL_COLD       = (74, 84, 112)
COL_ARCANE     = (150, 88, 196)
COL_TITLE      = (232, 176, 96)

COL_NIGHT_GROUND = (24, 18, 26)     # 夜晚地面（比白天的暖褐色更暗更冷）
COL_SLIME        = (110, 176, 90)   # 糖果史萊姆本體（改成綠色）
COL_SLIME_DARK   = (66, 122, 56)    # 史萊姆陰影/斑點

random.seed(31)


def load_cjk_font(size, bold=False):
    candidates = [
        "Microsoft JhengHei", "Microsoft YaHei", "PMingLiU", "SimHei",
        "Noto Sans CJK TC", "Noto Sans CJK SC", "Heiti TC", "Arial Unicode MS",
    ]
    for name in candidates:
        try:
            f = pygame.font.SysFont(name, size, bold=bold)
            if f is not None:
                return f
        except Exception:
            continue
    return pygame.font.Font(None, size)


dialogue_font = load_cjk_font(14 * SCALE)
hint_font = load_cjk_font(10 * SCALE)
end_font = load_cjk_font(20 * SCALE, bold=True)

CHAR_PER_SEC = 26.0


def wrap_text(text, font, max_width):
    lines = []
    current = ""
    for ch in text:
        test = current + ch
        if font.size(test)[0] > max_width and current:
            lines.append(current)
            current = ch
        else:
            current = test
    if current:
        lines.append(current)
    return lines


def frame_pose(t, interval=0.5):
    return int(t / interval) % 2


def draw_head_with_hair(surf, x, y, face_r, hair_r, skin, hair, hair_outline=(20, 16, 14), facing="front"):
    if facing == "back":
        aacircle(surf, hair, (x, y), hair_r)
        pygame.gfxdraw.aacircle(surf, int(x), int(y), int(hair_r), hair_outline)
        return
    aacircle(surf, hair, (x, y - hair_r * 0.15), hair_r)
    pygame.gfxdraw.aacircle(surf, int(x), int(y - hair_r * 0.15), int(hair_r), hair_outline)
    aacircle(surf, skin, (x, y + face_r * 0.28), face_r)


# ------------------------------------------------------------------
# 第一幕內容（後續幕次之後直接接在 ACTS 清單後面延伸即可）
# ------------------------------------------------------------------
ACTS = [
    {
        "bg": "night_crowd",
        "lines": [
            "好奇的村民來到兄妹附近觀察。",
            "黑暗中，村民的身影逐漸扭曲。",
            "糖果史萊姆出現，緩慢爬過道路，不斷分裂。",
            "漢賽爾第一次揮起提燈，也第一次用書上學來的招式擊退敵人。",
        ],
    },
]

LINE_WARP_START = 1     # 跑到「身影逐漸扭曲」→ 開始扭曲
LINE_SLIME_START = 2    # 跑到「糖果史萊姆出現」→ 變成史萊姆
LINE_FIGHT_START = 3    # 跑到「漢賽爾第一次揮起提燈」→ 舉燈迎敵


# ------------------------------------------------------------------
# 背景：夜晚村莊（跟白天同一個村莊，只是天色與地面換成夜晚色調）
# ------------------------------------------------------------------
def build_gradient(top, bottom):
    grad = pygame.Surface((1, INTERNAL_H))
    for y in range(INTERNAL_H):
        f = y / INTERNAL_H
        r = top[0] + (bottom[0] - top[0]) * f
        g = top[1] + (bottom[1] - top[1]) * f
        b = top[2] + (bottom[2] - top[2]) * f
        grad.set_at((0, y), (int(r), int(g), int(b)))
    return pygame.transform.scale(grad, (INTERNAL_W, INTERNAL_H))


SKY_NIGHT = build_gradient(COL_BG_TOP, COL_BG_BOTTOM)
GROUND_Y = INTERNAL_H - 46   # 跟白天版同一條地面基準線，日夜場景可以無縫接軌

HOUSES = []
x = -10
while x < INTERNAL_W + 10:
    w = random.randint(34, 58)
    h = random.randint(30, 52)
    HOUSES.append((x, w, h))
    x += w + random.randint(4, 14)

NIGHT_EYES = [
    (hx + random.uniform(0.3, 0.7) * hw, GROUND_Y - random.uniform(10, hh * 0.6), random.uniform(0, math.tau))
    for hx, hw, hh in HOUSES if random.random() < 0.3
]


def draw_village_night_bg(surf, t):
    surf.blit(SKY_NIGHT, (0, 0))
    ground_y = GROUND_Y
    pygame.draw.rect(surf, COL_NIGHT_GROUND, (0, ground_y, INTERNAL_W, INTERNAL_H - ground_y))
    for gx in range(0, INTERNAL_W, 18):
        pygame.draw.line(surf, (16, 12, 18), (gx, ground_y + 4), (gx - 6, INTERNAL_H), 1)
    # 房子剪影：底部＝GROUND_Y，跟角色腳底同一條線
    for hx, hw, hh in HOUSES:
        base_y = ground_y
        top_y = base_y - hh
        wall = pygame.Rect(hx, top_y + 10, hw, hh - 10)
        pygame.draw.rect(surf, COL_SILHOUETTE, wall)
        pygame.draw.polygon(surf, COL_SILHOUETTE,
                             [(hx - 4, top_y + 10), (hx + hw / 2, top_y), (hx + hw + 4, top_y + 10)])
    # 暗處零星的紅色眼睛（呼應序幕版夜晚的不安感）
    for ex, ey, phase in NIGHT_EYES:
        blink = 0.5 + 0.5 * math.sin(t * 1.3 + phase)
        if blink > 0.6:
            aacircle(surf, COL_BLOOD, (ex, ey), 1)


# ------------------------------------------------------------------
# 角色：漢賽爾／葛蕾特 —— 站姿沿用白天版比例，只是配色維持不變
# ------------------------------------------------------------------
def draw_hansel_stand(surf, x, y, pose, facing="front"):
    hair = (120, 70, 40)
    skin = (222, 178, 140)
    vest = (94, 62, 40)
    shirt = (222, 214, 198)
    pants = (58, 50, 44)

    bend = 1 if pose == 1 else 0
    leg_l = pygame.Rect(x - 5, y - 16, 4, 16)
    leg_r = pygame.Rect(x + 1, y - 16 + bend, 4, 16 - bend)
    body = pygame.Rect(x - 7, y - 32, 14, 18)

    pygame.draw.rect(surf, pants, leg_l)
    pygame.draw.rect(surf, pants, leg_r)
    pygame.draw.rect(surf, shirt, body)
    outline_rect(surf, body)
    if facing != "back":
        vest_pts = [(x - 7, y - 32), (x - 1, y - 32), (x - 3, y - 14), (x - 7, y - 14)]
        pygame.draw.polygon(surf, vest, vest_pts)
    draw_head_with_hair(surf, x, y - 36, 6, 7.5, skin, hair, hair_outline=(50, 28, 16), facing=facing)
    return (x, y - 36)


def draw_gretel_stand(surf, x, y, pose, facing="front"):
    hair = (232, 198, 96)
    skin = (226, 184, 148)
    dress = (222, 218, 212)

    bend = 1 if pose == 0 else 0
    body = pygame.Rect(x - 6, y - 30, 12, 18)

    pygame.draw.rect(surf, (58, 50, 46), (x - 4, y - 14, 3, 14))
    pygame.draw.rect(surf, (58, 50, 46), (x + 1, y - 14 + bend, 3, 14 - bend))
    pygame.draw.rect(surf, dress, body)
    outline_rect(surf, body)
    draw_head_with_hair(surf, x, y - 34, 5, 6.5, skin, hair, hair_outline=(110, 84, 40), facing=facing)
    aacircle(surf, hair, (x - 6, y - 27), 3)
    aacircle(surf, hair, (x + 6, y - 27), 3)


def draw_hansel_fight(surf, x, y, t):
    """漢賽爾舉燈迎敵：一手高舉提燈（唯一暖光源），另一手揮出帶奧術微光的招式。"""
    hair = (120, 70, 40)
    skin = (222, 178, 140)
    vest = (94, 62, 40)
    shirt = (222, 214, 198)
    pants = (58, 50, 44)

    stance = 3
    leg_l = pygame.Rect(x - 8, y - 16, 4, 16)
    leg_r = pygame.Rect(x + 4, y - 16, 4, 16)
    body = pygame.Rect(x - 7, y - 32, 14, 18)
    vest_pts = [(x - 7, y - 32), (x - 1, y - 32), (x - 3, y - 14), (x - 7, y - 14)]

    pygame.draw.rect(surf, pants, leg_l)
    pygame.draw.rect(surf, pants, leg_r)
    pygame.draw.rect(surf, shirt, body)
    outline_rect(surf, body)
    pygame.draw.polygon(surf, vest, vest_pts)
    draw_head_with_hair(surf, x, y - 36, 6, 7.5, skin, hair, hair_outline=(50, 28, 16))

    # 舉燈的手（固定高舉，微微晃動）
    lantern_x = x - 12
    lantern_y = y - 40 + math.sin(t * 5) * 1.2
    pygame.draw.line(surf, skin, (x - 6, y - 28), (lantern_x, lantern_y), 3)
    lantern_rect = pygame.Rect(lantern_x - 2, lantern_y - 2, 4, 5)
    pygame.draw.rect(surf, (60, 50, 30), lantern_rect)
    outline_rect(surf, lantern_rect, color=(30, 22, 12))
    aacircle(surf, COL_AMBER, (lantern_x, lantern_y), 1.6)

    # 揮擊的手：快速掃動的弧線＋奧術火花殘影
    swing = math.sin(t * 7.0)
    hand_x = x + 12 + swing * 8
    hand_y = y - 24 - abs(swing) * 4
    pygame.draw.line(surf, skin, (x + 6, y - 26), (hand_x, hand_y), 3)
    aacircle(surf, (*COL_ARCANE, 160), (hand_x, hand_y), 2.2)
    aacircle(surf, (*COL_AMBER, 90), (hand_x - swing * 4, hand_y + 2), 1.4)

    return (lantern_x, lantern_y)


def draw_lantern_glow(canvas_surf, center, base_radius, t):
    """提燈暖光：全場唯一持續光源，光圈半徑≈角色身高1.5倍，帶輕微火苗閃爍。"""
    glow_layer.fill((0, 0, 0, 0))
    flicker = base_radius * (1 + 0.06 * math.sin(t * 9.0) + 0.03 * math.sin(t * 23.0))
    steps = 16
    for i in range(steps, 0, -1):
        r = flicker * i / steps
        a = int(40 * (1 - i / steps) ** 1.6)   # 整體調暗（原本64），提燈不要亮成探照燈
        col = COL_AMBER if i < steps * 0.6 else COL_AMBER_DIM
        pygame.draw.circle(glow_layer, (*col, a), (int(center[0]), int(center[1])), int(r))
    canvas_surf.blit(glow_layer, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)


# ------------------------------------------------------------------
# 村民：正常（昏暗）→ 扭曲 → 糖果史萊姆，三段連續轉變
# ------------------------------------------------------------------
VILLAGER_PALETTE = [
    dict(shirt=(70, 60, 52), pants=(38, 34, 30), hair=(50, 38, 30)),
    dict(shirt=(56, 64, 68), pants=(34, 34, 38), hair=(28, 24, 22)),
    dict(shirt=(74, 50, 44), pants=(36, 30, 28), hair=(64, 56, 50)),
    dict(shirt=(52, 56, 44), pants=(32, 30, 26), hair=(22, 18, 16)),
    dict(shirt=(78, 68, 58), pants=(40, 34, 30), hair=(44, 32, 26)),
]

VILLAGER_SLOTS = [
    # 跟白天版第一幕同一組站位，讓日夜兩幕的構圖看起來是同一群人、同一個地方
    (-95, 0, 0.92), (-58, 0, 0.8), (58, 0, 0.8), (98, 0, 0.92),
    (-30, 0, 0.72), (34, 0, 0.72),
]


def draw_villager_dim(surf, x, y, scale, palette, pose, warp_amt, t, seed):
    """正常（昏暗）到扭曲的過渡狀態：warp_amt 0~1。"""
    shirt = palette["shirt"]
    pants = palette["pants"]
    hair = palette["hair"]
    skin = (150, 122, 108)  # 夜晚昏暗膚色，比白天暗

    def s(v):
        return v * scale

    jitter = math.sin(t * 16 + seed) * 2.4 * warp_amt
    stretch = 1 + 0.5 * warp_amt

    bend = 1 if pose == 1 else 0
    leg_h = s(14) * stretch
    leg_l = pygame.Rect(x - s(4) + jitter, y - leg_h, s(3), leg_h)
    leg_r = pygame.Rect(x + s(1) - jitter, y - leg_h + bend, s(3), leg_h - bend)
    body_h = s(16) * stretch
    body = pygame.Rect(x - s(6) - jitter * 0.5, y - s(14) - body_h, s(12), body_h)

    pygame.draw.rect(surf, pants, leg_l)
    pygame.draw.rect(surf, pants, leg_r)
    pygame.draw.rect(surf, shirt, body)
    outline_rect(surf, body)
    head_y = y - s(14) - body_h - s(3)
    draw_head_with_hair(surf, x - jitter * 0.5, head_y, s(5), s(6.2), skin, hair, hair_outline=(10, 8, 8))

    if warp_amt > 0.15:
        a = int(220 * min(1.0, warp_amt))
        for ex in (x - s(2) - jitter * 0.5, x + s(2) - jitter * 0.5):
            aacircle(surf, (*COL_BLOOD, int(a * 0.35)), (ex, head_y), max(1, s(1.6)))
            aacircle(surf, (255, 110, 100, a), (ex, head_y), max(1, s(0.6)))


def draw_slime(surf, x, y, scale, t, seed):
    """糖果史萊姆：主體 + 一小塊正在分裂出去的分身，帶輕微擠壓感。"""
    wob = math.sin(t * 3.0 + seed)
    squash = 1 + 0.08 * wob

    def s(v):
        return v * scale

    body_w, body_h = s(13) * squash, s(9) / squash
    body_rect = pygame.Rect(x - body_w / 2, y - body_h, body_w, body_h)
    pygame.draw.ellipse(surf, COL_SLIME, body_rect)
    pygame.draw.ellipse(surf, OUTLINE, body_rect, 1)
    for dx_, dy_ in ((-s(3), -s(4)), (s(4), -s(2))):
        aacircle(surf, COL_SLIME_DARK, (x + dx_, y - body_h * 0.5 + dy_), s(1.4))

    # 分裂中的小分身，隨時間慢慢從主體旁邊挪開
    split = 0.5 + 0.5 * math.sin(t * 0.8 + seed * 2)
    small_x = x + s(9) + s(4) * split
    small_r = s(3.2)
    aacircle(surf, COL_SLIME, (small_x, y - small_r * 0.8), small_r)
    pygame.gfxdraw.aacircle(surf, int(small_x), int(y - small_r * 0.8), int(small_r), OUTLINE)

    # 簡單的生氣小臉
    eye_y = y - body_h * 0.55
    aacircle(surf, (20, 10, 14), (x - s(3), eye_y), s(0.9))
    aacircle(surf, (20, 10, 14), (x + s(3), eye_y), s(0.9))


def draw_villager_or_slime(surf, x, y, scale, palette, pose, warp_amt, slime_amt, t, seed):
    """村民 → 史萊姆是連續的漸變過程，不是瞬間切換：
    用兩張暫存透明畫布分別畫『扭曲的村民』與『史萊姆』，各自設定透明度後疊在一起做交叉淡化。"""
    if slime_amt <= 0.0:
        draw_villager_dim(surf, x, y, scale, palette, pose, warp_amt, t, seed)
        return
    if slime_amt >= 1.0:
        draw_slime(surf, x, y, scale, t, seed)
        return

    villager_layer = pygame.Surface((INTERNAL_W, INTERNAL_H), pygame.SRCALPHA)
    draw_villager_dim(villager_layer, x, y, scale, palette, pose, 1.0, t, seed)
    villager_layer.set_alpha(int(255 * (1.0 - slime_amt)))
    surf.blit(villager_layer, (0, 0))

    slime_layer = pygame.Surface((INTERNAL_W, INTERNAL_H), pygame.SRCALPHA)
    draw_slime(slime_layer, x, y, scale, t, seed)
    slime_layer.set_alpha(int(255 * slime_amt))
    surf.blit(slime_layer, (0, 0))


def draw_night_crowd_scene(surf, t, state):
    draw_village_night_bg(surf, t)
    center_x, center_y = INTERNAL_W // 2, GROUND_Y

    warp_amt, slime_amt, fighting = state

    for i, (dx, dy, sc) in enumerate(VILLAGER_SLOTS):
        palette = VILLAGER_PALETTE[i % len(VILLAGER_PALETTE)]
        vx = center_x + dx
        vy = center_y + dy
        pose = frame_pose(t + i * 0.13)
        draw_villager_or_slime(surf, vx, vy, sc, palette, pose, warp_amt, slime_amt, t, seed=i)

    pose = frame_pose(t)
    if fighting:
        lantern_pos = draw_hansel_fight(surf, center_x - 10, center_y, t)
        draw_gretel_stand(surf, center_x + 14, center_y, pose, facing="back")
        draw_lantern_glow(surf, lantern_pos, 46, t)
    else:
        draw_hansel_stand(surf, center_x - 10, center_y, pose, facing="back")
        draw_gretel_stand(surf, center_x + 12, center_y, pose, facing="back")


# ------------------------------------------------------------------
# 字幕推進狀態機（與前兩支檔案同一套規則）
# ------------------------------------------------------------------
class DialogueState:
    def __init__(self):
        self.act_index = 0
        self.line_index = 0
        self.reveal = 0.0
        self.finished = False
        self.transitioning = False
        self.trans_phase = "out"
        self.trans_timer = 0.0
        self.line_timer = 0.0   # 這一句字幕顯示了多久（給扭曲/史萊姆漸變用）

    def current_lines(self):
        return ACTS[self.act_index]["lines"]

    def current_text(self):
        return self.current_lines()[self.line_index]

    def line_fully_shown(self):
        return self.reveal >= len(self.current_text())

    def advance(self):
        if self.finished or self.transitioning:
            return
        if not self.line_fully_shown():
            self.reveal = len(self.current_text())
            return
        if self.line_index + 1 < len(self.current_lines()):
            self.line_index += 1
            self.reveal = 0.0
            self.line_timer = 0.0
            return
        if self.act_index + 1 < len(ACTS):
            self.transitioning = True
            self.trans_phase = "out"
            self.trans_timer = 0.0
        else:
            self.finished = True

    def update(self, dt):
        if self.transitioning:
            self.trans_timer += dt
            if self.trans_phase == "out" and self.trans_timer >= 0.5:
                self.act_index += 1
                self.line_index = 0
                self.reveal = 0.0
                self.line_timer = 0.0
                self.trans_phase = "in"
                self.trans_timer = 0.0
            elif self.trans_phase == "in" and self.trans_timer >= 0.5:
                self.transitioning = False
            return
        if not self.finished:
            if not self.line_fully_shown():
                self.reveal += CHAR_PER_SEC * dt
            self.line_timer += dt

    def transition_alpha(self):
        if not self.transitioning:
            return 0
        if self.trans_phase == "out":
            return int(255 * min(1.0, self.trans_timer / 0.5))
        return int(255 * max(0.0, 1.0 - self.trans_timer / 0.5))

    def scene_state(self):
        """回傳 (warp_amt, slime_amt, fighting) 給夜晚村莊場景用。"""
        li = self.line_index
        warp_ramp = min(1.0, self.line_timer / 1.0)
        slime_ramp = min(1.0, self.line_timer / 1.8)   # 史萊姆漸變拉長，交叉淡化才看得明顯
        if li < LINE_WARP_START:
            return (0.0, 0.0, False)
        if li == LINE_WARP_START:
            return (warp_ramp, 0.0, False)
        if li == LINE_SLIME_START:
            return (1.0, slime_ramp, False)
        if li >= LINE_FIGHT_START:
            return (1.0, 1.0, True)
        return (1.0, 1.0, False)


def draw_dialogue_box(surf, state):
    strip = pygame.Rect(0, SCENE_H_PX, WINDOW_W, SUBTITLE_H_PX)
    pygame.draw.rect(surf, COL_SILHOUETTE, strip)

    pad_x = 20 * SCALE
    hint = hint_font.render("滑鼠左鍵　繼續", True, (150, 140, 150))
    surf.blit(hint, (pad_x, SCENE_H_PX - hint.get_height() - 4 * SCALE))

    pygame.draw.line(surf, COL_AMBER_DIM, (0, SCENE_H_PX), (WINDOW_W, SCENE_H_PX), max(1, SCALE // 2))

    text = state.current_text()
    shown = text[: int(state.reveal)]
    wrapped = wrap_text(shown, dialogue_font, WINDOW_W - pad_x * 2 - 20 * SCALE)
    ly = SCENE_H_PX + 8 * SCALE
    for wline in wrapped[:2]:
        label = dialogue_font.render(wline, True, COL_BONE)
        surf.blit(label, (pad_x, ly))
        ly += 18 * SCALE

    if state.line_fully_shown():
        blink = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() * 0.006)
        if blink > 0.4:
            tri_y = SCENE_H_PX + SUBTITLE_H_PX - 16 * SCALE
            tri = [(WINDOW_W - pad_x - 8 * SCALE, tri_y),
                   (WINDOW_W - pad_x, tri_y),
                   (WINDOW_W - pad_x - 4 * SCALE, tri_y + 6 * SCALE)]
            pygame.draw.polygon(surf, COL_TITLE, tri)


def draw_end_card(surf):
    veil = pygame.Surface((WINDOW_W, WINDOW_H))
    veil.fill(COL_SILHOUETTE)
    surf.blit(veil, (0, 0))
    label = end_font.render("第一幕　完", True, COL_TITLE)
    surf.blit(label, (WINDOW_W // 2 - label.get_width() // 2, WINDOW_H // 2 - 20 * SCALE))
    sub = hint_font.render("更多內容 即將加入", True, COL_BONE)
    surf.blit(sub, (WINDOW_W // 2 - sub.get_width() // 2, WINDOW_H // 2 + 10 * SCALE))


VIGNETTE = build_vignette()


# ------------------------------------------------------------------
# 主迴圈
# ------------------------------------------------------------------
def main():
    state = DialogueState()
    t = 0.0

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0
        t += dt

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                state.advance()

        state.update(dt)

        bg_kind = ACTS[state.act_index]["bg"]
        if bg_kind == "night_crowd":
            draw_night_crowd_scene(canvas, t, state.scene_state())

        if state.finished:
            draw_end_card(screen)
        else:
            alpha = state.transition_alpha()
            if alpha > 0:
                veil = pygame.Surface((INTERNAL_W, INTERNAL_H))
                veil.fill(COL_SILHOUETTE)
                veil.set_alpha(alpha)
                canvas.blit(veil, (0, 0))

            canvas.blit(VIGNETTE, (0, 0))

            scaled = pygame.transform.smoothscale(canvas, (WINDOW_W, SCENE_H_PX))
            screen.blit(scaled, (0, 0))

            draw_dialogue_box(screen, state)

        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()