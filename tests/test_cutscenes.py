"""四段過場動畫都要跑得起來，而且都要能跳過。

它們是另一位組員寫的獨立程式，接進來的方式是餵時間、餵事件、指定畫布 ——
也就是說任何一次重構都可能安靜地把它們弄壞：畫面照樣是黑的，只是什麼都沒有。
"""

from __future__ import annotations

import pygame
import pytest

from gingerbread.app.cutscene import CUTSCENES, CutsceneScene
from gingerbread.app.game import Game


def _boot() -> Game:
    game = Game(seed=1, fullscreen=False)
    game.session.load_profile("過場")
    return game


@pytest.mark.parametrize("key", sorted(CUTSCENES))
def test_a_cutscene_loads_and_draws(key):
    game = _boot()
    scene = CutsceneScene(game.session, key)
    assert scene.inner is not None, f"{key} 載不起來"
    game.stack.push(scene)
    for _ in range(120):
        game.stack.frame(1 / 60.0, [])
    assert game._crash_count == 0, game._last_crash


@pytest.mark.parametrize("key", sorted(CUTSCENES))
def test_a_cutscene_puts_ink_on_the_canvas(key):
    """真的畫了東西，不是一整片背景色。

    組員的 day_1 曾經整段畫不出來 —— 它的 draw 按著另一支的背景代號分派，而
    自己的幕用的是別的代號。畫面是黑的，程式沒有報錯。
    """
    game = _boot()
    game.stack.push(CutsceneScene(game.session, key))
    for _ in range(90):
        game.stack.frame(1 / 60.0, [])
    surface = game.window
    seen = {surface.get_at((x, y))[:3]
            for x in range(20, surface.get_width(), 37)
            for y in range(20, surface.get_height(), 31)}
    assert len(seen) > 3, f"{key} 畫面上只有 {len(seen)} 種顏色"


@pytest.mark.parametrize("key", sorted(CUTSCENES))
def test_escape_skips_a_cutscene(key):
    game = _boot()
    depth = len(game.stack.scenes)
    game.stack.push(CutsceneScene(game.session, key))
    for _ in range(10):
        game.stack.frame(1 / 60.0, [])
    for _ in range(4):
        game.stack.frame(1 / 60.0, [pygame.event.Event(
            pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0, unicode="",
            scancode=0)])
    assert len(game.stack.scenes) == depth, f"{key} 按 Esc 跳不掉"
