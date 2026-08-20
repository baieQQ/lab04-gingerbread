"""Immediate-mode interface toolkit — every screen in the game, ~280 lines.

One pass per frame does layout, drawing and hit-testing together, so a new
screen costs one method, not a class tree::

    class Menu(Scene):
        def update(self, app, ui, dt):
            ui.veil()
            col = Stack(pygame.Rect(330, 210, 240, 130), gap=12)
            if ui.button("story", col.slot(52), "七夜", "撐過七個夜晚"):
                app.replace(Play(mode="story"))
            if ui.button("endless", col.slot(52), "無盡", "打到倒下為止"):
                app.replace(Play(mode="endless"))

Three caches keep that free of the usual pygame traps.  Text goes through
:class:`~gingerbread.view.fonts.FontBook` (already cached).  Panels — every
translucent plate, border and veil — are cached by (size, colours, radius), so
a steady screen allocates **zero** Surfaces per frame.  Wrapping is memoised
because ``FontBook.wrap`` costs ~386 µs for one paragraph and screens re-wrap
the same unchanged strings sixty times a second.

Nothing here imports the model.  This layer paints and reports clicks; the
caller turns a click into an action string.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import pygame

from . import palette as P
from .fonts import FontBook

RGBA = tuple[int, ...]


@dataclass
class Theme:
    """Every colour and metric a screen uses, in one restylable place."""

    fg: RGBA = P.BONE
    fg_dim: RGBA = P.BONE_DIM
    fg_label: RGBA = P.MUTED
    fg_off: RGBA = P.DISABLED
    accent: RGBA = P.EMBER
    on_accent: RGBA = (20, 13, 2)          # text drawn on top of accent
    plate: RGBA = P.with_alpha(P.PANEL, 214)
    plate_hi: RGBA = P.with_alpha(P.PANEL_HI, 238)
    plate_on: RGBA = P.with_alpha(P.EMBER_DARK, 238)
    border: RGBA = P.LINE
    border_hi: RGBA = P.EMBER_DARK
    veil: RGBA = P.with_alpha(P.VOID, 242)
    pad: int = 10
    gap: int = 6
    row_h: int = 32
    body: str = "body"                     # FontBook size names, not numbers
    small: str = "small"
    title: str = "big"


def _atoms(text: str):
    """Atomic wrap units: one per CJK glyph, one per unbroken ASCII run.

    Chinese has no spaces, so a Latin word-wrapper drops a 40-character line
    onto one row and overflows the panel — hence per-character breaking.  But
    pure per-character breaking also shreds ``WASD``, ``2:00`` and ``+15%``
    across two lines, so an ASCII run stays glued together.
    """
    buf = ""
    for ch in text:
        if ch.isascii() and not ch.isspace():
            buf += ch
            continue
        if buf:
            yield buf
            buf = ""
        yield ch
    if buf:
        yield buf


class UI:
    """Drawing plus hit-testing against one target Surface."""

    CAP = 512                              # per-cache entry ceiling

    def __init__(self, surface: pygame.Surface, book: FontBook,
                 theme: Theme | None = None) -> None:
        self.surface = surface
        self.book = book
        self.theme = theme or Theme()
        self._plates: dict[tuple, pygame.Surface] = {}
        self._metrics: dict[tuple, tuple[int, int]] = {}
        self._wraps: dict[tuple, list[str]] = {}
        self._cuts: dict[tuple, str] = {}
        self.mouse = (-1, -1)
        self.events: list[pygame.event.Event] = []
        #: Maps a window coordinate onto this surface.  The game renders to a
        #: fixed logical canvas and scales it to whatever the display is, so
        #: every incoming pointer position has to come back through the same
        #: transform or the buttons sit somewhere the cursor is not.
        self.view_offset = (0, 0)
        self.view_scale = 1.0
        #: Layout scale.  Screens are written in a 900x648 grid and multiplied
        #: by this, so one set of coordinates serves every display size while
        #: the text is still rasterised at its final size.
        self.scale = 1.0
        self.moved = False
        self.held = False                  # left button currently down
        self.down: tuple[int, int] | None = None
        self.up: tuple[int, int] | None = None
        self.keys: list[int] = []          # KEYDOWNs this frame, for scenes
        self.focus = 0                     # keyboard cursor into the widget list
        self.activate = False              # Enter/Space waiting to be consumed
        self.inert = False                 # True while drawing a covered scene
        #: Arrows and Space are *gameplay* keys at night — they move Hansel and
        #: swing the lantern.  A scene that owns the keyboard sets this False so
        #: the same press does not also walk the focus ring.  It persists across
        #: frames, so set it once when the phase changes, not every frame.
        self.keyboard = True
        self._nav = 0
        self._active: str | None = None

    # ── frame boundaries ─────────────────────────────────────────────
    def s(self, value: float) -> int:
        """Convert a layout unit into device pixels."""
        return int(round(value * self.scale))

    def box(self, x: float, y: float, w: float, h: float) -> pygame.Rect:
        """A rect given in layout units."""
        return pygame.Rect(self.s(x), self.s(y), self.s(w), self.s(h))

    def to_canvas(self, pos: tuple[int, int]) -> tuple[int, int]:
        """Translate a window position into canvas coordinates."""
        ox, oy = self.view_offset
        scale = self.view_scale or 1.0
        return (int((pos[0] - ox) / scale), int((pos[1] - oy) / scale))

    def begin(self, events: Iterable[pygame.event.Event]) -> None:
        pos = self.to_canvas(pygame.mouse.get_pos())
        self.moved, self.mouse = pos != self.mouse, pos
        self.down = self.up = None
        self.activate = False
        self.keys = []
        # 這一幀的原始事件，給需要自己解讀輸入的場景用 —— 過場動畫是組員寫
        # 的，它有自己的 handle_event，餵它 pygame 事件比把它的輸入邏輯拆開
        # 重寫誠實得多。
        self.events = list(events)
        self._nav = 0
        for e in self.events:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                self.down, self.held = self.to_canvas(e.pos), True
            elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
                self.up, self.held = self.to_canvas(e.pos), False
            elif e.type == pygame.KEYDOWN:
                self.keys.append(e.key)     # scenes always see the raw key
                if not self.keyboard:
                    continue
                if e.key in (pygame.K_DOWN, pygame.K_RIGHT):
                    self.focus += 1
                elif e.key in (pygame.K_UP, pygame.K_LEFT):
                    self.focus -= 1
                elif e.key == pygame.K_TAB:
                    self.focus += -1 if e.mod & pygame.KMOD_SHIFT else 1
                elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                    self.activate = True

    def end(self) -> None:
        self.focus = self.focus % self._nav if self._nav else 0
        if self.up is not None:
            self._active = None

    def reset_focus(self) -> None:
        self.focus, self._active = 0, None

    # ── text ─────────────────────────────────────────────────────────
    def measure(self, text: str, size: str | None = None) -> tuple[int, int]:
        key = (text, size or self.theme.body)
        hit = self._metrics.get(key)
        if hit is None:
            if len(self._metrics) > self.CAP * 4:
                self._metrics.clear()
            hit = self._metrics[key] = self.book.measure(*key)
        return hit

    def wrap(self, text: str, width: int, size: str | None = None) -> list[str]:
        """Memoised, ASCII-aware wrap.  See :func:`_atoms`."""
        key = (text, size or self.theme.body, width)
        hit = self._wraps.get(key)
        if hit is not None:
            return hit
        if len(self._wraps) > self.CAP:
            self._wraps.clear()
        lines: list[str] = []
        for para in text.split("\n"):
            cur = ""
            for atom in _atoms(para):
                if cur and self.measure(cur + atom, key[1])[0] > width:
                    lines.append(cur)
                    cur = "" if atom == " " else atom
                else:
                    cur += atom
            lines.append(cur)
        self._wraps[key] = lines
        return lines

    def truncate(self, text: str, width: int, size: str | None = None) -> str:
        key = (text, size or self.theme.body, width)
        hit = self._cuts.get(key)
        if hit is None:
            if len(self._cuts) > self.CAP:
                self._cuts.clear()
            hit = self._cuts[key] = self.book.truncate(text, key[1], width)
        return hit

    def text(self, s: str, pos: tuple[int, int], size: str | None = None,
             colour: RGBA | None = None, align: str = "left",
             width: int | None = None) -> pygame.Rect:
        """Draw one line.  ``pos`` is the anchor and is always vertically centred."""
        size = size or self.theme.body
        if not s or not s.strip():
            return pygame.Rect(pos, (0, self.book.line_height(size)))
        if width is not None:
            s = self.truncate(s, width, size)
        surf = self.book.render(s, size, colour or self.theme.fg)
        rect = surf.get_rect()
        setattr(rect, {"left": "midleft", "center": "center",
                       "right": "midright"}[align], pos)
        self.surface.blit(surf, rect)
        return rect

    def paragraph(self, s: str, rect: pygame.Rect, size: str | None = None,
                  colour: RGBA | None = None, align: str = "left",
                  line_h: int | None = None) -> int:
        """Wrap into ``rect.width``; returns the height actually used."""
        size = size or self.theme.body
        line_h = line_h or self.book.line_height(size)
        x = {"left": rect.left, "center": rect.centerx, "right": rect.right}[align]
        y = rect.top + line_h // 2
        for line in self.wrap(s, rect.width, size):
            self.text(line, (x, y), size, colour, align)
            y += line_h
        return y - line_h // 2 - rect.top

    def label_value(self, rect: pygame.Rect, label: str, value: str,
                    size: str | None = None, label_colour: RGBA | None = None,
                    value_colour: RGBA | None = None) -> None:
        """``label ....... value`` — the HUD, shop and result-ledger workhorse."""
        value = str(value)
        vw = self.measure(value, size)[0]
        self.text(label, (rect.left, rect.centery), size,
                  label_colour or self.theme.fg_label, "left",
                  width=max(8, rect.width - vw - self.theme.gap * 2))
        self.text(value, (rect.right, rect.centery), size,
                  value_colour or self.theme.fg, "right")

    # ── plates ───────────────────────────────────────────────────────
    def panel(self, rect: pygame.Rect, fill: RGBA | None = None,
              border: RGBA | None = None, width: int = 1, radius: int = 0) -> None:
        fill = self.theme.plate if fill is None else fill
        border = self.theme.border if border is None else border
        key = (rect.width, rect.height, fill, border, width, radius)
        surf = self._plates.get(key)
        if surf is None:
            if len(self._plates) > self.CAP:
                self._plates.clear()
            surf = pygame.Surface(rect.size, pygame.SRCALPHA)
            if fill:
                pygame.draw.rect(surf, fill, surf.get_rect(), 0, radius)
            if border and width:
                pygame.draw.rect(surf, border, surf.get_rect(), width, radius)
            self._plates[key] = surf
        self.surface.blit(surf, rect.topleft)

    def veil(self, alpha: int | None = None) -> None:
        c = self.theme.veil
        self.panel(self.surface.get_rect(),
                   c if alpha is None else P.with_alpha(c[:3], alpha), None, 0)

    def dots(self, pos: tuple[int, int], total: int, filled: int, radius: int = 5,
             gap: int = 15, on: RGBA | None = None, off: RGBA | None = None) -> int:
        """Hearts, action points, chapter pips — one primitive, three uses."""
        on = on or self.theme.accent
        off = off or self.theme.border
        for i in range(total):
            centre = (pos[0] + radius + i * gap, pos[1])
            if i < filled:
                pygame.draw.circle(self.surface, on, centre, radius)
            else:
                pygame.draw.circle(self.surface, off, centre, radius, 1)
        return total * gap

    def bar(self, rect: pygame.Rect, frac: float, fill: RGBA | None = None) -> None:
        """Timers, health, cooldowns.  Drawn, not blitted — no allocation."""
        pygame.draw.rect(self.surface, self.theme.border, rect)
        w = int(rect.width * max(0.0, min(1.0, frac)))
        if w:
            pygame.draw.rect(self.surface, fill or self.theme.accent,
                             pygame.Rect(rect.x, rect.y, w, rect.height))

    # ── the one interactive widget ───────────────────────────────────
    def button(self, key: str, rect: pygame.Rect, label: str, sub: str | None = None,
               enabled: bool = True, selected: bool = False,
               size: str | None = None, fill: RGBA | None = None) -> bool:
        """True on the frame it is clicked, or Enter'd while keyboard-focused.

        Disabled buttons are skipped by keyboard navigation entirely, so a shop
        where six of nine rows are unaffordable tabs through three rows.
        """
        t = self.theme
        live = enabled and not self.inert
        hot = live and rect.collidepoint(self.mouse)
        slot = -1
        if live:
            slot, self._nav = self._nav, self._nav + 1
            if hot and (self.moved or self.down):
                self.focus = slot          # mouse and keyboard share one cursor
        focused = live and self.keyboard and slot == self.focus
        if hot and self.down:
            self._active = key
        pressed = hot and self.held and self._active == key
        clicked = bool(hot and self.up is not None and self._active == key)
        if focused and self.activate:
            clicked, self.activate = True, False

        if not enabled:
            bg, fg, bd = t.plate, t.fg_off, t.border
        elif pressed or selected:
            bg, fg, bd = t.plate_on, t.on_accent, t.accent
        elif hot or focused:
            bg, fg, bd = t.plate_hi, t.fg, t.accent
        else:
            bg, fg, bd = (fill or t.plate), t.fg, t.border
        self.panel(rect, bg, bd, self.s(2) if focused else max(1, self.s(1)))
        pad = self.s(t.pad)
        inner = rect.width - pad * 2
        if sub:
            # Both offsets and the padding scale with the display.  They used to
            # be fixed pixel counts while the fonts scaled, so on any screen
            # larger than the layout grid the two lines grew into each other and
            # every button looked cramped.
            gap = max(self.book.line_height(size or t.body),
                      self.book.line_height(t.small)) // 2
            self.text(label, (rect.left + pad, rect.centery - gap + self.s(1)),
                      size, fg, "left", width=inner)
            self.text(sub, (rect.left + pad, rect.centery + gap - self.s(1)),
                      t.small,
                      t.on_accent if (pressed or selected) else
                      (t.fg_off if not enabled else t.fg_dim), "left", width=inner)
        else:
            self.text(label, rect.center, size, fg, "center", width=inner)
        return clicked


class Stack:
    """A cursor that hands out rows (or columns) inside a rect.

    A 3-item shop and a 9-item shop are the same caller code: build the Stack,
    loop, call :meth:`slot`.  Use :meth:`height` to size the plate first.
    """

    def __init__(self, rect: pygame.Rect, pad: int = 0, gap: int = 6,
                 horizontal: bool = False) -> None:
        self.rect = pygame.Rect(rect)
        self.inner = self.rect.inflate(-2 * pad, -2 * pad)
        self.gap, self.h = gap, horizontal
        self.cursor = self.inner.left if horizontal else self.inner.top

    def slot(self, size: int, span: int | None = None) -> pygame.Rect:
        if self.h:
            r = pygame.Rect(self.cursor, self.inner.top, size, span or self.inner.height)
        else:
            r = pygame.Rect(self.inner.left, self.cursor, span or self.inner.width, size)
        self.cursor += size + self.gap
        return r

    def skip(self, size: int) -> None:
        self.cursor += size

    def rest(self) -> pygame.Rect:
        if self.h:
            return pygame.Rect(self.cursor, self.inner.top,
                               max(0, self.inner.right - self.cursor), self.inner.height)
        return pygame.Rect(self.inner.left, self.cursor, self.inner.width,
                           max(0, self.inner.bottom - self.cursor))

    @staticmethod
    def height(n: int, item: int, gap: int = 6, pad: int = 0) -> int:
        """Size a plate to fit n rows *before* placing it."""
        return n * item + max(0, n - 1) * gap + 2 * pad

    @staticmethod
    def split(rect: pygame.Rect, n: int, gap: int = 6,
              horizontal: bool = True) -> list[pygame.Rect]:
        """n equal cells — the 4-card action rail, the 2-slot spell bar."""
        rect = pygame.Rect(rect)
        if horizontal:
            w = (rect.width - gap * (n - 1)) / n
            return [pygame.Rect(round(rect.x + i * (w + gap)), rect.y,
                                round(w), rect.height) for i in range(n)]
        h = (rect.height - gap * (n - 1)) / n
        return [pygame.Rect(rect.x, round(rect.y + i * (h + gap)),
                            rect.width, round(h)) for i in range(n)]


class Scene:
    """Draw and handle input in one pass.  ``opaque = False`` makes an overlay."""

    opaque = True
    #: True for scenes that use Escape themselves.  The shell opens the pause
    #: menu on Escape before the stack ever sees the key, so a scene that wants
    #: to mean something else by it has to say so — otherwise the on-screen
    #: hint says "Esc 跳過" and pressing Esc opens a menu instead.
    wants_escape = False

    def enter(self, app: "SceneStack") -> None: ...
    def exit(self, app: "SceneStack") -> None: ...
    def update(self, app: "SceneStack", ui: UI, dt: float) -> None: ...


class SceneStack:
    """menu → prologue → play → result, with push/pop.

    Only the top scene sees input — ``ui.inert`` gates every hit-test — so a
    result ledger can sit over a still-drawn battlefield without the action
    rail underneath stealing the click.
    """

    def __init__(self, ui: UI) -> None:
        self.ui = ui
        self.scenes: list[Scene] = []

    @property
    def top(self) -> Scene | None:
        return self.scenes[-1] if self.scenes else None

    def push(self, scene: Scene) -> None:
        self.scenes.append(scene)
        self.ui.reset_focus()
        scene.enter(self)

    def pop(self) -> None:
        if self.scenes:
            self.scenes.pop().exit(self)
            self.ui.reset_focus()

    def replace(self, scene: Scene) -> None:
        self.pop()
        self.push(scene)

    def frame(self, dt: float, events: Sequence[pygame.event.Event]) -> None:
        ui = self.ui
        ui.begin(events)
        base = len(self.scenes) - 1
        while base > 0 and not self.scenes[base].opaque:
            base -= 1                      # find the last full-cover scene
        for scene in self.scenes[base:]:
            ui.inert = scene is not self.scenes[-1]
            scene.update(self, ui, dt)
        ui.inert = False
        ui.end()
