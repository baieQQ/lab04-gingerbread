"""碰到會死、碰到會被彈開 —— 這兩件事都要只發生一次。

夜晚的主迴圈是「掃過每一隻怪、把活著的收進 survivors、最後覆蓋 state.monsters」。
任何在那個迴圈裡把怪從 state.monsters 上拿掉的動作，都會被最後那一行覆蓋掉。
這支測試盯的就是那個縫。
"""

from __future__ import annotations

from gingerbread import model as m
from gingerbread.model import constants as C, rules


def _night(skill: str, monster: str, at=(486.0, 300.0)):
    meta = m.Meta(night=4)
    meta.skills = [skill]
    state = m.new_game(seed=5, meta=meta)
    state = m.apply_action(state, "begin_night")
    state.monsters.clear()
    state.warnings.clear()
    state.sleepers.clear()
    state.player.x, state.player.y = 450.0, 300.0
    beast = rules.make_monster(state, monster, *at)
    beast.wake = 0.0
    state.monsters.append(beast)
    return state


def test_a_monster_killed_by_contact_dies_once():
    """雷鳴電死一隻分裂怪，它就該裂一次。

    以前它會留在場上，每一格再死一次 —— 九格生出十八隻小分裂怪、糖霜每一格
    掉一份、擊殺數每一格加一。
    """
    state = _night("thunderclap", "splitter")
    state = m.apply_action(state, "cast:thunderclap")
    for _ in range(180):
        if state.monsters:
            beast = state.monsters[0]
            state.player.x += 3.0 if beast.x > state.player.x else -3.0
        state = m.apply_action(state, "tick")
        if not any(x.spec == "splitter" for x in state.monsters):
            break
    children = [x for x in state.monsters if x.spec == "splitterling"]
    assert len(children) <= 3, f"裂出了 {len(children)} 隻"
    assert state.stats.kills <= 2, f"擊殺數 {state.stats.kills}"
    assert all(x.hp > -10 for x in state.monsters)


def test_a_bomber_killed_by_contact_explodes_once():
    state = _night("thunderclap", "bomber")
    state = m.apply_action(state, "cast:thunderclap")
    booms = 0
    for _ in range(180):
        if state.monsters:
            beast = state.monsters[0]
            state.player.x += 3.0 if beast.x > state.player.x else -3.0
        state = m.apply_action(state, "tick")
        booms += sum(1 for e in state.events if "boom" in e or "explo" in e)
        if not state.monsters:
            break
    assert booms <= 1, f"炸了 {booms} 次"


def test_the_ward_throws_a_monster_off_instead_of_deleting_it():
    """聖癒是護罩，不是清場。

    以前撞上護罩的怪會直接從場上消失 —— 那讓聖癒變成一個八秒的無敵殺區，比
    它該有的樣子強太多，也不是它文案上說的那件事。
    """
    state = _night("blessing", "villager",
                   at=(C.SISTER_X + 26.0, C.SISTER_Y))
    state = m.apply_action(state, "cast:blessing")
    for _ in range(120):
        state = m.apply_action(state, "tick")
    assert state.monsters, "護罩把怪弄不見了"
    assert state.meta.sister_hp == state.meta.max_sister_hp
    assert state.stats.reached_sister == 0
    away = abs(state.monsters[0].x - C.SISTER_X)
    assert away > 26.0, "被彈開的怪應該離她更遠"


def test_without_the_ward_the_monster_still_reaches_her():
    state = _night("blessing", "villager",
                   at=(C.SISTER_X + 26.0, C.SISTER_Y))
    for _ in range(120):
        state = m.apply_action(state, "tick")
    assert state.stats.reached_sister >= 1
    assert state.meta.sister_hp < state.meta.max_sister_hp
