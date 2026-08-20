# -*- coding: utf-8 -*-
"""
《糖果屋之後》｜第一天：歸來（白天）- Day 1 Daytime, Three Acts
=================================================================
與序幕（candy_house_prologue_3acts.py）共用同一套標準，不另外調整：
    - 480x270 邏輯畫布、SCALE=2 → 視窗 960x640（動畫場景 + 獨立字幕區）
    - 同一組色票（COL_AMBER / COL_BLOOD / COL_ARCANE / COL_BONE ...）
    - 圓形一律 aacircle 反鋸齒、主要造型加深色描邊、smoothscale 放大
    - 暗角(vignette) 只蓋在動畫場景，不蓋字幕
    - 字幕：滑鼠左鍵推進，提示文字貼在字幕框正上方，逐字打字機顯現
    - 角色比例／配色沿用漢賽爾／葛蕾特既有設計，不重新設計角色

第一幕：兄妹回到村莊，被正常型態的村民包圍；字幕跑到「目光」那句時，
        村民的眼睛集體發出微光看向葛蕾特。
第二幕：漢賽爾翻開燒焦的書，開始練習書裡的「咒語」。
第三幕：巫嬸（老婦人）上前，送上一小包白色菱形糖霜。

操作：滑鼠左鍵推進字幕／換幕，ESC 離開。
    pip install pygame
    python candy_house_day1_daytime.py
"""

import math
import random

import pygame
import pygame.gfxdraw

# ------------------------------------------------------------------
# 視窗規格（與序幕版完全一致）
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

canvas = pygame.Surface((INTERNAL_W, INTERNAL_H))
glow_layer = pygame.Surface(
    (INTERNAL_W, INTERNAL_H),
    pygame.SRCALPHA,
)

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
# 色票：與序幕版完全同一組，不新增、不改色
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

# 白天限定：僅用來畫「天光」與「地面」，色相仍鎖在同一套黑紫/暖色語意裡，
# 不是換成鮮豔的卡通藍天——維持黑暗童話的低飽和基調，只是把明度提高一階。
COL_DAY_SKY_TOP    = (58, 46, 56)
COL_DAY_SKY_BOTTOM = (132, 104, 78)
COL_DAY_GROUND     = (96, 74, 54)
COL_DAY_SILHOUETTE = (54, 40, 42)

random.seed(21)


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
    """限制在 ~2fps 的姿勢切換（0/1），維持像素逐格感，不做流暢補間。"""
    return int(t / interval) % 2


def draw_head_with_hair(surf, x, y, face_r, hair_r, skin, hair, hair_outline=(20, 16, 14), facing="front"):
    """統一的頭部畫法：
    facing='front' → 先畫較大的『髮型底色圓』，再疊偏下偏小的臉部膚色圓，露出髮線，不會禿頭。
    facing='back'  → 只畫髮色（背面看不到臉），用來表現角色背對鏡頭／背對他人。"""
    if facing == "back":
        aacircle(surf, hair, (x, y), hair_r)
        pygame.gfxdraw.aacircle(surf, int(x), int(y), int(hair_r), hair_outline)
        return
    aacircle(surf, hair, (x, y - hair_r * 0.15), hair_r)
    pygame.gfxdraw.aacircle(surf, int(x), int(y - hair_r * 0.15), int(hair_r), hair_outline)
    aacircle(surf, skin, (x, y + face_r * 0.28), face_r)


# ------------------------------------------------------------------
# 三幕內容
# ------------------------------------------------------------------
ACTS = [
    {
        "bg": "crowd",
        "lines": [
            "兄妹回到村莊，村民熱烈迎接。",
            "葛蕾特向大家分享森林裡的經歷，以及自己殺死女巫的事。",
            "村民有人好奇，有人議論，也有人對她的故事將信將疑。",
            "漢賽爾開始注意那些落在妹妹身上的目光。",
        ],
    },
    {
        "bg": "training",
        "lines": [
            "他翻開那本從糖果屋帶出來的書，開始鍛鍊自己——",
            "書裡的文字很怪，像某種咒語，",
            "但他只當成女巫的邪門筆記，能學到本事就好，沒有多想。",
        ],
    },
    {
        "bg": "witch_aunt",
        "lines": [
            "一位村里的婦人上前接濟兄妹，送上一小包糖霜當見面禮，",
            "說是自家做的，配方是老一輩傳下來的。",
            "她自稱巫嬸。",
            "漢賽爾當下只覺得她面善，沒放在心上。",
        ],
    },
]

# 第一幕：跑到這一句（索引 3＝第四句「目光」）時，村民集體眼睛發光
EYES_GLOW_ACT, EYES_GLOW_LINE = 0, 3


# ------------------------------------------------------------------
# 背景：村莊白天（三幕共用同一套天空/地面，只換前景擺設）
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
GROUND_Y = INTERNAL_H - 46   # 統一地面基準線，所有角色的腳底都對齊這條線

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
    # 地面簡單的石板紋理
    for gx in range(0, INTERNAL_W, 18):
        pygame.draw.line(surf, (80, 60, 44), (gx, ground_y + 4), (gx - 6, INTERNAL_H), 1)
    # 遠方房舍剪影（白天用較亮的暖褐色，不是純黑，維持景深）
    # 房子底部＝GROUND_Y，跟所有角色的腳底同一條線，不再有 4px 落差
    for hx, hw, hh in HOUSES:
        base_y = ground_y
        top_y = base_y - hh
        wall = pygame.Rect(hx, top_y + 10, hw, hh - 10)
        pygame.draw.rect(surf, COL_DAY_SILHOUETTE, wall)
        pygame.draw.polygon(surf, COL_DAY_SILHOUETTE,
                             [(hx - 4, top_y + 10), (hx + hw / 2, top_y), (hx + hw + 4, top_y + 10)])
    # 淡淡的塵霧感（微弱移動的橫向光斑，暗示白天的懶洋洋氛圍）
    haze_y = ground_y - 10 + 4 * math.sin(t * 0.3)
    haze = pygame.Surface((INTERNAL_W, 3), pygame.SRCALPHA)
    haze.fill((255, 220, 180, 14))
    surf.blit(haze, (0, int(haze_y)))


# ------------------------------------------------------------------
# 角色：漢賽爾／葛蕾特——沿用序幕版的比例與描邊風格，只是換成站姿
# ------------------------------------------------------------------
def draw_hansel_stand(surf, x, y, pose, alert=False, facing="front"):
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
        pygame.draw.polygon(surf, vest, vest_pts)  # 背心開襟只在正面看得到
    draw_head_with_hair(surf, x, y - 36, 6, 7.5, skin, hair, hair_outline=(50, 28, 16), facing=facing)

    if alert:
        # 微微側頭、留意四周的警覺感：肩膀多一道輪廓陰影
        pygame.draw.line(surf, (60, 40, 26), (x - 7, y - 30), (x - 3, y - 26), 1)

    return (x, y - 36)  # 頭部座標，給眼神/情緒效果用


def draw_gretel_stand(surf, x, y, pose, talking=False, facing="front"):
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

    if talking and facing != "back":
        # 說故事的手勢：手臂微微揚起（背對時看不到手勢，不畫）
        wave = 2 * math.sin(pygame.time.get_ticks() * 0.006)
        pygame.draw.line(surf, skin, (x + 6, y - 24), (x + 12, y - 26 + wave), 2)


# ------------------------------------------------------------------
# 村民：白天為正常人形，配色偏樸素（不搶主角），眼睛平時不畫，
# 只有觸發「目光」時才點亮血紅色的雙眼並對著葛蕾特看
# ------------------------------------------------------------------
VILLAGER_PALETTE = [
    dict(shirt=(96, 84, 70), pants=(52, 46, 40), hair=(70, 52, 40)),
    dict(shirt=(80, 92, 96), pants=(46, 46, 50), hair=(40, 34, 30)),
    dict(shirt=(104, 70, 60), pants=(50, 40, 38), hair=(90, 80, 70)),
    dict(shirt=(74, 78, 60), pants=(44, 42, 36), hair=(30, 26, 24)),
    dict(shirt=(110, 96, 80), pants=(58, 48, 40), hair=(60, 44, 34)),
]

VILLAGER_SLOTS = [
    # (dx, dy, scale)  以漢賽爾／葛蕾特為中心的相對位置；地面是平面沒有透視深度，
    # 所以 dy 一律是 0——每個人的腳底都精準貼在同一條地面線上，不再有人看起來浮空
    (-95, 0, 0.92), (-58, 0, 0.8), (58, 0, 0.8), (98, 0, 0.92),
    (-30, 0, 0.72), (34, 0, 0.72),
]


def draw_villager(surf, x, y, scale, palette, pose, eyes_glow_amt):
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

    if eyes_glow_amt > 0:
        # 目光效果：小小一顆圓形光點（柔和外暈 + 亮核心），不是大色塊
        a_core = int(255 * eyes_glow_amt)
        a_halo = int(90 * eyes_glow_amt)
        for ex in (x - s(2), x + s(2)):
            aacircle(surf, (*COL_BLOOD, a_halo), (ex, head_y + s(0.3)), max(1, s(1.6)))
            aacircle(surf, (255, 120, 110, a_core), (ex, head_y + s(0.3)), max(1, s(0.6)))


def draw_crowd_scene(surf, t, eyes_glow_amt):
    draw_village_bg(surf, t)
    center_x, center_y = INTERNAL_W // 2, GROUND_Y

    for i, (dx, dy, sc) in enumerate(VILLAGER_SLOTS):
        palette = VILLAGER_PALETTE[i % len(VILLAGER_PALETTE)]
        sway = math.sin(t * 0.6 + i) * 1.5
        vx = center_x + dx + sway
        vy = center_y + dy
        pose = frame_pose(t + i * 0.13)
        draw_villager(surf, vx, vy, sc, palette, pose, eyes_glow_amt)

    pose = frame_pose(t)
    # 兄妹背對村民：鏡頭在他們後方，村民的臉（與發光的目光）都朝向兄妹／鏡頭
    draw_hansel_stand(surf, center_x - 10, center_y, pose, alert=eyes_glow_amt > 0.1, facing="back")
    draw_gretel_stand(surf, center_x + 12, center_y, pose, talking=True, facing="back")


# ------------------------------------------------------------------
# 第二幕：翻開書本、練習「咒語」
# ------------------------------------------------------------------
class Spark:
    """奧術火花：練習時從書頁與手邊冒出的紫色小光點。"""

    def __init__(self, origin):
        self.origin = origin
        self.reset()

    def reset(self):
        self.x = self.origin[0] + random.uniform(-6, 6)
        self.y = self.origin[1] + random.uniform(-4, 4)
        self.vy = random.uniform(-10, -4)
        self.vx = random.uniform(-6, 6)
        self.life = random.uniform(0.5, 1.1)
        self.age = 0.0

    def update(self, dt):
        self.age += dt
        if self.age >= self.life:
            self.reset()
            return
        self.x += self.vx * dt
        self.y += self.vy * dt

    def draw(self, surf):
        f = 1 - self.age / self.life
        if f <= 0:
            return
        a = int(220 * f)
        aacircle(surf, (*COL_ARCANE, a), (self.x, self.y), 1.2)


SPARKS = [Spark((236, 168)) for _ in range(14)]


def draw_open_book(surf, x, y, t):
    flutter = math.sin(t * 4) * 1.5
    left = pygame.Rect(x - 16, y - 6, 15, 12)
    right = pygame.Rect(x + 1, y - 6, 15, 12)
    pygame.draw.polygon(surf, COL_BOOK,
                         [(x - 16, y - 6), (x, y - 8 + flutter), (x, y + 6 + flutter), (x - 16, y + 6)])
    pygame.draw.polygon(surf, (56, 42, 34),
                         [(x, y - 8 + flutter), (x + 16, y - 6), (x + 16, y + 6), (x, y + 6 + flutter)])
    pygame.draw.line(surf, COL_BOOK_EDGE, (x - 16, y - 6), (x - 1, y - 7 + flutter), 1)
    pygame.draw.line(surf, COL_BOOK_EDGE, (x + 16, y - 6), (x + 1, y - 7 + flutter), 1)
    outline_polygon(surf, [(x - 16, y - 6), (x, y - 8 + flutter), (x + 16, y - 6),
                            (x + 16, y + 6), (x, y + 6 + flutter), (x - 16, y + 6)], color=(50, 20, 10))


def draw_hansel_training(surf, x, y, t):
    hair = (120, 70, 40)
    skin = (222, 178, 140)
    vest = (94, 62, 40)
    shirt = (222, 214, 198)
    pants = (58, 50, 44)

    swing = math.sin(t * 3.2)
    step = frame_pose(t, 0.4)
    lean = 2 if step == 1 else -1

    leg_l = pygame.Rect(x - 6 + lean, y - 16, 4, 16)
    leg_r = pygame.Rect(x + 2 - lean, y - 16, 4, 16)
    body = pygame.Rect(x - 7, y - 32, 14, 18)
    vest_pts = [(x - 7, y - 32), (x - 1, y - 32), (x - 3, y - 14), (x - 7, y - 14)]

    pygame.draw.rect(surf, pants, leg_l)
    pygame.draw.rect(surf, pants, leg_r)
    pygame.draw.rect(surf, shirt, body)
    outline_rect(surf, body)
    pygame.draw.polygon(surf, vest, vest_pts)
    draw_head_with_hair(surf, x, y - 36, 6, 7.5, skin, hair, hair_outline=(50, 28, 16))

    # 練習的手：往前比劃，帶一點奧術微光殘影
    hand_x = x + 14 + swing * 6
    hand_y = y - 24 - abs(swing) * 3
    pygame.draw.line(surf, skin, (x + 6, y - 26), (hand_x, hand_y), 3)
    aacircle(surf, (*COL_ARCANE, 130), (hand_x, hand_y), 2.2)


def draw_training_scene(surf, t):
    draw_village_bg(surf, t)
    book_pos = (250, GROUND_Y - 28)
    hansel_pos = (216, GROUND_Y)

    draw_open_book(surf, *book_pos, t)
    draw_hansel_training(surf, *hansel_pos, t)

    for sp in SPARKS:
        sp.origin = (book_pos[0] - 4, book_pos[1] - 6)
        sp.draw(surf)


# ------------------------------------------------------------------
# 第三幕：巫嬸（老婦人）送糖霜
# ------------------------------------------------------------------
def draw_old_woman(surf, x, y, t, offering=True):
    shawl = (120, 70, 96)      # 與 COL_ARCANE 同色系但更沉，暗示她的真實身分
    dress = (60, 46, 52)
    skin = (210, 176, 150)
    hair = (200, 196, 190)

    sway = math.sin(t * 1.4) * 1
    body = pygame.Rect(x - 7 + sway, y - 30, 14, 30)   # 裙擺延伸到 y（GROUND_Y），腳底跟房子底部齊平
    shawl_pts = [(x - 9 + sway, y - 34), (x + 9 + sway, y - 34), (x + 7 + sway, y - 12), (x - 7 + sway, y - 12)]

    pygame.draw.rect(surf, dress, body)
    outline_rect(surf, body)
    pygame.draw.polygon(surf, shawl, shawl_pts)
    outline_polygon(surf, shawl_pts, color=(40, 20, 30))
    draw_head_with_hair(surf, x + sway, y - 36, 5, 6.2, skin, hair, hair_outline=(150, 146, 140))

    if offering:
        hand_x = x + 12 + sway
        hand_y = y - 22
        pygame.draw.line(surf, skin, (x + 5 + sway, y - 24), (hand_x, hand_y), 2)
        return (hand_x, hand_y)
    return (x + sway, y - 22)


def draw_candy_diamond(surf, x, y, t):
    glow = 0.6 + 0.4 * math.sin(t * 5)
    pts = [(x, y - 4), (x + 4, y), (x, y + 4), (x - 4, y)]
    pygame.draw.polygon(surf, COL_BONE, pts)
    outline_polygon(surf, pts, color=(150, 140, 130))
    aacircle(surf, (255, 255, 255, int(90 * glow)), (x, y), 2)


def draw_witch_aunt_scene(surf, t, approach):
    draw_village_bg(surf, t)
    center_x, center_y = INTERNAL_W // 2, GROUND_Y

    pose = frame_pose(t)
    draw_hansel_stand(surf, center_x - 10, center_y, pose)
    draw_gretel_stand(surf, center_x + 12, center_y, pose)

    # 老婦人從畫面左側走入，approach: 0~1
    start_x, end_x = -20, center_x - 42
    wx = start_x + (end_x - start_x) * approach
    hand_pos = draw_old_woman(surf, wx, center_y, t, offering=approach >= 0.98)

    if approach >= 0.98:
        draw_candy_diamond(surf, hand_pos[0] + 4, hand_pos[1], t)


# ------------------------------------------------------------------
# 字幕推進狀態機（與序幕版同一套規則：滑鼠推進、逐字顯現、播完自動換幕）
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
        self.act_timer = 0.0   # 這一幕已經播了多久（給進場動畫，如老婦人走位用）

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
                self.act_timer = 0.0
                self.trans_phase = "in"
                self.trans_timer = 0.0
            elif self.trans_phase == "in" and self.trans_timer >= 0.5:
                self.transitioning = False
            return
        if not self.finished:
            if not self.line_fully_shown():
                self.reveal += CHAR_PER_SEC * dt
            self.act_timer += dt

    def transition_alpha(self):
        if not self.transitioning:
            return 0
        if self.trans_phase == "out":
            return int(255 * min(1.0, self.trans_timer / 0.5))
        return int(255 * max(0.0, 1.0 - self.trans_timer / 0.5))

    def eyes_glow_amount(self):
        if self.act_index != EYES_GLOW_ACT or self.line_index != EYES_GLOW_LINE:
            return 0.0
        return min(1.0, 0.4 + 0.6 * min(1.0, self.reveal / max(1, len(self.current_text()))))


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
    sub = hint_font.render("提升自己 迎接晚上", True, COL_BONE)
    surf.blit(sub, (WINDOW_W // 2 - sub.get_width() // 2, WINDOW_H // 2 + 10 * SCALE))


VIGNETTE = build_vignette()


# ------------------------------------------------------------------
# 主迴圈
# ------------------------------------------------------------------
class PrologueScene:
    def __init__(self):
        self.state = DialogueState()
        self.t = 0.0

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
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
            draw_burning_house(
                canvas,
                self.t,
                self.state.hansel_pose,
                self.state.gretel_pose,
                self.state.book_picked,
            )

            for e in EMBERS:
                e.update(1 / FPS)
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

        scaled = pygame.transform.smoothscale(
            canvas,
            (WINDOW_W, SCENE_H_PX),
        )

        screen.blit(scaled, (0, 0))

        draw_dialogue_box(screen, self.state)

    @property
    def finished(self):
        return self.state.finished
