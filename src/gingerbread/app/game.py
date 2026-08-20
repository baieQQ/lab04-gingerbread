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
from .scenes import (FUN_MODES, HUD_H, NAME_LIMIT, RAIL_H,
                     ProfileScene, build_menu)

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

#: 一個檔案裝所有人的存檔，鍵是暱稱。
#:
#: 分成很多個檔案的話，「有哪些存檔」這個問題就得靠掃資料夾回答，而資料夾裡
#: 會有別人放的東西。一個 JSON 由這支程式全權負責，讀壞了就當作沒有存檔。
PROFILES_PATH = Path.home() / ".gingerbread_profiles.json"


def _merge_max(saved: list, run: list) -> list:
    """逐格取大值，長度取長的那一邊。"""
    out = list(saved)
    while len(out) < len(run):
        out.append(0)
    for i, value in enumerate(run):
        out[i] = max(out[i], int(value))
    return out


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
        #: 目前的存檔名稱；空字串代表還沒選（走舊的單一存檔）。
        self.profile = ""
        #: 三個娛樂開關，見 ``scenes.FUN_MODES``。跟著存檔走而不是跟著一局走
        #: —— 「特殊存檔才有的狀況」是玩家選存檔時就決定好的事，不是打到一半
        #: 開的外掛。
        self.fun = {key: False for key, _name, _note in FUN_MODES}
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
                         best_endless_kills=self.saved.best_endless_kills,
                         # 難度以前掉在這裡：選了簡單再按七夜，開出來的是一
                         # 般。難度是存檔的屬性，新的一局要帶著它走。
                         difficulty=self.saved.difficulty)
        # 星等與次數是「整輪」的紀錄，不是「這一局」的 —— 帶進去讓它繼續累
        # 積，成績單上第三夜打了七次才是七次，不是重開之後又變成一次。
        carried.night_stars = list(self.saved.night_stars)
        carried.night_tries = list(self.saved.night_tries)
        for key, on in self.fun.items():
            setattr(carried, key, on)
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

    def set_difficulty(self, key: str) -> None:
        """記住難度，並套用到還沒開始的這一局。"""
        self.saved.difficulty = key
        self.state.meta.difficulty = key
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
        # 星等與挑戰次數以前只活在這一局的 meta 裡，從來沒有回到存檔 ——
        # 七夜地圖上的星星和成績單讀的都是 self.saved，所以兩邊永遠是零。
        # 逐格取大值而不是直接覆蓋：「從頭開始」會把這一局的紀錄清成零，那不
        # 該把已經拿到的成績一起清掉。
        self.saved.night_stars = _merge_max(self.saved.night_stars,
                                            meta.night_stars)
        self.saved.night_tries = _merge_max(self.saved.night_tries,
                                            meta.night_tries)
        self._save()

    # ── 存檔（以暱稱為單位）────────────────────────────────────────
    def profiles(self) -> dict:
        """所有存檔，讀壞了就當作沒有。"""
        try:
            raw = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def profile_names(self) -> list:
        """存檔名稱，最近玩過的排前面。"""
        rows = self.profiles()
        return sorted(rows, key=lambda k: -int(rows[k].get("stamp", 0)))

    def load_profile(self, name: str) -> None:
        """切換到某個存檔；沒有這個名字就開一個新的。"""
        self.profile = name[:NAME_LIMIT]
        row = self.profiles().get(self.profile, {})
        self.taught = {str(k) for k in row.get("taught", [])}
        self.onboarding = bool(row.get("onboarding", True))
        stars = [int(v) for v in row.get("night_stars", [])]
        while len(stars) <= m.constants.CAMPAIGN_NIGHTS:
            stars.append(0)
        self.saved = m.Meta(
            best_night=int(row.get("best_night", 0)),
            best_endless_ticks=int(row.get("best_endless_ticks", 0)),
            best_endless_kills=int(row.get("best_endless_kills", 0)),
            difficulty=str(row.get("difficulty", m.constants.DEFAULT_DIFFICULTY)),
        )
        self.saved.night_stars = stars
        tries = [int(v) for v in row.get("night_tries", [])]
        while len(tries) <= m.constants.CAMPAIGN_NIGHTS:
            tries.append(0)
        self.saved.night_tries = tries
        fun = row.get("fun", {})
        self.fun = {key: bool(fun.get(key, False))
                    for key, _name, _note in FUN_MODES}
        # 換存檔就換一局。留著上一個人打到一半的場地，等於把別人的進度接到
        # 這個名字底下。
        self.start(m.Mode.CAMPAIGN)
        self.story_shown = 0
        self.cutscenes_played.clear()
        self._save_profile()

    def set_fun(self, key: str, on: bool) -> None:
        """開關一個娛樂模式，並且立刻套用到手上這一局。"""
        if key not in self.fun:
            return
        self.fun[key] = bool(on)
        if getattr(self.state.meta, key) != bool(on):
            # 走 model 的動作而不是直接改欄位，這樣快照看得到，而且 freecast
            # 打開的時候還在等的冷卻也會一起放掉。
            self.state = m.apply_action(self.state, key)
        self._save_profile()

    def delete_profile(self, name: str) -> None:
        rows = self.profiles()
        rows.pop(name, None)
        self._write_profiles(rows)

    def _save_profile(self) -> None:
        if not getattr(self, "profile", ""):
            return
        rows = self.profiles()
        rows[self.profile] = {
            "best_night": self.saved.best_night,
            "best_endless_ticks": self.saved.best_endless_ticks,
            "best_endless_kills": self.saved.best_endless_kills,
            "night_stars": list(self.saved.night_stars),
            "night_tries": list(self.saved.night_tries),
            "difficulty": self.saved.difficulty,
            "fun": dict(self.fun),
            "taught": sorted(self.taught),
            "onboarding": self.onboarding,
            # 排序用的時間戳。用 tick 計數而不是時鐘，因為 model 那邊禁止讀
            # 系統時間，而這裡沿用同一個習慣比較不會有人搞混。
            "stamp": int(rows.get(self.profile, {}).get("stamp", 0)) + 1,
        }
        self._write_profiles(rows)

    def _write_profiles(self, rows: dict) -> None:
        try:
            PROFILES_PATH.write_text(
                json.dumps(rows, ensure_ascii=False, indent=1),
                encoding="utf-8")
        except OSError:
            pass                      # a read-only home directory is not fatal

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
        self._save_profile()
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
        # 第一個畫面是「誰在玩」，不是主選單。名字要先有，這一輪的教學進度、
        # 星等和挑戰次數才有地方記。
        self.stack.push(ProfileScene(self.session, first=True))
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
                    elif event.key == pygame.K_F7:
                        # 跳關。第四夜以後的怪不該每次都要從第一夜打一小時
                        # 才看得到。
                        self.session.state = m.apply_action(
                            self.session.state, "skipnight")
                        self.session.story_shown = 0
                    elif event.key == pygame.K_F8:
                        # 開圖。跟 F10 一樣是給我們自己測試用的。
                        self.session.state = m.apply_action(
                            self.session.state, "seeall")
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
            try:
                self.stack.frame(dt, events)
                self.session.cast_from_keys(self.ui.keys)
                self.audio.consume(self.session.drain())
                self.audio.music(self.session.music_key())
            except Exception:                          # noqa: BLE001
                # 一格畫壞了不該讓整個遊戲消失。
                #
                # 未捕捉的例外會讓視窗直接關掉 —— 玩家看到的是「遊戲當了」，
                # 而我們拿到的是「沒有任何線索」。擺攤的時候更糟：下一個人
                # 走過來，畫面是空的。
                #
                # 印出完整 traceback（開發的人看得到），畫面上留一行給玩家，
                # 然後繼續跑。真的每一幀都壞，起碼壞得看得見。
                self._crash()
            self._draw_crash()
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

    #: 最近一次當掉的摘要，畫在畫面上讓人抄下來。
    _last_crash: str = ""
    _crash_count: int = 0

    def _crash(self) -> None:
        """記下這一格的例外，印出來，然後讓遊戲繼續跑。"""
        import traceback

        self._crash_count += 1
        lines = traceback.format_exc().strip().split("\n")
        self._last_crash = lines[-1][:96] if lines else "unknown"
        # 前三次印完整的；再多就只印一行，否則一個每幀都炸的錯誤會把終端機
        # 洗到看不見最早的那一次 —— 而最早的那一次才是原因。
        if self._crash_count <= 3:
            traceback.print_exc()
        else:
            print(f"[gingerbread] 又當了一次（第 {self._crash_count} 次）："
                  f"{self._last_crash}")

    def _draw_crash(self) -> None:
        """把最近一次的錯誤畫在畫面最上面。"""
        if not self._last_crash:
            return
        book = self.book
        text = f"當掉了（{self._crash_count}）：{self._last_crash}"
        try:
            label = book.render(text, "small", (255, 120, 120))
        except Exception:                              # noqa: BLE001
            return
        strip = pygame.Surface((self.canvas.get_width(),
                                label.get_height() + 8))
        strip.fill((40, 8, 12))
        self.canvas.blit(strip, (0, 0))
        self.canvas.blit(label, (6, 4))

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
