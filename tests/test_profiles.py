"""存檔：一個名字記住一個人的進度。

這支測試盯的是「開了遊戲、打了名字、關掉、再開」這條路 —— 存檔的價值全部在
那個「再開」上，而那正是手動測試最不會去做的一步。
"""

from __future__ import annotations

import pygame
import pytest

from gingerbread import model as m
from gingerbread.model import rules
from gingerbread.app.game import Game
from gingerbread.app.scenes import MenuScene, ProfileScene


def _boot() -> Game:
    game = Game(seed=1, fullscreen=False)
    for _ in range(3):
        game.stack.frame(1 / 60.0, [])
    return game


def _type(game: Game, text: str) -> None:
    game.stack.frame(1 / 60.0, [pygame.event.Event(pygame.TEXTINPUT,
                                                   text=text)])


def _press(game: Game, key: int) -> None:
    game.stack.frame(1 / 60.0, [pygame.event.Event(pygame.KEYDOWN, key=key,
                                                   mod=0, unicode="",
                                                   scancode=0)])


def test_the_first_screen_asks_who_is_playing():
    game = _boot()
    assert isinstance(game.stack.top, ProfileScene)


def test_a_typed_nickname_becomes_a_profile():
    game = _boot()
    _type(game, "小白")
    _press(game, pygame.K_RETURN)
    assert game.session.profile == "小白"
    assert "小白" in game.session.profile_names()


def test_progress_comes_back_after_a_restart():
    """關掉再開，星等、難度和教學進度都還在。"""
    game = _boot()
    _type(game, "小白")
    _press(game, pygame.K_RETURN)
    game.session.set_difficulty("hard")
    game.session.set_onboarding(False)
    game.session.state.meta.award_stars(1, 3)
    game.session.state.meta.count_try(1)
    game.session.act("tick")            # 走一次 _remember，寫進存檔

    again = Game(seed=1, fullscreen=False)
    again.session.load_profile("小白")
    assert again.session.saved.difficulty == "hard"
    assert again.session.onboarding is False
    assert again.session.saved.night_stars[1] == 3
    assert again.session.saved.night_tries[1] >= 1


def test_two_names_do_not_share_progress():
    game = _boot()
    _type(game, "小白")
    _press(game, pygame.K_RETURN)
    game.session.state.meta.award_stars(2, 3)
    game.session.act("tick")

    game.session.load_profile("阿婷")
    assert game.session.saved.night_stars[2] == 0
    game.session.load_profile("小白")
    assert game.session.saved.night_stars[2] == 3


def test_a_character_the_font_cannot_draw_is_refused():
    """暱稱只收畫得出來的字。

    畫不出來的字進到存檔裡，會在畫面上變成一個洞 —— 那種看起來像遊戲壞掉、
    其實只是字型沒有這個字的洞。
    """
    game = _boot()
    scene = game.stack.top
    assert isinstance(scene, ProfileScene)
    _type(game, "小\U0001f600白")       # 中間夾一個表情符號
    assert "\U0001f600" not in scene.draft
    assert scene.draft == "小白"


def test_the_nickname_is_capped():
    game = _boot()
    scene = game.stack.top
    _type(game, "一二三四五六七八九十十一十二")
    assert len(scene.draft) == 10


@pytest.mark.parametrize("key,flag", [("freecast", "freecast"),
                                      ("seeall", "seeall"),
                                      ("godmode", "godmode")])
def test_a_fun_switch_reaches_the_run_and_the_save(key, flag):
    game = _boot()
    _type(game, "玩玩")
    _press(game, pygame.K_RETURN)
    game.session.set_fun(key, True)
    assert getattr(game.session.state.meta, flag) is True
    game.session.start(m.Mode.CAMPAIGN)   # 新的一局也要帶著走
    assert getattr(game.session.state.meta, flag) is True

    again = Game(seed=1, fullscreen=False)
    again.session.load_profile("玩玩")
    assert again.session.fun[key] is True


def test_free_cooldowns_mean_a_skill_can_be_cast_twice_in_a_row():
    game = _boot()
    _type(game, "玩玩")
    _press(game, pygame.K_RETURN)
    game.session.state.meta.skills = ["bolt"]
    game.session.state = m.apply_action(game.session.state, "begin_night")
    # 技能不會被放在空無一人的場上，所以先給它一個目標。
    game.session.state.monsters.append(
        rules.make_monster(game.session.state, "villager", 460.0, 300.0))
    game.session.state = m.apply_action(game.session.state, "cast:bolt")
    assert game.session.state.cooldowns["bolt"] > 0

    game.session.set_fun("freecast", True)
    assert game.session.state.cooldowns["bolt"] == 0
    game.session.state = m.apply_action(game.session.state, "cast:bolt")
    assert game.session.state.cooldowns["bolt"] == 0


def test_deleting_the_last_profile_leaves_the_name_entry_open():
    game = _boot()
    _type(game, "小白")
    _press(game, pygame.K_RETURN)
    scene = game.stack.top
    scene._delete(game.stack, game.ui, "小白")
    assert game.session.profile == ""
    assert scene.typing is True
    # 刪掉之後不准又被寫回去。
    game.session._save_profile()
    assert "小白" not in game.session.profile_names()


def test_starting_from_the_profile_screen_reaches_the_menu():
    game = _boot()
    _type(game, "小白")
    _press(game, pygame.K_RETURN)
    game.stack.top._leave(game.stack)
    assert isinstance(game.stack.top, MenuScene)
