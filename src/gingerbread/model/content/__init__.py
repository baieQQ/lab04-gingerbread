"""All game content, and the check that it is internally consistent.

Everything a designer edits lives in this package.  Nothing here imports the
rules, so a content file can never accidentally depend on engine internals —
which is what keeps the tables movable to JSON later.

:func:`check` runs at startup and fails loudly.  That is deliberate: content
errors are almost always silent otherwise.  A misspelled trait simply does
nothing, a stage naming a monster that was renamed spawns nothing, and both
show up weeks later as "the game feels wrong" rather than as an error anyone
can act on.
"""

from __future__ import annotations

from .bosses import BOSSES
from .events import EVENTS
from .maps import ENDLESS_ROTATION, MAPS
from .monsters import ENDLESS_POOL, MONSTERS
from .spells import SPELLS
from .stages import STAGES, stage_for
from .story import BEATS, ENDLESS_BEAT, Beat
from .upgrades import ENDLESS_OFFER, SHOP_ORDER, UPGRADES

__all__ = [
    "BEATS", "Beat", "BOSSES", "ENDLESS_BEAT", "EVENTS", "MAPS", "MONSTERS", "SPELLS", "STAGES", "UPGRADES",
    "ENDLESS_POOL", "ENDLESS_ROTATION", "ENDLESS_OFFER", "SHOP_ORDER",
    "stage_for", "check",
]


def _spawn_cycles() -> list[str]:
    """Return a problem for every loop in the "this dies into that" graph.

    A monster that splits into itself — or into something that splits back into
    it — spawns forever, and the run degenerates into an unkillable fountain
    that eventually takes the frame rate with it.  It is an easy row to write by
    accident and impossible to spot by reading the table, because each
    individual row looks fine.  Depth-first search catches both the direct case
    and any longer loop.
    """
    graph: dict[str, list[str]] = {}
    for key, spec in MONSTERS.items():
        target = spec.params.get("split_into")
        graph[key] = [str(target)] if target and target in MONSTERS else []

    problems: list[str] = []
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {key: WHITE for key in graph}

    def walk(node: str, trail: list[str]) -> None:
        colour[node] = GREY
        for nxt in graph[node]:
            if colour[nxt] == GREY:
                loop = " -> ".join(trail[trail.index(nxt):] + [nxt])
                problems.append(f"monsters spawn in a loop: {loop}")
            elif colour[nxt] == WHITE:
                walk(nxt, trail + [nxt])
        colour[node] = BLACK

    for key in graph:
        if colour[key] == WHITE:
            walk(key, [key])
    return problems


def _gretel_is_reachable() -> list[str]:
    """Fail any map whose obstacles wall Gretel off.

    She stands at a fixed point and never moves, so an obstacle placed on or
    beside her stops every monster from ever getting within her reach — and the
    night becomes unloseable while looking completely normal.  It happened:
    two of the maps below shipped with a blocker centred exactly on her, and
    the balance figures measured from those nights were meaningless until this
    check found them.

    Two rules.  Nothing may overlap the ring a monster has to stand in to take
    her, and enough of that ring must stay open that she can actually be
    approached.
    """
    import math

    from .. import constants as C

    smallest = min(spec.radius for spec in MONSTERS.values())
    contact = C.SISTER_REACH + smallest
    problems: list[str] = []

    for key, spec in MAPS.items():
        open_arcs = 0
        for step in range(36):
            angle = step * math.tau / 36
            px = C.SISTER_X + math.cos(angle) * contact
            py = C.SISTER_Y + math.sin(angle) * contact
            blocked = any(
                math.hypot(px - ox, py - oy) <= orad + smallest
                for ox, oy, orad, _occludes in spec.obstacles
            )
            if not blocked:
                open_arcs += 1

        for ox, oy, orad, _occludes in spec.obstacles:
            gap = math.hypot(ox - C.SISTER_X, oy - C.SISTER_Y)
            if gap < orad + contact:
                problems.append(
                    f"map {key!r}: obstacle at ({ox:.0f}, {oy:.0f}) r={orad:.0f} "
                    f"is {gap:.0f} from Gretel — a monster of radius "
                    f"{smallest:.0f} can never reach her, so the night cannot "
                    f"be lost"
                )
        # Hansel starts at a fixed point too, and an obstacle sitting on it
        # traps him completely: the slide-along-walls logic finds every
        # candidate position blocked and refuses to move at all, so the night
        # begins with a player who cannot walk.  It shipped that way on two
        # maps.
        spawn_x, spawn_y = C.SISTER_X, C.SISTER_Y + 92.0
        for ox, oy, orad, _occludes in spec.obstacles:
            gap = math.hypot(ox - spawn_x, oy - spawn_y)
            if gap < orad + C.PLAYER_RADIUS + 6:
                problems.append(
                    f"map {key!r}: obstacle at ({ox:.0f}, {oy:.0f}) r={orad:.0f} "
                    f"covers Hansel's spawn point — he starts unable to move")

        if open_arcs < 8:
            problems.append(
                f"map {key!r}: only {open_arcs}/36 approaches to Gretel are "
                f"open; she is walled in"
            )
    return problems


def check() -> None:
    """Validate every cross-reference in the content tables.

    Raises ``LookupError`` listing **all** problems at once — fixing a content
    table one crash at a time is miserable, and a designer who has just renamed
    a monster wants the whole blast radius in one message.
    """
    from ..registry import validate_names

    problems: list[str] = []

    # ── every key matches the dict it is filed under ─────────────────
    for table_name, table in (("monsters", MONSTERS), ("bosses", BOSSES),
                              ("maps", MAPS), ("upgrades", UPGRADES),
                              ("spells", SPELLS), ("events", EVENTS)):
        for filed_under, spec in table.items():
            if spec.key != filed_under:
                problems.append(
                    f"{table_name}[{filed_under!r}] has key={spec.key!r}; "
                    "the dict key and the spec key must match"
                )

    # ── stages point at real maps, monsters and bosses ───────────────
    for night, stage in STAGES.items():
        if stage.night != night:
            problems.append(f"stages[{night}] declares night={stage.night}")
        if stage.map_key not in MAPS:
            problems.append(f"night {night}: unknown map {stage.map_key!r}")
        for name in stage.recipe:
            if name not in MONSTERS:
                problems.append(f"night {night}: unknown monster {name!r}")
        if stage.boss is not None and stage.boss not in BOSSES:
            problems.append(f"night {night}: unknown boss {stage.boss!r}")
        if any(t < 0 for t in stage.surges):
            problems.append(f"night {night}: a surge time is negative")

    # ── bosses summon things that exist, and their phases descend ────
    for key, boss in BOSSES.items():
        if not boss.phases:
            problems.append(f"boss {key!r}: no phases")
        previous = 1.1
        for index, phase in enumerate(boss.phases):
            if phase.until_hp >= previous:
                problems.append(
                    f"boss {key!r} phase {index}: until_hp={phase.until_hp} is not "
                    f"below the previous phase's {previous}; phases must descend"
                )
            previous = phase.until_hp
            for summon, every in phase.summons:
                if summon not in MONSTERS:
                    problems.append(
                        f"boss {key!r} phase {index}: unknown summon {summon!r}")
                if every <= 0:
                    problems.append(
                        f"boss {key!r} phase {index}: summon interval must be > 0")
        if boss.phases and boss.phases[-1].until_hp > 0:
            problems.append(
                f"boss {key!r}: the last phase must run to until_hp=0, "
                f"or the boss becomes unkillable below {boss.phases[-1].until_hp}"
            )

    # ── traits that spawn other monsters name real ones ──────────────
    for key, spec in MONSTERS.items():
        target = spec.params.get("split_into")
        if target is not None and target not in MONSTERS:
            problems.append(f"monster {key!r}: split_into {target!r} does not exist")
        if spec.hp <= 0:
            problems.append(f"monster {key!r}: hp must be positive")
        if spec.radius <= 0:
            problems.append(f"monster {key!r}: radius must be positive")

    problems.extend(_spawn_cycles())
    problems.extend(_gretel_is_reachable())

    # ── shop and endless offers reference real upgrades ──────────────
    for name in SHOP_ORDER:
        if name not in UPGRADES:
            problems.append(f"SHOP_ORDER names unknown upgrade {name!r}")
    for name in ENDLESS_OFFER:
        if name not in UPGRADES:
            problems.append(f"ENDLESS_OFFER names unknown upgrade {name!r}")
    for name, _weight in ENDLESS_POOL:
        if name not in MONSTERS:
            problems.append(f"ENDLESS_POOL names unknown monster {name!r}")
    for name in ENDLESS_ROTATION:
        if name not in MAPS:
            problems.append(f"ENDLESS_ROTATION names unknown map {name!r}")

    if problems:
        raise LookupError(
            "content tables are inconsistent:\n  " + "\n  ".join(problems))

    # Behaviour and trait names are checked separately, because that needs the
    # registries to be populated — which only happens once behaviours.py has
    # been imported.
    validate_names(
        [(f"怪物 {key}", spec.behaviour, spec.traits, spec.params)
         for key, spec in MONSTERS.items()]
        + [(f"頭目 {key}", boss.phases[0].behaviour, boss.traits, boss.params)
           for key, boss in BOSSES.items()]
        + [(f"頭目 {key} 第 {i + 1} 階段", phase.behaviour, (), phase.params)
           for key, boss in BOSSES.items()
           for i, phase in enumerate(boss.phases)]
    )


def newcomers(night: int) -> tuple[str, ...]:
    """Return the species appearing for the first time on ``night``.

    Derived from the stage table rather than written down beside it.  A list
    typed by hand goes stale the first time somebody reorders a night's cast,
    and it goes stale silently — the game would introduce a monster that no
    longer comes, and say nothing about the one that does.
    """
    stage = STAGES.get(night)
    if stage is None:
        return ()
    seen: set[str] = set()
    for earlier in range(1, night):
        past = STAGES.get(earlier)
        if past is not None:
            seen.update(past.recipe)
            if past.boss:
                seen.add(past.boss)
    fresh = [key for key in dict.fromkeys(stage.recipe) if key not in seen]
    return tuple(fresh)
