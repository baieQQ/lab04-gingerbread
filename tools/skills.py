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
    raise SystemExit(main())
