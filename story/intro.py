# -*- coding: utf-8 -*-
"""
《糖果屋之後》｜序幕三幕劇 - Prologue in Three Acts
=================================================================
第一幕：純字幕（七年前被遺棄、遇見糖果屋與女巫、葛蕾特殺死女巫逃出森林）
第二幕：動畫＋字幕（糖果屋燃燒／女巫在屋後看／兩兄妹在屋前撿到燒焦的書）
第三幕：純字幕（漢賽爾立誓保護妹妹，但書與那場勝利其實沒有真正結束）

互動方式：
- 按【滑鼠左鍵】：
    - 若目前這句字幕還在逐字顯現 → 立即完整顯示
    - 若這句字幕已完整顯示   → 換下一句
    - 若這一幕的字幕已經跑完 → 淡出、換下一幕
    - 三幕全部結束後        → 停在完結畫面
- ESC 或關閉視窗：結束程式

    pip install pygame
    python candy_house_prologue_3acts.py
"""

import math
import os
import random
import sys

import pygame
import pygame.gfxdraw

# ------------------------------------------------------------------
# 內部像素畫布設定
# 畫質強化：
#   1) 最終放大改用 smoothscale（原本 nearest scale 會有明顯方塊感）
#   2) 圓形（頭部/眼睛/火星/糖霜點）改用 gfxdraw 反鋸齒繪製
#   3) 主要造型加上深色描邊（像素 RPG 常見的「墨線」處理）
#   4) 加入畫面暗角(vignette)，呼應海報本身的邊框壓暗處理
# 邏輯座標仍維持 480x270（所有繪圖數值不用重算），只在輸出端做更細緻的處理
# ------------------------------------------------------------------
INTERNAL_W, INTERNAL_H = 480, 270
SCALE = 2                        # 原本 3 倍會讓視窗高達 1032px，很多筆電螢幕塞不下（字幕區被擠出螢幕外）
SUBTITLE_LOGICAL_H = 50          # 字幕區塊高度（邏輯像素），獨立畫在動畫下方，不疊在畫面上
SCENE_H_PX = INTERNAL_H * SCALE  # 動畫場景實際顯示高度
SUBTITLE_H_PX = SUBTITLE_LOGICAL_H * SCALE
WINDOW_W = INTERNAL_W * SCALE
WINDOW_H = SCENE_H_PX + SUBTITLE_H_PX   # 視窗 = 動畫場景 + 獨立字幕區
FPS = 60
OUTLINE = (12, 9, 18)


def aacircle(surf, color, center, radius):
    """反鋸齒圓形（頭部、眼睛、火星、糖霜點都改用這個，邊緣更滑順）。"""
    cx, cy, r = int(center[0]), int(center[1]), max(1, int(radius))
    pygame.gfxdraw.filled_circle(surf, cx, cy, r, color)
    pygame.gfxdraw.aacircle(surf, cx, cy, r, color)


def outline_rect(surf, rect, color=OUTLINE, width=1):
    pygame.draw.rect(surf, color, rect, width)


def outline_polygon(surf, points, color=OUTLINE, width=1):
    pygame.draw.polygon(surf, color, points, width)


def build_vignette():
    """畫面邊角壓暗，呼應海報邊框處理；只在啟動時建立一次。
    強度調低（原本 175 太暗），且只疊在美術畫布上，不會蓋到文字。"""
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

pygame.init()
# 有視窗就用現成的，沒有才開一個。
# 這樣單獨執行（python story/xxx.py）跟被主程式 import 進去都成立 —— import
# 的時候如果無條件 set_mode，會把主程式的視窗搶過來重設大小。
screen = pygame.display.get_surface() or pygame.display.set_mode((WINDOW_W, WINDOW_H))
pygame.display.set_caption("糖果屋之後｜序幕 - Prologue")
canvas = pygame.Surface((INTERNAL_W, INTERNAL_H))
glow_layer = pygame.Surface((INTERNAL_W, INTERNAL_H), pygame.SRCALPHA)
clock = pygame.time.Clock()

# ------------------------------------------------------------------
# 色票（沿用海報 / 分鏡腳本規定的角色語意色）
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
COL_FLAME_1    = (255, 120, 40)
COL_FLAME_2    = (255, 190, 70)
COL_BOOK       = (40, 30, 26)
COL_BOOK_EDGE  = (220, 120, 50)

random.seed(11)


def _bundled_font_path():
    """assets/GameCJK-Subset.ttf 的位置，找不到就回 None。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        candidate = os.path.join(here, "assets", "GameCJK-Subset.ttf")
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return None


def load_cjk_font(size, bold=False):
    """優先用遊戲自帶的字型，其次才找系統字型。

    原本是直接 SysFont 掃一串候選名稱，第一個是 Microsoft JhengHei。問題是
    **SysFont 找不到字型時不會回傳 None，它會靜默退回預設的拉丁字型** ——
    所以在 Windows 以外的機器上，第一個候選就「成功」了，拿回來的字型一個
    中文都畫不出來，整段字幕變成一排豆腐。

    改成先用專案自帶的那份字型檔（跟遊戲本體同一份），換哪一台電腦都一樣。
    真的找不到才回去掃系統字型，而且改用 match_font 驗證 —— 那個函式找不到
    是真的回傳 None。
    """
    path = _bundled_font_path()
    if path:
        try:
            font = pygame.font.Font(path, size)
            font.set_bold(bold)
            return font
        except Exception:
            pass
    for name in ("Heiti TC", "PingFang TC", "Noto Sans CJK TC",
                 "Microsoft JhengHei", "Arial Unicode MS"):
        found = pygame.font.match_font(name)
        if found:
            return pygame.font.Font(found, size)
    return pygame.font.Font(None, size)


dialogue_font = load_cjk_font(14 * SCALE)
hint_font = load_cjk_font(10 * SCALE)
end_font = load_cjk_font(20 * SCALE, bold=True)


# ------------------------------------------------------------------
# 文字換行（以字元為單位，適合無空白斷詞的中文）
# ------------------------------------------------------------------
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


# ------------------------------------------------------------------
# 三幕內容
# ------------------------------------------------------------------
ACTS = [
    {
        "bg": "forest",
        "lines": [
            "七年前，兄妹被父母遺棄在森林裡。",
            "他們遇見糖果屋，遇見女巫。",
            "葛蕾特殺死了女巫，帶著漢賽爾逃出森林。",
        ],
    },
    {
        "bg": "burning_house",
        "lines": [
            "逃離前，葛蕾特隨手從屋裡撿走一本燒焦大半的書，只當作戰利品，沒人細讀內容。",
        ],
    },
    {
        "bg": "forest_dawn",
        "lines": [
            "那天之後，漢賽爾便認定一件事——",
            "這一次，換他來保護妹妹。",
            "他不知道，那本書，還有那場勝利，其實都沒有真正結束。",
        ],
    },
]

CHAR_PER_SEC = 26.0   # 字幕逐字顯現速度


# ------------------------------------------------------------------
# 背景：森林剪影（第一幕／第三幕共用，第三幕加一點黎明色調）
# ------------------------------------------------------------------
def build_gradient(top, bottom):
    grad = pygame.Surface((1, INTERNAL_H))
    for y in range(INTERNAL_H):
        t = y / INTERNAL_H
        r = top[0] + (bottom[0] - top[0]) * t
        g = top[1] + (bottom[1] - top[1]) * t
        b = top[2] + (bottom[2] - top[2]) * t
        grad.set_at((0, y), (int(r), int(g), int(b)))
    return pygame.transform.scale(grad, (INTERNAL_W, INTERNAL_H))


SKY_NIGHT = build_gradient(COL_BG_TOP, COL_BG_BOTTOM)
SKY_DAWN = build_gradient((22, 14, 30), (58, 34, 40))

TREES = []
x = -20
while x < INTERNAL_W + 20:
    w = random.randint(18, 34)
    h = random.randint(50, 100)
    TREES.append((x, w, h))
    x += w + random.randint(-4, 6)

FOG_PATCHES = [
    dict(x=random.uniform(0, INTERNAL_W), y=random.uniform(190, 240),
         w=random.uniform(60, 130), speed=random.uniform(3, 8))
    for _ in range(5)
]


def draw_forest_bg(surf, t, dawn=False):
    surf.blit(SKY_DAWN if dawn else SKY_NIGHT, (0, 0))
    ground_y = INTERNAL_H - 34
    pygame.draw.rect(surf, COL_SILHOUETTE, (0, ground_y, INTERNAL_W, INTERNAL_H - ground_y))
    for tx, tw, th in TREES:
        base_y = ground_y + 6
        top_y = base_y - th
        pygame.draw.polygon(
            surf, COL_SILHOUETTE,
            [(tx, base_y), (tx + tw / 2, top_y), (tx + tw, base_y)],
        )
    for fog in FOG_PATCHES:
        fog["x"] = (fog["x"] + fog["speed"] * (1 / FPS)) % (INTERNAL_W + fog["w"])
        fx = fog["x"] - fog["w"]
        fog_surf = pygame.Surface((int(fog["w"]), 14), pygame.SRCALPHA)
        col = (90, 80, 110, 40) if not dawn else (120, 90, 90, 40)
        pygame.draw.ellipse(fog_surf, col, (0, 0, int(fog["w"]), 14))
        surf.blit(fog_surf, (int(fx), int(fog["y"])))
    if dawn:
        # 地平線一絲微光，暗示「事情還沒結束、但天終究會亮」
        glow = pygame.Surface((INTERNAL_W, 30), pygame.SRCALPHA)
        for i in range(30):
            a = int(50 * (1 - i / 30))
            pygame.draw.line(glow, (255, 150, 90, a), (0, 30 - i), (INTERNAL_W, 30 - i))
        surf.blit(glow, (0, ground_y - 14))


# ------------------------------------------------------------------
# 背景：燃燒的糖果屋（第二幕）
# ------------------------------------------------------------------
def draw_burning_house(surf, t, hansel_pose, gretel_pose, book_picked):
    surf.blit(SKY_NIGHT, (0, 0))
    ground_y = INTERNAL_H - 40
    pygame.draw.rect(surf, COL_SILHOUETTE, (0, ground_y, INTERNAL_W, INTERNAL_H - ground_y))
    for tx, tw, th in TREES[::2]:
        base_y = ground_y + 4
        top_y = base_y - th * 0.6
        pygame.draw.polygon(surf, COL_SILHOUETTE,
                             [(tx, base_y), (tx + tw / 2, top_y), (tx + tw, base_y)])

    hx, hy, hw, hh = 190, ground_y - 70, 100, 70  # 房屋主體範圍

    # --- 火光暈染背景（多層漸層，取代單一圓形，過渡更柔和） ---
    flicker = 0.85 + 0.15 * math.sin(t * 9) + 0.05 * math.sin(t * 23)
    fire_glow = pygame.Surface((INTERNAL_W, INTERNAL_H), pygame.SRCALPHA)
    center = (hx + hw // 2, hy + 10)
    layers = 18
    base_r = 120 * flicker
    for i in range(layers, 0, -1):
        r = base_r * i / layers
        a = int(60 * (1 - i / layers) ** 1.7)
        col = (255, 150, 60) if i < layers * 0.55 else (255, 90, 30)
        pygame.draw.circle(fire_glow, (*col, a), center, int(r))
    surf.blit(fire_glow, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)

    # --- 女巫剪影：躲在屋後看著兩兄妹 ---
    witch_x, witch_y = hx + hw // 2, hy - 26
    sway = math.sin(t * 0.9) * 2
    hat_pts = [(witch_x - 16 + sway, witch_y + 30), (witch_x + sway, witch_y - 6),
               (witch_x + 16 + sway, witch_y + 30)]
    pygame.draw.polygon(surf, (*COL_ARCANE,), hat_pts)
    outline_polygon(surf, hat_pts, color=(30, 16, 40))
    brim_pts = [(witch_x - 20 + sway, witch_y + 44), (witch_x + sway, witch_y + 26),
                (witch_x + 20 + sway, witch_y + 44)]
    pygame.draw.polygon(surf, COL_SILHOUETTE, brim_pts)  # 帽緣暗影蓋住臉
    blink = 0.5 + 0.5 * math.sin(t * 2.4)
    if blink > 0.4:
        eye_a = int(160 * blink)
        aacircle(surf, (*COL_AMBER, eye_a), (witch_x - 5 + sway, witch_y + 36), 1.6)
        aacircle(surf, (*COL_AMBER, eye_a), (witch_x + 5 + sway, witch_y + 36), 1.6)

    # --- 糖果屋本體 ---
    wall_rect = pygame.Rect(hx, hy + 20, hw, hh - 20)
    pygame.draw.rect(surf, (92, 58, 40), wall_rect)                            # 牆
    outline_rect(surf, wall_rect)
    roof_pts = [(hx - 8, hy + 22), (hx + hw / 2, hy - 10), (hx + hw + 8, hy + 22)]
    pygame.draw.polygon(surf, (110, 66, 44), roof_pts)                         # 屋頂
    outline_polygon(surf, roof_pts)
    for i in range(6):  # 屋頂糖霜／薑餅裝飾點（反鋸齒圓點）
        dx = hx - 4 + i * (hw + 8) / 5
        aacircle(surf, COL_BONE, (dx, hy + 20), 1.6)
    door_rect = pygame.Rect(hx + hw / 2 - 8, hy + 42, 16, 28)
    pygame.draw.rect(surf, (50, 30, 22), door_rect)                            # 門
    outline_rect(surf, door_rect)
    win_l = pygame.Rect(hx + 16, hy + 32, 14, 12)
    win_r = pygame.Rect(hx + hw - 30, hy + 32, 14, 12)
    for win in (win_l, win_r):
        pygame.draw.rect(surf, (200, 160, 90), win)                            # 窗（透火光）
        outline_rect(surf, win, color=(70, 40, 20))

    # --- 火焰（雙層閃爍多邊形，沿屋頂與牆角燃燒）---
    def flame(cx, base_y, height, phase):
        pts_outer = []
        pts_inner = []
        segs = 5
        for i in range(segs + 1):
            fx = cx - height * 0.35 + height * 0.7 * i / segs
            jitter = math.sin(t * 12 + phase + i) * 3
            fy = base_y - height * (0.3 + 0.7 * abs(math.sin(i * 1.3 + phase))) + jitter
            pts_outer.append((fx, fy))
        pts_outer.append((cx + height * 0.35, base_y))
        pts_outer.append((cx - height * 0.35, base_y))
        pygame.draw.polygon(surf, COL_FLAME_1, pts_outer)
        outline_polygon(surf, pts_outer, color=(90, 30, 10))
        for i in range(segs + 1):
            fx = cx - height * 0.2 + height * 0.4 * i / segs
            jitter = math.sin(t * 14 + phase + i) * 2
            fy = base_y - height * 0.55 * (0.3 + 0.7 * abs(math.sin(i * 1.5 + phase))) + jitter
            pts_inner.append((fx, fy))
        pts_inner.append((cx + height * 0.2, base_y))
        pts_inner.append((cx - height * 0.2, base_y))
        pygame.draw.polygon(surf, COL_FLAME_2, pts_inner)

    flame(hx + 14, hy + 20, 30, 0.0)
    flame(hx + hw / 2, hy - 8, 40, 1.4)
    flame(hx + hw - 14, hy + 20, 30, 2.6)

    # --- 兩兄妹在屋前撿書 ---
    fx0, fy0 = hx + hw / 2 - 8, ground_y
    draw_book(surf, fx0, fy0, picked=book_picked, t=t)
    draw_gretel_crouch(surf, fx0 - 14, fy0, gretel_pose, picking=not book_picked)
    draw_hansel_crouch(surf, fx0 + 16, fy0, hansel_pose)

    # 餘燼粒子交由外部粒子系統疊加


def draw_book(surf, x, y, picked, t):
    if picked:
        return  # 撿起後改畫在葛蕾特手上，見 draw_gretel_crouch
    book_rect = pygame.Rect(x - 6, y - 5, 12, 8)
    pygame.draw.rect(surf, COL_BOOK, book_rect)
    outline_rect(surf, book_rect, color=(60, 24, 10))
    pygame.draw.rect(surf, (*COL_BOOK_EDGE,), (x - 6, y - 5, 12, 2))
    aacircle(surf, (*COL_BOOK_EDGE,), (x - 5, y - 5), 1)


def draw_hansel_crouch(surf, x, y, pose):
    hair = (120, 70, 40)
    skin = (222, 178, 140)
    vest = (94, 62, 40)
    shirt = (222, 214, 198)
    pants = (58, 50, 44)
    bend = 6 if pose == 0 else 3
    leg_l = pygame.Rect(x - 5, y - 10 + bend, 4, 10 - bend)
    leg_r = pygame.Rect(x + 1, y - 10 + bend, 4, 10 - bend)
    body = pygame.Rect(x - 6, y - 22 + bend, 12, 14)
    vest_pts = [(x - 6, y - 22 + bend), (x, y - 22 + bend), (x - 2, y - 10 + bend), (x - 6, y - 10 + bend)]
    hair_pts = [(x - 6, y - 30 + bend), (x + 6, y - 30 + bend), (x + 4, y - 24 + bend), (x - 4, y - 24 + bend)]

    pygame.draw.rect(surf, pants, leg_l)
    pygame.draw.rect(surf, pants, leg_r)
    pygame.draw.rect(surf, shirt, body)
    outline_rect(surf, body)
    pygame.draw.polygon(surf, vest, vest_pts)
    aacircle(surf, skin, (x, y - 26 + bend), 5)
    pygame.draw.polygon(surf, hair, hair_pts)
    outline_polygon(surf, hair_pts, color=(50, 28, 16))


def draw_gretel_crouch(surf, x, y, pose, picking):
    hair = (232, 198, 96)
    skin = (226, 184, 148)
    dress = (222, 218, 212)
    bend = 6 if pose == 0 else 3
    body = pygame.Rect(x - 5, y - 20 + bend, 10, 14)
    hair_pts = [(x - 5, y - 28 + bend), (x + 5, y - 28 + bend), (x + 5, y - 20 + bend), (x - 5, y - 20 + bend)]

    pygame.draw.rect(surf, dress, body)
    outline_rect(surf, body)
    pygame.draw.rect(surf, (58, 50, 46), (x - 4, y - 10 + bend, 3, 10 - bend))
    pygame.draw.rect(surf, (58, 50, 46), (x + 1, y - 10 + bend, 3, 10 - bend))
    aacircle(surf, skin, (x, y - 24 + bend), 4)
    pygame.draw.polygon(surf, hair, hair_pts)
    outline_polygon(surf, hair_pts, color=(110, 84, 40))
    if picking:
        pygame.draw.line(surf, skin, (x - 5, y - 14 + bend), (x - 10, y - 6 + bend), 2)
    else:
        # 書已撿起，握在手中，燒焦邊緣仍隱隱發光
        hand = (x - 9, y - 12 + bend)
        book_rect = pygame.Rect(hand[0] - 5, hand[1] - 4, 10, 7)
        pygame.draw.rect(surf, COL_BOOK, book_rect)
        outline_rect(surf, book_rect, color=(60, 24, 10))
        pygame.draw.rect(surf, COL_BOOK_EDGE, (hand[0] - 5, hand[1] - 4, 10, 2))


# ------------------------------------------------------------------
# 餘燼粒子（第二幕用）
# ------------------------------------------------------------------
class Ember:
    def __init__(self, origin):
        self.origin = origin
        self.reset()

    def reset(self):
        self.x = self.origin[0] + random.uniform(-30, 30)
        self.y = self.origin[1] + random.uniform(-10, 10)
        self.vy = random.uniform(-16, -9)
        self.vx = random.uniform(-4, 4)
        self.life = random.uniform(0.7, 1.6)
        self.age = 0.0

    def update(self, dt):
        self.age += dt
        if self.age >= self.life:
            self.reset()
            return
        self.x += self.vx * dt
        self.y += self.vy * dt

    def draw(self, surf):
        t = 1 - self.age / self.life
        if t <= 0:
            return
        col = (255, int(180 * t + 60), int(80 * t))
        aacircle(surf, col, (self.x, self.y), 1.1)


EMBERS = [Ember((240, 168)) for _ in range(24)]

VIGNETTE = build_vignette()


# ------------------------------------------------------------------
# 字幕框（VN 式逐字顯現 + 滑鼠推進）
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
        self.hansel_pose = 0
        self.gretel_pose = 0
        self.pose_timer = 0.0
        self.book_picked = False
        self.book_timer = 0.0

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
                self.book_picked = False
                self.book_timer = 0.0
                self.trans_phase = "in"
                self.trans_timer = 0.0
            elif self.trans_phase == "in" and self.trans_timer >= 0.5:
                self.transitioning = False
            return
        if not self.finished and not self.line_fully_shown():
            self.reveal += CHAR_PER_SEC * dt

        # 第二幕的撿書動畫節奏：蹲下幾次之後書被撿起
        if ACTS[self.act_index]["bg"] == "burning_house":
            self.pose_timer += dt
            if self.pose_timer > 0.55:
                self.pose_timer = 0.0
                self.hansel_pose = 1 - self.hansel_pose
                self.gretel_pose = 1 - self.gretel_pose
            self.book_timer += dt
            if self.book_timer > 2.2:
                self.book_picked = True

    def transition_alpha(self):
        if not self.transitioning:
            return 0
        if self.trans_phase == "out":
            return int(255 * min(1.0, self.trans_timer / 0.5))
        return int(255 * max(0.0, 1.0 - self.trans_timer / 0.5))


def draw_dialogue_box(surf, state):
    """字幕畫在動畫場景『下方』獨立的字幕區（不疊加在動畫畫面上）。
    surf 傳入 screen（視窗解析度），文字維持銳利。
    版面：提示文字貼在字幕框『正上方』（動畫區與字幕區交界處），字幕內容在框內。"""
    strip = pygame.Rect(0, SCENE_H_PX, WINDOW_W, SUBTITLE_H_PX)
    pygame.draw.rect(surf, COL_SILHOUETTE, strip)                       # 字幕區底色（實心，不透動畫）

    pad_x = 20 * SCALE

    # 提示文字貼在字幕框正上方（分隔線之上，動畫區這一側）
    hint = hint_font.render("滑鼠左鍵　繼續", True, (150, 140, 150))
    surf.blit(hint, (pad_x, SCENE_H_PX - hint.get_height() - 4 * SCALE))

    pygame.draw.line(surf, COL_AMBER_DIM, (0, SCENE_H_PX), (WINDOW_W, SCENE_H_PX), max(1, SCALE // 2))

    # 字幕內容在框內
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
    """結束畫面同樣直接畫在視窗解析度上，維持文字銳利。"""
    veil = pygame.Surface((WINDOW_W, WINDOW_H))
    veil.fill(COL_SILHOUETTE)
    surf.blit(veil, (0, 0))
    label = end_font.render("序幕完", True, COL_TITLE)
    surf.blit(label, (WINDOW_W // 2 - label.get_width() // 2, WINDOW_H // 2 - 20 * SCALE))
    sub = hint_font.render("Day 1｜遊戲 即將開始", True, COL_BONE)
    surf.blit(sub, (WINDOW_W // 2 - sub.get_width() // 2, WINDOW_H // 2 + 10 * SCALE))




# ------------------------------------------------------------------
# 給主程式用的場景包裝
#
# 跟 main() 畫的是同一份東西，差別只在它不擁有視窗、不擁有主迴圈：
# 由呼叫者餵 dt 和事件，畫到呼叫者給的 surface 上。這樣同一份動畫既能
# 單獨執行，也能被 app/cutscene.py 接進遊戲流程裡。
# ------------------------------------------------------------------
class PrologueScene:
    def __init__(self):
        self.state = DialogueState()
        self.t = 0.0

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.state.advance()
        elif event.type == pygame.KEYDOWN and event.key in (
                pygame.K_SPACE, pygame.K_RETURN):
            self.state.advance()

    def update(self, dt):
        self.t += dt
        self.state.update(dt)

    def draw(self, screen):
        bg_kind = ACTS[self.state.act_index]["bg"]
        if bg_kind == "forest":
            draw_forest_bg(canvas, self.t, dawn=False)
        elif bg_kind == "forest_dawn":
            draw_forest_bg(canvas, self.t, dawn=True)
        elif bg_kind == "burning_house":
            draw_burning_house(canvas, self.t, self.state.hansel_pose,
                               self.state.gretel_pose, self.state.book_picked)
            for e in EMBERS:
                e.update(1.0 / FPS)
                e.draw(canvas)


        if self.state.finished:
            draw_end_card(screen)
            return

        alpha = self.state.transition_alpha()
        if alpha > 0:
            veil = pygame.Surface((INTERNAL_W, INTERNAL_H))
            veil.fill(COL_SILHOUETTE)
            veil.set_alpha(alpha)
            canvas.blit(veil, (0, 0))

        canvas.blit(VIGNETTE, (0, 0))
        scaled = pygame.transform.smoothscale(canvas, (WINDOW_W, SCENE_H_PX))
        screen.blit(scaled, (0, 0))
        draw_dialogue_box(screen, self.state)

    @property
    def finished(self):
        return self.state.finished

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
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                print("[click] 推進字幕")
                state.advance()

        state.update(dt)

        bg_kind = ACTS[state.act_index]["bg"]
        if bg_kind == "forest":
            draw_forest_bg(canvas, t, dawn=False)
        elif bg_kind == "forest_dawn":
            draw_forest_bg(canvas, t, dawn=True)
        elif bg_kind == "burning_house":
            draw_burning_house(canvas, t, state.hansel_pose, state.gretel_pose, state.book_picked)
            for e in EMBERS:
                e.update(dt)
                e.draw(canvas)

        if state.finished:
            # 結束畫面：直接在視窗解析度上畫實心背景＋文字，不經過低解析度畫布
            draw_end_card(screen)
        else:
            alpha = state.transition_alpha()
            if alpha > 0:
                veil = pygame.Surface((INTERNAL_W, INTERNAL_H))
                veil.fill(COL_SILHOUETTE)
                veil.set_alpha(alpha)
                canvas.blit(veil, (0, 0))

            canvas.blit(VIGNETTE, (0, 0))  # 邊角壓暗，只作用在美術畫布，不蓋到文字

            # 用 smoothscale 放大場景美術，只填滿「動畫場景區」（不含字幕區）
            scaled = pygame.transform.smoothscale(canvas, (WINDOW_W, SCENE_H_PX))
            screen.blit(scaled, (0, 0))

            # 字幕畫在動畫下方獨立的字幕區，不會擋到動畫畫面
            draw_dialogue_box(screen, state)

        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
