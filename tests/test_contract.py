"""Tests for the four contract functions.

Each test names the rule it protects and states the expected observation before
asserting it.  None of them opens a display or presses a key: the whole game is
simulated, which is what makes a failure reproducible from a seed alone.
"""

from __future__ import annotations

import copy
import json
import math

import pytest

from gingerbread import model as m
from gingerbread.model import geometry as g


# ── 1. fresh / restart ───────────────────────────────────────────────
def test_new_game_is_deterministic_for_the_same_seed() -> None:
    """Rule: same seed -> same starting snapshot."""
    assert m.snapshot(m.new_game(seed=42)) == m.snapshot(m.new_game(seed=42))


def test_the_seed_does_not_change_the_opening_layout() -> None:
    """Rule: the seed drives reinforcements, not who is standing there at dusk.

    Which faces the player learns to recognise must not be luck — the whole
    premise is that tonight's monsters are the people you saw in daylight.
    """
    a = m.new_game(seed=1)
    b = m.new_game(seed=999)
    assert a.sleepers == b.sleepers


def test_a_fresh_game_starts_with_gretel_at_full_health() -> None:
    state = m.new_game(seed=3)
    assert state.meta.sister_hp == m.SISTER_MAX_HP
    assert state.player.hp == state.player.max_hp


# ── 2. normal actions ────────────────────────────────────────────────
def test_the_day_sells_permanent_upgrades() -> None:
    """Rule: sugar is spent in daylight, and what it buys does not expire.

    The day used to sell temporary buffs *and* a screen between nights sold
    permanent ones.  Two shops with opposite rules is one shop too many, and the
    player had to hold both in their head to plan a night.
    """
    state = m.new_game(seed=7)
    state.meta.sugar = 40
    before = m.derive(state).attack

    after = m.apply_action(state, "buy:lantern")
    assert after.meta.sugar < state.meta.sugar
    assert m.derive(after).attack == before + 1

    # And it survives into the next night, unlike the old day buff.
    carried = copy.deepcopy(after.meta)
    carried.night += 1
    assert m.derive(m.new_game(seed=7, meta=carried)).attack == before + 1


def test_skills_are_bought_and_equipped_in_daylight() -> None:
    """Rule: the day's other job is choosing what to carry.

    Each slot is one tier's shelf — L carries a first-tier skill, ；a
    second-tier one — and each shelf has its own pool of points, so buying a
    two-point skill never costs the player a one-point one.
    """
    state = m.new_game(seed=7)
    assert state.meta.slots == [None, None], "nothing is handed over"
    assert state.meta.skill_points_1 == 1
    assert state.meta.skill_points_2 == 1, "one of each on the first day"

    # A second-tier skill lands on the second shelf and spends only that pool.
    after = m.apply_action(state, "learn:thunderclap")
    assert after.meta.slots[1] == "thunderclap"
    assert after.meta.skill_points_2 == 0
    assert after.meta.skill_points_1 == 1, "the first shelf is untouched"
    assert "thunderclap" in after.meta.skills

    # A first-tier skill lands on the first shelf and cannot go on the second.
    both = m.apply_action(after, "learn:cage")
    assert both.meta.slots == ["cage", "thunderclap"]
    with pytest.raises(m.ActionError):
        m.apply_action(both, "slot:1:cage")

    # Learning it twice must not cost a second point.
    again = m.apply_action(both, "learn:cage")
    assert again.meta.skill_points_1 == both.meta.skill_points_1

    # And with the pool empty, a second first-tier skill is refused.
    broke = m.apply_action(both, "learn:bolt")
    assert "bolt" not in broke.meta.skills


def test_the_day_waits_for_the_player() -> None:
    """Rule: daylight has no clock; only ``begin_night`` ends it.

    It was timed when it rationed action points.  As a shop and a loadout
    screen, a countdown would only punish the player for reading it.
    """
    state = m.new_game(seed=5)
    for _ in range(m.to_ticks(m.DAY_SECONDS) * 3):
        state = m.apply_action(state, "tick")
    assert state.phase is m.Phase.DAY
    assert m.apply_action(state, "begin_night").phase is m.Phase.NIGHT


# ── 3. boundaries and invalid input ──────────────────────────────────
def test_unknown_action_raises() -> None:
    """Rule: a bad action is a programming error, not a silent no-op.

    Actions will be fed in from content and input tables, so a typo has to fail
    loudly — an over-permissive parser hides the mistake until someone notices
    a control that never worked.
    """
    state = m.new_game(seed=1)
    for bad in ("fly", "move:", "move:sideways", "buy:nothing", "cast:fireball"):
        with pytest.raises(m.ActionError):
            m.apply_action(state, bad)


def test_actions_illegal_in_this_phase_are_ignored_not_charged() -> None:
    """Rule: an impossible action must never cost the player anything."""
    state = m.new_game(seed=1)
    assert m.apply_action(state, "buy:haste").meta.sugar == state.meta.sugar
    assert m.apply_action(state, "next_night").phase is state.phase


def test_player_is_clamped_inside_the_playfield_on_every_side() -> None:
    """Rule: the player's centre stays within the margin, inclusive."""
    state = m.apply_action(m.new_game(seed=1), "begin_night")
    for _ in range(600):
        state = m.apply_action(state, "move:left+up")
    assert state.player.x == pytest.approx(m.constants.PLAY_MARGIN)
    assert state.player.y == pytest.approx(m.constants.PLAY_MARGIN)


def test_tangent_circles_count_as_contact() -> None:
    """Rule: touching at exactly one point IS contact (inclusive boundary)."""
    assert g.circles_touch(0, 0, 10, 25, 0, 15) is True
    assert g.circles_touch(0, 0, 10, 25.001, 0, 15) is False


def test_spawn_points_always_land_on_an_edge() -> None:
    """Regression: the web build sampled x and y from two separate rolls.

    A quarter of all arrivals therefore appeared in the middle of the field,
    next to Gretel, with no approach to intercept.
    """
    from gingerbread.model.rng import Rng

    rng = Rng(1234)
    inset = m.constants.SPAWN_EDGE_INSET
    for _ in range(4000):
        x, y = g.edge_point(rng)
        on_edge = (
            math.isclose(x, inset) or math.isclose(x, m.WIDTH - inset)
            or math.isclose(y, inset) or math.isclose(y, m.HEIGHT - inset)
        )
        assert on_edge, f"({x}, {y}) is not on the perimeter"


# ── 4. terminal rule ─────────────────────────────────────────────────
def test_is_terminal_only_at_a_real_ending() -> None:
    """Rule: day, night and the shop are all in progress; only loss/victory end."""
    state = m.new_game(seed=3)
    assert m.is_terminal(state) is False
    assert m.is_terminal(m.apply_action(state, "begin_night")) is False


def test_losing_every_heart_ends_the_run() -> None:
    """Rule: the run ends when Gretel is taken."""
    state = m.apply_action(m.new_game(seed=5), "begin_night")
    for _ in range(m.to_ticks(m.NIGHT_SECONDS) + 20):
        state = m.apply_action(state, "tick")          # never defend
        if m.is_terminal(state):
            break
    assert state.phase is m.Phase.LOST
    assert state.meta.sister_hp == 0


def test_hearts_never_go_below_zero() -> None:
    """Invariant: 0 <= sister_hp <= SISTER_MAX_HP at every observed tick.

    Regression: the previous version subtracted once per monster arriving in
    the same tick with no floor, and reached -5 under a crowd.
    """
    state = m.apply_action(m.new_game(seed=57), "begin_night")
    for _ in range(m.to_ticks(m.NIGHT_SECONDS) + 20):
        state = m.apply_action(state, "tick")
        assert 0 <= state.meta.sister_hp <= m.SISTER_MAX_HP
        if m.is_terminal(state):
            break


def test_going_down_does_not_end_the_night_by_itself() -> None:
    """Rule: the run ends because Gretel was taken, never because Hansel tired.

    Measured before this was fixed: across three scripted skill levels and
    several seeds, *every* loss came from Hansel going down and none from
    Gretel — which inverts what the game is about.
    """
    state = m.apply_action(m.new_game(seed=5), "begin_night")
    saw_down = False
    for _ in range(m.to_ticks(m.NIGHT_SECONDS) + 20):
        # Walk *into* the crowd without ever swinging: the fastest way to get
        # knocked down repeatedly, which is exactly the case under test.
        target = min(state.monsters,
                     key=lambda mo: math.hypot(mo.x - state.player.x,
                                               mo.y - state.player.y),
                     default=None)
        if target is None:
            action = "tick"
        else:
            parts = []
            if target.x > state.player.x + 2:
                parts.append("right")
            elif target.x < state.player.x - 2:
                parts.append("left")
            if target.y > state.player.y + 2:
                parts.append("down")
            elif target.y < state.player.y - 2:
                parts.append("up")
            action = "move:" + "+".join(sorted(parts)) if parts else "tick"

        state = m.apply_action(state, action)
        if state.player.downs > 0:
            saw_down = True
        if m.is_terminal(state):
            break

    assert saw_down, "walking into every monster should knock Hansel down"
    assert state.phase is m.Phase.LOST
    assert state.meta.sister_hp == 0, "the loss must be Gretel's hearts running out"


# ── 5. invariant: apply_action must not mutate its input ─────────────
def test_apply_action_never_changes_the_supplied_state() -> None:
    """Rule: apply_action returns a NEW state and leaves the old one intact."""
    state = m.apply_action(m.new_game(seed=11), "begin_night")
    before = m.snapshot(state)
    for action in ("tick", "move:right", "swing", "move:up+dash", "cast:bolt"):
        result = m.apply_action(state, action)
        assert m.snapshot(state) == before, f"{action} mutated the input state"
        assert result is not state


# ── 6. replay determinism ────────────────────────────────────────────
def test_the_same_script_replays_to_the_same_snapshot() -> None:
    """Rule: a fixed seed plus a fixed action list reproduces exactly."""
    script = ["begin_night"] + ["move:right+swing", "tick", "move:up"] * 300
    first = m.run_script(42, script)
    second = m.run_script(42, script)
    assert m.snapshot(first) == m.snapshot(second)
    assert m.snapshot(first)["digest"] == m.snapshot(second)["digest"]


def test_different_seeds_diverge() -> None:
    """A determinism test that cannot fail proves nothing; this pins the other side."""
    script = ["begin_night"] + ["tick"] * 900
    assert (m.snapshot(m.run_script(1, script))["digest"]
            != m.snapshot(m.run_script(2, script))["digest"])


def test_snapshot_is_json_safe() -> None:
    """Rule: evidence must survive being written to a file unchanged."""
    state = m.apply_action(m.new_game(seed=8), "begin_night")
    for _ in range(200):
        state = m.apply_action(state, "move:left+swing")
    text = json.dumps(m.snapshot(state), sort_keys=True)
    assert json.loads(text) == m.snapshot(state)


def test_snapshot_notices_a_single_pixel_of_drift() -> None:
    """Rule: the evidence must be able to *see* a divergence.

    The previous snapshot rounded coordinates to three decimals and only
    counted entities, so two runs that had drifted apart compared equal for
    thousands of ticks.  Evidence that cannot fail is not evidence.
    """
    state = m.apply_action(m.new_game(seed=8), "begin_night")
    for _ in range(120):
        state = m.apply_action(state, "tick")

    nudged = m.apply_action(state, "tick")
    nudged.player.x += 1e-9
    assert m.snapshot(nudged)["digest"] != m.snapshot(m.apply_action(state, "tick"))["digest"]


# ── 7. modes ─────────────────────────────────────────────────────────
def test_endless_starts_at_night_and_has_no_day() -> None:
    """Rule: the two modes are different games, and the state says which."""
    state = m.new_game(seed=4, mode=m.Mode.ENDLESS)
    assert state.phase is m.Phase.NIGHT
    assert state.meta.mode is m.Mode.ENDLESS
    assert m.snapshot(state)["mode"] == "endless"


def test_endless_never_reaches_dawn() -> None:
    """Rule: endless ends only when Gretel is taken."""
    state = m.new_game(seed=4, mode=m.Mode.ENDLESS)
    for _ in range(m.to_ticks(m.NIGHT_SECONDS) + 600):
        state = m.apply_action(state, "tick")
        if m.is_terminal(state):
            break
        assert state.phase is m.Phase.NIGHT


def test_the_two_modes_do_not_share_a_replay_hash() -> None:
    script = ["tick"] * 400
    a = m.run_script(9, script, mode=m.Mode.ENDLESS)
    b = m.run_script(9, ["begin_night"] + script)
    assert m.snapshot(a)["digest"] != m.snapshot(b)["digest"]
