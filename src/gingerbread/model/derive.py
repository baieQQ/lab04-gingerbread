"""Derived player statistics, and the world's light geometry.

Two kinds of "computed from state" live here, and both exist so that the answer
is computed in exactly one place.

**Player stats.**  Attack, light radius, swing speed and the rest are a base
value plus whatever the bought upgrades add.  The rules ask for the total; they
never know which upgrades exist.  So a new upgrade is one row in
``content/upgrades.py``, and every rule that reads that stat picks it up for
free.

**Lights.**  Lighting is a rule, not decoration — a light-fearing monster
freezes when lit, so the model has to be able to answer "is this point lit?"
without a display.  The renderer asks this module for the same list it draws,
which is what keeps what the player *sees* and what the rules *do* in step.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import constants as C
from .content.monsters import MONSTERS
from .content.upgrades import UPGRADES
from .entities import Light

if TYPE_CHECKING:                      # pragma: no cover - typing only
    from .state import Meta, State


@dataclass(frozen=True, slots=True)
class Derived:
    """The player's effective numbers after upgrades, this night's bonuses and
    any temporary condition."""

    attack: int
    light: float
    swing_range: float
    swing_arc: float
    swing_cooldown: float
    move_speed: float
    max_hp: int
    #: Multiplier on every skill cooldown; 1.0 is unmodified.
    cooldown_scale: float = 1.0


def _totals(meta: "Meta") -> dict[str, float]:
    """Sum every bought upgrade into its target stat.

    Unknown keys are ignored rather than raising: a save file written before an
    upgrade was renamed should still load and simply lose that upgrade, not
    refuse to start the game.
    """
    out: dict[str, float] = {}
    for key, level in meta.upgrades.items():
        spec = UPGRADES.get(key)
        if spec is None or level <= 0:
            continue
        capped = min(level, spec.max_level)
        out[spec.stat] = out.get(spec.stat, 0.0) + spec.per_level * capped
    return out


def derive(state: "State") -> Derived:
    """Return the player's effective stats right now.

    Night-only bonuses (whetting the lantern, adding oil) are stored as
    upgrade levels on a temporary key that the night clears, so they flow
    through the same summation as permanent growth instead of needing their own
    branch in every rule that reads a stat.
    """
    totals = _totals(state.meta)

    # Percentage upgrades compound.  "+12% attack speed" four times is
    # 1.12**4, not 1.48 — which is why these are kept apart from the flat ones
    # and applied multiplicatively.  Compounding is what stops the fifth
    # purchase feeling like the first.
    haste = (1.0 + totals.get("swing_speed_pct", 0.0))
    cooldown = C.SWING_COOLDOWN / max(0.2, haste)

    light = ((C.START_LIGHT
              * (1.0 + totals.get("light_pct", 0.0))
              + totals.get("light", 0.0))
             * float(state.meta.dials["light"])
             * state.light_scale * state.fog_scale)
    if state.player.doused > 0:
        light *= C.DOUSE_FACTOR
    if state.player.downed > 0:
        light = C.DOWNED_LIGHT_RADIUS

    arc = C.SWING_ARC + math.radians(totals.get("swing_arc_deg", 0.0))

    # Skill cooldowns, floored at half.  A cap rather than a soft curve because
    # the player should be able to read "−50%" off the shop and have it be true;
    # a diminishing return that quietly stops at −38% is a lie in a menu.
    cooldown_scale = max(C.COOLDOWN_FLOOR,
                         1.0 - totals.get("cooldown_pct", 0.0))

    return Derived(
        attack=int(1 + totals.get("attack", 0.0)),
        light=min(light, C.LIGHT_CAP),
        swing_range=min(C.SWING_RANGE + totals.get("swing_range", 0.0),
                        C.SWING_RANGE_CAP),
        swing_arc=min(arc, C.SWING_ARC_CAP),
        swing_cooldown=max(cooldown, C.SWING_COOLDOWN_CAP),
        move_speed=min(C.WALK_SPEED + totals.get("move_speed", 0.0),
                       C.WALK_SPEED_CAP),
        max_hp=min(int(C.PLAYER_START_HP + totals.get("player_hp", 0.0)),
                   C.PLAYER_MAX_HP_CAP),
        cooldown_scale=cooldown_scale,
    )


def element_multiplier(element: str | None, weakness: str | None) -> float:
    """Return the damage multiplier for hitting ``weakness`` with ``element``."""
    if element is None or weakness is None:
        return 1.0
    return C.WEAKNESS_MULTIPLIER if element == weakness else 1.0


def lights_of(state: "State") -> list[Light]:
    """Return every light in the world this tick.

    Order matters only for drawing, not for rules.  The lantern comes first so
    the renderer can treat ``[0]`` as the warm one without a search.
    """
    stats = derive(state)
    lights = [Light(state.player.x, state.player.y, stats.light,
                    cold=False, source="lantern")]

    # Gretel carries a small ember of her own.  She has to stay visible even
    # when the lantern is far away or doused: the person being protected is the
    # anchor that makes the darkness meaningful instead of merely obstructive.
    lights.append(Light(C.SISTER_X, C.SISTER_Y, C.SISTER_LIGHT_RADIUS,
                        cold=True, source="sister"))

    for drop in state.drops:
        if not drop.fake:
            # Small on purpose.  At 22 px a handful of dropped crystals lit the
            # entire field and quietly undid the darkness the game is built on —
            # the loot was defeating the central mechanic.  Just enough to catch
            # the eye, not enough to navigate by.
            lights.append(Light(drop.x, drop.y, 9.0, cold=True, source="drop"))

    for x, y, radius in state.map_lights:
        lights.append(Light(x, y, radius * state.light_scale * state.fog_scale,
                            cold=True, source="map"))

    # A twister and a water trap both glow.  Without this a trap the player set
    # themselves is invisible the moment they walk away from it, which makes
    # placing one an act of faith rather than a plan.  Marked cold so it is
    # excluded from ``FEARED_SOURCES`` — these must not freeze light-fearing
    # monsters, or the trap would repel the very things it exists to catch.
    # Anything holding a shot lights itself up.  A ranged attacker in the dark
    # is unanswerable — the player cannot go and deal with what they cannot
    # find — and unanswerable is not the same as hard.  ``source="tell"`` keeps
    # it out of ``FEARED_SOURCES``, so a wind-up never freezes anything.
    # A boss that has planted itself to work is *lit* by the work.  Without
    # this the reaper's fog would be a puzzle whose answer — go and hit the
    # thing that is doing it — is hidden by the puzzle itself, and the player
    # would be reduced to sweeping a black screen with a lantern.
    for boss in state.bosses:
        if boss.memory.get("planted", 0.0) > 0:
            lights.append(Light(boss.x, boss.y, C.CHANNEL_LIGHT_RADIUS,
                                cold=True, source="tell"))

    for monster in state.monsters:
        if monster.charge <= 0:
            continue
        row = MONSTERS.get(monster.spec)
        if row is not None and row.charge_light > 0:
            lights.append(Light(monster.x, monster.y, row.charge_light,
                                cold=False, source="tell"))

    for hazard in state.hazards:
        lights.append(Light(hazard.x, hazard.y, hazard.radius * 0.9,
                            cold=True, source="hazard"))

    # Moonlight reveals the whole field.  It is marked ``source="reveal"`` so
    # the light-fearing test can exclude it: a ten-second event that pinned
    # every such monster in place would not be a twist, it would be a pause.
    if state.reveal_ticks > 0:
        lights.append(Light(C.SISTER_X, C.SISTER_Y, 760.0,
                            cold=True, source="reveal"))

    return lights


#: Sources a light-fearing monster reacts to.  The lantern is the weapon; a
#: chapel candle counts too, which is what lets a map's fixed lights interact
#: with the bestiary for free.  Moonlight deliberately does not.
FEARED_SOURCES: tuple[str, ...] = ("lantern", "map")


def is_lit(state: "State", x: float, y: float, *,
           lantern_only: bool = False,
           fraction: float = C.LIT_FRACTION) -> bool:
    """Return True when (x, y) sits in the bright part of a qualifying light.

    ``fraction`` is deliberately a parameter rather than a constant.  Two rules
    ask about light and they need different edges: a light-fearing monster
    freezes only in the genuinely bright core, while a monster that keeps to the
    rim of the lantern's reach cares about the outermost visible edge.  Hard-
    coding one threshold would make the other feel wrong, and at a fully
    upgraded lantern the gap between them is over a hundred pixels.
    """
    for light in lights_of(state):
        if lantern_only and light.source not in FEARED_SOURCES:
            continue
        if light.covers(x, y, fraction):
            return True
    return False


def light_level(state: "State", x: float, y: float) -> float:
    """Return how lit (x, y) is, from 0 (black) to 1 (full brightness).

    Uses ``max`` across lights, never a sum.  That matches how the renderer
    composites the darkness mask, and the match is the point: if this said
    "lit" where the screen shows black, a light-fearing monster would freeze in
    a place the player cannot see, and the game would look broken while
    behaving exactly as designed.
    """
    best = 0.0
    for light in lights_of(state):
        if light.radius <= 0:
            continue
        d = math.hypot(x - light.x, y - light.y)
        level = 1.0 - (d / light.radius)
        if level > best:
            best = level
    return max(0.0, min(1.0, best))
