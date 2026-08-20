"""每一隻王，打得死嗎？打多久？

技能對王的傷害上了限之後，要問的下一個問題是「戰鬥還打得完嗎」——一個不會
被技能刪掉、但也七十秒打不死的王，只是換一種輸法。

機器人會走過去揮燈、技能一好就放，然後回報幾秒把王打倒。王之夜有七十秒。

    .venv/bin/python tools/bossfight.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gingerbread import model as m                       # noqa: E402
from gingerbread.model import constants as C             # noqa: E402
from gingerbread.model import rules                      # noqa: E402
from gingerbread.model.content import BOSSES, SPELLS     # noqa: E402

#: 王之夜是第幾夜。
NIGHT_OF = {"slime": 2, "shade_archer": 3, "mist_reaper": 4,
            "ash_hob": 5, "moonfall": 6, "witch": 7}


def fight(boss_key: str, skills: list[str], *, cap: float = 70.0,
          upgrades: int = 2):
    meta = m.Meta(night=NIGHT_OF[boss_key])
    meta.skills = list(skills)
    # 打到那一夜的人身上會有升級。給一個保守的量：攻擊力和揮燈速度各兩級。
    meta.upgrades = {"forge": min(2, upgrades), "swing_rate": upgrades}
    state = m.new_game(seed=11, meta=meta)
    state = m.apply_action(state, "begin_night")
    state.monsters.clear()
    state.warnings.clear()
    state.sleepers.clear()
    rules.spawn_boss(state, boss_key)
    boss = state.bosses[0]
    boss.x, boss.y = 450.0, 200.0
    boss.wake = 0.0
    state.player.x, state.player.y = 450.0, 260.0

    ticks = int(cap / C.FIXED_DT)
    for step in range(ticks):
        state.monsters.clear()          # 只量王，不量小怪
        if not state.bosses:
            return step * C.FIXED_DT, True, 0.0, "kill"
        boss = state.bosses[0]
        for key in skills:
            if state.cooldowns.get(key, 0) <= 0:
                state = m.apply_action(state, f"cast:{key}")
        moves = []
        if boss.x > state.player.x + 6:
            moves.append("right")
        elif boss.x < state.player.x - 6:
            moves.append("left")
        if boss.y > state.player.y + 6:
            moves.append("down")
        elif boss.y < state.player.y - 6:
            moves.append("up")
        moves.append("swing")
        state = m.apply_action(state, "move:" + "+".join(sorted(moves)))
        if state.phase is not m.Phase.NIGHT:
            left = (state.bosses[0].hp / max(1, state.bosses[0].max_hp)
                    if state.bosses else 0.0)
            return (step * C.FIXED_DT, not state.bosses, left,
                    state.phase.value)
    left = state.bosses[0].hp / max(1, state.bosses[0].max_hp)
    return cap, False, left, "night"


def main() -> int:
    matching = {"thunder": ("bolt", "thunderclap"), "light": ("holy", "blessing"),
                "wind": ("tornado", "windrun"), "water": ("cage", "riptide")}
    print(f"{'王':<8}{'弱點':<8}{'只揮燈':>10}{'帶剋星':>10}{'帶錯技能':>12}")
    bad = []
    for key, spec in BOSSES.items():
        weak = spec.weakness
        counter = list(matching.get(weak or "", ("bolt", "thunderclap")))
        wrong = ["holy", "blessing"] if weak != "light" else ["cage", "riptide"]
        plain, ok_plain, left_p, why_p = fight(key, [])
        with_counter, ok_counter, left_c, why_c = fight(key, counter)
        with_wrong, ok_wrong, left_w, why_w = fight(key, wrong)
        名 = spec.name
        def show(secs, ok, left, why):
            if ok:
                return f"{secs:.0f}s"
            tag = {"lost": "死了", "night": "沒打完"}.get(why, why)
            return f"{tag}剩{left * 100:.0f}%"
        print(f"{名:<8}{weak or '無':<8}"
              f"{show(plain, ok_plain, left_p, why_p):>12}"
              f"{show(with_counter, ok_counter, left_c, why_c):>12}"
              f"{show(with_wrong, ok_wrong, left_w, why_w):>14}")
        if not ok_counter:
            bad.append(f"{名}：帶著剋星也打不死")
        elif with_counter >= with_wrong:
            bad.append(f"{名}：剋星沒有比帶錯技能快")
    print()
    for line in bad:
        print("  ! " + line)
    if not bad:
        print("每一隻王都打得死，而且帶剋星比較快。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
