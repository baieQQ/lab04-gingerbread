"""Build the bundled CJK font subset from the text the game actually contains.

The web build ships with no system fonts, so a font has to travel with it — and
a full Traditional Chinese face is around 20 MB, which is far too much to send
to a browser.  The answer is a subset containing only the characters the game
uses.

The important part is *how* the character set is decided.  It is not a hand-kept
list: this script parses every source file and collects the characters out of
every string literal it finds.  Content is arriving as data tables full of
Chinese names, so a hand-kept list would fall behind the moment a partner adds a
monster — and the failure is silent.  A missing glyph does not raise; it renders
as nothing, so a menu button simply looks empty.

Usage::

    .venv/bin/python tools/build_font.py

Re-run it after any content change.  The check at the end fails loudly if a
character the game uses did not make it in.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

try:
    from fontTools import subset
    from fontTools.ttLib import TTFont
except ImportError:                                   # pragma: no cover
    sys.exit("fontTools is required:  .venv/bin/python -m pip install fonttools")

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "assets" / "GameCJK-Subset.ttf"

#: Searched in order.  STHeiti is chosen ahead of Hiragino deliberately: both
#: are present on macOS, but Hiragino measured ~27x slower per render and ~28x
#: slower per ``font.size()`` call, which is a real cost in a text-heavy HUD.
SOURCE_FONTS = (
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "C:/Windows/Fonts/msjh.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)

#: Always included regardless of what the source scan finds.  These cover the
#: characters that only ever appear through string formatting — digits and
#: punctuation assembled at runtime never show up in a literal.
ALWAYS = (
    "0123456789"
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    " .,:;!?%+-*/=<>()[]{}#@&_'\"`~^$|\\"
    "、。，：；！？「」『』（）《》〈〉—…·～　"      # incl. U+3000 ideographic space
    "×÷←→↑↓●○■□★☆"
)

#: Characters no text font will supply, so asking for them only produces noise
#: in the report.  Emoji in particular must never be used as game text: a system
#: emoji font cannot be subset into the web build, so they render as nothing.
#: Icons belong in ``assets/images/``, where a missing file falls back to a
#: drawn shape instead of to a hole.
def _is_renderable(char: str) -> bool:
    code = ord(char)
    if code >= 0x1F000:                       # emoji and pictographs
        return False
    if 0x2190 <= code <= 0x2BFF:              # arrows, dingbats, misc symbols
        return code in {
            0x2190, 0x2191, 0x2192, 0x2193,   # arrows, used in the result ledger
            0x2212,                            # true minus sign, used in prices
            0x25A0, 0x25A1, 0x25CF, 0x25CB,   # filled/hollow squares and circles
            0x2605, 0x2606,                    # stars
        }
    return True

#: Words that must survive even if a refactor temporarily removes them from the
#: source — the menu is the first thing a player sees, and a blank button there
#: is worse than any other missing glyph.
SAFETY_NET = (
    "七夜主線無盡模式開始繼續離開設定返回選單暫停確定取消"
    "商店購買升級選擇難度紀錄最佳成績分數存活時間擊殺"
    "白天晚上準備行動點提燈光照糖霜生命防禦攻擊速度範圍冷卻移動"
    "第夜撐過了葛蕾特不見顆半心補血"
)


def collect_from_source(root: Path) -> set[str]:
    """Return every character appearing in a string literal under ``root``.

    Uses the ``ast`` module rather than a regular expression so that escapes,
    f-strings, implicit concatenation and multi-line strings are all handled the
    way Python itself handles them.
    """
    found: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        if any(part in {".venv", "build", "__pycache__"} for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            print(f"  ! skipped {path.relative_to(root)}: {exc}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found |= set(node.value)
    return found


def pick_source_font() -> str:
    for candidate in SOURCE_FONTS:
        if os.path.exists(candidate):
            return candidate
    sys.exit("no source CJK font found; edit SOURCE_FONTS for this machine")


def main() -> int:
    # story/ 也要掃：過場動畫的字幕是另一位組員寫的，那些字不在 src/ 裡，
    # 漏掉的話字型子集就缺字，他的字幕會整排變成豆腐。
    wanted = collect_from_source(ROOT / "src") | collect_from_source(ROOT / "story")
    wanted |= collect_from_source(ROOT / "tools")
    wanted |= set(ALWAYS) | set(SAFETY_NET)

    # Control characters would bloat the cmap and can never be drawn; emoji and
    # exotic symbols are dropped with a note rather than reported as failures.
    wanted = {c for c in wanted if c.isprintable() or c == " "}
    unrenderable = sorted(c for c in wanted if not _is_renderable(c))
    if unrenderable:
        print(f"skipping {len(unrenderable)} symbol(s) no text font provides: "
              f"{''.join(unrenderable)}")
        print("  (if any of these appear in game text, replace them with an "
              "asset image — they will render as nothing in the web build)")
    wanted = {c for c in wanted if _is_renderable(c)}

    source = pick_source_font()
    print(f"source font : {source}")
    print(f"characters  : {len(wanted)}")

    font = TTFont(source, fontNumber=0)
    options = subset.Options()
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.notdef_outline = True
    options.recalc_bounds = True
    # Keeping hinting would be ideal, but a CID-keyed CFF source can carry hint
    # masks the subsetter cannot rewrite, and the result renders blank.  Dropping
    # hinting costs a little crispness at small sizes and always works.
    options.hinting = False

    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text="".join(sorted(wanted)))
    subsetter.subset(font)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    font.save(OUTPUT)
    font.close()

    # ── verify, because a missing glyph is silent at runtime ─────────
    built = TTFont(OUTPUT)
    covered: set[int] = set()
    for table in built["cmap"].tables:
        covered |= set(table.cmap.keys())
    built.close()

    missing = sorted(c for c in wanted if ord(c) not in covered)
    size_kb = OUTPUT.stat().st_size / 1024
    print(f"written     : {OUTPUT.relative_to(ROOT)}  ({size_kb:.0f} KB, "
          f"{len(covered)} glyphs)")

    if missing:
        print(f"MISSING {len(missing)}: {''.join(missing)}")
        print("the source font does not contain these; pick a fuller source font")
        return 1
    print("all requested characters are present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
