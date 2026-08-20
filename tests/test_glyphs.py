"""遊戲裡寫得出來的每一個字，字型都要畫得出來。

缺字在這款遊戲裡出過兩次事，而且兩次都不像缺字：一次是 SDL_ttf 在量寬度的時
候直接把遊戲關掉，一次是它安靜地讓整個畫面從此沒有文字。兩次的起點都一樣 ——
有人加了一行中文，沒有重跑 ``tools/build_font.py``。

所以這支測試做的事就是那件事的自動版：把原始碼裡所有字串裡的字收集起來，一個
一個問字型畫不畫得出來。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pygame

from gingerbread.view.fonts import FontBook

ROOT = Path(__file__).resolve().parent.parent
SKIP_PARTS = {".venv", "build", "__pycache__", "web", "tools", "tests"}

#: 只出現在註解、說明文件字串裡的符號，畫面上永遠不會出現。
NEVER_DRAWN = set("⚠≈")


def _characters() -> set[str]:
    found: set[str] = set()
    for folder in ("src", "story"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            if any(part in SKIP_PARTS for part in path.parts):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    found |= set(node.value)
    return {c for c in found
            if c.isprintable() and not c.isascii() and c not in NEVER_DRAWN}


def test_every_character_in_the_source_is_in_the_font():
    pygame.init()
    pygame.display.set_mode((64, 64))
    book = FontBook(root=str(ROOT))
    missing = sorted(c for c in _characters() if not book.can_render(c, "body"))
    assert not missing, (
        f"字型少了 {len(missing)} 個字：{''.join(missing)}\n"
        "重跑 .venv/bin/python tools/build_font.py")


def test_a_player_typed_name_can_be_drawn():
    """暱稱走的是系統字型，所以子集沒有的字也畫得出來。"""
    pygame.init()
    pygame.display.set_mode((64, 64))
    book = FontBook(root=str(ROOT))
    for char in "曾哲瀚陳彥婷昱安":
        assert book.can_render(char, "name"), char
