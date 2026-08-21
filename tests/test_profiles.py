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


def test_the_enter_that_picks_a_character_does_not_submit():
    """注音選字按的也是 Enter。

    SDL 會在同一幀送出「選好的字」和「Enter 這個按鍵」，而先到的是按鍵 ——
    所以一趟掃下來，表單會在字進到欄位之前就被送出，送出的是一個空名字。
    實際的後果是：存檔叫「玩家」，而且之後每一次都說「這個名字已經有人用了」。
    """
    game = _boot()
    scene = game.stack.top
    game.stack.frame(1 / 60.0, [
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0,
                           unicode="\r", scancode=0),
        pygame.event.Event(pygame.TEXTINPUT, text="曾"),
    ])
    assert scene.draft == "曾"
    assert game.session.profile == "", "輸入法那一下 Enter 把表單送出去了"
    assert scene.typing is True

    # 下一幀單獨按 Enter，才是真的送出。
    _press(game, pygame.K_RETURN)
    assert game.session.profile == "曾"


def test_an_empty_name_is_refused_instead_of_becoming_a_default():
    game = _boot()
    scene = game.stack.top
    _press(game, pygame.K_RETURN)
    assert game.session.profile == ""
    assert "玩家" not in game.session.profile_names()
    assert scene.warn


def test_the_fun_modes_are_locked_until_the_first_night_is_survived():
    """三個娛樂模式要先照規則打過一夜才解得開。"""
    from gingerbread.app.scenes import FUN_MODES

    game = _boot()
    _type(game, "小白")
    _press(game, pygame.K_RETURN)
    scene = game.stack.top
    assert game.session.saved.best_night == 0

    # 網格掃過整個右半邊：鎖著的時候按不動。
    for x in range(455, 815, 18):
        for y in range(270, 400, 12):
            pygame.mouse.set_pos((x, y))
            for event in (
                pygame.event.Event(pygame.MOUSEMOTION, pos=(x, y), rel=(1, 1),
                                   buttons=(0, 0, 0), touch=False),
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(x, y),
                                   button=1, touch=False),
                pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(x, y), button=1,
                                   touch=False)):
                game.stack.frame(1 / 60.0, [event])
    assert not any(game.session.fun.values()), "第一夜還沒過就開得起來"

    # 撐過第一夜之後就解鎖了。
    game.session.saved.best_night = 1
    unlocked = []
    for key, _label, _note in FUN_MODES:
        game.session.set_fun(key, True)
        unlocked.append(game.session.fun[key])
    assert all(unlocked)
    assert scene is game.stack.top


def test_the_demo_profile_exists_on_a_fresh_machine():
    """內建展示存檔：拉下專案的每一台機器，清單上都有「展示」。

    這是給擺攤和上台用的 —— 一份全新存檔要打一小時才看得到第七夜，而展示的
    重點是給人看整個遊戲。它不是藏起來的機關：出現在清單上、刪掉會回到原廠
    狀態。
    """
    game = _boot()                      # conftest 已把存檔導到空的暫存資料夾
    assert "展示" in game.session.profile_names()

    game.session.load_profile("展示")
    assert game.session.saved.best_night == 7
    assert game.session.onboarding is False
    assert sum(game.session.saved.night_stars) > 0
    assert game.session.taught          # 教學全部標成看過

    # 刪掉＝重置：清單上還在，再載入回到原廠狀態。
    game.session.state.meta.award_stars(1, 1)
    game.session.delete_profile("展示")
    assert "展示" in game.session.profile_names()
    game.session.load_profile("展示")
    assert game.session.saved.night_stars[1] == 3


def test_tutorials_depend_on_onboarding_not_on_which_night():
    """怪物教學關：開著新手引導、這個存檔沒教過，哪一夜都給練。

    以前只有第一到第三夜有教學關 —— 對用存檔跳關的人是錯的：直接跳到第五夜
    的人，恰好最需要認識第五夜的新怪。
    """
    from gingerbread.model.content import newcomers

    game = _boot()
    _type(game, "小白")
    _press(game, pygame.K_RETURN)
    game.session.set_onboarding(True)
    for night in range(1, m.constants.CAMPAIGN_NIGHTS + 1):
        fresh = newcomers(night)
        untaught = tuple(k for k in fresh if k not in game.session.taught)
        if fresh:
            assert untaught == tuple(fresh), f"第 {night} 夜的新怪被跳過"

    # 關掉引導＝不教；重新打開＝全部重新教（教過的紀錄清掉）。
    game.session.teach("villager")
    game.session.set_onboarding(False)
    game.session.set_onboarding(True)
    assert "villager" not in game.session.taught
