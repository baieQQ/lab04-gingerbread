"""The pygame shell: the only part that touches devices.

One frame runs in one direction::

    events + held keys -> action string
                       -> apply_action(state, action)   the model owns outcomes
                       -> Board.draw(state)             read-only
                       -> scenes draw the interface
                       -> display.flip() -> clock.tick()

The loop is ``async`` so the same file builds for the web with pygbag without
changing a rule.
"""

from __future__ import annotations

import asyncio
import json
import os
from copy import deepcopy
from pathlib import Path

import pygame

from .. import model as m
from ..view import palette as P
from ..view.assets import AssetLibrary
from ..view.audio import Audio
from ..view.board import Board
from ..view.fonts import FontBook
from ..view.ui import SceneStack, UI
from .scenes import HUD_H, RAIL_H, build_menu

#: The game is laid out at this fixed size and then scaled to whatever the
#: display is.  Every screen keeps its hand-placed coordinates, and the text
#: grows with the window instead of staying 13 pixels tall on a large monitor.
CANVAS_W = m.WIDTH
CANVAS_H = m.HEIGHT + HUD_H + RAIL_H
WINDOW_W, WINDOW_H = CANVAS_W, CANVAS_H
FPS = 60

#: How many simulation steps one frame may run before the rest is discarded.
#: Without a cap a slow frame snowballs; without *discarding* the remainder, a
#: browser tab that stalls for a second comes back and fast-forwards through the
#: night the player cannot see.
MAX_STEPS_PER_FRAME = 5

SAVE_PATH = Path.home() / ".gingerbread_save.json"


class Session:
    """Everything the scenes share: the run, the renderer, and the save file."""

    def __init__(self, book: FontBook, seed: int = 42) -> None:
        self.seed = seed
        self.book = book
        self.assets = AssetLibrary(quiet=True)
        self.board_surface = pygame.Surface((m.WIDTH, m.HEIGHT)).convert()
        self.board = Board(self.board_surface, self.book, self.assets)
        self.board.warm_up()

        #: Monsters the player has already been walked through, kept across
        #: runs.  A practice round is worth seeing once; on the fourth run it is
        #: an obstacle between the player and the game.
        self.taught: set[str] = set()
        #: Whether the walkthroughs run at all.  **On by default**, and it stays
        #: on until the player says otherwise: a first-time player never finds a
        #: setting they do not know they need, so the help has to be the thing
        #: they turn *off*, not the thing they turn on.
        self.onboarding = True
        self.saved = self._load()
        self.state = m.new_game(seed=seed)
        self.accumulator = 0.0
        self.ticks = 0
        #: Which night's opening card has already been shown, so it appears
        #: once per night and not once per frame.
        self.story_shown = 0
        #: 已經播過的夜晚過場，避免重打同一夜時又看一次三分鐘的動畫。
        self.cutscenes_played: set[str] = set()
        #: Events heard since the shell last drained them.  ``apply_action``
        #: clears ``state.events`` every tick and a frame can run five ticks, so
        #: anything that only read the newest state would hear one tick in five.
        self.heard: list[str] = []

    def rebuild_view(self) -> None:
        """Rebuild anything that baked pixels at the old scale."""
        self.board = Board(self.board_surface, self.book, self.assets)
        self.board.warm_up()

    # ── run control ──────────────────────────────────────────────────
    def start(self, mode: m.Mode) -> None:
        carried = m.Meta(mode=mode,
                         best_night=self.saved.best_night,
                         best_endless_ticks=self.saved.best_endless_ticks,
                         best_endless_kills=self.saved.best_endless_kills)
        self.state = m.new_game(seed=self.seed, meta=carried, mode=mode)
        self.accumulator = 0.0
        self.story_shown = 0

    def restart(self) -> None:
        """Wipe the run and go back to night one."""
        self.start(self.state.meta.mode)

    def retry_night(self) -> None:
        """Replay the night that was just lost, keeping everything earned.

        The whole point is that a losing run still compounds: the sugar, the
        upgrades and the skills all survive, so the same night is attempted by a
        stronger Hansel each time.  Only Gretel and the night itself are reset.
        """
        carried = deepcopy(self.state.meta)
        carried.sister_hp = carried.max_sister_hp
        self.state = m.new_game(seed=self.seed, meta=carried,
                                mode=carried.mode)
        self.accumulator = 0.0

    def to_menu(self, app: SceneStack) -> None:
        """Tear every screen down and go back to the start.

        Pops rather than replaces so a pause menu opened over a shop opened over
        a night unwinds cleanly instead of leaving a scene stranded underneath.
        """
        while app.scenes:
            app.pop()
        app.push(build_menu(self))

    def act(self, action: str) -> None:
        """Apply one non-movement action and keep the records up to date."""
        self.state = m.apply_action(self.state, action)
        self._remember()

    # ── the tick ─────────────────────────────────────────────────────
    def advance(self, dt: float, ui: UI) -> None:
        state = self.state
        if state.phase not in (m.Phase.DAY, m.Phase.NIGHT):
            return

        action = self._input_action(state)
        self.accumulator += dt
        steps = 0
        while self.accumulator >= m.FIXED_DT and steps < MAX_STEPS_PER_FRAME:
            self.accumulator -= m.FIXED_DT
            self.state = m.apply_action(self.state, action)
            self.heard.extend(self.state.events)
            self.ticks += 1
            steps += 1
            if self.state.phase not in (m.Phase.DAY, m.Phase.NIGHT):
                break

        # Drop whatever is left rather than owing it: catching up on a backlog
        # runs the night at double speed with no input, which is worse than
        # losing a fraction of a second.
        if self.accumulator > m.FIXED_DT * MAX_STEPS_PER_FRAME:
            self.accumulator = 0.0

        if self.state.phase is not state.phase:
            self._remember()

    def set_onboarding(self, on: bool) -> None:
        """Turn the walkthroughs on or off, and remember it across runs."""
        if self.onboarding != on:
            self.onboarding = on
            self._save()

    def teach(self, key: str) -> None:
        """Mark a monster as introduced, and write it down immediately.

        Saved on the spot rather than at the end of the night: a player who
        quits during the practice has still seen it, and being shown it again
        because they closed the window is the exact annoyance this guards.
        """
        if key not in self.taught:
            self.taught.add(key)
            self._save()

    def drain(self) -> list[str]:
        """Hand over everything heard since the last call, and forget it."""
        out, self.heard = self.heard, []
        return out

    def music_key(self) -> str:
        """Which track this moment wants."""
        state = self.state
        if state.phase is m.Phase.NIGHT:
            return "boss" if any(b.hp > 0 for b in state.bosses) else "night"
        if state.phase is m.Phase.DAY:
            return "day"
        return "menu"

    @staticmethod
    def _input_action(state: m.State) -> str:
        """Turn the held keys into one action string.

        Level-triggered on purpose: movement and swinging should follow whether
        a key is *down*, not whether it was pressed this frame, or holding a
        direction would move one step and stop.
        """
        if state.phase is not m.Phase.NIGHT:
            return "tick"

        keys = pygame.key.get_pressed()
        parts: list[str] = []
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            parts.append("left")
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            parts.append("right")
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            parts.append("up")
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            parts.append("down")
        # J swings, K guards — the layout from the design document.  Space is
        # kept as a second swing key because it is what every hand reaches for.
        if keys[pygame.K_j] or keys[pygame.K_SPACE]:
            parts.append("swing")
        if keys[pygame.K_k]:
            parts.append("guard")
        if keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]:
            parts.append("dash")

        # Skills are edge-triggered — holding L must not spend the whole stock
        # in one frame — so they are read from the event keys instead.
        if not parts:
            return "tick"
        return "move:" + "+".join(sorted(parts))

    #: Slot key -> which of the two carried skills it casts.
    SLOT_KEYS = ((pygame.K_l, 0), (pygame.K_SEMICOLON, 1))

    def cast_from_keys(self, keys: list[int]) -> None:
        if self.state.phase is not m.Phase.NIGHT:
            return
        for key, slot in self.SLOT_KEYS:
            if key not in keys:
                continue
            carried = self.state.meta.slots[slot]
            if carried:
                self.state = m.apply_action(self.state, f"cast:{carried}")

    # ── save file ────────────────────────────────────────────────────
    def _remember(self) -> None:
        meta = self.state.meta
        self.saved.best_night = max(self.saved.best_night, meta.best_night)
        self.saved.best_endless_ticks = max(self.saved.best_endless_ticks,
                                            meta.best_endless_ticks)
        self.saved.best_endless_kills = max(self.saved.best_endless_kills,
                                            meta.best_endless_kills)
        self._save()

    def _load(self) -> m.Meta:
        """Read the record file, treating any problem as "no records yet".

        A corrupt or old save must never stop the game from starting; the only
        thing kept across runs is a handful of best-scores.
        """
        try:
            raw = json.loads(SAVE_PATH.read_text(encoding="utf-8"))
            self.taught = {str(k) for k in raw.get("taught", [])}
            self.onboarding = bool(raw.get("onboarding", True))
            return m.Meta(
                best_night=int(raw.get("best_night", 0)),
                best_endless_ticks=int(raw.get("best_endless_ticks", 0)),
                best_endless_kills=int(raw.get("best_endless_kills", 0)),
            )
        except (OSError, ValueError, TypeError):
            return m.Meta()

    def _save(self) -> None:
        try:
            SAVE_PATH.write_text(json.dumps({
                "best_night": self.saved.best_night,
                "best_endless_ticks": self.saved.best_endless_ticks,
                "best_endless_kills": self.saved.best_endless_kills,
                "taught": sorted(self.taught),
                "onboarding": self.onboarding,
            }), encoding="utf-8")
        except OSError:
            pass                      # a read-only home directory is not fatal


class Game:
    def __init__(self, seed: int = 42, fullscreen: bool = True) -> None:
        pygame.init()
        try:
            pygame.mixer.init()
        except pygame.error:
            pass                      # no audio device: the game still runs
        pygame.display.set_caption("糖果屋之後 · After the Gingerbread House")

        self.fullscreen = fullscreen
        self.window = self._open_display()
        self.clock = pygame.time.Clock()
        self.seed = seed

        self._build_canvas()
        self.audio = Audio()
        self.session = Session(self.book, seed=seed)
        self.ui = UI(self.canvas, self.book)
        self.ui.scale = self.scale
        self.ui.view_offset = self.origin
        self.stack = SceneStack(self.ui)
        self.stack.push(build_menu(self.session))
        self.running = True

    def _build_canvas(self) -> None:
        """Carve a correctly-proportioned drawing area out of the window.

        Everything draws straight into the window through this subsurface, at
        the display's real resolution — so text is rasterised at the size it
        appears instead of being rendered small and blown up, which is what made
        the interface look soft.  Screens are still written in a 900x648 grid;
        ``ui.s()`` turns those units into device pixels.
        """
        window_w, window_h = self.window.get_size()
        self.scale = min(window_w / CANVAS_W, window_h / CANVAS_H)
        size = (int(CANVAS_W * self.scale), int(CANVAS_H * self.scale))
        self.origin = ((window_w - size[0]) // 2, (window_h - size[1]) // 2)
        self.canvas = self.window.subsurface(pygame.Rect(self.origin, size))
        self.book = FontBook(scale=self.scale)

    def _open_display(self) -> pygame.Surface:
        surface = self._request_display()
        # A display smaller than the layout cannot be letterboxed into — every
        # ``ui.s()`` collapses to zero and the game draws into nothing.  Seen
        # for real under WebAssembly, where a fullscreen request returns 1x1.
        if surface.get_width() < 8 or surface.get_height() < 8:
            self.fullscreen = False
            surface = pygame.display.set_mode((CANVAS_W, CANVAS_H))
        return surface

    def _request_display(self) -> pygame.Surface:
        if self.fullscreen:
            # No ``SCALED``: this class does its own letterboxed scaling, and
            # letting pygame scale as well would apply the transform twice —
            # the cursor would land nowhere near the button under it.
            return pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        return pygame.display.set_mode((CANVAS_W, CANVAS_H), pygame.RESIZABLE)

    def toggle_fullscreen(self) -> None:
        self.fullscreen = not self.fullscreen
        self.window = self._open_display()
        self._build_canvas()
        # Fonts are sized for the old scale; rebuild everything that holds one.
        self.session.book = self.book
        self.session.rebuild_view()
        self.ui = UI(self.canvas, self.book)
        self.ui.scale = self.scale
        self.ui.view_offset = self.origin
        self.stack.ui = self.ui
        # The one full clear that is still right: the window has just been
        # rebuilt, the bars have moved, and no scene has painted yet.
        self.window.fill(P.VOID)

    async def run(self) -> None:
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0

            # Drained exactly once.  Two drains anywhere in a frame means
            # whichever runs second sees an empty queue, and half the game
            # silently stops responding.
            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_F11:
                        self.toggle_fullscreen()
                    elif event.key == pygame.K_m:
                        muted = self.audio.toggle_mute()
                        print(f"[gingerbread] {'靜音' if muted else '開聲音'}")
                    elif event.key == pygame.K_F9:
                        self._screenshot()
                    elif event.key == pygame.K_F10:
                        # Test switch.  F10 rather than a letter so it cannot be
                        # hit while playing, and it goes through the model so
                        # the HUD and the snapshot both know it is on.
                        self.session.state = m.apply_action(
                            self.session.state, "godmode")
                    elif event.key == pygame.K_ESCAPE:
                        # Escape opens the pause menu rather than quitting.
                        # Quitting on the key that every player presses to see
                        # their options is a way to lose a run by accident.
                        #
                        # 除非最上面那個場景自己要用 Esc。過場動畫的畫面上就
                        # 寫著「Esc 跳過」，而這裡搶先開了暫停選單 —— 玩家照
                        # 著畫面上的字按，得到的是另一件事。
                        top = self.stack.top
                        if getattr(top, "wants_escape", False):
                            pass          # 交給場景自己處理
                        else:
                            self._toggle_pause()

            self._clear_bars()
            self.stack.frame(dt, events)
            self.session.cast_from_keys(self.ui.keys)
            self.audio.consume(self.session.drain())
            self.audio.music(self.session.music_key())
            pygame.display.flip()
            await asyncio.sleep(0)          # required for the web build
        pygame.quit()

    def _screenshot(self) -> None:
        """Save what is on screen right now, for reporting what a frame did.

        A bug that shows up for one frame cannot be described in words, and it
        cannot be caught by a headless replay either — the frame has to be
        photographed while it is happening.
        """
        folder = Path.home() / "Desktop"
        n = 1
        while (folder / f"糖果屋截圖-{n:02d}.png").exists():
            n += 1
        path = folder / f"糖果屋截圖-{n:02d}.png"
        pygame.image.save(self.window, str(path))
        print(f"[gingerbread] screenshot saved to {path}")

    def _clear_bars(self) -> None:
        """Repaint only the letterbox, never the playfield.

        The loop used to fill the *whole* window before drawing.  That put one
        moment in every frame where the entire window — playfield, HUD, hint
        strip — was a single flat colour, and on a software window with no
        vsync the compositor can present exactly that moment: a full-screen
        black flash lasting one frame, HUD included, with nothing wrong in the
        simulation behind it.  Every frame of this game repaints the whole
        canvas anyway (board blit, HUD plate, rail plate), so clearing it first
        bought nothing and cost that flash.

        The bars outside the canvas are the only pixels no scene owns, and they
        never change, so painting them is nearly free.
        """
        window_w, window_h = self.window.get_size()
        left, top = self.origin
        width, height = self.canvas.get_size()
        for bar in (pygame.Rect(0, 0, left, window_h),
                    pygame.Rect(left + width, 0, window_w - left - width, window_h),
                    pygame.Rect(left, 0, width, top),
                    pygame.Rect(left, top + height, width, window_h - top - height)):
            if bar.width > 0 and bar.height > 0:
                self.window.fill(P.VOID, bar)

    def _toggle_pause(self) -> None:
        from .scenes import PauseScene, PracticeScene, TutorialScene

        # Escape belongs to whatever is teaching, if anything is.  Opening a
        # pause menu over a walkthrough would make the one key that obviously
        # means "I have seen enough" do something else instead.
        if isinstance(self.stack.top, (TutorialScene, PracticeScene)):
            self.session.set_onboarding(False)
            self.stack.pop()
            return
        if isinstance(self.stack.top, PauseScene):
            self.stack.pop()
        else:
            self.stack.push(PauseScene(self.session, self))


# ── headless evidence ────────────────────────────────────────────────
def check(seed: int = 42, nights: int = 2) -> dict[str, object]:
    """Play a scripted run with no display and return comparable evidence.

    Deliberately longer and busier than a few seconds of standing still: an
    "evidence" run with no kills, no drops and one random draw proves almost
    nothing about determinism.
    """
    import math

    state = m.new_game(seed=seed)
    for _ in range(nights):
        for action in ("whet", "oil", "whet", "oil"):
            state = m.apply_action(state, action)
        state = m.apply_action(state, "begin_night")

        while state.phase is m.Phase.NIGHT:
            live = [x for x in list(state.monsters) + list(state.bosses)
                    if x.active]
            if not live:
                state = m.apply_action(state, "tick")
                continue
            target = min(live, key=lambda x: math.hypot(x.x - m.SISTER_X,
                                                        x.y - m.SISTER_Y))
            parts = []
            if target.x > state.player.x + 6:
                parts.append("right")
            elif target.x < state.player.x - 6:
                parts.append("left")
            if target.y > state.player.y + 6:
                parts.append("down")
            elif target.y < state.player.y - 6:
                parts.append("up")
            parts.append("swing")
            state = m.apply_action(state, "move:" + "+".join(sorted(parts)))

        if state.phase is not m.Phase.SHOP:
            break
        state = m.apply_action(state, "next_night")

    return m.snapshot(state)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="gingerbread")
    parser.add_argument("--check", action="store_true",
                        help="run one deterministic headless check and print JSON")
    parser.add_argument("--content", action="store_true",
                        help="list every registered behaviour, trait, spell and event")
    parser.add_argument("--assets", action="store_true",
                        help="report which art and audio files are still missing")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--windowed", action="store_true",
                        help="start in a window instead of full screen")
    args = parser.parse_args(argv)

    # Keep stdout clean: the pygame banner would otherwise be part of the
    # evidence, and upgrading pygame would fail a byte-for-byte comparison for
    # a reason that has nothing to do with the game.
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

    if args.content:
        from ..model.registry import vocabulary
        print(vocabulary())
        return 0

    if args.check:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        print(json.dumps(check(seed=args.seed), ensure_ascii=False,
                         sort_keys=True))
        return 0

    if args.assets:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((8, 8))
        session = Session(FontBook(), seed=args.seed)
        session.board.draw(session.state, 0)
        for key in session.assets.missing_report():
            print(key)
        print(session.assets.summary())
        return 0

    asyncio.run(Game(seed=args.seed, fullscreen=not args.windowed).run())
    return 0
