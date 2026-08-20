"""Balance measurement harness.

Runs scripted players of three skill levels through the game and reports how
long each survives.  Balance questions are settled here rather than by feel,
because feel is one person playing the version they just tuned.

The interesting output is the **spread**, not the average.  A build where all
three bots die at the same time is not difficult — it has a wall in it that
skill cannot move.  A build where they separate is one where playing better is
worth something.

Usage::

    .venv/bin/python tools/balance.py                 # both modes
    .venv/bin/python tools/balance.py --mode endless
    .venv/bin/python tools/balance.py --sweep ENDLESS_BASE_INTERVAL 2.4 3.2 4.4

The sweep form patches one constant and re-measures, which is how the current
numbers were chosen.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gingerbread import model as m                       # noqa: E402
from gingerbread.model import constants as C             # noqa: E402
from gingerbread.model.content.upgrades import SHOP_ORDER, UPGRADES  # noqa: E402

SEEDS = (1, 7, 42, 77, 113)


# ── the bots ─────────────────────────────────────────────────────────
def _threats(state):
    return [x for x in list(state.monsters) + list(state.bosses) if x.active]


def _steps(px, py, tx, ty, deadzone=5.0):
    out = []
    if tx > px + deadzone:
        out.append("right")
    elif tx < px - deadzone:
        out.append("left")
    if ty > py + deadzone:
        out.append("down")
    elif ty < py - deadzone:
        out.append("up")
    return out


def careless(state):
    """Chases whatever is nearest and swings constantly.

    Swinging out of range wastes the cooldown, which is a real cost — this bot
    exists to measure what that costs.
    """
    live = _threats(state)
    if not live:
        return "tick"
    target = min(live, key=lambda x: math.hypot(x.x - state.player.x,
                                                x.y - state.player.y))
    parts = _steps(state.player.x, state.player.y, target.x, target.y)
    parts.append("swing")
    return "move:" + "+".join(sorted(parts))


def careful(state):
    """Intercepts by urgency and only swings in range."""
    live = _threats(state)
    if not live:
        return "tick"
    target = min(live, key=lambda x: (
        math.hypot(x.x - m.SISTER_X, x.y - m.SISTER_Y) - C.SISTER_REACH)
        / max(1.0, x.speed))
    stats = m.derive(state)
    gap = math.hypot(target.x - state.player.x, target.y - state.player.y)
    parts = _steps(state.player.x, state.player.y, target.x, target.y)
    if gap <= stats.swing_range + 8:
        parts.append("swing")
    if not parts:
        return "swing"
    return "move:" + "+".join(sorted(parts))


def skilled(state):
    """Careful, plus dashing to cover ground and casting when swamped."""
    live = _threats(state)
    if not live:
        return "tick"
    if len(live) >= 6:
        # meta.spells 這個欄位在某次重構之後就不存在了，而這一行從此每一次
        # 都會拋 AttributeError —— 也就是「高手機器人」的那一列數字，已經很久
        # 沒有量到任何東西。
        for key in state.meta.slots:
            if key and state.cooldowns.get(key, 0) <= 0:
                return f"cast:{key}"
    action = careful(state)
    target = min(live, key=lambda x: (
        math.hypot(x.x - m.SISTER_X, x.y - m.SISTER_Y) - C.SISTER_REACH)
        / max(1.0, x.speed))
    gap = math.hypot(target.x - state.player.x, target.y - state.player.y)
    if gap > 170 and state.player.dash_cooldown <= 0 and action.startswith("move:"):
        return action + "+dash"
    return action


BOTS = {"careless": careless, "careful": careful, "skilled": skilled}


# ── decisions the bots make outside combat ───────────────────────────
def pick_offer(state):
    """Take healing when hurt, otherwise the best damage upgrade available."""
    if (state.meta.sister_hp <= state.meta.max_sister_hp - 2
            and "mend" in state.pending_choice):
        return "mend"
    for key in ("grip", "lantern", "reach", "shade", "boots", "stamina"):
        if key in state.pending_choice:
            return key
    return state.pending_choice[0]


def spend_in_shop(state):
    changed = True
    while changed:
        changed = False
        for key in SHOP_ORDER:
            spec = UPGRADES[key]
            level = state.meta.level(key)
            if level >= spec.max_level:
                continue
            if key == "mend" and state.meta.sister_hp >= state.meta.max_sister_hp:
                continue
            if state.meta.sugar < spec.cost(level, C.UPGRADE_PRICE_STEP):
                continue
            before = state.meta.sugar
            state = m.apply_action(state, f"buy:{key}")
            changed = state.meta.sugar != before
    return state


def prepare_day(state):
    """學技能、把上場的兩個位子塞滿。

    **沒有這一步，白天永遠不會結束。** 天黑那顆按鈕要兩個位子都有技能才按得
    下去，而這支工具原本只是一直送 tick —— 所以整個 campaign 量測會停在第一
    個白天，永遠跑不完。（那也是一個好消息：真人玩家不可能卡在這裡，因為第一
    天就有一點技能點可以花。）
    """
    from gingerbread.model.content import SPELLS

    for tier, keys in ((1, ("bolt", "holy", "tornado", "cage")),
                       (2, ("thunderclap", "windrun", "riptide", "blessing"))):
        for key in keys:
            if key in state.meta.skills or state.meta.points_for(tier) <= 0:
                continue
            state = m.apply_action(state, f"learn:{key}")
    for index, tier in ((0, 1), (1, 2)):
        if state.meta.slots[index]:
            continue
        for key in state.meta.skills:
            if SPELLS[key].tier == tier:
                state = m.apply_action(state, f"slot:{index}:{key}")
                break
    return state


# ── runs ─────────────────────────────────────────────────────────────
def run_endless(seed, bot, cap=400_000):
    state = m.new_game(seed=seed, mode=m.Mode.ENDLESS)
    for _ in range(cap):
        state = m.apply_action(state, bot(state))
        if state.pending_choice:
            state = m.apply_action(state, f"choose:{pick_offer(state)}")
        if state.phase is not m.Phase.NIGHT:
            break
    else:
        # Reaching the cap means the bot is effectively immortal at these
        # numbers.  Say so rather than reporting the cap as a survival time.
        print(f"    (seed {seed} hit the {cap}-tick cap and was still alive)")
    return state


def run_campaign(seed, bot, cap=20_000):
    state = m.new_game(seed=seed)
    nights = []
    for _ in range(C.CAMPAIGN_NIGHTS):
        for action in ("whet", "oil", "whet", "oil"):
            state = m.apply_action(state, action)
        state = prepare_day(state)
        if any(slot is None for slot in state.meta.slots):
            print(f"    (seed {seed} 第 {state.meta.night} 夜湊不滿兩個技能，停在白天)")
            break
        state = m.apply_action(state, "begin_night")
        steps = 0
        while state.phase is m.Phase.NIGHT and steps < cap:
            state = m.apply_action(state, bot(state))
            steps += 1
        nights.append((state.meta.night, state.phase.value,
                       state.stats.kills, state.meta.sister_hp))
        if state.phase is not m.Phase.SHOP:
            break
        state = spend_in_shop(state)
        state = m.apply_action(state, "next_night")
    return state, nights


# ── reporting ────────────────────────────────────────────────────────
def report_endless() -> None:
    print("無盡模式　（目標：一般玩家 6–10 分鐘，高手 20 分鐘）")
    for name, bot in BOTS.items():
        times = [run_endless(seed, bot).elapsed for seed in SEEDS]
        average = sum(times) / len(times) / 60
        spread = " ".join(f"{t / 60:.1f}" for t in times)
        print(f"  {name:9s} 平均 {average:5.1f} 分   各場 {spread}")


def report_campaign() -> None:
    print("七夜模式　（目標：謹慎玩家能過第 1–2 夜，高手能通關）")
    for name, bot in BOTS.items():
        reached = []
        for seed in SEEDS:
            state, nights = run_campaign(seed, bot)
            reached.append(C.CAMPAIGN_NIGHTS if state.phase is m.Phase.VICTORY
                           else nights[-1][0])
        average = sum(reached) / len(reached)
        print(f"  {name:9s} 平均撐到第 {average:.1f} 夜   各場 {reached}")


def sweep(name: str, values: list[str]) -> None:
    """Re-measure endless with one constant patched to each value in turn."""
    original = getattr(C, name)
    print(f"掃描 {name}（原值 {original}）")
    for raw in values:
        value = float(raw)
        setattr(C, name, value)
        times = [run_endless(seed, careful).elapsed for seed in SEEDS]
        average = sum(times) / len(times) / 60
        spread = " ".join(f"{t / 60:.1f}" for t in times)
        print(f"  {name}={value:<6} 平均 {average:5.1f} 分   各場 {spread}")
    setattr(C, name, original)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="balance")
    parser.add_argument("--mode", choices=("endless", "campaign", "both"),
                        default="both")
    parser.add_argument("--sweep", nargs="+", metavar=("CONSTANT", "VALUE"),
                        help="patch one constant and re-measure endless")
    args = parser.parse_args(argv)

    if args.sweep:
        sweep(args.sweep[0], args.sweep[1:])
        return 0

    if args.mode in ("endless", "both"):
        report_endless()
    if args.mode in ("campaign", "both"):
        report_campaign()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
