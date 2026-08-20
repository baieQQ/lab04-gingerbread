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

#: 私用區的字碼。沒有任何一套真的字型會有這裡的字形，所以它畫出來的一定是
#: .notdef —— 拿它當樣本，就能問「這個字這套字型有沒有」：畫出來跟它一模一
#: 樣，就是沒有。
#:
#: 這件事沒有別的問法。``Font.metrics`` 對缺字回傳的是 .notdef 的度量（不是
#: None），字型子集又刻意保留了 .notdef 的輪廓，所以量得到寬度不代表畫得出
#: 字。玩家自己打的暱稱是唯一會踩到這件事的地方 —— 遊戲裡其他的字都在原始碼
#: 裡，build_font 掃得到。
_NOTDEF: Final = "\ue000"


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


def load_font(size: int, root: str | None = None, *,
              prefer_system: bool = False) -> pygame.font.Font:
    """Return a font that can draw Traditional Chinese, or pygame's default.

    ``prefer_system`` 把捆在遊戲裡的子集排到最後。子集只收原始碼裡出現過的
    字，對「遊戲自己的字」剛剛好，對「玩家打進來的字」則是幾乎一定缺 —— 存檔
    暱稱要用的是這一條路。找不到系統字型（網頁版就沒有）才退回子集，所以最壞
    的情況是暱稱只能用打得出來的那些字，不是整個壞掉。
    """
    order = (_CANDIDATES[1:] + _CANDIDATES[:1]) if prefer_system else _CANDIDATES
    for base in _search_roots(root):
        for candidate in order:
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
        # 玩家自己打的字（存檔暱稱）專用。見 SYSTEM_SIZES。
        "name": 22,
        "name_small": 14,
    }

    #: 這幾個尺寸走系統字型而不是捆進來的子集 —— 見 ``load_font``。
    SYSTEM_SIZES: Final = ("name", "name_small")

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
        self._root = root
        self._pixels = {name: max(8, int(round(size * scale)))
                        for name, size in self.SIZES.items()}
        self._fonts = {name: load_font(px, root,
                                       prefer_system=name in self.SYSTEM_SIZES)
                       for name, px in self._pixels.items()}
        #: (字, 尺寸) -> 這套字型畫不畫得出來。見 :meth:`can_render`。
        self._known: dict[tuple[str, str], bool] = {}
        self._cache: dict[tuple[str, str, RGB], pygame.Surface] = {}
        #: Strings already reported as unrenderable, so one bad label logs once
        #: instead of sixty times a second.
        self._warned: set[str] = set()

    def _revive(self, size: str) -> None:
        """丟掉一個出過錯的字型物件，重新開一份。

        SDL_ttf 在 "Couldn't find glyph" 之後**不會自己恢復** —— 那個 Font 物
        件從此每一次 render 都回傳空白。所以「吞掉例外繼續跑」這個做法，會把
        一次缺字放大成整個畫面從此沒有文字：評分頁只剩幾根長條和兩張立繪，
        而那正是它壞掉的樣子。

        重開一份是唯一乾淨的復原方式，而且很便宜（只發生在出錯的那一次）。
        算過的快取也要一起丟，否則已經存進去的空白會被一直拿出來用。
        """
        try:
            self._fonts[size] = load_font(
                self._pixels[size], self._root,
                prefer_system=size in self.SYSTEM_SIZES)
        except Exception:                              # noqa: BLE001
            return
        self._cache = {k: v for k, v in self._cache.items() if k[1] != size}

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
            self._revive(size)
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

    def _size(self, font, text: str) -> tuple[int, int]:
        """``font.size`` that never raises.

        字型是子集，只收原始碼裡出現過的字 —— 而遊戲裡有一整批字串是**執行時
        才組出來的**（評分頁的「最弱的一環：漢賽爾　受傷 6 次」就是拼出來的）。
        任何一個沒被 build_font 掃到的字，都會讓 SDL_ttf 在 ``size()`` 拋
        "Couldn't find glyph"。

        ``render`` 早就有這個防護，``size`` 沒有 —— 而每一次排版都會先量寬度，
        所以缺字實際上是從量測那一步殺掉遊戲的，不是從畫的那一步。缺字應該是
        「那個字變成空白」，不是「遊戲關掉」。
        """
        try:
            return font.size(text)
        except pygame.error as exc:
            if text not in self._warned:
                self._warned.add(text)
                print(f"[gingerbread] 這行字量不出寬度：{text!r} — {exc}")
            for name, existing in self._fonts.items():
                if existing is font:
                    self._revive(name)
                    break
            # 退回一個估計值：中日韓字大約是行高的寬度，其餘算一半。
            unit = font.get_linesize()
            wide = sum(1 for ch in text if ord(ch) > 0x2E7F)
            return (int(wide * unit + (len(text) - wide) * unit * 0.5), unit)

    def measure(self, text: str, size: str = "body") -> tuple[int, int]:
        """Return the pixel size this text would occupy."""
        return self._size(self._fonts[size], text)

    def can_render(self, char: str, size: str = "name") -> bool:
        """這套字型畫不畫得出 ``char``。

        畫一次跟 .notdef 比對，比對完記起來。缺字在這個遊戲裡只有一個入口
        —— 玩家自己打的暱稱 —— 而擋在輸入那一關，比讓它一路畫到畫面上再想
        辦法補救乾淨得多：畫不出來的字根本不該被收進存檔的名字裡。
        """
        key = (char, size)
        hit = self._known.get(key)
        if hit is not None:
            return hit
        font = self._fonts[size]
        try:
            blank = font.render(_NOTDEF, True, (255, 255, 255))
            drawn = font.render(char, True, (255, 255, 255))
        except pygame.error:
            self._revive(size)
            return False
        ok = (drawn.get_size() != blank.get_size()
              or pygame.image.tobytes(drawn, "RGBA")
              != pygame.image.tobytes(blank, "RGBA"))
        self._known[key] = ok
        return ok

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
                if current and self._size(font, trial)[0] > width:
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
        if self._size(font, text)[0] <= width:
            return text
        budget = width - self._size(font, ellipsis)[0]
        if budget <= 0:
            return ellipsis
        current = ""
        for char in text:
            if self._size(font, current + char)[0] > budget:
                break
            current += char
        return current + ellipsis
