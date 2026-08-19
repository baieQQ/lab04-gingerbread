"""Font discovery and cached text rendering.

Two problems are solved here, both of which have already cost this project a
debugging session:

1. **Finding a font that can actually draw Chinese.**  A font file can exist
   and load without error yet still paint nothing for a CJK glyph — wrong
   subset, wrong font, or a corrupt table.  SDL_ttf reports no error; the text
   just comes out blank.  So every candidate is *verified* by rendering a glyph
   and inspecting the result before it is trusted.

2. **Not re-rasterising text that never changed.**  ``Font.render`` is one of
   the most expensive calls in a pygame frame.  Almost all of this game's text
   is static ("糖霜", "第 3 夜", a shop item name), so it is cached by
   (text, size, colour) and the cache is reused across frames.
"""

from __future__ import annotations

import os
from typing import Final

import pygame

from .palette import RGB

#: Searched in order.  The bundled subset comes first because the web build has
#: no system fonts at all — see ``build_web.py``.
_CANDIDATES: Final = (
    "assets/GameCJK-Subset.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "C:/Windows/Fonts/msjh.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
)

#: One character that must render, and one that must render for the check to
#: mean anything.  Both appear in the game, so a subset built for this game
#: will contain them.
_PROBE: Final = "糖"


def _search_roots(explicit: str | None) -> list[str]:
    """Directories that might contain ``assets/``.

    The package sits at ``src/gingerbread/view/fonts.py`` in the repo but at a
    flattened ``gingerbread/view/fonts.py`` inside the pygbag web build.
    Walking upward and trying every level — rather than hard-coding a count of
    ``dirname`` calls — keeps discovery working under both layouts.  A previous
    version hard-coded three levels and broke silently when the layout changed.
    """
    if explicit:
        return [explicit]
    roots = [os.getcwd()]
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        roots.append(here)
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return roots


def _paints_ink(font: pygame.font.Font) -> bool:
    """Return True only if this font actually puts pixels down for ``_PROBE``.

    The **alpha** channel is what must be inspected.  Anti-aliased pygame text
    is rendered in the requested colour at varying opacity, so every pixel of
    an RGB channel can read 255 even where nothing was drawn — testing colour
    instead of alpha reports "fine" for a completely blank glyph.  That exact
    mistake once led this project to rebuild a perfectly good font file.
    """
    try:
        surface = font.render(_PROBE, True, (255, 255, 255))
    except pygame.error:
        return False
    width, height = surface.get_size()
    if width == 0 or height == 0:
        return False
    for x in range(0, width, 2):
        for y in range(0, height, 2):
            if surface.get_at((x, y))[3] > 20:
                return True
    return False


def load_font(size: int, root: str | None = None) -> pygame.font.Font:
    """Return a font that can draw Traditional Chinese, or pygame's default."""
    for base in _search_roots(root):
        for candidate in _CANDIDATES:
            path = candidate if os.path.isabs(candidate) else os.path.join(base, candidate)
            if not os.path.exists(path):
                continue
            try:
                font = pygame.font.Font(path, size)
            except (OSError, pygame.error):
                continue
            if _paints_ink(font):
                return font
    print("[gingerbread] warning: no CJK-capable font found; "
          "Chinese text will render as blank boxes")
    return pygame.font.Font(None, size)


class FontBook:
    """Named font sizes plus a render cache.

    Sizes are named rather than numeric at the call site (``book.render("糖霜",
    "small", MUTED)``) so a later type-scale change is one edit here instead of
    a search for every magic number.
    """

    SIZES: Final = {
        "tiny": 11,
        "small": 13,
        "body": 16,
        "title": 22,
        "big": 26,
        "huge": 40,
    }

    #: Beyond this many cached surfaces the cache is cleared wholesale.  A
    #: strict LRU would be tidier, but text here is drawn from a small fixed
    #: vocabulary plus a few counters; the cache simply never grows in practice
    #: and the cap only exists so a pathological case cannot leak forever.
    _CAP: Final = 1200

    def __init__(self, root: str | None = None, scale: float = 1.0) -> None:
        """``scale`` multiplies every named size.

        Text is rasterised at the size it will actually appear.  Drawing at a
        fixed small size and scaling the finished frame up is what made the
        interface look soft: glyphs were being interpolated rather than
        rendered, and no amount of font work fixes that.
        """
        self.scale = scale
        self._fonts = {name: load_font(max(8, int(round(size * scale))), root)
                       for name, size in self.SIZES.items()}
        self._cache: dict[tuple[str, str, RGB], pygame.Surface] = {}
        #: Strings already reported as unrenderable, so one bad label logs once
        #: instead of sixty times a second.
        self._warned: set[str] = set()

    def font(self, size: str = "body") -> pygame.font.Font:
        """Return the raw pygame font for measurement or custom rendering."""
        return self._fonts[size]

    def render(self, text: str, size: str = "body",
               colour: RGB = (240, 229, 205)) -> pygame.Surface:
        """Return a cached surface for this exact (text, size, colour).

        The returned surface is shared — callers must treat it as read-only and
        must not blit onto it or change its alpha.  Use :meth:`fade` when a
        varying opacity is needed.
        """
        key = (text, size, colour)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        if len(self._cache) >= self._CAP:
            self._cache.clear()
        try:
            surface = self._fonts[size].render(text, True, colour)
        except pygame.error as exc:
            # **A label must never be able to close the game.**  SDL_ttf raises
            # "Text has zero width" for a string it cannot lay out at all — a
            # size it dislikes, a subset missing every glyph in the line — and
            # an uncaught one takes the whole window down on a screen the
            # developer does not own.  A missing caption is a blemish; a window
            # that vanishes on the title screen is the end of the demo.
            if text not in self._warned:
                self._warned.add(text)
                print(f"[gingerbread] 這行字畫不出來（{size}）：{text!r} — {exc}")
            surface = pygame.Surface((1, self.line_height(size)),
                                     pygame.SRCALPHA)
        self._cache[key] = surface
        return surface

    def fade(self, text: str, size: str, colour: RGB, alpha: int) -> pygame.Surface:
        """Return a private copy of the text at a given opacity.

        Separate from :meth:`render` because ``set_alpha`` mutates the surface,
        and mutating a cached surface would change every other user of it.

        Fully opaque returns the cached surface untouched.  ``set_alpha(255)``
        on a per-pixel-alpha surface makes pygame skip blending and copy the
        whole thing, which turns anti-aliased text into a solid rectangle of
        background — the same failure that painted the playfield black during a
        surge.  There is nothing to fade at 255 anyway.
        """
        if alpha >= 255:
            return self.render(text, size, colour)
        surface = self.render(text, size, colour).copy()
        surface.set_alpha(max(0, alpha))
        return surface

    def measure(self, text: str, size: str = "body") -> tuple[int, int]:
        """Return the pixel size this text would occupy."""
        return self._fonts[size].size(text)

    def line_height(self, size: str = "body") -> int:
        return self._fonts[size].get_linesize()

    def wrap(self, text: str, size: str, width: int) -> list[str]:
        """Break ``text`` into lines that each fit inside ``width`` pixels.

        Breaking happens **per character**, not per word.  Chinese has no spaces
        to break on, so a word-based wrapper would return one enormous line and
        overflow the panel.  Explicit newlines in the input are honoured.
        """
        font = self._fonts[size]
        lines: list[str] = []
        for paragraph in text.split("\n"):
            if not paragraph:
                lines.append("")
                continue
            current = ""
            for char in paragraph:
                trial = current + char
                if current and font.size(trial)[0] > width:
                    lines.append(current)
                    current = char
                else:
                    current = trial
            if current:
                lines.append(current)
        return lines

    def truncate(self, text: str, size: str, width: int, ellipsis: str = "…") -> str:
        """Shorten ``text`` until it fits ``width``, appending an ellipsis."""
        font = self._fonts[size]
        if font.size(text)[0] <= width:
            return text
        budget = width - font.size(ellipsis)[0]
        if budget <= 0:
            return ellipsis
        current = ""
        for char in text:
            if font.size(current + char)[0] > budget:
                break
            current += char
        return current + ellipsis
