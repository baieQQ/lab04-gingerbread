"""Pure geometry shared by the rules.

Every function here is a total function of its arguments: no state, no
randomness that is not passed in, no clock.  Collision, sight and spawn
placement all go through these, so there is exactly one definition of "touching"
and exactly one definition of "blocked" in the whole game.
"""

from __future__ import annotations

import math
from typing import Final, Iterable, TYPE_CHECKING

from . import constants as C

if TYPE_CHECKING:                      # pragma: no cover - typing only
    from .entities import Obstacle


def clamp(value: float, low: float, high: float) -> float:
    """Return ``value`` constrained to the inclusive interval [low, high]."""
    return max(low, min(high, value))


def distance(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def distance_squared(ax: float, ay: float, bx: float, by: float) -> float:
    """Squared distance — use this for comparisons to skip the square root."""
    dx, dy = ax - bx, ay - by
    return dx * dx + dy * dy


def circles_touch(ax: float, ay: float, ar: float,
                  bx: float, by: float, br: float) -> bool:
    """Return True when two circles overlap **or touch at exactly one point**.

    ``<=`` so tangency counts as contact.  Ambiguity at the boundary is where
    "he definitely didn't hit me" bug reports come from, so the rule is stated
    once, here, and every caller inherits it.
    """
    reach = ar + br
    return distance_squared(ax, ay, bx, by) <= reach * reach


def normalise(dx: float, dy: float) -> tuple[float, float]:
    """Return a unit vector, or (0, 0) for a zero-length input.

    Returning zero rather than raising means "no direction" is representable,
    which callers want far more often than they want an exception.
    """
    length = math.hypot(dx, dy)
    if length == 0.0:
        return (0.0, 0.0)
    return (dx / length, dy / length)


def angle_between(ax: float, ay: float, bx: float, by: float) -> float:
    """Angle in radians from point A to point B."""
    return math.atan2(by - ay, bx - ax)


def angle_difference(a: float, b: float) -> float:
    """Smallest absolute angle between two headings, in [0, pi].

    Written with the modulo trick rather than repeated add/subtract loops so it
    is constant time and cannot spin on a pathological input.
    """
    return abs(((a - b + math.pi * 3) % math.tau) - math.pi)


#: The swing cone's half-angle, given as its cosine and sine rather than as an
#: angle.  Written as literals on purpose: ``math.cos``/``sin``/``atan2``/``asin``
#: are handed to the platform's C library, and a one-unit-in-the-last-place
#: difference between macOS and WebAssembly was measured to change the outcome
#: of 64 out of 72 simulated nights.  ``math.hypot`` is safe — CPython
#: implements it itself — so distance work can stay as it is, but every angle
#: comparison here is built from multiplication and addition only, which IEEE
#: 754 guarantees to be bit-identical everywhere.
#:
#: These correspond to 0.78 radians (about 44.7°); ``tests`` pins them against
#: ``math`` so editing one without the other is caught.
ARC_COS: Final = 0.7109135380122773
ARC_SIN: Final = 0.7032794192004103


def within_cone(origin_x: float, origin_y: float,
                face_x: float, face_y: float,
                target_x: float, target_y: float, target_radius: float,
                reach: float,
                arc_cos: float = ARC_COS, arc_sin: float = ARC_SIN) -> bool:
    """Return True when a circular target is inside the swing cone.

    Takes the facing as a **unit vector**, not an angle, so no ``atan2`` is
    needed to produce it and none is needed to compare it.

    The cone widens for bigger targets: a brute at the very edge of the arc
    should be hittable, because the player is aiming at a body rather than at a
    point.  That widening is done by measuring the target's distance from the
    cone's two boundary rays instead of by adding ``asin(r/d)`` to an angle —
    same result, no libm.
    """
    vx, vy = target_x - origin_x, target_y - origin_y
    d = math.hypot(vx, vy)
    if d > reach + target_radius:
        return False
    if d <= target_radius:
        return True                      # standing inside it: always a hit

    # Is the centre inside the cone?  cos is monotonically decreasing over
    # [0, pi], so "angle <= half_arc" is exactly "cosine >= cos(half_arc)".
    if (vx * face_x + vy * face_y) / d >= arc_cos:
        return True

    # Otherwise the body may still overlap a boundary ray.  Rotating the facing
    # by ±half_arc needs only the cosine and sine already in hand.
    for sign in (1.0, -1.0):
        ux = face_x * arc_cos - face_y * (arc_sin * sign)
        uy = face_x * (arc_sin * sign) + face_y * arc_cos
        along = vx * ux + vy * uy
        if along <= 0.0:
            continue                     # the ray points away from the target
        if along > reach:
            along = reach                # clamp to the cone's finite length
        if math.hypot(vx - ux * along, vy - uy * along) <= target_radius:
            return True
    return False


def ring_offset(rng, index: int, count: int, radius: float,
                jitter: float = 0.0) -> tuple[float, float]:
    """Return a point on a circle, rounded so platforms agree.

    ``cos``/``sin`` come from the platform's C library, so two machines can
    disagree in the last bit.  That difference is around 1e-16 and it compounds:
    a run was measured to grow a 1e-13 pixel discrepancy into a visible one in
    under a minute.  Rounding to nine decimals is far finer than anything the
    game can express — sub-nanometre, on a 900-pixel field — and it erases the
    disagreement entirely.
    """
    turn = (index / max(1, count)) * math.tau + 0.4
    if jitter:
        turn += rng.between(-jitter, jitter)
    return (round(math.cos(turn) * radius, 9),
            round(math.sin(turn) * radius, 9))


def perimeter_slot(index: int, count: int,
                   inset: float = C.SPAWN_EDGE_INSET) -> tuple[float, float]:
    """第 ``index`` 個位置，沿著左右兩側均分。**不用亂數。**

    白天站在場邊的那些村民就是今晚會變的那些怪，而「今晚會遇到誰」是設計，不
    是運氣 —— 所以它們的位置由索引決定，不由種子決定。這是有測試在守的規則。

    只用左右兩側：場地 900×520，從上下走到葛蕾特面前的路程只有一半多，而白天
    的村民排在哪一邊，決定的是玩家有多少時間攔它。
    """
    half = max(1, (count + 1) // 2)
    row = index // 2
    x = inset if index % 2 == 0 else C.WIDTH - inset
    span = C.HEIGHT - inset * 2
    y = inset + span * ((row + 0.5) / half)
    return (x, y)


def side_point(rng, inset: float = C.SPAWN_EDGE_INSET) -> tuple[float, float]:
    """只從左右兩邊進場。

    場地是 900×520 —— 寬比高多了將近一倍。從上下進來的東西，走到葛蕾特面前的
    路程只有從左右進來的一半多一點，所以同一隻怪從哪一邊來，難度差很多。鏡子
    怪要繞到背後才打得到，那個繞行需要空間，從上下進場等於沒有空間。
    """
    if rng.below(2) == 0:
        return (inset, inset + rng.random() * (C.HEIGHT - inset * 2))
    return (C.WIDTH - inset, inset + rng.random() * (C.HEIGHT - inset * 2))


def edge_point(rng, inset: float = C.SPAWN_EDGE_INSET) -> tuple[float, float]:
    """Return a random point on the playfield perimeter.

    One side is chosen, then a position along it — **both from the same roll's
    side value**.  The web prototype called an equivalent helper twice and took
    the x from one result and the y from another, which put a quarter of all
    arrivals in the middle of the field instead of at an edge.  Monsters
    appearing next to Gretel with no approach to intercept is the difference
    between hard and unfair, so the two coordinates are produced together here
    and cannot drift apart.
    """
    side = rng.below(4)
    if side == 0:                                    # top
        return (inset + rng.random() * (C.WIDTH - inset * 2), inset)
    if side == 1:                                    # right
        return (C.WIDTH - inset, inset + rng.random() * (C.HEIGHT - inset * 2))
    if side == 2:                                    # bottom
        return (inset + rng.random() * (C.WIDTH - inset * 2), C.HEIGHT - inset)
    return (inset, inset + rng.random() * (C.HEIGHT - inset * 2))   # left


def blocked_by(obstacles: Iterable["Obstacle"], x: float, y: float,
               radius: float) -> "Obstacle | None":
    """Return the first obstacle a circle at (x, y) overlaps, or None."""
    for obstacle in obstacles:
        if circles_touch(x, y, radius, obstacle.x, obstacle.y, obstacle.radius):
            return obstacle
    return None


def slide(obstacles: Iterable["Obstacle"], from_x: float, from_y: float,
          to_x: float, to_y: float, radius: float) -> tuple[float, float]:
    """Move toward a target, going around anything in the way.

    Three fallbacks, in order, each answering a failure that was measured in
    play rather than imagined.

    **Each axis alone.**  Walking into a wall at a shallow angle otherwise stops
    the mover dead, and both the player and the monsters snag on scenery in a
    way that reads as broken collision rather than as a wall.

    **The obstacle's tangent.**  Axis retries do nothing against a *circle* met
    head-on: both single-axis candidates are still inside it, so the move is
    refused — and refused again next tick, from the same place, toward the same
    target, forever.  That is what left villagers standing motionless against
    the mill on night two.  The tangent is the one direction guaranteed to be
    clear of a circle, and taking it is what turns a rock into something a
    monster walks *around* instead of into.

    **Getting out from inside.**  A mover can end up within an obstacle it could
    never have walked into: a barricade dropped on top of it, or a spawn on a
    bad tile.  From in there every candidate above is blocked and it is sealed
    in place permanently.  So when the starting point is *already* inside
    something, any step that increases the distance from that thing is allowed —
    the one case where leaving an obstacle matters more than never entering one.
    """
    if blocked_by(obstacles, to_x, to_y, radius) is None:
        return (to_x, to_y)

    trapped = blocked_by(obstacles, from_x, from_y, radius)
    if trapped is not None:
        here = distance(from_x, from_y, trapped.x, trapped.y)
        for cand_x, cand_y in ((to_x, to_y), (to_x, from_y), (from_x, to_y)):
            if distance(cand_x, cand_y, trapped.x, trapped.y) > here:
                return (cand_x, cand_y)
        out_x, out_y = normalise(from_x - trapped.x, from_y - trapped.y)
        if out_x == 0.0 and out_y == 0.0:
            return (from_x, from_y)
        step = max(0.5, distance(from_x, from_y, to_x, to_y))
        return (from_x + out_x * step, from_y + out_y * step)

    if blocked_by(obstacles, to_x, from_y, radius) is None:
        return (to_x, from_y)
    if blocked_by(obstacles, from_x, to_y, radius) is None:
        return (from_x, to_y)

    hit = blocked_by(obstacles, to_x, to_y, radius)
    step = distance(from_x, from_y, to_x, to_y)
    if hit is None or step <= 0.0:
        return (from_x, from_y)
    out_x, out_y = normalise(from_x - hit.x, from_y - hit.y)
    if out_x == 0.0 and out_y == 0.0:
        return (from_x, from_y)
    # Two tangents; take whichever makes progress toward where it was going.
    move_x, move_y = to_x - from_x, to_y - from_y
    tan_x, tan_y = -out_y, out_x
    if tan_x * move_x + tan_y * move_y < 0.0:
        tan_x, tan_y = out_y, -out_x
    slip_x = from_x + tan_x * step
    slip_y = from_y + tan_y * step
    if blocked_by(obstacles, slip_x, slip_y, radius) is None:
        return (slip_x, slip_y)
    # Hugging the surface can still clip a neighbouring circle where two
    # obstacles meet.  One more try, easing outward as well as along.
    slip_x += out_x * step * 0.6
    slip_y += out_y * step * 0.6
    if blocked_by(obstacles, slip_x, slip_y, radius) is None:
        return (slip_x, slip_y)
    return (from_x, from_y)


def sight_blocked(obstacles: Iterable["Obstacle"],
                  ax: float, ay: float, bx: float, by: float) -> bool:
    """Return True when a sight-blocking obstacle sits between two points.

    Tests the perpendicular distance from each obstacle's centre to the segment,
    with the projection clamped to the segment — so an obstacle behind the
    viewer or past the target never counts.
    """
    dx, dy = bx - ax, by - ay
    span = dx * dx + dy * dy
    for obstacle in obstacles:
        if not obstacle.blocks_sight:
            continue
        if span == 0.0:
            if distance(ax, ay, obstacle.x, obstacle.y) <= obstacle.radius:
                return True
            continue
        t = clamp(((obstacle.x - ax) * dx + (obstacle.y - ay) * dy) / span, 0.0, 1.0)
        near_x, near_y = ax + dx * t, ay + dy * t
        if distance(near_x, near_y, obstacle.x, obstacle.y) <= obstacle.radius:
            return True
    return False
