"""把整個殼層跑久一點，看它會不會壞。

按鈕全掃測的是「按下去會不會炸」，這一支測的是另一件事：讓遊戲自己跑很多幀，
場景一個換過一個，中間有王、有技能、有天亮、有死掉 —— 任何一幀丟出例外都會
被 Game 的保險絲接住，畫面上只留一行字。那個保險絲救了展場，但也會讓一個真
的錯誤在測試裡看起來像沒事，所以這裡直接檢查保險絲有沒有跳過。
"""

from __future__ import annotations

import pygame

from gingerbread import model as m
from gingerbread.app.game import Game
from gingerbread.app.scenes import PlayScene, build_menu


def _boot(**fun) -> Game:
    game = Game(seed=3, fullscreen=False)
    game.session.load_profile("耐久")
    for key, on in fun.items():
        game.session.set_fun(key, on)
    game.session.set_onboarding(False)
    # 過場動畫會停在最上面等玩家點下一句，而它一停，底下的遊戲就不再前進。
    # 這支測試量的是遊戲迴圈，不是動畫，所以先把它們標記成看過了。
    from gingerbread.app.cutscene import CUTSCENES

    game.session.cutscenes_played.update(CUTSCENES)
    game.session.story_shown = 99
    game.stack.pop()
    game.stack.push(build_menu(game.session))
    return game


def _play(game: Game, frames: int, keys=()) -> None:
    for i in range(frames):
        events = []
        if keys and i % 40 == 0:
            events = [pygame.event.Event(pygame.KEYDOWN, key=k, mod=0,
                                         unicode="", scancode=0)
                      for k in keys]
        game.stack.frame(1 / 60.0, events)
        game.session.cast_from_keys(game.ui.keys)
        game.session.drain()


def test_seven_nights_run_through_the_shell_without_the_fuse_blowing():
    """開著無敵一路跑七夜，把每一個場景都經過一次。"""
    game = _boot(godmode=True, freecast=True)
    game.session.start(m.Mode.CAMPAIGN)
    game.stack.push(PlayScene(game.session))
    for night in range(1, m.constants.CAMPAIGN_NIGHTS + 1):
        # 白天：學技能、上場、天黑。
        state = game.session.state
        for tier, keys in ((1, ("bolt", "holy", "tornado", "cage")),
                           (2, ("thunderclap", "windrun", "riptide",
                                "blessing"))):
            for key in keys:
                if (key not in state.meta.skills
                        and state.meta.points_for(tier) > 0):
                    game.session.act(f"learn:{key}")
                    state = game.session.state
        for index, tier in ((0, 1), (1, 2)):
            if state.meta.slots[index]:
                continue
            for key in state.meta.skills:
                if m.content.SPELLS[key].tier == tier:
                    game.session.act(f"slot:{index}:{key}")
                    state = game.session.state
                    break
        game.session.act("begin_night")
        game.session.story_shown = 99
        # 夜晚：一邊走一邊放技能，直到天亮或輸掉。
        for _ in range(200):
            _play(game, 30, keys=(pygame.K_l, pygame.K_SEMICOLON))
            if game.session.state.phase is not m.Phase.NIGHT:
                break
        assert game._crash_count == 0, game._last_crash
        if game.session.state.phase is m.Phase.VICTORY:
            break
        if game.session.state.phase is not m.Phase.SHOP:
            break
        game.session.act("next_night")
        _play(game, 10)
    assert game._crash_count == 0, game._last_crash
    assert game.session.state.meta.night >= 2, "開著無敵連第二夜都到不了"


def test_a_thousand_frames_of_menus_do_not_blow_the_fuse():
    game = _boot()
    from gingerbread.app import scenes as S

    for factory in (lambda: S.CodexScene(game.session),
                    lambda: S.LedgerScene(game.session, victory=False),
                    lambda: S.CreditsScene(game.session),
                    lambda: S.ProfileScene(game.session),
                    lambda: S.MapScene(game.session)):
        game.stack.push(factory())
        _play(game, 200)
        game.stack.pop()
    assert game._crash_count == 0, game._last_crash


def test_toggling_fullscreen_keeps_everything_drawable():
    """切換全螢幕會重建畫布、重建字型、重建 Board。

    這條路上每一個持有舊尺寸的東西都得換掉，漏一個就是「切回來之後字全部糊
    掉」或「按鈕的位置跟游標對不上」。
    """
    game = _boot()
    from gingerbread.app import scenes as S

    game.stack.push(S.CodexScene(game.session))
    _play(game, 20)
    for _ in range(3):
        game.toggle_fullscreen()
        _play(game, 20)
        assert game.ui.scale > 0
        assert game.book is game.session.book
        assert game.stack.ui is game.ui
        # 字還畫得出來，而且是照新的尺寸畫的。
        surface = game.book.render("撐過了第 3 夜", "body", (240, 229, 205))
        assert surface.get_width() > 10
    assert game._crash_count == 0, game._last_crash


def test_a_night_played_with_the_lantern_only_still_ends():
    """完全不放技能、只揮燈，也要走得完一夜（不管是天亮還是輸掉）。"""
    game = _boot()
    game.session.start(m.Mode.CAMPAIGN)
    game.stack.push(PlayScene(game.session))
    game.session.act("learn:bolt")
    game.session.act("learn:thunderclap")
    game.session.act("slot:0:bolt")
    game.session.act("slot:1:thunderclap")
    game.session.act("begin_night")
    game.session.story_shown = 99
    for _ in range(200):
        _play(game, 30)
        if game.session.state.phase is not m.Phase.NIGHT:
            break
    assert game.session.state.phase is not m.Phase.NIGHT, "一夜跑不完"
    assert game._crash_count == 0, game._last_crash
