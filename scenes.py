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

import pygame

from .. import model as m
from ..model.content import BOSSES, EVENTS, MONSTERS
from ..model.content import SPELLS as SPELL_TABLE
from ..model.content import stage_for
from ..model.content.elements import ELEMENTS
from ..model.content.upgrades import SHOP_ORDER, UPGRADES
from ..model.registry import describe_mechanic
from ..view import palette as P
from ..view.ui import Scene, SceneStack, Stack, UI

#: Layout units.  The board sits between the HUD strip and the hint strip.
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

    def update(self, app: SceneStack, ui: UI, dt: float) -> None:
        ui.veil(252)
        ui.text("糖果屋之後", (ui.s(MID), ui.s(92)), "huge", P.EMBER, "center")
        ui.text("這一次，換他來保護妹妹。",
                (ui.s(MID), ui.s(142)), "body", P.BONE_DIM, "center")

        col = _col(ui, MID - 170, 196, 340, 280, gap=12)
        if ui.button("campaign", col.slot(ui.s(60)), "七夜",
                     "撐過七個夜晚，每一夜都有牠們的頭目"):
            self.g.start(m.Mode.CAMPAIGN)
            app.replace(PrologueScene(self.g))
        if ui.button("endless", col.slot(ui.s(60)), "無盡",
                     "牠們不會停。撐到你倒下為止"):
            self.g.start(m.Mode.ENDLESS)
            app.replace(PlayScene(self.g))
        if ui.button("codex", col.slot(ui.s(42)), "圖鑑", "看看你會遇到什麼"):
            app.push(CodexScene(self.g))

        meta = self.g.saved
        best = f"最佳：第 {meta.best_night} 夜"
        if meta.best_endless_ticks:
            seconds = int(meta.best_endless_ticks * m.FIXED_DT)
            best += f"　·　無盡 {seconds // 60}:{seconds % 60:02d}"
        ui.text(best, (ui.s(MID), ui.s(442)), "small", P.MUTED, "center")
        ui.text("方向鍵或滑鼠選擇　·　Enter 確定　·　F11 全螢幕",
                (ui.s(MID), ui.s(608)), "small", P.MUTED, "center")


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

        if state.meta.skill_points:
            ui.text("技能點", (ui.s(x), ui.s(9)), "tiny", P.MUTED)
            ui.text(str(state.meta.skill_points), (ui.s(x), ui.s(25)),
                    "body", P.ARCANE)
            x += 66

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
        if seconds >= 0:
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

        if state.surge_tell > 0:
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
        ui.text(f"學新技能　（技能點 {state.meta.skill_points}）",
                (ui.s(right), ui.s(160)), "small", P.ARCANE)
        skills = _col(ui, right, 178, width, 46 * len(SPELL_TABLE), gap=6)
        for key, spec in sorted(SPELL_TABLE.items()):
            known = key in state.meta.skills
            element = ELEMENTS.get(spec.element, {}).get("name", "")
            tag = "已學會" if known else f"技能點 {spec.cost}"
            # What it *does*, not just what it costs.  A list of prices asks the
            # player to buy something they cannot picture.
            sub = f"{spec.description}"
            if ui.button(f"learn:{key}", skills.slot(ui.s(44)),
                         f"{spec.name}（{element}）　冷卻 {spec.cooldown:.0f}s　{tag}",
                         sub, enabled=not known and
                         state.meta.skill_points >= spec.cost,
                         selected=known):
                self.g.act(f"learn:{key}")

        # ── the two carried slots ────────────────────────────────────
        slots_y = 178 + 46 * len(SPELL_TABLE) + 14
        ui.text("帶上場的兩個", (ui.s(right), ui.s(slots_y)), "small", P.ARCANE)
        slot_cells = Stack.split(ui.box(right, slots_y + 16, width, 42),
                                 2, gap=ui.s(10))
        for index, (cell, tag) in enumerate(zip(slot_cells, ("L", "；"))):
            key = state.meta.slots[index]
            name = SPELL_TABLE[key].name if key in SPELL_TABLE else "空的"
            if ui.button(f"slot{index}", cell, f"{tag}　{name}",
                         "點一下換" if state.meta.skills else "還沒學會",
                         enabled=bool(state.meta.skills)):
                self._cycle_slot(state, index)

        if ui.button("night", ui.box(MID - 120, 566, 240, 48), "天黑",
                     "準備好了就開始"):
            self.g.act("begin_night")

    def _cycle_slot(self, state: m.State, index: int) -> None:
        """Put the next learned skill into this slot.

        Cycling rather than opening a picker: with four skills and two slots, a
        second menu would cost more attention than the choice is worth.
        """
        owned = list(state.meta.skills)
        if not owned:
            return
        current = state.meta.slots[index]
        nxt = (owned[0] if current not in owned
               else owned[(owned.index(current) + 1) % len(owned)])
        self.g.act(f"slot:{index}:{nxt}")

    # ── night ────────────────────────────────────────────────────────
    def _night_bar(self, ui: UI, state: m.State) -> None:
        top = HUD_H + m.HEIGHT
        ui.panel(ui.box(0, top, 900, RAIL_H), P.INK, P.LINE)

        cells = Stack.split(ui.box(250, top + 8, 400, 26), 2, gap=ui.s(10))
        for slot, (cell, tag) in enumerate(zip(cells, ("L", "；"))):
            key = state.meta.slots[slot]
            if not key or key not in SPELL_TABLE:
                ui.text(f"{tag} —", (cell.centerx, cell.centery), "small",
                        P.MUTED, "center")
                continue
            spec = SPELL_TABLE[key]
            left = state.cooldowns.get(key, 0)
            if left > 0:
                # The bar *is* the readout.  A number counting down asks the
                # player to read while fighting; a shrinking bar does not.
                ui.bar(cell, 1.0 - left / max(1, int(spec.cooldown * 60)),
                       P.ARCANE_BRIGHT)
                ui.text(f"{tag} {spec.name}", (cell.centerx, cell.centery),
                        "small", P.MUTED, "center")
            else:
                ui.text(f"{tag} {spec.name}　可用", (cell.centerx, cell.centery),
                        "small", P.ARCANE_BRIGHT, "center")

        # The first night says out loud what the lantern is for.  The darkness
        # is the game's central rule and nothing on screen was explaining it —
        # a player who thinks their monitor is broken is not being challenged.
        if state.meta.night == 1 and state.meta.mode is m.Mode.CAMPAIGN:
            ui.text("提燈照到的地方才看得見。看不見的東西還是在走。",
                    (ui.s(MID), ui.s(top + 52)), "small", P.EMBER, "center")
        else:
            ui.text("WASD 移動　·　J 揮燈　·　K 防禦　·　Shift 衝刺　·　Esc 選單　·　F9 截圖",
                    (ui.s(MID), ui.s(top + 52)), "small", P.BONE_DIM, "center")


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

        s = state.stats
        rows = [
            ("揮燈擊退", f"{s.kills_by_lantern} 人", False, True),
            ("技能清場", f"{s.kills_by_spell} 人", False, s.kills_by_spell > 0),
            ("撿到糖霜", f"{s.sugar_picked} 顆", False, True),
            ("留在雪地上", f"{s.sugar_left} 顆，天亮就沒了",
             s.sugar_left > 0, s.sugar_left > 0),
            ("摸到葛蕾特", f"{s.reached_sister} 人", s.reached_sister > 0, True),
            ("你倒下", f"{s.downs} 次", s.downs > 0, s.downs > 0),
        ]
        y = 220
        for label, value, bad, shown in rows:
            if not shown:
                continue
            ui.text(label, (ui.s(MID - 190), ui.s(y)), "small", P.BONE_DIM)
            ui.text("→", (ui.s(MID - 44), ui.s(y)), "small", P.EMBER_DARK)
            ui.text(value, (ui.s(MID - 14), ui.s(y)), "small",
                    P.BLOOD if bad else P.BONE)
            y += 30

        ui.text(f"糖霜 {state.meta.sugar}　·　明天會再多一點技能點",
                (ui.s(MID), ui.s(y + 26)), "body", P.SUGAR, "center")

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
    """怪物圖鑑 / 頭目圖鑑 / 技能圖鑑."""

    PAGES = ("怪物", "頭目", "技能")
    PER_PAGE = 7

    def __init__(self, app_state) -> None:
        self.g = app_state
        self.page = 0
        self.scroll = 0

    def update(self, app: SceneStack, ui: UI, dt: float) -> None:
        ui.veil(250)
        ui.text("圖鑑", (ui.s(MID), ui.s(38)), "big", P.EMBER, "center")

        # =========================================================
        # 鍵盤控制
        #
        # W / ↑       往上捲動
        # S / ↓       往下捲動
        # A / ←       上一個圖鑑
        # D / →       下一個圖鑑
        # Enter       確認
        # Esc         返回
        # =========================================================

        if pygame.K_w in ui.keys or pygame.K_UP in ui.keys:
            self._scroll_up()

        if pygame.K_s in ui.keys or pygame.K_DOWN in ui.keys:
            self._scroll_down()

        if pygame.K_a in ui.keys or pygame.K_LEFT in ui.keys:
            self._previous_page()

        if pygame.K_d in ui.keys or pygame.K_RIGHT in ui.keys:
            self._next_page()

        if pygame.K_RETURN in ui.keys or pygame.K_KP_ENTER in ui.keys:
            self._confirm()

        if pygame.K_ESCAPE in ui.keys:
            app.pop()
            return

        # =========================================================
        # 上方圖鑑分類按鈕
        # =========================================================

        tabs = Stack.split(
            ui.box(MID - 210, 64, 420, 32),
            3,
            gap=ui.s(6)
        )

        for index, (name, cell) in enumerate(
            zip(self.PAGES, tabs)
        ):
            if ui.button(
                f"tab{index}",
                cell,
                name,
                selected=index == self.page
            ):
                self.page = index
                self.scroll = 0

        # =========================================================
        # 圖鑑內容
        # =========================================================

        rows = self._rows()

        # 防止資料變少後 scroll 超出範圍
        max_scroll = max(0, len(rows) - self.PER_PAGE)
        self.scroll = min(self.scroll, max_scroll)

        y = 120

        for title, stats, note in rows[
            self.scroll:self.scroll + self.PER_PAGE
        ]:
            ui.text(
                title,
                (ui.s(MID - 320), ui.s(y)),
                "body",
                P.BONE
            )

            ui.text(
                stats,
                (ui.s(MID - 150), ui.s(y + 2)),
                "small",
                P.BONE_DIM
            )

            if note:
                ui.text(
                    ui.truncate(
                        note,
                        ui.s(420),
                        "small"
                    ),
                    (ui.s(MID - 150), ui.s(y + 24)),
                    "small",
                    P.EMBER_DARK
                )

            y += 56

        # =========================================================
        # 捲動提示
        # =========================================================

        if len(rows) > self.PER_PAGE:
            last = min(
                len(rows),
                self.scroll + self.PER_PAGE
            )

            ui.text(
                f"W/S/↑/↓ 捲動　"
                f"A/D/←/→ 切換圖鑑　"
                f"Enter 確認　Esc 返回",
                (ui.s(MID), ui.s(552)),
                "small",
                P.MUTED,
                "center"
            )

            ui.text(
                f"{self.scroll + 1}–{last} / {len(rows)}",
                (ui.s(MID), ui.s(570)),
                "small",
                P.MUTED,
                "center"
            )
        else:
            ui.text(
                "A/D/←/→ 切換圖鑑　Enter 確認　Esc 返回",
                (ui.s(MID), ui.s(552)),
                "small",
                P.MUTED,
                "center"
            )

        # =========================================================
        # 返回按鈕
        # =========================================================

        if ui.button(
            "back",
            ui.box(MID - 90, 578, 180, 40),
            "返回"
        ):
            app.pop()

    # =============================================================
    # 鍵盤功能
    # =============================================================

    def _scroll_up(self) -> None:
        """W / ↑：往上捲動圖鑑。"""
        self.scroll = max(0, self.scroll - 1)

    def _scroll_down(self) -> None:
        """S / ↓：往下捲動圖鑑。"""
        rows = self._rows()

        max_scroll = max(
            0,
            len(rows) - self.PER_PAGE
        )

        self.scroll = min(
            max_scroll,
            self.scroll + 1
        )

    def _previous_page(self) -> None:
        """A / ←：切換到上一個圖鑑。"""
        self.page = max(0, self.page - 1)

        # 切換分類後回到第一頁
        self.scroll = 0

    def _next_page(self) -> None:
        """D / →：切換到下一個圖鑑。"""
        self.page = min(
            len(self.PAGES) - 1,
            self.page + 1
        )

        # 切換分類後回到第一頁
        self.scroll = 0

    def _confirm(self) -> None:
        """Enter：確認目前的圖鑑分類。"""

        # 目前圖鑑沒有需要 Enter 執行的項目，
        # 因此 Enter 只負責確認目前分類。
        #
        # 如果之後想讓 Enter 打開怪物詳細資料，
        # 可以在這裡加入。
        pass

    # =============================================================
    # 圖鑑資料
    # =============================================================

    def _rows(self) -> list[tuple[str, str, str]]:
        if self.page == 0:
            return [
                self._monster_row(s)
                for s in MONSTERS.values()
            ]

        if self.page == 1:
            return [
                self._boss_row(s)
                for s in BOSSES.values()
            ]

        return [
            self._skill_row(s)
            for s in SPELL_TABLE.values()
        ]

    # =============================================================
    # 機制說明
    # =============================================================

    @staticmethod
    def _mechanics(spec) -> str:
        names = list(
            getattr(spec, "traits", ())
        )

        if getattr(spec, "behaviour", "charge") != "charge":
            names.insert(
                0,
                spec.behaviour
            )

        return "　".join(
            describe_mechanic(name)
            for name in names
        )

    # =============================================================
    # 怪物
    # =============================================================

    def _monster_row(
        self,
        spec
    ) -> tuple[str, str, str]:

        weak = ELEMENTS.get(
            spec.weakness or "",
            {}
        ).get("name")

        stats = (
            f"血 {spec.hp}　"
            f"速 {spec.speed:.0f}　"
            f"糖霜 {spec.sugar}"
            + (
                "　打不退"
                if not spec.knockable
                else ""
            )
            + (
                f"　弱點 {weak}"
                if weak
                else ""
            )
        )

        return (
            spec.name,
            stats,
            self._mechanics(spec)
        )

    # =============================================================
    # 頭目
    # =============================================================

    def _boss_row(
        self,
        spec
    ) -> tuple[str, str, str]:

        weak = ELEMENTS.get(
            spec.weakness or "",
            {}
        ).get(
            "name",
            "沒有單一解答"
        )

        stats = (
            f"{spec.title}　"
            f"血 {spec.hp}　"
            f"弱點 {weak}　"
            f"{len(spec.phases)} 階段"
        )

        return (
            spec.name,
            stats,
            spec.phases[0].announce
            or self._mechanics(spec)
        )

    # =============================================================
    # 技能
    # =============================================================

    def _skill_row(
        self,
        spec
    ) -> tuple[str, str, str]:

        element = ELEMENTS.get(
            spec.element,
            {}
        ).get("name", "")

        stats = (
            f"{element}　"
            f"技能點 {spec.cost}　"
            f"冷卻 {spec.cooldown:.0f} 秒　"
            + (
                f"持續 {spec.duration:.0f} 秒"
                if spec.duration
                else "瞬間"
            )
        )

        return (
            spec.name,
            stats,
            spec.description
        )


def build_menu(app_state) -> Scene:
    return MenuScene(app_state)
