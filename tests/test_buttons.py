"""每一顆按鈕都要按得下去。

會有這支測試，是因為一個只在**按下去的那一刻**才會炸的錯誤活了下來：選單的
按鈕分支寫成 ``if ui.button(...): self._go(app, ...)``，而 ``app`` 因為一次
重構被留在另一個方法裡。截圖測試照樣通過 —— 沒有人點，那一行就永遠不會求值。

所以這裡不看畫面，只做一件事：把每一個場景裡的每一顆按鈕依序點過一遍，任何
一顆炸了就讓測試失敗。
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame                                        # noqa: E402

from gingerbread import model as m                   # noqa: E402
from gingerbread.app.game import Game                # noqa: E402
from gingerbread.app.scenes import (CodexScene, CreditsScene,  # noqa: E402
                                    DawnScene, LedgerScene, MapScene,
                                    PauseScene, PlayScene, ProfileScene,
                                    ResultScene, build_menu)


def _click(game, pos):
    """對著 pos 完整走一次「移動→按下→放開」。"""
    pygame.mouse.set_pos(pos)
    for event in (
        pygame.event.Event(pygame.MOUSEMOTION, pos=pos, rel=(1, 1),
                           buttons=(0, 0, 0), touch=False),
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1,
                           touch=False),
        pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1,
                           touch=False),
    ):
        game.stack.frame(1 / 60.0, [event])


def _sweep(game, step=26):
    """掃過整個畫面點一遍。

    用網格而不是去問 UI 要按鈕座標：按鈕是 immediate-mode 畫出來的，沒有可以
    列舉的清單，而網格夠密就一定會踩到每一顆。
    """
    width, height = game.window.get_size()
    for y in range(step // 2, height, step):
        for x in range(step // 2, width, step):
            _click(game, (x, y))


def _fresh(scene_factory=None, **meta):
    game = Game(seed=1, fullscreen=False)
    # 開機第一個畫面是「誰在玩」。先給它一個名字再走到主選單，不然掃到的是
    # 存檔畫面而不是要測的那一頁。
    game.session.load_profile("測試")
    game.stack.pop()
    game.stack.push(build_menu(game.session))
    game.session.set_onboarding(False)
    for key, value in meta.items():
        setattr(game.session.state.meta, key, value)
    if scene_factory is not None:
        game.stack.push(scene_factory(game))
    for _ in range(4):
        game.stack.frame(1 / 60.0, [])
    return game


def test_main_menu_buttons_are_all_clickable():
    """主選單：七夜、無盡、圖鑑、新手引導、四段難度。"""
    game = _fresh()
    _sweep(game)


def test_the_profile_screen_survives_every_button():
    """存檔畫面：選存檔、開娛樂開關、刪除、建立新的，全部點過一遍。

    這一頁比別頁危險 —— 它的按鈕會刪東西、會重建整局。而網格掃描會**真的**
    按下「真的刪」，所以 conftest 把存檔路徑換到暫存資料夾這件事，是這支測試
    能存在的前提。
    """
    game = Game(seed=1, fullscreen=False)
    game.session.load_profile("甲")
    game.session.load_profile("乙")
    game.stack.pop()
    game.stack.push(ProfileScene(game.session, first=True))
    for _ in range(4):
        game.stack.frame(1 / 60.0, [])
    _sweep(game)


def test_the_credits_screen_survives_every_button():
    game = _fresh()
    game.stack.push(CreditsScene(game.session))
    _sweep(game)


@pytest.mark.parametrize("factory", [
    lambda g: CodexScene(g.session),
    lambda g: MapScene(g.session),
    lambda g: PauseScene(g.session, g),
    lambda g: LedgerScene(g.session, victory=True),
    lambda g: ProfileScene(g.session),
])
def test_overlay_scene_buttons(factory):
    game = _fresh()
    game.stack.push(PlayScene(game.session))
    game.stack.push(factory(game))
    for _ in range(120):                    # 讓地圖的展開動畫跑完
        game.stack.frame(1 / 60.0, [])
    _sweep(game)


def test_result_and_dawn_buttons():
    """結算與天亮 —— 兩個都有「再來一次」這種會重建整局的按鈕。"""
    for phase, factory in ((m.Phase.LOST, lambda g: ResultScene(g.session)),
                           (m.Phase.SHOP, lambda g: DawnScene(g.session))):
        game = _fresh()
        game.session.state = m.apply_action(game.session.state, "begin_night")
        game.session.state.phase = phase
        game.stack.push(PlayScene(game.session))
        game.stack.push(factory(game))
        for _ in range(180):                # 死亡淡出要跑完才會有按鈕
            game.stack.frame(1 / 60.0, [])
        _sweep(game)
