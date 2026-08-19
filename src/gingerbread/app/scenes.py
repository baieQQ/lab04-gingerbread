"""Every screen in the game.

A scene draws and handles input in one pass, so adding a screen is one class
with one ``update`` method.

**Coordinates are layout units, not pixels.**  Screens are written against a
fixed 900×648 grid and every number goes through ``ui.s()``, which converts it
to device pixels for whatever display the game is on.  Text is then rasterised
at its final size rather than drawn small and scaled up — that difference is the
entire reason the interface used to look soft.

The stack is ``menu → prologue → play``, with the dawn ledger, the endless
offer, the codex and the pause menu pushed on top as overlays.  Only the top
scene sees input.
"""

from __future__ import annotations

import math

import pygame

from .. import model as m
from ..model.content import BEATS, BOSSES, ENDLESS_BEAT, EVENTS, MONSTERS
from ..model.content import newcomers
from ..model.content import SPELLS as SPELL_TABLE
from ..model.content import stage_for
from ..model.content.elements import ELEMENTS
from ..model.content.upgrades import SHOP_ORDER, UPGRADES
from ..model.registry import describe_mechanic
from ..view import palette as P
from ..view.ui import Scene, SceneStack, Stack, UI

#: Layout units.  The board sits between the HUD strip and the hint strip.
#: The grade badge's colour.  S and A are the lantern's warm gold; D is the
#: colour everything hostile in this game is drawn in.
_GRADE_COLOUR = {"S": P.EMBER_CORE, "A": P.EMBER, "B": P.BONE,
                 "C": P.BONE_DIM, "D": P.BLOOD}

HUD_H = 54
RAIL_H = 74
MID = 450


def _col(ui: UI, x: float, y: float, w: float, h: float, gap: float = 8):
    return Stack(ui.box(x, y, w, h), gap=ui.s(gap))


# ── menu ─────────────────────────────────────────────────────────────
class MenuScene(Scene):
    """The start screen: pick a mode.

    Two modes rather than a difficulty setting, because they are different
    games: one is a story with an ending, the other is a score attack.
    """

    def __init__(self, app_state) -> None:
        self.g = app_state

    def _go(self, app: SceneStack, mode) -> None:
        """Into the walkthrough, or straight into the game if it is switched off.

        The switch is honoured here rather than inside the walkthrough, so a
        player who turned it off never sees the screen flash up and vanish.
        """
        if self.g.onboarding:
            app.replace(TutorialScene(self.g, mode))
            return
        self.g.start(mode)
        app.replace(PrologueScene(self.g) if mode is m.Mode.CAMPAIGN
                    else PlayScene(self.g))

    def update(self, app: SceneStack, ui: UI, dt: float) -> None:
        ui.veil(252)
        ui.text("糖果屋之後", (ui.s(MID), ui.s(92)), "huge", P.EMBER, "center")
        ui.text("這一次，換他來保護妹妹。",
                (ui.s(MID), ui.s(142)), "body", P.BONE_DIM, "center")

        col = _col(ui, MID - 170, 196, 340, 220, gap=12)
        if ui.button("campaign", col.slot(ui.s(60)), "七夜",
                     "撐過七個夜晚，每一夜都有牠們的頭目"):
            self._go(app, m.Mode.CAMPAIGN)

        if ui.button("endless", col.slot(ui.s(60)), "無盡",
                     "牠們不會停。撐到你倒下為止"):
            self._go(app, m.Mode.ENDLESS)
        if ui.button("codex", col.slot(ui.s(42)), "圖鑑", "看看你會遇到什麼"):
            app.push(CodexScene(self.g))
        on = self.g.onboarding
        if ui.button("guide", col.slot(ui.s(42)),
                     f"新手引導：{'開' if on else '關'}",
                     "操作說明與怪物體驗關"):
            self.g.set_onboarding(not on)

        meta = self.g.saved
        best = f"最佳：第 {meta.best_night} 夜"
        if meta.best_endless_ticks:
            seconds = int(meta.best_endless_ticks * m.FIXED_DT)
            best += f"　·　無盡 {seconds // 60}:{seconds % 60:02d}"
        ui.text(best, (ui.s(MID), ui.s(442)), "small", P.MUTED, "center")
        ui.text("方向鍵或滑鼠選擇　·　Enter 確定　·　F11 全螢幕",
                (ui.s(MID), ui.s(608)), "small", P.MUTED, "center")


# ── tutorial ─────────────────────────────────────────────────────────
class TutorialScene(Scene):
    """共用於七夜與無盡模式的操作導覽。

    只處理 UI 與按鍵確認；不修改 model、不建立教學專屬戰局。
    """

    PAGES = (
        (
            "燈火未熄",
            (
                "葛蕾特還在等你。",
                "黑夜裡，燈籠照得到的地方，才是你能守住的地方。",
            ),
            "這是你要守住的人。",
        ),
        (
            "移動與面向",
            (
                "使用 [W][A][S][D] 或方向鍵移動。",
                "最後移動的方向，決定燈籠與揮擊方向。",
            ),
            "現在試試看：用 WASD 走幾步。",
        ),
        (
            "燈籠揮擊",
            (
                "按 [J] 或 [Space] 揮動燈籠。",
                "面向敵人再揮擊，才能守住葛蕾特。",
            ),
            "現在試試看：面向不同方向揮幾下。",
        ),
        (
            "衝刺閃避",
            (
                "按 [Shift] 衝刺，冷卻 1.4 秒。",
                "衝刺的那一瞬間撞到誰都不會受傷，是用來穿過去的。",
            ),
            "現在試試看：按 Shift 衝出去。",
        ),
        (
            "舉燈守衛",
            (
                "按住 [K] 舉燈守衛，期間任何傷害都扣不到你。",
                "代價是守衛時揮不了燈——擋得住，但殺不了。",
            ),
            "現在試試看：按住 K，看那個圈。",
        ),
        (
            "敵人攻擊預兆",
            (
                "紅色圓圈與箭頭：有人要從那裡出現，箭頭是牠要去的方向。",
                "站著不動、身上發亮：牠在蓄力遠程攻擊。",
                "蓄力中被打到就會中斷——過去打斷牠，比站著等牠射划算。",
            ),
            "這些預兆在真的夜晚都會出現。",
        ),
        (
            "技能",
            (
                "按 [L] 放一階技能，按 [；] 放二階技能。",
                "白天用技能點學技能，一階一點、二階兩點，各自佔一個鍵。",
                "閃電這種可以蓄力的，按著不放會越蓄越大，放開才打出去。",
            ),
            "技能有冷卻，格子填滿才能再放一次。",
        ),
        (
            "準備好了",
            (
                "你已學會移動、揮燈、衝刺、守衛與讀招。",
                "保護葛蕾特，直到天亮。",
            ),
            "準備好就開始。",
        ),
    )

    #: Seconds a page must be on screen before Enter will turn it.  The player
    #: is being asked to *try* the thing, not to acknowledge a dialog, and a
    #: page that can be dismissed on the same keypress that opened it will be.
    DWELL = 3.0

    def __init__(self, app_state, mode: m.Mode) -> None:
        self.g = app_state
        self.mode = mode
        self.page = 0
        self.state: m.State | None = None
        self.accumulator = 0.0
        self.ticks = 0
        self.dwell = 0.0

    def enter(self, app: SceneStack) -> None:
        app.ui.keyboard = False       # the focus ring must not eat WASD
        self.state = build_arena()

    def exit(self, app: SceneStack) -> None:
        app.ui.keyboard = True

    def _start_mode(self, app: SceneStack) -> None:
        """只在教學結束或跳過時，才真正建立遊戲 run。"""
        self.g.start(self.mode)

        if self.mode is m.Mode.CAMPAIGN:
            app.replace(PrologueScene(self.g))
        else:
            app.replace(PlayScene(self.g))

    #: Who appears on each page, as (species or None for Hansel, offset).
    #: ``None`` is Hansel; ``"gretel"`` is her.  Drawn left to right.
    CAST = (
        (("gretel", -70), ("hansel", 70)),                 # 燈火未熄
        (("hansel", 0),),                                  # 移動與面向
        (("hansel", -60), ("villager", 70)),               # 燈籠揮擊
        (("hansel", -60), ("bomber", 80)),                 # 衝刺閃避
        (("hansel", -60), ("brute", 80)),                  # 舉燈守衛
        (("archer", -80), ("mirror", 80)),                 # 敵人攻擊預兆
        (("hansel", 0),),                                  # 技能
        (("gretel", -70), ("hansel", 70)),                 # 準備好了
    )

    def _cast(self, ui: UI, panel: pygame.Rect) -> None:
        """Draw this page's characters, using the game's own figure code."""
        row = self.CAST[self.page] if self.page < len(self.CAST) else ()
        base_y = panel.top + ui.s(118)
        for who, offset in row:
            x = panel.centerx + ui.s(offset)
            if who == "hansel":
                self._figure(ui, x, base_y, 15, (74, 88, 126), build="tall",
                             hair=(96, 74, 52))
                if self.page == 4:            # 守衛：把那個圈畫出來
                    pygame.draw.circle(ui.surface, P.MOON, (x, base_y),
                                       ui.s(26), max(2, ui.s(2)))
                if self.page == 6:            # 技能：把兩個鍵畫在旁邊
                    for i, (tag, colour) in enumerate(
                            ((("L"), P.ARCANE_BRIGHT), (("；"), P.EMBER))):
                        cell = ui.box(0, 0, 54, 34)
                        cell.center = (x + ui.s(-70 + i * 140), base_y)
                        ui.panel(cell, P.PANEL, colour)
                        ui.text(tag, cell.center, "body", colour, "center")
                        ui.text(f"{i + 1} 階",
                                (cell.centerx, cell.bottom + ui.s(12)),
                                "small", P.BONE_DIM, "center")
                if self.page == 2:            # 揮燈：把那道弧畫出來
                    pygame.draw.arc(ui.surface, P.EMBER,
                                    pygame.Rect(x - ui.s(6), base_y - ui.s(34),
                                                ui.s(76), ui.s(68)),
                                    -0.8, 0.8, max(2, ui.s(3)))
            elif who == "gretel":
                self._figure(ui, x, base_y, 14, (236, 232, 224),
                             build="small", hair=(214, 176, 92), skirt=True)
            else:
                self._monster(ui, x, base_y, who)

    @staticmethod
    def _figure(ui: UI, x: int, y: int, radius: int, colour, **kw) -> None:
        from ..view import figures as F

        F.shadow(ui.surface, x, y, ui.s(radius))
        F.humanoid(ui.surface, x, y, ui.s(radius), colour,
                   phase=0.6, moving=False, squash=0.0,
                   facing=(0.0, 1.0), **kw)

    def _monster(self, ui: UI, x: int, y: int, key: str) -> None:
        from ..view import figures as F

        spec = MONSTERS.get(key)
        if spec is None:
            return
        radius = ui.s(spec.radius * 1.3)
        F.shadow(ui.surface, x, y, radius)
        span = max(10, int(radius * 3.4))
        art = self.g.assets.scaled(f"monster.{key}", (span, span))
        if art is not None:
            ui.surface.blit(art, art.get_rect(
                midbottom=(x, int(y + radius * 0.9))))
        else:
            F.humanoid(ui.surface, x, y, radius, spec.colour,
                       phase=0.2, moving=False, squash=0.0,
                       facing=(0.0, 1.0))
        ui.text(spec.name, (x, y + ui.s(26)), "small", P.BONE_DIM, "center")

    def _draw_keys(self, ui: UI) -> None:
        """固定顯示的操作速查列。"""
        ui.text("Esc　關閉新手引導", (ui.s(150), ui.s(572)), "small", P.MUTED)
        cells = Stack.split(ui.box(150, 500, 600, 44), 4, gap=ui.s(10))
        controls = (
            ("WASD", "移動"),
            ("J / Space", "揮燈"),
            ("Shift", "衝刺"),
            ("K", "守衛"),
        )

        for rect, (key, label) in zip(cells, controls):
            ui.panel(rect, P.PANEL, P.LINE)
            ui.text(
                key,
                (rect.centerx, rect.centery - ui.s(8)),
                "small",
                P.EMBER,
                "center",
            )
            ui.text(
                label,
                (rect.centerx, rect.centery + ui.s(10)),
                "tiny",
                P.BONE_DIM,
                "center",
            )

    def update(self, app: SceneStack, ui: UI, dt: float) -> None:
        # Paint the whole canvas first.  This scene draws the field into the
        # middle band and floats panels over it, which leaves the HUD strip and
        # the bottom rail untouched — and since the main loop stopped clearing
        # the window, "untouched" means whatever was there before, including the
        # uninitialised white of the very first frame.
        ui.panel(ui.box(0, 0, 900, m.HEIGHT + HUD_H + RAIL_H), P.VOID, None)

        # The live field, underneath everything.  The page names a key; the
        # player presses that key and watches it happen, on the real character
        # under the real rules — rather than reading a description and finding
        # out whether they understood it during a night that counts.
        if self.state is not None:
            step_arena(self, dt, self.g)
            self.g.board.draw(self.state, self.ticks)
            board = self.g.board_surface
            target = (ui.s(m.WIDTH), ui.s(m.HEIGHT))
            if target != board.get_size():
                board = pygame.transform.smoothscale(board, target)
            ui.surface.blit(board, (0, ui.s(HUD_H)))
        self.dwell += dt

        title, lines, objective = self.PAGES[self.page]
        accent = P.BLOOD if self.page == 5 else P.EMBER

        panel = ui.box(MID - 320, 14, 640, 272)
        ui.panel(panel, P.PANEL, accent, width=ui.s(2), radius=ui.s(8))

        ui.text(
            title,
            (panel.centerx, ui.s(32)),
            "big",
            accent,
            "center",
        )

        # The people the words are about, drawn with the same code that draws
        # them in the game.  A page that says "按 [K] 舉燈守衛" beside a picture
        # of Hansel with the shield up is teaching one thing; the same sentence
        # alone is asking the player to imagine it and check later.
        self._cast(ui, panel)

        y = 190
        for line in lines:
            ui.text(
                line,
                (panel.centerx, ui.s(y)),
                "body",
                P.BONE,
                "center",
            )
            y += 28

        task = ui.box(MID - 250, 296, 500, 40)
        ui.panel(task, P.INK, accent, radius=ui.s(6))
        ui.text(objective, task.center, "body", accent, "center")

        # The Enter prompt counts itself in.  A greyed prompt with no reason
        # given reads as broken; a number counting down reads as "not yet".
        left = self.DWELL - self.dwell
        last = self.page >= len(self.PAGES) - 1
        prompt = ui.box(MID - 190, 552, 380, 40)
        if left > 0:
            ui.panel(prompt, P.PANEL, P.LINE)
            ui.text(f"{left:.0f} 秒後可按 Enter", prompt.center,
                    "small", P.MUTED, "center")
        else:
            ui.panel(prompt, P.PANEL, P.BONE_DIM)
            ui.text("Enter　" + ("開始遊戲" if last else "下一頁"),
                    prompt.center, "body", P.BONE, "center")

        self._draw_keys(ui)

        if pygame.K_ESCAPE in ui.keys:
            self.g.set_onboarding(False)
            self._start_mode(app)
            return

        if self.dwell < self.DWELL:
            return
        if pygame.K_RETURN not in ui.keys and pygame.K_KP_ENTER not in ui.keys:
            return

        if self.page >= len(self.PAGES) - 1:
            self._start_mode(app)
            return
        self.page += 1
        self.dwell = 0.0

# ── prologue ─────────────────────────────────────────────────────────
#: Every line is Hansel's, and none of it is verified.  That is the story: the
#: ending reveals there were no monsters, only a village and a brother whose
#: fear reshaped it.  The prologue states what he believes, never what happened.
PROLOGUE_LINES = (
    ("七年前，我們被父母丟在森林裡。", False),
    ("我們遇見糖果屋，遇見女巫。", False),
    ("最後是葛蕾特殺死了她，帶著我走出森林。", False),
    ("那天之後，我就認定了一件事——", False),
    ("這一次，換我來保護妹妹。", True),
    ("我們回到村子。他們張開手臂迎接我們。", False),
    ("有人好奇，有人議論，也有人不相信她的故事。", False),
    ("我開始注意那些落在妹妹身上的目光。", True),
)


class PrologueScene(Scene):
    def __init__(self, app_state) -> None:
        self.g = app_state
        self.elapsed = 0.0
        self.revealed = False

    def update(self, app: SceneStack, ui: UI, dt: float) -> None:
        self.elapsed += dt
        ui.veil(250)
        ui.text("序章", (ui.s(MID), ui.s(70)), "title", P.EMBER, "center")

        shown = (len(PROLOGUE_LINES) if self.revealed
                 else int(self.elapsed / 0.55) + 1)
        y = 140
        for index, (line, strong) in enumerate(PROLOGUE_LINES):
            if index >= shown:
                break
            ui.text(line, (ui.s(MID), ui.s(y)), "title" if strong else "body",
                    P.EMBER if strong else P.BONE, "center")
            y += 44 if strong else 36

        done = shown >= len(PROLOGUE_LINES)
        ui.text("空白鍵開始第一夜" if done else "空白鍵跳過",
                (ui.s(MID), ui.s(604)), "small",
                P.EMBER if done else P.MUTED, "center")

        if pygame.K_SPACE in ui.keys or pygame.K_RETURN in ui.keys or ui.up:
            if done:
                app.replace(PlayScene(self.g))
            else:
                self.revealed = True


# ── play ─────────────────────────────────────────────────────────────
class PlayScene(Scene):
    """The game: HUD, board, and — in daylight — the preparation panel."""

    def __init__(self, app_state) -> None:
        self.g = app_state
        self._was_night = False

    def enter(self, app: SceneStack) -> None:
        app.ui.keyboard = self.g.state.phase is not m.Phase.NIGHT

    def update(self, app: SceneStack, ui: UI, dt: float) -> None:
        g, state = self.g, self.g.state

        # Arrows and J drive Hansel at night; letting the focus ring eat them
        # would make every keypress do two things.
        night = state.phase is m.Phase.NIGHT
        if night != self._was_night:
            self._was_night = night
            ui.keyboard = not night

        if not ui.inert:
            g.advance(dt, ui)

        g.board.draw(state, g.ticks)
        board = g.board_surface
        target = (ui.s(m.WIDTH), ui.s(m.HEIGHT))
        if target != board.get_size():
            board = pygame.transform.smoothscale(board, target)
        ui.surface.blit(board, (0, ui.s(HUD_H)))

        self._hud(ui, state)
        self._announce(ui, state)
        if state.phase is m.Phase.DAY:
            self._prepare(ui, state)
        else:
            self._night_bar(ui, state)

        # Hand off only while this scene is on top.  The endless offer is a
        # translucent overlay, so this scene keeps drawing underneath it and
        # would push a second copy every frame; 3000 frames produced 300 stacked
        # copies before this guard existed.
        if ui.inert:
            return
        # The night's card, once, before anything else that day.  Guarded by a
        # remembered night number rather than a flag so replaying a lost night
        # shows it again — that is exactly when a player needs reminding what
        # they are walking back into.
        if state.phase is m.Phase.DAY and g.story_shown != state.meta.night:
            g.story_shown = state.meta.night
            app.push(StoryScene(g))
            return

        if state.phase is m.Phase.SHOP:
            app.push(DawnScene(g))
        elif state.phase in (m.Phase.LOST, m.Phase.VICTORY):
            app.push(ResultScene(g))
        elif state.pending_choice:
            app.push(ChoiceScene(g))

    # ── hud ──────────────────────────────────────────────────────────
    def _hud(self, ui: UI, state: m.State) -> None:
        ui.panel(ui.box(0, 0, 900, HUD_H), P.PANEL, P.LINE)

        night = state.phase is m.Phase.NIGHT
        accent = P.NIGHT_BLUE if night else P.EMBER
        ui.panel(ui.box(12, 13, 68, 28), accent if not night else P.PANEL, accent)
        ui.text("夜晚" if night else "白天", (ui.s(46), ui.s(27)), "small",
                (20, 13, 2) if not night else accent, "center")

        x = 96
        if state.meta.mode is m.Mode.CAMPAIGN:
            ui.text("第幾夜", (ui.s(x), ui.s(9)), "tiny", P.MUTED)
            ui.text(str(state.meta.night), (ui.s(x), ui.s(25)), "body", P.BONE)
            x += 62

        ui.text("葛蕾特", (ui.s(x), ui.s(9)), "tiny", P.MUTED)
        hearts = state.meta.max_sister_hp // 2
        for i in range(hearts):
            left = state.meta.sister_hp - i * 2
            colour = (P.BLOOD if left >= 2
                      else P.mix(P.BLOOD, P.BLOOD_DARK, 0.5) if left == 1
                      else P.BLOOD_DARK)
            pygame.draw.circle(ui.surface, colour,
                               (ui.s(x + 6 + i * 14), ui.s(33)), ui.s(5))
        x += hearts * 14 + 24

        ui.text("漢賽爾", (ui.s(x), ui.s(9)), "tiny", P.MUTED)
        for i in range(state.player.max_hp):
            filled = i < state.player.hp
            pygame.draw.circle(ui.surface, P.BONE if filled else P.LINE,
                               (ui.s(x + 5 + i * 11), ui.s(33)), ui.s(4),
                               0 if filled else max(1, ui.s(1)))
        x += state.player.max_hp * 11 + 24

        ui.text("糖霜", (ui.s(x), ui.s(9)), "tiny", P.MUTED)
        ui.text(str(state.meta.sugar), (ui.s(x), ui.s(25)), "body", P.SUGAR)
        x += 66

        if state.meta.skill_points_1 or state.meta.skill_points_2:
            ui.text("技能點", (ui.s(x), ui.s(9)), "tiny", P.MUTED)
            ui.text(f"{state.meta.skill_points_1}／{state.meta.skill_points_2}",
                    (ui.s(x), ui.s(25)), "body", P.ARCANE)
            x += 76

        if state.combo > 2:
            ui.text(f"連段 ×{state.combo}", (ui.s(x), ui.s(25)), "body", P.EMBER)

        if state.meta.godmode:
            # Loud on purpose.  A cheat the player forgets is on turns every
            # later judgement about difficulty into nonsense.
            ui.text("無敵模式　F10 關閉", (ui.s(690), ui.s(33)), "small",
                    P.ARCANE_BRIGHT, "right")

        # Campaign nights count down; endless counts up; daylight has no clock.
        if state.meta.mode is m.Mode.ENDLESS:
            seconds = int(state.elapsed)
        elif night:
            seconds = max(0, int(state.timer + 0.999))
        else:
            seconds = -1
        if state.overtime:
            # "0:00" while the night refuses to end reads as a stuck clock.
            ui.text("延長", (ui.s(884), ui.s(13)), "title", P.BOSS, "right")
        elif seconds >= 0:
            ui.text(f"{seconds // 60}:{seconds % 60:02d}",
                    (ui.s(884), ui.s(13)), "title", accent, "right")

        pygame.draw.rect(ui.surface, P.LINE, ui.box(0, HUD_H - 3, 900, 3))
        if night and state.ticks_total:
            pygame.draw.rect(ui.surface, accent,
                             ui.box(0, HUD_H - 3, 900 * state.timer_fraction, 3))

    def _announce(self, ui: UI, state: m.State) -> None:
        """Say, in words, what just changed.

        The rules announce every change they make; nothing drew the
        announcement, so the red vignette before a surge was a border going red
        and a night event was the rules quietly becoming different.  Both were
        reported as "an effect I do not understand" — which is what an
        unexplained rule change always looks like from the other side of the
        screen.
        """
        if state.phase is not m.Phase.NIGHT:
            return

        if state.overtime:
            live = [b for b in state.bosses if b.hp > 0]
            who = BOSSES[live[0].spec].name if live and live[0].spec in BOSSES \
                else "牠"
            title, sub, colour = ("天亮了，但牠還站著",
                                  f"打倒{who}才算撐過這一夜", P.BOSS)
        elif state.surge_tell > 0:
            title, sub, colour = ("一次來三個",
                                  "紅框亮起是預告，紅圈是他們會出現的位置",
                                  P.BLOOD)
        elif state.event and state.event in EVENTS:
            spec = EVENTS[state.event]
            seconds = max(0, int(state.event_ticks / 60 + 0.999))
            title = f"{spec.name}　{seconds} 秒"
            sub, colour = spec.description, P.ARCANE_BRIGHT
        else:
            return

        plate = ui.box(MID - 165, HUD_H + 12, 330, 46)
        ui.panel(plate, P.PANEL, colour)
        # Two lines, spaced off the font's own line height rather than off a
        # fixed pixel count — the number that was wrong everywhere else.
        gap = ui.book.line_height("small") // 2
        ui.text(title, (plate.centerx, plate.centery - gap), "body",
                colour, "center")
        ui.text(sub, (plate.centerx, plate.centery + gap + ui.s(3)), "small",
                P.BONE_DIM, "center")

    # ── daylight ─────────────────────────────────────────────────────
    def _prepare(self, ui: UI, state: m.State) -> None:
        """Spend sugar on Hansel, spend a skill point on a new answer, then go.

        Two currencies with one job each.  Sugar makes the numbers bigger; skill
        points add options.  When they were the same currency every new skill
        was measured against a health upgrade, and the interesting choice —
        "stronger, or a different answer?" — collapsed into arithmetic.
        """
        # Dim the board only.  Veiling the whole canvas greyed out the HUD as
        # well, which is the one thing that has to stay readable while the
        # player decides what to spend.
        ui.panel(ui.box(0, HUD_H, 900, m.HEIGHT + RAIL_H),
                 P.with_alpha(P.VOID, 222), None)
        stage = stage_for(state.meta.night)

        ui.text(f"第 {state.meta.night} 夜　白天", (ui.s(MID), ui.s(64)),
                "big", P.EMBER, "center")
        ui.text(stage.tagline, (ui.s(MID), ui.s(98)), "small", P.BONE_DIM, "center")

        # Who is coming, as words.  Reading a list beats squinting at
        # silhouettes, and it is the information the day exists to act on.
        roster: dict[str, int] = {}
        for key in stage.recipe:
            roster[key] = roster.get(key, 0) + 1
        cast = "　".join(f"{MONSTERS[k].name}×{n}"
                         for k, n in roster.items() if k in MONSTERS)
        if stage.boss and stage.boss in BOSSES:
            cast += f"　＋　{BOSSES[stage.boss].name}"
        ui.text(ui.truncate(f"今晚：{cast}", ui.s(770), "small"),
                (ui.s(MID), ui.s(124)), "small", P.BLOOD, "center")

        # Two columns.  Stacked, the list ran off the bottom of the screen and
        # the "nightfall" button landed on top of the last skill — and the fix
        # is not a smaller font, it is admitting there are two separate
        # decisions here and giving each one its own side.
        left, right = 60, 470
        width = 370

        # ── left: upgrades, paid in sugar ────────────────────────────
        rows = [k for k in SHOP_ORDER
                if state.meta.night >= UPGRADES[k].unlock_night]
        ui.text(f"用糖霜強化漢賽爾　（{state.meta.sugar}）",
                (ui.s(left), ui.s(160)), "small", P.SUGAR)
        col = _col(ui, left, 178, width, 44 * len(rows), gap=6)
        for key in rows:
            spec = UPGRADES[key]
            level = state.meta.level(key)
            maxed = level >= spec.max_level
            price = spec.cost(level, m.constants.UPGRADE_PRICE_STEP)
            full = (key == "mend"
                    and state.meta.sister_hp >= state.meta.max_sister_hp)
            label = (spec.name if spec.consumable
                     else f"{spec.name}  {level}/{spec.max_level}")
            sub = ("已經到頂" if maxed else "她現在沒有傷口" if full
                   else f"{spec.description}　糖霜 {price}")
            can = not maxed and not full and state.meta.sugar >= price
            if ui.button(f"buy:{key}", col.slot(ui.s(42)), label, sub,
                         enabled=can):
                self.g.act(f"buy:{key}")

        # ── right: skills, paid in skill points ──────────────────────
        ui.text("學新技能",
                (ui.s(right), ui.s(160)), "small", P.ARCANE)
        # Two shelves side by side.  Eight skills in one column ran off the
        # bottom of the screen, and stacking them also hid the thing that makes
        # the list readable: L carries the left column, ；carries the right.
        shelf_w = (width - 12) // 2
        columns = {}
        for tier in (1, 2):
            head = ui.box(right + (tier - 1) * (shelf_w + 12), 168, shelf_w, 18)
            left = state.meta.points_for(tier)
            ui.text(f"{tier} 階　{'L' if tier == 1 else '；'} 鍵"
                    f"　·　技能點 {left}",
                    (head.centerx, head.centery), "small",
                    P.ARCANE_BRIGHT if tier == 1 else P.EMBER, "center")
            columns[tier] = _col(ui, right + (tier - 1) * (shelf_w + 12), 188,
                                 shelf_w, 46 * 4, gap=5)

        order = {"thunder": 0, "light": 1, "wind": 2, "water": 3}
        for key, spec in sorted(SPELL_TABLE.items(),
                                key=lambda kv: (kv[1].tier,
                                                order.get(kv[1].element, 9))):
            known = key in state.meta.skills
            element = ELEMENTS.get(spec.element, {}).get("name", "")
            tag = "已學會" if known else "1 點"
            sub = ui.truncate(spec.description, ui.s(shelf_w - 24), "small")
            if ui.button(f"learn:{key}", columns[spec.tier].slot(ui.s(44)),
                         f"{spec.name}（{element}）　{spec.cooldown:.0f} 秒　{tag}",
                         sub, enabled=not known and
                         state.meta.points_for(spec.tier) >= spec.cost,
                selected=known):
                self.g.act(f"learn:{key}")

        # ── the two carried slots ────────────────────────────────────
        # Directly under the two shelves, not below a column that no longer
        # exists: the skills used to be one list of eight and this was measured
        # from its height, which now overshoots into the 天黑 button.
        slots_y = 396
        ui.text("帶上場的兩個", (ui.s(right), ui.s(slots_y)), "small", P.ARCANE)
        slot_cells = Stack.split(ui.box(right, slots_y + 16, width, 42),
                                 2, gap=ui.s(10))
        for index, (cell, tag) in enumerate(zip(slot_cells, ("L", "；"))):
            key = state.meta.slots[index]
            name = SPELL_TABLE[key].name if key in SPELL_TABLE else "空的"
            tier = 1 if index == 0 else 2
            same = [k for k in state.meta.skills
                    if k in SPELL_TABLE and SPELL_TABLE[k].tier == tier]
            if ui.button(f"slot{index}", cell, f"{tag}　{name}",
                         f"點一下換（會的 {len(same)} 個）" if same
                         else f"還沒學會 {tier} 階技能",
                         enabled=bool(same)):
                self._cycle_slot(state, index)

        # Both shelves have to be filled before the night will start.  A player
        # who walks into night one with two empty slots has not chosen not to
        # use skills — they have not noticed the skills exist, and they will
        # spend the night wondering why two of their four keys do nothing.
        empty = [i for i in (0, 1) if not state.meta.slots[i]]
        ready = not empty
        if ready:
            why = "準備好了就開始"
        else:
            missing = "、".join(f"{i + 1} 階" for i in empty)
            why = f"先選好 {missing} 技能（在右邊）"
        if ui.button("night", ui.box(MID - 140, 566, 280, 48), "天黑",
                     why, enabled=ready):
            self.g.act("begin_night")

    def _cycle_slot(self, state: m.State, index: int) -> None:
        """Put the next learned skill of *this slot's tier* into it.

        Cycling rather than opening a picker: with four skills per shelf, a
        second menu would cost more attention than the choice is worth.

        Filtered by tier, because the slots stopped being interchangeable.  An
        unfiltered cycle offered first-tier skills for the ；shelf and the rules
        refused them — correctly, and by raising, so the game closed the moment
        anyone pressed the button.
        """
        want = 1 if index == 0 else 2
        owned = [k for k in state.meta.skills
                 if k in SPELL_TABLE and SPELL_TABLE[k].tier == want]
        if not owned:
            return
        current = state.meta.slots[index]
        nxt = (owned[0] if current not in owned
               else owned[(owned.index(current) + 1) % len(owned)])
        self.g.act(f"slot:{index}:{nxt}")

    # ── night ────────────────────────────────────────────────────────
    #: The four keys, in the order a hand meets them.  ``None`` for the two
    #: skill slots means "read the loadout" — the panel below fills them in.
    KEYS = (("J", "揮燈", None), ("K", "防禦", None),
            ("L", None, 0), ("；", None, 1))

    def _night_bar(self, ui: UI, state: m.State) -> None:
        top = HUD_H + m.HEIGHT
        ui.panel(ui.box(0, top, 900, RAIL_H), P.INK, P.LINE)

        if state.meta.night == 1 and state.meta.mode is m.Mode.CAMPAIGN:
            hint = "提燈照到的地方才看得見。看不見的東西還是在走。"
            colour = P.EMBER
        else:
            hint = "WASD 移動　·　Shift 衝刺　·　Esc 選單　·　F9 截圖"
            colour = P.BONE_DIM
        ui.text(hint, (ui.s(24), ui.s(top + 30)), "small", colour)

        self._keypad(ui, state, top)

    def _keypad(self, ui: UI, state: m.State, top: int) -> None:
        """Four keys, bottom right, each showing what it is and whether it is up.

        Written as one row of identical cells on purpose.  Attack, guard and the
        two skills were previously three different shapes in three places — a
        cooldown bar for skills, nothing at all for the lantern, and a line of
        prose for the guard — so the player had to *learn* that they were the
        same kind of thing.  Four boxes in a row says it without a word.

        Everything drawn here is read out of the model.  The jolt on a press is
        derived from ``swing_anim`` and from a cooldown that has just been set,
        never from the keyboard: the renderer must not be able to disagree with
        the rules about whether something fired.
        """
        stats = m.derive(state)
        p = state.player
        cell_w, cell_h, gap = 82, 58, 8
        x0 = 900 - 24 - (cell_w * 4 + gap * 3)

        for i, (tag, fixed_name, slot) in enumerate(self.KEYS):
            rect = ui.box(x0 + i * (cell_w + gap), top + 8, cell_w, cell_h)
            name, frac, live, held = fixed_name, 1.0, True, False

            if i == 0:                                   # J — the lantern
                full = max(0.001, stats.swing_cooldown)
                frac = 1.0 - p.swing_cooldown / full
                live = p.swing_cooldown <= 0
                held = p.swing_anim > 0
            elif i == 1:                                 # K — the guard
                held = p.guarding
                live = not p.helpless
            else:                                        # L / ； — the skills
                key = state.meta.slots[slot]
                spec = SPELL_TABLE.get(key) if key else None
                if spec is None:
                    name = "—"
                    frac, live = 1.0, False
                else:
                    name = spec.name
                    total = max(1, int(spec.cooldown * 60))
                    left = state.cooldowns.get(key, 0)
                    frac = 1.0 - left / total
                    live = left <= 0
                    # Just cast: the cooldown is still within a few frames of
                    # full.  That is the press, read back out of the rules.
                    held = left > total - 8

            self._key_cell(ui, rect, tag, name or "—", frac, live, held, i)

    @staticmethod
    def _key_icon(ui: UI, rect: pygame.Rect, slot: int, colour) -> None:
        """A tiny glyph per key, drawn rather than loaded.

        Four shapes the player can tell apart at a glance without reading:
        the lantern's arc, a shield, and the two skill sigils.  Drawn from
        primitives so they cost no asset and scale with the display.
        """
        cx, cy = rect.centerx, rect.top + ui.s(11)
        r = ui.s(7)
        if slot == 0:                                     # J — the swing arc
            pygame.draw.arc(ui.surface, colour,
                            pygame.Rect(cx - r, cy - r, r * 2, r * 2),
                            -1.0, 1.0, max(2, ui.s(2)))
            pygame.draw.circle(ui.surface, colour, (cx - r, cy), max(1, ui.s(2)))
        elif slot == 1:                                   # K — a shield
            pygame.draw.polygon(ui.surface, colour, [
                (cx, cy - r), (cx + r, cy - r + ui.s(2)),
                (cx, cy + r), (cx - r, cy - r + ui.s(2))], max(2, ui.s(2)))
        elif slot == 2:                                   # L — a spark
            pygame.draw.polygon(ui.surface, colour, [
                (cx + ui.s(2), cy - r), (cx - r + ui.s(3), cy + ui.s(1)),
                (cx, cy + ui.s(1)), (cx - ui.s(2), cy + r),
                (cx + r - ui.s(3), cy - ui.s(1)), (cx, cy - ui.s(1))])
        else:                                             # ； — a ring
            pygame.draw.circle(ui.surface, colour, (cx, cy), r, max(2, ui.s(2)))

    def _key_cell(self, ui: UI, rect: pygame.Rect, tag: str, name: str,
                  frac: float, live: bool, held: bool, slot: int = 0) -> None:
        # The jolt.  Two pixels, upward — enough to register as a response and
        # small enough that four of them firing at once is not a jumble.
        if held:
            rect = rect.move(0, -ui.s(2))

        edge = P.EMBER if held else (P.ARCANE_BRIGHT if live else P.LINE_HI)
        ui.panel(rect, P.PANEL_HI if held else P.PANEL, edge)

        # The cooldown fills the cell from the left, behind the text, so the
        # cell *is* the gauge — a bar somewhere else is one more thing to learn
        # the meaning of.  Inset so it never eats the border, and kept dark: the
        # first version was bright enough to swallow the label, which made the
        # readout least readable exactly while the player was waiting on it.
        if frac < 1.0:
            inner = rect.inflate(-ui.s(4), -ui.s(4))
            inner.width = max(0, int(inner.width * max(0.0, frac)))
            if inner.width > 0:
                pygame.draw.rect(ui.surface, P.mix(P.PANEL, P.ARCANE, 0.30),
                                 inner)
                pygame.draw.rect(ui.surface, P.ARCANE, inner, max(1, ui.s(1)))

        # The name stays legible whatever the state; only the key letter changes
        # colour.  Greying out the *name* while it recharges hides the one word
        # that says what the key is for.
        # The letter is coloured separately from the border.  Reusing the border
        # colour put a dark grey glyph on top of the cooldown fill, which hid
        # the one character telling the player which key this cell is.
        letter = P.EMBER if held else (P.ARCANE_BRIGHT if live else P.BONE_DIM)
        self._key_icon(ui, rect, slot, letter)
        ui.text(tag, (rect.centerx, rect.centery + ui.s(2)), "small",
                letter, "center")
        ui.text(name, (rect.centerx, rect.bottom - ui.s(11)), "small",
                P.BONE if live or held else P.BONE_DIM, "center")


def build_arena(monster_key: str | None = None) -> "m.State":
    """A night with the teeth pulled: nothing spawns, nothing can be lost.

    Shared by the walkthrough and the monster rounds so both run the *real*
    rules.  A hand-written practice loop would drift away from the game the
    first time either changed, and the drift would be invisible until a player
    learned something that was no longer true.
    """
    from ..model.rules import make_monster

    state = m.new_game(seed=1, meta=m.Meta(night=1, godmode=True))
    state = m.apply_action(state, "begin_night")
    state.sleepers.clear()
    state.monsters.clear()
    state.surges.clear()
    state.obstacles.clear()
    state.boss_key = None
    state.boss_sent = True
    state.ticks_total = state.ticks_left = 60 * 60 * 10
    state.hush_ticks = 60 * 60 * 10
    if monster_key is not None:
        # To the side, not above: the banner covers the top of the field, and a
        # monster spawned up there hides behind the text introducing it.
        monster = make_monster(state, monster_key,
                               m.SISTER_X - 280.0, m.SISTER_Y - 30.0)
        monster.wake = 0.0
        state.monsters.append(monster)
    state.player.x, state.player.y = m.SISTER_X, m.SISTER_Y + 110.0
    return state


def step_arena(scene, dt: float, session) -> None:
    """Run ``scene.state`` forward by one frame of real input."""
    from .game import MAX_STEPS_PER_FRAME, Session

    steps = 0
    scene.accumulator += dt
    while scene.accumulator >= m.FIXED_DT and steps < MAX_STEPS_PER_FRAME:
        scene.accumulator -= m.FIXED_DT
        scene.state = m.apply_action(scene.state,
                                     Session._input_action(scene.state))
        session.heard.extend(scene.state.events)
        scene.ticks += 1
        steps += 1
    if scene.accumulator > m.FIXED_DT * MAX_STEPS_PER_FRAME:
        scene.accumulator = 0.0


# ── the practice arena ───────────────────────────────────────────────
#: Nights whose newcomers get a hands-on round rather than a paragraph.  After
#: night three the player has the vocabulary to read a written line, and by then
#: a compulsory practice bout before every night is an obstacle, not a lesson.
PRACTICE_NIGHTS = (1, 2, 3)


class PracticeScene(Scene):
    """Meet each new monster once, alone, with nothing at stake.

    A written description tells the player what a monster *does*; it cannot
    tell them what it feels like to be walked down by one.  So this is the real
    game — same rules, same rendering, same keys — with three things removed:
    Gretel cannot be hurt, no reinforcements arrive, and there is no clock.
    What is left is one monster and the space to learn it.

    It runs its own ``State``, entirely separate from the run.  Borrowing the
    campaign's state and putting it back would mean one bug here could corrupt a
    night the player had already survived; a private state cannot.
    """

    def __init__(self, app_state, keys: tuple[str, ...]) -> None:
        self.g = app_state
        self.queue = [k for k in keys if k in MONSTERS]
        self.index = 0
        self.state: m.State | None = None
        self.accumulator = 0.0
        self.ticks = 0
        self.cleared = 0.0            # seconds since the current one fell

    def enter(self, app: SceneStack) -> None:
        app.ui.keyboard = False       # the focus ring must not eat WASD
        self._begin()

    def exit(self, app: SceneStack) -> None:
        app.ui.keyboard = True

    # ── one round ────────────────────────────────────────────────────
    def _begin(self) -> None:
        """Build a clean arena holding exactly one monster."""
        self.state = build_arena(self.queue[self.index])
        self.accumulator = 0.0
        self.ticks = 0
        self.cleared = 0.0

    def _advance(self, dt: float) -> None:
        step_arena(self, dt, self.g)

    # ── the frame ────────────────────────────────────────────────────
    def update(self, app: SceneStack, ui: UI, dt: float) -> None:
        if self.state is None or self.index >= len(self.queue):
            app.pop()
            return

        alive = any(x.hp > 0 for x in self.state.monsters)
        if alive:
            self._advance(dt)
        else:
            self.cleared += dt
            self._advance(dt)         # let the death effects finish playing

        board = self.g.board
        board.draw(self.state, self.ticks)
        surface = self.g.board_surface
        target = (ui.s(m.WIDTH), ui.s(m.HEIGHT))
        if target != surface.get_size():
            surface = pygame.transform.smoothscale(surface, target)
        ui.surface.blit(surface, (0, ui.s(HUD_H)))

        if alive:
            self._spotlight(ui)
        self._banner(ui)
        self._rail(app, ui, alive)

        if ui.inert:
            return
        if not alive and self.cleared > 1.1:
            self._next(app)

    def _next(self, app: SceneStack) -> None:
        self.g.teach(self.queue[self.index])
        self.index += 1
        if self.index >= len(self.queue):
            app.pop()
            return
        self._begin()

    def _skip(self, app: SceneStack) -> None:
        """Leave the walkthroughs behind, for good but not irreversibly."""
        self.g.set_onboarding(False)
        app.pop()

    # ── presentation ─────────────────────────────────────────────────
    def _banner(self, ui: UI) -> None:
        """The monster's name and what it does, at a size that can be read.

        This was one line of 13px text in a 54px strip, which is the size the
        HUD uses for numbers the player already knows the meaning of.  It is the
        wrong size for the *one* sentence they have never seen before and are
        about to be tested on.  Name at title size, behaviour at body size, on a
        plate of its own.
        """
        spec = MONSTERS[self.queue[self.index]]
        plate = ui.box(0, 0, 900, 92)
        ui.panel(plate, P.PANEL, P.LINE)
        pygame.draw.rect(ui.surface, P.EMBER,
                         pygame.Rect(plate.left, plate.top, ui.s(4),
                                     plate.height))

        ui.text(spec.name, (ui.s(28), ui.s(14)), "big", P.EMBER)
        ui.text(f"{self.index + 1} / {len(self.queue)}",
                (ui.s(872), ui.s(18)), "title", P.MUTED, "right")
        for i, line in enumerate(
                ui.wrap(StoryScene._describe(spec), ui.s(800), "body")[:2]):
            ui.text(line, (ui.s(28), ui.s(52 + i * 22)), "body", P.BONE)

    def _spotlight(self, ui: UI) -> None:
        """Point at the thing being taught.

        The arena is dark by design, and a monster the player cannot find is a
        lesson that never starts.  A ring and a bobbing arrow follow it for as
        long as it lives — this is the one screen where being told exactly where
        to look is the whole point.
        """
        live = [x for x in self.state.monsters if x.hp > 0]
        if not live:
            return
        target = live[0]
        x = ui.s(target.x)
        y = ui.s(target.y) + ui.s(HUD_H)
        bob = math.sin(self.ticks / 9.0) * ui.s(4)
        radius = ui.s(30) + int(math.sin(self.ticks / 11.0) * ui.s(3))
        pygame.draw.circle(ui.surface, P.EMBER, (x, y), radius, max(2, ui.s(2)))
        tip = int(y - ui.s(38) + bob)
        pygame.draw.polygon(ui.surface, P.EMBER, [
            (x, tip + ui.s(14)), (x - ui.s(9), tip), (x + ui.s(9), tip)])

    def _rail(self, app: SceneStack, ui: UI, alive: bool) -> None:
        top = HUD_H + m.HEIGHT
        ui.panel(ui.box(0, top, 900, RAIL_H), P.INK, P.LINE)
        if alive:
            line = "葛蕾特在這一關不會受傷。放心試，打倒牠就繼續。"
            colour = P.BONE
        else:
            line = "打倒了。"
            colour = P.EMBER
        ui.text(line, (ui.s(24), ui.s(top + 18)), "body", colour)
        ui.text("WASD 移動　·　J 揮燈　·　K 防禦　·　Shift 衝刺　·　"
                "之後可在暫停選單把引導開回來",
                (ui.s(24), ui.s(top + 46)), "small", P.MUTED)

        rect = ui.box(668, top + 14, 208, 46)
        if ui.button("skip", rect, "關閉新手引導", "Esc"):
            self._skip(app)


# ── the card between nights ──────────────────────────────────────────
class StoryScene(Scene):
    """What has happened, and who is new tonight.

    Shown once at the head of each day, before the shop.  Two jobs in one
    screen, and they belong together: the night's story beat says *why* the
    village is worse, and the introductions say *how* — the same escalation,
    told twice, once in prose and once in mechanics.

    Every monster line comes from the registry, not from a paragraph typed
    here.  A monster whose behaviour is retuned re-explains itself; one written
    up by hand would go on describing what it used to do.
    """

    def __init__(self, app_state) -> None:
        self.g = app_state

    def update(self, app: SceneStack, ui: UI, dt: float) -> None:
        state = self.g.state
        night = state.meta.night
        endless = state.meta.mode is m.Mode.ENDLESS
        beat = ENDLESS_BEAT if endless else BEATS.get(night, ENDLESS_BEAT)

        ui.veil(250)
        title = "無盡" if endless else f"第 {night} 夜"
        ui.text(title, (ui.s(MID), ui.s(52)), "huge", P.BONE, "center")
        ui.text(beat.heading, (ui.s(MID), ui.s(104)), "title", P.EMBER, "center")
        ui.paragraph(beat.body, ui.box(MID - 300, 146, 600, 110), "body",
                     P.BONE_DIM, "center")

        fresh = () if endless else newcomers(night)
        boss = None if endless else self._boss_key(night)

        # Nights one to three hand their newcomers to a practice round instead
        # of describing them.  Reading "被打死會炸開" and *being* caught by the
        # blast are not the same lesson, and the second one sticks.
        hands_on = (night in PRACTICE_NIGHTS and fresh and not endless
                    and self.g.onboarding)

        y = 274
        if fresh or boss:
            ui.text("今晚第一次出現", (ui.s(MID), ui.s(y)), "small",
                    P.MUTED, "center")
            y += 26
            # Compact whenever the full rows would not fit.  Six species is
            # 324 pixels of list on a 520-pixel field, which pushed the button
            # off the bottom of the screen — the one control the card has.
            if hands_on or len(fresh) > 3:
                # Just the names.  Six full rows ran off the bottom of the
                # screen on night one, and every word of them is about to be
                # said again — properly — in the practice round.
                names = [MONSTERS[k].name for k in fresh]
                for row in (names[:3], names[3:]):
                    if not row:
                        continue
                    ui.text("　·　".join(row), (ui.s(MID), ui.s(y)),
                            "title", P.VILLAGER, "center")
                    y += 34
                if not hands_on:
                    ui.text("完整說明在暫停選單的圖鑑裡",
                            (ui.s(MID), ui.s(y)), "small", P.MUTED, "center")
                    y += 26
            else:
                for key in fresh:
                    y = self._row(ui, y, MONSTERS[key].name,
                                  self._describe(MONSTERS[key]), P.VILLAGER)
            if boss is not None:
                spec = BOSSES[boss]
                # Its title and its weakness, not a sentence of atmosphere.
                # The one thing a player needs before a boss fight is which
                # skill to bring, and that is a fact the table already knows.
                weak = ELEMENTS.get(getattr(spec, "weakness", None) or "")
                note = spec.title
                if weak:
                    note = f"{note}　·　弱點：{weak['name']}"
                y = self._row(ui, y, f"{spec.name}　（Boss）", note, P.BOSS)

        col = _col(ui, MID - 150, max(y + 18, 556), 300, 60, gap=10)
        if hands_on:
            if ui.button("go", col.slot(ui.s(46)), "先認識他們",
                         "一隻一隻試，葛蕾特不會受傷"):
                app.replace(PracticeScene(self.g, fresh))
            return
        if ui.button("go", col.slot(ui.s(46)), "天亮了") or ui.up:
            app.pop()

    @staticmethod
    def _boss_key(night: int) -> str | None:
        from ..model.content import stage_for

        stage = stage_for(night)
        return stage.boss if stage else None

    @staticmethod
    def _describe(spec) -> str:
        """One line, assembled from what the monster actually does."""
        parts = [describe_mechanic(spec.behaviour)]
        parts += [describe_mechanic(t) for t in getattr(spec, "traits", ())]
        return "　".join(parts)

    def _row(self, ui: UI, y: int, name: str, note: str, accent) -> int:
        rect = ui.box(MID - 300, y, 600, 46)
        ui.panel(rect, P.PANEL, P.LINE)
        pygame.draw.rect(ui.surface, accent,
                         pygame.Rect(rect.left, rect.top, ui.s(3), rect.height))
        ui.text(name, (rect.left + ui.s(16), rect.top + ui.s(8)), "body", P.BONE)
        ui.text(ui.truncate(note, rect.width - ui.s(32), "small"),
                (rect.left + ui.s(16), rect.top + ui.s(27)), "small", P.MUTED)
        return y + 54


# ── dawn ─────────────────────────────────────────────────────────────
class DawnScene(Scene):
    """What the night cost, and nothing to decide.

    Spending moved into daylight, so this screen has one job: say what happened
    before the player plans the next night.  A ledger and a shopping list on one
    screen meant neither got read.
    """

    def __init__(self, app_state) -> None:
        self.g = app_state

    def update(self, app: SceneStack, ui: UI, dt: float) -> None:
        state = self.g.state
        ui.veil(238)

        ui.text(f"撐過了第 {state.meta.night} 夜", (ui.s(MID), ui.s(124)),
                "big", P.BONE, "center")
        ui.text("天亮了，村民又變回和善的樣子。",
                (ui.s(MID), ui.s(162)), "small", P.BONE_DIM, "center")

        report = m.grade_night(state)

        # The grade, and immediately underneath it the reason.  A letter on its
        # own teaches nothing; the player reads "C" and learns only that they
        # are being judged.  Naming the weakest line turns the same letter into
        # an instruction for tomorrow night.
        badge = ui.box(MID - 46, 190, 92, 74)
        ui.panel(badge, P.PANEL, _GRADE_COLOUR.get(report.grade, P.BONE))
        ui.text(report.grade, (badge.centerx, badge.top + ui.s(8)), "huge",
                _GRADE_COLOUR.get(report.grade, P.BONE), "center")
        ui.text(f"{report.points}/{report.out_of}",
                (badge.centerx, badge.bottom - ui.s(20)), "small",
                P.MUTED, "center")
        if report.weakest is not None:
            ui.text(f"最弱的一環：{report.weakest.label}　{report.weakest.detail}",
                    (ui.s(MID), ui.s(274)), "small", P.EMBER, "center")

        y = 306
        for line in report.lines:
            ui.text(line.label, (ui.s(MID - 210), ui.s(y)), "small", P.BONE_DIM)
            bar = ui.box(MID - 150, y + 4, 200, 10)
            ui.bar(bar, line.fraction,
                   P.BLOOD if line.fraction < 0.4 else
                   (P.EMBER if line.fraction < 0.85 else P.GOOD))
            ui.text(f"{line.points}/{line.out_of}",
                    (ui.s(MID + 66), ui.s(y)), "small", P.BONE)
            ui.text(ui.truncate(line.detail, ui.s(190), "small"),
                    (ui.s(MID + 110), ui.s(y)), "small", P.MUTED)
            y += 26

        ui.text(f"糖霜 {state.meta.sugar}　·　明天會再多一點技能點",
                (ui.s(MID), ui.s(y + 18)), "body", P.SUGAR, "center")

        if ui.button("next", ui.box(MID - 120, 524, 240, 46), "進入下一個白天"):
            self.g.act("next_night")
            app.pop()


# ── endless offer ────────────────────────────────────────────────────
class ChoiceScene(Scene):
    """Endless has no day, so growth is chosen mid-run."""

    opaque = False

    def __init__(self, app_state) -> None:
        self.g = app_state

    def update(self, app: SceneStack, ui: UI, dt: float) -> None:
        state = self.g.state
        if not state.pending_choice:
            app.pop()
            return

        ui.veil(170)
        ui.text("挑一樣帶走", (ui.s(MID), ui.s(150)), "big", P.EMBER, "center")
        cells = Stack.split(ui.box(120, 216, 660, 96),
                            len(state.pending_choice), gap=ui.s(14))
        for key, rect in zip(state.pending_choice, cells):
            spec = UPGRADES[key]
            level = state.meta.level(key)
            if ui.button(f"choose:{key}", rect, spec.name,
                         f"{spec.description}（{level}/{spec.max_level}）"):
                self.g.act(f"choose:{key}")
                app.pop()


# ── result ───────────────────────────────────────────────────────────
class ResultScene(Scene):
    def __init__(self, app_state) -> None:
        self.g = app_state

    def update(self, app: SceneStack, ui: UI, dt: float) -> None:
        state = self.g.state
        ui.veil(246)
        won = state.phase is m.Phase.VICTORY

        ui.text("第一個冬天過去了" if won else "葛蕾特不見了",
                (ui.s(MID), ui.s(140)), "huge",
                P.EMBER if won else P.BONE, "center")

        if won:
            line = "七夜之後，村子安靜下來了。"
        elif state.meta.mode is m.Mode.ENDLESS:
            seconds = int(state.elapsed)
            line = (f"撐了 {seconds // 60}:{seconds % 60:02d}，"
                    f"擊退 {state.stats.kills} 人。")
        else:
            line = "黑暗裡有很多雙手。你沒能全部擋下來。"
        ui.text(line, (ui.s(MID), ui.s(198)), "body", P.BONE_DIM, "center")

        col = _col(ui, MID - 150, 268, 300, 190, gap=12)
        if won:
            if ui.button("again", col.slot(ui.s(46)), "再玩一次"):
                self.g.restart()
                app.pop()
        else:
            # Losing keeps the糖霜, the upgrades, the skills and the night.
            # Wiping them meant every loss cost the player the *learning* as
            # well as the run, and a seventh night nobody could reach might as
            # well not exist.  Starting over is still there, as a choice.
            if ui.button("again", col.slot(ui.s(46)), "再試一次這一夜",
                         "保留糖霜、升級和技能"):
                self.g.retry_night()
                app.pop()
            if ui.button("fresh", col.slot(ui.s(46)), "從頭開始",
                         "回到第一夜，清空所有進度"):
                self.g.restart()
                app.pop()
        if ui.button("menu", col.slot(ui.s(46)), "回選單"):
            self.g.to_menu(app)


# ── pause ────────────────────────────────────────────────────────────
class PauseScene(Scene):
    """Esc, from anywhere.  The game stays visible behind it, because the point
    of stopping is to look at what you stopped."""

    opaque = False

    def __init__(self, app_state, game) -> None:
        self.g = app_state
        self.game = game

    def update(self, app: SceneStack, ui: UI, dt: float) -> None:
        ui.veil(200)
        ui.text("暫停", (ui.s(MID), ui.s(130)), "big", P.EMBER, "center")

        col = _col(ui, MID - 130, 190, 260, 290, gap=10)
        if ui.button("resume", col.slot(ui.s(44)), "繼續"):
            app.pop()
        if ui.button("codex", col.slot(ui.s(44)), "圖鑑"):
            app.push(CodexScene(self.g))
        on = self.g.onboarding
        if ui.button("guide", col.slot(ui.s(44)),
                     f"新手引導：{'開' if on else '關'}",
                     "怪物體驗關與操作說明"):
            self.g.set_onboarding(not on)
        if ui.button("full", col.slot(ui.s(44)),
                     "切換視窗" if self.game.fullscreen else "切換全螢幕", "F11"):
            self.game.toggle_fullscreen()
        if ui.button("menu", col.slot(ui.s(44)), "回主選單", "這一場會結束"):
            self.g.to_menu(app)
        if ui.button("quit", col.slot(ui.s(44)), "離開遊戲"):
            self.game.running = False

        ui.text("Esc 也可以直接關掉這個選單",
                (ui.s(MID), ui.s(604)), "small", P.MUTED, "center")


# ── codex ────────────────────────────────────────────────────────────
class CodexScene(Scene):
    """怪物圖鑑 / 頭目圖鑑 / 技能圖鑑.

    Every line is generated from the same tables the simulation reads — stats
    from the spec, mechanic descriptions from the registry entries.  Nothing is
    written twice, so it cannot say one thing while the game does another, which
    is what happens to a hand-kept bestiary within a month of the first balance
    pass.
    """

    PAGES = ("怪物", "頭目", "技能")
    PER_PAGE = 7

    def __init__(self, app_state) -> None:
        self.g = app_state
        self.page = 0
        self.scroll = 0

    def update(self, app: SceneStack, ui: UI, dt: float) -> None:
        ui.veil(250)
        ui.text("圖鑑", (ui.s(MID), ui.s(38)), "big", P.EMBER, "center")

        tabs = Stack.split(ui.box(MID - 210, 64, 420, 32), 3, gap=ui.s(6))
        for index, (name, cell) in enumerate(zip(self.PAGES, tabs)):
            if ui.button(f"tab{index}", cell, name, selected=index == self.page):
                self.page, self.scroll = index, 0

        rows = self._rows()
        if pygame.K_DOWN in ui.keys:
            self.scroll = min(max(0, len(rows) - self.PER_PAGE), self.scroll + 1)
        if pygame.K_UP in ui.keys:
            self.scroll = max(0, self.scroll - 1)

        y = 120
        for title, stats, note in rows[self.scroll:self.scroll + self.PER_PAGE]:
            ui.text(title, (ui.s(MID - 320), ui.s(y)), "body", P.BONE)
            ui.text(stats, (ui.s(MID - 150), ui.s(y + 2)), "small", P.BONE_DIM)
            if note:
                ui.text(ui.truncate(note, ui.s(420), "small"),
                        (ui.s(MID - 150), ui.s(y + 24)), "small", P.EMBER_DARK)
            y += 56

        if len(rows) > self.PER_PAGE:
            last = min(len(rows), self.scroll + self.PER_PAGE)
            ui.text(f"↑↓ 捲動　{self.scroll + 1}–{last} / {len(rows)}",
                    (ui.s(MID), ui.s(552)), "small", P.MUTED, "center")

        if ui.button("back", ui.box(MID - 90, 578, 180, 40), "返回"):
            app.pop()

    def _rows(self) -> list[tuple[str, str, str]]:
        if self.page == 0:
            return [self._monster_row(s) for s in MONSTERS.values()]
        if self.page == 1:
            return [self._boss_row(s) for s in BOSSES.values()]
        return [self._skill_row(s) for s in SPELL_TABLE.values()]

    @staticmethod
    def _mechanics(spec) -> str:
        names = list(getattr(spec, "traits", ()))
        if getattr(spec, "behaviour", "charge") != "charge":
            names.insert(0, spec.behaviour)
        return "　".join(describe_mechanic(name) for name in names)

    def _monster_row(self, spec) -> tuple[str, str, str]:
        weak = ELEMENTS.get(spec.weakness or "", {}).get("name")
        stats = (f"血 {spec.hp}　速 {spec.speed:.0f}　糖霜 {spec.sugar}"
                 + ("　打不退" if not spec.knockable else "")
                 + (f"　弱點 {weak}" if weak else ""))
        return (spec.name, stats, self._mechanics(spec))

    def _boss_row(self, spec) -> tuple[str, str, str]:
        weak = ELEMENTS.get(spec.weakness or "", {}).get("name", "沒有單一解答")
        stats = f"{spec.title}　血 {spec.hp}　弱點 {weak}　{len(spec.phases)} 階段"
        return (spec.name, stats,
                spec.phases[0].announce or self._mechanics(spec))

    def _skill_row(self, spec) -> tuple[str, str, str]:
        element = ELEMENTS.get(spec.element, {}).get("name", "")
        stats = (f"{element}　技能點 {spec.cost}　冷卻 {spec.cooldown:.0f} 秒　"
                 + (f"持續 {spec.duration:.0f} 秒" if spec.duration else "瞬間"))
        return (spec.name, stats, spec.description)


def build_menu(app_state) -> Scene:
    return MenuScene(app_state)
