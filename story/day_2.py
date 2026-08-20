# -*- coding: utf-8 -*-
"""
《糖果屋之後》｜第二天：白天（第一幕）- Day 2 Daytime, Act 1
=================================================================
延續 candy_house_day1_daytime.py 第一幕的村莊白天場景（同一批村民、同一條地面線），
這次加入巫嬸一起入鏡，並用對話框呈現村民追問細節的橋段。與其他檔案共用同一套標準：
    - 480x270 邏輯畫布、SCALE=2 → 視窗 960x640
    - 同一組色票、aacircle 反鋸齒、深色描邊、smoothscale 放大、暗角只蓋動畫不蓋字幕
    - 所有角色腳底統一貼齊 GROUND_Y（跟房子底部同一條線）
    - 頭部一律 draw_head_with_hair（大髮色圓＋偏小臉部圓），不會光頭
    - 字幕：滑鼠左鍵推進，提示文字貼字幕框正上方，逐字打字機顯現
    - ACTS 裡每一行字串都要有逗號分隔（避免被誤接成一整條超長字幕）
    - 結尾文字不加括號

第一幕字幕與動畫觸發點：
    第1句：村民開始詢問更多關於女巫的細節，葛蕾特一一回答。
           → 村民＋巫嬸的頭上一起冒出「？」對話框
    第2句：巫嬸問得比別人都仔細，尤其追問……
           → 其他村民的對話框消失，只剩巫嬸的「？」對話框
    第3句：漢賽爾隨口提到那本書，巫嬸的表情閃過一瞬異樣……
           → 所有對話框消失，換漢賽爾冒出對話框，裡面是一個小書本圖樣
    第4句：漢賽爾沒有察覺，只覺得村民的目光已經變了……
           → 村民的眼神轉為懷疑（冷色瞇眼微光，跟夜晚那種超自然血紅發光是不同語彙）

操作：滑鼠左鍵推進字幕，ESC 離開。
    pip install pygame
    python candy_house_day2_daytime_act1.py
"""

import math
import os
import random
import sys

import pygame
import pygame.gfxdraw

# ------------------------------------------------------------------
# 視窗規格（與前面所有檔案完全一致）
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
# 有視窗就用現成的，沒有才開一個。
# 這樣單獨執行（python story/xxx.py）跟被主程式 import 進去都成立 —— import
# 的時候如果無條件 set_mode，會把主程式的視窗搶過來重設大小。
screen = pygame.display.get_surface() or pygame.display.set_mode((WINDOW_W, WINDOW_H))
pygame.display.set_caption("糖果屋之後｜第二天 白天（第一幕）")
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
# 色票：與前面所有檔案同一組
# ------------------------------------------------------------------
COL_BONE       = (235, 228, 210)
COL_BLOOD      = (198, 40, 46)
COL_COLD       = (74, 84, 112)
COL_ARCANE     = (150, 88, 196)
COL_TITLE      = (232, 176, 96)
COL_AMBER_DIM  = (150, 96, 40)
COL_SILHOUETTE = (16, 12, 24)
COL_BOOK       = (40, 30, 26)
COL_BOOK_EDGE  = (220, 120, 50)

COL_DAY_SKY_TOP    = (58, 46, 56)
COL_DAY_SKY_BOTTOM = (132, 104, 78)
COL_DAY_GROUND     = (96, 74, 54)
COL_DAY_SILHOUETTE = (54, 40, 42)

random.seed(42)


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
bubble_font = load_cjk_font(9 * SCALE, bold=True)   # 對話框裡的「？」用，字級較小

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
# 第一幕內容
# ------------------------------------------------------------------
ACTS = [
    {
        "bg": "crowd_talk",
        "lines": [
            "村民開始詢問更多關於女巫的細節，葛蕾特一一回答。",
            "巫嬸問得比別人都仔細，尤其追問：糖果屋裡除了女巫的屍體，還有沒有留下什麼東西。",
            "漢賽爾隨口提到那本書，巫嬸的表情閃過一瞬異樣，很快又掩飾過去。",
            "漢賽爾沒有察覺，只覺得村民的目光已經變了——原本的好奇，在他眼裡逐漸變成懷疑。",
        ],
    },
]

LINE_ALL_ASK = 0        # 大家一起問問題
LINE_WITCH_ONLY = 1     # 只剩巫嬸的問題
LINE_HANSEL_BOOK = 2    # 換漢賽爾說話，冒出書本圖樣
LINE_SUSPICION = 3      # 村民眼神轉為懷疑


# ------------------------------------------------------------------
# 背景：村莊白天（跟第一天第一幕同一套生成邏輯）
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


SKY_DAY = build_gradient(COL_DAY_SKY_TOP, COL_DAY_SKY_BOTTOM)
GROUND_Y = INTERNAL_H - 46   # 跟第一天白天版同一條地面基準線

HOUSES = []
x = -10
while x < INTERNAL_W + 10:
    w = random.randint(34, 58)
    h = random.randint(30, 52)
    HOUSES.append((x, w, h))
    x += w + random.randint(4, 14)


def draw_village_bg(surf, t):
    surf.blit(SKY_DAY, (0, 0))
    ground_y = GROUND_Y
    pygame.draw.rect(surf, COL_DAY_GROUND, (0, ground_y, INTERNAL_W, INTERNAL_H - ground_y))
    for gx in range(0, INTERNAL_W, 18):
        pygame.draw.line(surf, (80, 60, 44), (gx, ground_y + 4), (gx - 6, INTERNAL_H), 1)
    # 房子底部＝GROUND_Y，跟所有角色的腳底同一條線
    for hx, hw, hh in HOUSES:
        base_y = ground_y
        top_y = base_y - hh
        wall = pygame.Rect(hx, top_y + 10, hw, hh - 10)
        pygame.draw.rect(surf, COL_DAY_SILHOUETTE, wall)
        pygame.draw.polygon(surf, COL_DAY_SILHOUETTE,
                             [(hx - 4, top_y + 10), (hx + hw / 2, top_y), (hx + hw + 4, top_y + 10)])
    haze_y = ground_y - 10 + 4 * math.sin(t * 0.3)
    haze = pygame.Surface((INTERNAL_W, 3), pygame.SRCALPHA)
    haze.fill((255, 220, 180, 14))
    surf.blit(haze, (0, int(haze_y)))


# ------------------------------------------------------------------
# 角色：漢賽爾／葛蕾特——這幕是面對面對話，改成正面朝向村民
# ------------------------------------------------------------------
def draw_hansel_stand(surf, x, y, pose):
    hair = (120, 70, 40)
    skin = (222, 178, 140)
    vest = (94, 62, 40)
    shirt = (222, 214, 198)
    pants = (58, 50, 44)

    bend = 1 if pose == 1 else 0
    leg_l = pygame.Rect(x - 5, y - 16, 4, 16)
    leg_r = pygame.Rect(x + 1, y - 16 + bend, 4, 16 - bend)
    body = pygame.Rect(x - 7, y - 32, 14, 18)
    vest_pts = [(x - 7, y - 32), (x - 1, y - 32), (x - 3, y - 14), (x - 7, y - 14)]

    pygame.draw.rect(surf, pants, leg_l)
    pygame.draw.rect(surf, pants, leg_r)
    pygame.draw.rect(surf, shirt, body)
    outline_rect(surf, body)
    pygame.draw.polygon(surf, vest, vest_pts)
    draw_head_with_hair(surf, x, y - 36, 6, 7.5, skin, hair, hair_outline=(50, 28, 16))
    return (x, y - 36)


def draw_gretel_stand(surf, x, y, pose):
    hair = (232, 198, 96)
    skin = (226, 184, 148)
    dress = (222, 218, 212)

    bend = 1 if pose == 0 else 0
    body = pygame.Rect(x - 6, y - 30, 12, 18)

    pygame.draw.rect(surf, (58, 50, 46), (x - 4, y - 14, 3, 14))
    pygame.draw.rect(surf, (58, 50, 46), (x + 1, y - 14 + bend, 3, 14 - bend))
    pygame.draw.rect(surf, dress, body)
    outline_rect(surf, body)
    draw_head_with_hair(surf, x, y - 34, 5, 6.5, skin, hair, hair_outline=(110, 84, 40))
    aacircle(surf, hair, (x - 6, y - 27), 3)
    aacircle(surf, hair, (x + 6, y - 27), 3)
    return (x, y - 34)


def draw_old_woman(surf, x, y, t):
    shawl = (120, 70, 96)
    dress = (60, 46, 52)
    skin = (210, 176, 150)
    hair = (200, 196, 190)

    sway = math.sin(t * 1.1) * 1
    body = pygame.Rect(x - 7 + sway, y - 30, 14, 30)
    shawl_pts = [(x - 9 + sway, y - 34), (x + 9 + sway, y - 34), (x + 7 + sway, y - 12), (x - 7 + sway, y - 12)]

    pygame.draw.rect(surf, dress, body)
    outline_rect(surf, body)
    pygame.draw.polygon(surf, shawl, shawl_pts)
    outline_polygon(surf, shawl_pts, color=(40, 20, 30))
    draw_head_with_hair(surf, x + sway, y - 36, 5, 6.2, skin, hair, hair_outline=(150, 146, 140))
    return (x + sway, y - 36)


# ------------------------------------------------------------------
# 村民（正常白天型態，含眼神懷疑效果）
# ------------------------------------------------------------------
VILLAGER_PALETTE = [
    dict(shirt=(96, 84, 70), pants=(52, 46, 40), hair=(70, 52, 40)),
    dict(shirt=(80, 92, 96), pants=(46, 46, 50), hair=(40, 34, 30)),
    dict(shirt=(104, 70, 60), pants=(50, 40, 38), hair=(90, 80, 70)),
    dict(shirt=(74, 78, 60), pants=(44, 42, 36), hair=(30, 26, 24)),
    dict(shirt=(110, 96, 80), pants=(58, 48, 40), hair=(60, 44, 34)),
]

# 沿用第一天第一幕同一組站位，讓兩幕構圖看起來是同一個場景；
# 巫嬸額外插入一個靠近兄妹的位置（她總是湊得比較近）
VILLAGER_SLOTS = [
    (-95, 0.92), (-58, 0.8), (58, 0.8), (98, 0.92), (34, 0.72),
]
WITCH_SLOT = (-30, 0.85)


def draw_villager(surf, x, y, scale, palette, pose, suspicion_amt):
    shirt = palette["shirt"]
    pants = palette["pants"]
    hair = palette["hair"]
    skin = (214, 172, 138)

    def s(v):
        return v * scale

    bend = 1 if pose == 1 else 0
    leg_l = pygame.Rect(x - s(4), y - s(14), s(3), s(14))
    leg_r = pygame.Rect(x + s(1), y - s(14) + bend, s(3), s(14) - bend)
    body = pygame.Rect(x - s(6), y - s(28), s(12), s(16))

    pygame.draw.rect(surf, pants, leg_l)
    pygame.draw.rect(surf, pants, leg_r)
    pygame.draw.rect(surf, shirt, body)
    outline_rect(surf, body)
    head_y = y - s(31)
    draw_head_with_hair(surf, x, head_y, s(5), s(6.2), skin, hair, hair_outline=(20, 16, 14))

    if suspicion_amt > 0:
        # 懷疑的眼神：瞇成一條線＋冷色微光，跟夜晚那種血紅發光是不同的視覺語彙
        a = int(220 * suspicion_amt)
        narrow = s(1.4)
        for ex in (x - s(2), x + s(2)):
            pygame.draw.line(surf, (*OUTLINE,), (ex - narrow, head_y), (ex + narrow, head_y), 1)
            aacircle(surf, (*COL_COLD, a), (ex, head_y), max(1, s(0.7)))

    return (x, head_y)


def draw_speech_bubble(surf, x, top_y, kind, alpha):
    """對話框：kind='q' 是問號、kind='book' 是小書本圖樣。alpha 0~255。"""
    if alpha <= 0:
        return
    bw, bh = (18, 13) if kind == "q" else (22, 15)
    bubble = pygame.Surface((bw + 4, bh + 8), pygame.SRCALPHA)
    body_rect = pygame.Rect(2, 2, bw, bh)
    pygame.draw.rect(bubble, (*COL_BONE, alpha), body_rect, border_radius=3)
    pygame.draw.rect(bubble, (*OUTLINE, alpha), body_rect, 1, border_radius=3)
    tail = [(bw / 2, bh + 2), (bw / 2 + 4, bh + 2), (bw / 2, bh + 7)]
    pygame.draw.polygon(bubble, (*COL_BONE, alpha), tail)

    if kind == "q":
        q = bubble_font.render("?", True, (*OUTLINE,))
        q.set_alpha(alpha)
        bubble.blit(q, (bw / 2 - q.get_width() / 2 + 2, bh / 2 - q.get_height() / 2 + 1))
    else:
        # 小書本：兩片書頁＋書脊，沿用既定的書本色票
        page_l = pygame.Rect(bw / 2 - 6, bh / 2 - 3, 6, 6)
        page_r = pygame.Rect(bw / 2, bh / 2 - 3, 6, 6)
        book_layer = pygame.Surface((bw + 4, bh + 8), pygame.SRCALPHA)
        pygame.draw.rect(book_layer, (*COL_BOOK, alpha), page_l)
        pygame.draw.rect(book_layer, (60, 42, 30, alpha), page_r)
        pygame.draw.line(book_layer, (*COL_BOOK_EDGE, alpha), (bw / 2, bh / 2 - 3), (bw / 2, bh / 2 + 3), 1)
        bubble.blit(book_layer, (0, 0))

    surf.blit(bubble, (x - (bw + 4) / 2, top_y - (bh + 8)))


def draw_crowd_talk_scene(surf, t, state):
    draw_village_bg(surf, t)
    center_x, center_y = INTERNAL_W // 2, GROUND_Y

    villager_bubble_alpha, witch_bubble_alpha, hansel_bubble_alpha, suspicion_amt = state

    for i, (dx, sc) in enumerate(VILLAGER_SLOTS):
        palette = VILLAGER_PALETTE[i % len(VILLAGER_PALETTE)]
        vx = center_x + dx
        pose = frame_pose(t + i * 0.13)
        head = draw_villager(surf, vx, center_y, sc, palette, pose, suspicion_amt)
        draw_speech_bubble(surf, head[0], head[1] - 8 * sc, "q", villager_bubble_alpha)

    witch_x = center_x + WITCH_SLOT[0]
    witch_head = draw_old_woman(surf, witch_x, center_y, t)
    draw_speech_bubble(surf, witch_head[0], witch_head[1] - 8, "q", witch_bubble_alpha)

    pose = frame_pose(t)
    hansel_head = draw_hansel_stand(surf, center_x - 10, center_y, pose)
    draw_gretel_stand(surf, center_x + 12, center_y, pose)
    draw_speech_bubble(surf, hansel_head[0], hansel_head[1] - 8, "book", hansel_bubble_alpha)


# ------------------------------------------------------------------
# 字幕推進狀態機
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
        self.line_timer = 0.0

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
        """回傳 (villager_bubble_alpha, witch_bubble_alpha, hansel_bubble_alpha, suspicion_amt)。"""
        li = self.line_index
        fade_in = min(1.0, self.line_timer / 0.4)
        fade_out = max(0.0, 1.0 - self.line_timer / 0.4)

        if li == LINE_ALL_ASK:
            a = int(255 * fade_in)
            return (a, a, 0, 0.0)
        if li == LINE_WITCH_ONLY:
            va = int(255 * fade_out)
            return (va, 255, 0, 0.0)
        if li == LINE_HANSEL_BOOK:
            ha = int(255 * fade_in)
            return (0, 0, ha, 0.0)
        if li >= LINE_SUSPICION:
            hb = int(255 * fade_out) if self.line_timer < 0.4 else 0
            suspicion = min(1.0, self.line_timer / 1.2)
            return (0, 0, hb, suspicion)
        return (0, 0, 0, 0.0)


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
    label = end_font.render("白天 完", True, COL_TITLE)
    surf.blit(label, (WINDOW_W // 2 - label.get_width() // 2, WINDOW_H // 2 - 20 * SCALE))
    sub = hint_font.render("懷疑正在蔓延", True, COL_BONE)
    surf.blit(sub, (WINDOW_W // 2 - sub.get_width() // 2, WINDOW_H // 2 + 10 * SCALE))


VIGNETTE = build_vignette()




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
        if bg_kind == "crowd_talk":
            draw_crowd_talk_scene(canvas, self.t, self.state.scene_state())


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
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                state.advance()

        state.update(dt)

        bg_kind = ACTS[state.act_index]["bg"]
        if bg_kind == "crowd_talk":
            draw_crowd_talk_scene(canvas, t, state.scene_state())

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
