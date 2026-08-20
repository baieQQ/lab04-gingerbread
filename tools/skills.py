"""每一個技能對每一隻王，到底打掉幾成血。

「有些技能會秒王」這句話，只有量出來才知道是哪幾個、差多少。這支工具把王放
在固定的位置、只放一次技能、然後空轉十五秒，看血條掉了多少 —— 中間不揮燈、
不放第二次，所以量到的就是這個技能自己的貢獻。

    .venv/bin/python tools/skills.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gingerbread import model as m                       # noqa: E402
from gingerbread.model import constants as C             # noqa: E402
from gingerbread.model import rules                      # noqa: E402
from gingerbread.model.content import BOSSES, SPELLS     # noqa: E402

#: 貼著打（疾風、雷鳴要靠碰撞才有傷害），還是站在原地放。
CHASERS = {"windrun", "thunderclap"}


def arena(boss_key: str, spell_key: str, *, night: int = 7):
    """一隻王、一個技能、沒有別的怪。"""
    meta = m.Meta(night=night)
    meta.skills = [spell_key]
    state = m.new_game(seed=5, meta=meta)
    state = m.apply_action(state, "begin_night")
    state.monsters.clear()
    state.warnings.clear()
    state.sleepers.clear()
    rules.spawn_boss(state, boss_key)
    boss = state.bosses[0]
    boss.x, boss.y = 450.0, 240.0
    # 出場的無敵時間跳過，不然前兩秒的技能全部打在空氣上。
    boss.wake = 0.0
    state.player.x, state.player.y = 450.0, 300.0
    state.feedback.freeze = 0.0
    return state, boss


def measure(boss_key: str, spell_key: str, seconds: float = 15.0):
    state, boss = arena(boss_key, spell_key)
    before = boss.hp
    rules.cast(state, spell_key)
    chase = spell_key in CHASERS
    for _ in range(int(seconds / C.FIXED_DT)):
        # 場上永遠只有王：小怪會分掉技能的傷害，也會自己去撞玩家。
        state.monsters.clear()
        if chase:
            # 貼上去磨。這正是「在王身上來迴蹭」那個玩法。
            dx = boss.x - state.player.x
            state.player.x += 3.0 if dx > 0 else -3.0
            state.player.y += (boss.y - state.player.y) * 0.08
        state = m.apply_action(state, "tick")
        if not state.bosses:
            return before, 0, True
        boss = state.bosses[0]
    return before, boss.hp, boss.hp <= 0


# ── 技能 × 小怪 ──────────────────────────────────────────────────────
def against(monster_key: str, spell_key: str, seconds: float = 8.0) -> str:
    """一隻怪、一個技能，看那個技能對它做了什麼。

    有兩件事要分清楚，不然量到的全是假的：

    1. **怪不見了不一定是死了。** 它也可能是走到葛蕾特那裡把她啃了 —— 那是
       技能*沒*擋住它。用 stats.reached_sister 分辨。
    2. **apply_action 會深拷貝。** 每一格之後手上那個物件就不是場上那一隻了，
       所以要靠 memory 上的記號重新找回來，不能存參考。
    """
    from gingerbread.model.content import MONSTERS

    meta = m.Meta(night=4)
    meta.skills = [spell_key]
    state = m.new_game(seed=5, meta=meta)
    state = m.apply_action(state, "begin_night")
    state.monsters.clear()
    state.warnings.clear()
    state.sleepers.clear()
    state.player.x, state.player.y = 450.0, 300.0
    # 面向右邊：龍捲風是朝著臉的方向放出去的，而剛出生的漢賽爾臉朝下 ——
    # 那會讓三道風全部從目標旁邊過去，量出來是「這個技能什麼都沒做」。
    state.player.face_x, state.player.face_y = 1.0, 0.0
    beast = rules.make_monster(state, monster_key, 486.0, 300.0)
    beast.wake = 0.0
    beast.memory["probe"] = 1.0
    state.monsters.append(beast)
    spec = MONSTERS[monster_key]
    armour_before = beast.armour
    reached = state.stats.reached_sister
    rules.cast(state, spell_key)

    moved = 0.0
    for _ in range(int(seconds / C.FIXED_DT)):
        found = [x for x in state.monsters if x.memory.get("probe")]
        if not found:
            return ("到妹妹" if state.stats.reached_sister > reached else "死")
        beast = found[0]
        moved = max(moved, abs(beast.x - 486.0) + abs(beast.y - 300.0))
        if spell_key in CHASERS:
            state.player.x += 3.0 if beast.x > state.player.x else -3.0
            state.player.y += (beast.y - state.player.y) * 0.08
        state = m.apply_action(state, "tick")

    found = [x for x in state.monsters if x.memory.get("probe")]
    if not found:
        return "到妹妹" if state.stats.reached_sister > reached else "死"
    beast = found[0]
    marks = []
    if beast.hp < spec.hp:
        marks.append(f"-{spec.hp - beast.hp}")
    if armour_before and beast.armour < armour_before:
        marks.append("破甲")
    if moved > 60:
        marks.append("推開")
    elif beast.stunned > 0:
        marks.append("定住")
    return "".join(marks) or "沒事"


def monster_matrix() -> None:
    from gingerbread.model.content import MONSTERS

    keys = list(MONSTERS)
    print(f"{'技能':<6}", end="")
    for key in keys:
        print(f"{MONSTERS[key].name[:4]:>7}", end="")
    print()
    for spell_key, spec in SPELLS.items():
        print(f"{spec.name:<6}", end="")
        for key in keys:
            print(f"{against(key, spell_key):>7}", end="")
        print()
    print()
    print("「到妹妹」＝這個技能沒攔住它，它走到葛蕾特那裡了。")


def main() -> int:
    order = [k for k in SPELLS]
    width = max(len(SPELLS[k].name) for k in order)
    print(f"{'技能':<{width + 2}}", end="")
    for key in BOSSES:
        print(f"{BOSSES[key].name:>10}", end="")
    print()
    trouble = []
    for spell_key in order:
        spec = SPELLS[spell_key]
        print(f"{spec.name:<{width + 2}}", end="")
        for boss_key in BOSSES:
            before, after, dead = measure(boss_key, spell_key)
            share = (before - after) / max(1, before)
            mark = "！" if share >= 0.5 else " "
            print(f"{share * 100:>8.0f}%{mark}", end="")
            if share >= 0.5:
                trouble.append((spec.name, BOSSES[boss_key].name,
                                share, dead))
        print()
    print()
    if trouble:
        print("一次就打掉一半以上：")
        for name, boss, share, dead in trouble:
            print(f"  {name} → {boss}：{share * 100:.0f}%"
                  + ("（直接死）" if dead else ""))
    else:
        print("沒有任何技能一次打掉王一半以上的血。")
    return 0


if __name__ == "__main__":
    import sys as _sys

    if "--monsters" in _sys.argv:
        monster_matrix()
        raise SystemExit(0)
    raise SystemExit(main())
