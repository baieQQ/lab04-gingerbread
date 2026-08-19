"""The mechanics a content table can name.

Read this file to learn the vocabulary; add to it only when a piece of content
genuinely cannot be expressed with what is here.  Every entry declares its own
parameters and a one-line description, which is what lets the codex be generated
rather than maintained — see ``registry.py``.

Two kinds live here.

**Behaviours** decide movement.  A monster names exactly one.

**Traits** react at fixed moments and *compose*.  A monster may name any number,
and none of them knows the others exist — which is what makes "an armoured one
that also revives" a data change and not a code change.

Every function obeys two rules without exception: randomness comes from
``state.streams`` and nowhere else, and nothing reads a clock.
"""

from __future__ import annotations

import math

from . import constants as C
from . import geometry as g
from .content.monsters import MONSTERS
from .derive import derive, is_lit
from .entities import Drop, Effect, Monster, Obstacle, Projectile, Puddle
from .registry import behaviour, param, trait
from .state import State


def _spec(monster: Monster):
    """Return the spec row for a monster, falling back to the plain villager."""
    return MONSTERS.get(monster.spec) or MONSTERS["villager"]


def _aim_around(state: State, mx: float, my: float, tx: float, ty: float,
                radius: float) -> tuple[float, float]:
    """Return a waypoint that clears whatever sits between here and there.

    Collision alone is not enough to make a chaser look like it can see.
    ``slide`` only reacts once the mover is *touching* something, so a monster
    walks straight into a rock, grinds along it, and reads as stuck even when it
    is technically still moving.  Steering earlier — aiming at the edge of the
    thing in the way rather than through it — is what makes the same monster
    look like it went *around*.

    Only the nearest blocker is considered.  Solving a whole corridor here would
    be a pathfinder, and one obstacle at a time is enough on a field this open.
    """
    dx, dy = tx - mx, ty - my
    span = dx * dx + dy * dy
    if span <= 0.0:
        return (tx, ty)

    best = None
    for block in state.obstacles:
        clear = block.radius + radius + 6.0
        t = g.clamp(((block.x - mx) * dx + (block.y - my) * dy) / span, 0.0, 1.0)
        near_x, near_y = mx + dx * t, my + dy * t
        off = g.distance(near_x, near_y, block.x, block.y)
        if off >= clear:
            continue
        reach = g.distance(mx, my, block.x, block.y)
        if best is None or reach < best[0]:
            best = (reach, block, near_x, near_y, off, clear)
    if best is None:
        return (tx, ty)

    _, block, near_x, near_y, off, clear = best
    side_x, side_y = g.normalise(near_x - block.x, near_y - block.y)
    if side_x == 0.0 and side_y == 0.0:
        # Dead-on at the centre, where there is no "away" to compute.  Either
        # tangent is as good as the other; picking from the geometry rather
        # than from a roll keeps two identical runs identical.
        side_x, side_y = g.normalise(-dy, dx)
    return (block.x + side_x * clear, block.y + side_y * clear)


def _walk_toward(state: State, monster: Monster, tx: float, ty: float,
                 dt: float, speed: float | None = None) -> None:
    """Step a monster toward a point, going around any obstacle in the way."""
    tx, ty = _aim_around(state, monster.x, monster.y, tx, ty,
                         _spec(monster).radius)
    dx, dy = g.normalise(tx - monster.x, ty - monster.y)
    if dx == 0.0 and dy == 0.0:
        return
    rate = monster.speed if speed is None else speed
    rate *= _ground_drag(state, monster)
    radius = _spec(monster).radius
    monster.x, monster.y = g.slide(
        state.obstacles, monster.x, monster.y,
        monster.x + dx * rate * dt, monster.y + dy * rate * dt, radius,
    )


def _ground_drag(state: State, monster: Monster) -> float:
    """Return the movement multiplier from whatever it is standing in.

    怒潮's mist is folded in here rather than given its own branch at every
    call site: from a monster's point of view it is simply more difficult
    ground, which is exactly what a puddle is.
    """
    slowest = C.MIST_SLOW if state.mist_ticks > 0 else 1.0
    for pool in state.puddles:
        if g.distance(monster.x, monster.y, pool.x, pool.y) <= pool.radius:
            slowest = min(slowest, pool.slow)
    return slowest


# ── behaviours ───────────────────────────────────────────────────────
@behaviour("charge", label="直衝",
           note="直線走向葛蕾特，不看別的")
def charge(state: State, monster: Monster, dt: float) -> None:
    """The default, and deliberately the simplest thing in the game.

    The player must be able to predict where an ordinary monster is going
    without thinking, so that the ones which *do* behave differently register as
    information rather than as noise.
    """
    _walk_toward(state, monster, C.SISTER_X, C.SISTER_Y, dt)


@behaviour("flank", label="繞行",
           note="先在外圍繞圈，過一陣子才切進去",
           params={"orbit": (150.0, "繞行半徑"),
                   "patience": (3.0, "繞多久之後才衝進去（秒）")})
def flank(state: State, monster: Monster, dt: float) -> None:
    """Circle Gretel at a distance, then commit.

    Steering is a tangent plus a radial correction, never a chase after a point
    that rotates around her.  The obvious version breaks whenever the monster is
    slower than that point moves: the target runs away around the circle, the
    straight line to it cuts the chord, and the monster walks through the middle
    and over Gretel.  A blend of tangent and radial cannot cross the centre.
    """
    spec = _spec(monster)
    orbit = max(40.0, param(spec, "flank", "orbit"))
    patience = param(spec, "flank", "patience")

    monster.memory["circled"] = monster.memory.get("circled", 0.0) + dt
    if monster.memory["circled"] >= patience:
        _walk_toward(state, monster, C.SISTER_X, C.SISTER_Y, dt)
        return

    if "spin" not in monster.memory:
        monster.memory["spin"] = 1.0 if state.rng.random() < 0.5 else -1.0
    spin = monster.memory["spin"]

    out_x, out_y = g.normalise(monster.x - C.SISTER_X, monster.y - C.SISTER_Y)
    if out_x == 0.0 and out_y == 0.0:
        out_x, out_y = 1.0, 0.0
    tan_x, tan_y = -out_y * spin, out_x * spin
    reach = g.distance(monster.x, monster.y, C.SISTER_X, C.SISTER_Y)
    pull = g.clamp((orbit - reach) / orbit, -1.0, 1.0)

    dx, dy = g.normalise(tan_x - out_x * pull, tan_y - out_y * pull)
    rate = monster.speed * _ground_drag(state, monster)
    monster.x, monster.y = g.slide(
        state.obstacles, monster.x, monster.y,
        g.clamp(monster.x + dx * rate * dt, 8, C.WIDTH - 8),
        g.clamp(monster.y + dy * rate * dt, 8, C.HEIGHT - 8),
        spec.radius)


@behaviour("standoff", label="遠程",
           note="停在遠處蓄力，然後朝葛蕾特射出去；要主動去打掉它",
           params={"standoff": (230.0, "停下來的距離"),
                   "windup": (2.0, "蓄力秒數"),
                   "reload": (1.4, "射完到下次蓄力的間隔"),
                   "shot_speed": (240.0, "飛行速度"),
                   "shot_damage": (1.0, "命中扣多少（半顆心為 1）")})
def standoff(state: State, monster: Monster, dt: float) -> None:
    """Stop out of reach and shoot.

    The only threat in the game that gets *worse* the longer the player stays on
    post, so the only one that can pull him away from her.  A game where the
    right answer is always "stand next to Gretel" has one decision in it.

    The wind-up is not flavour: it is the window the player is being sold.  A
    ranged attack with no tell is unanswerable, and unanswerable is not hard.
    """
    spec = _spec(monster)
    keep = param(spec, "standoff", "standoff")
    windup = param(spec, "standoff", "windup")
    reload_for = param(spec, "standoff", "reload")
    speed = param(spec, "standoff", "shot_speed")
    damage = int(param(spec, "standoff", "shot_damage"))

    reach = g.distance(monster.x, monster.y, C.SISTER_X, C.SISTER_Y)
    if reach > keep + 10 and monster.charge <= 0:
        _walk_toward(state, monster, C.SISTER_X, C.SISTER_Y, dt)
        return

    if monster.charge > 0:
        monster.charge -= dt
        if monster.charge > 0:
            return
        dx, dy = g.normalise(C.SISTER_X - monster.x, C.SISTER_Y - monster.y)
        state.projectiles.append(
            Projectile(x=monster.x, y=monster.y, vx=dx * speed, vy=dy * speed,
                       damage=damage, kind=spec.key))
        state.emit(f"shoot:{spec.key}")
        monster.memory["reload"] = reload_for
        return

    monster.memory["reload"] = monster.memory.get("reload", 0.0) - dt
    if monster.memory["reload"] <= 0:
        monster.charge = windup
        state.effects.append(Effect("windup", monster.x, monster.y,
                                    windup, windup))
        state.emit(f"windup:{spec.key}")


@behaviour("barricade", label="築牆",
           note="遠遠地蓄力，在地上丟出擋路的石頭",
           params={"standoff": (260.0, "停下來的距離"),
                   "windup": (3.0, "蓄力秒數"),
                   "reload": (4.0, "兩次之間的間隔"),
                   "rock_radius": (26.0, "石頭大小")})
def barricade(state: State, monster: Monster, dt: float) -> None:
    """Drop rocks between the player and where he needs to be.

    It never touches him.  It changes the shape of the field, which in a game
    about reaching one fixed point in time is a heavier attack than damage.
    """
    spec = _spec(monster)
    keep = param(spec, "barricade", "standoff")
    windup = param(spec, "barricade", "windup")
    reload_for = param(spec, "barricade", "reload")
    rock = param(spec, "barricade", "rock_radius")

    if g.distance(monster.x, monster.y, C.SISTER_X, C.SISTER_Y) > keep + 10 \
            and monster.charge <= 0:
        _walk_toward(state, monster, C.SISTER_X, C.SISTER_Y, dt)
        return

    if monster.charge > 0:
        monster.charge -= dt
        if monster.charge > 0:
            return
        angle = state.streams.spawn.random() * math.tau
        # One roll, six candidate spokes off it.  Rolling again per attempt
        # would draw a variable number of numbers from the stream and make the
        # night depend on how many rocks happened to be refused.
        for spoke in range(6):
            a = angle + spoke * math.tau / 6
            px = g.clamp(C.SISTER_X + math.cos(a) * 120, 40, C.WIDTH - 40)
            py = g.clamp(C.SISTER_Y + math.sin(a) * 120, 40, C.HEIGHT - 40)
            if _rock_fits(state, px, py, rock):
                state.obstacles.append(
                    Obstacle(x=px, y=py, radius=rock, blocks_sight=False,
                             kind="rock", life=C.ROCK_LIFE))
                state.effects.append(Effect("rock", px, py, 0.4, 0.4, rock))
                state.emit("barricade")
                break
        monster.memory["reload"] = reload_for
        return

    monster.memory["reload"] = monster.memory.get("reload", 0.0) - dt
    if monster.memory["reload"] <= 0:
        monster.charge = windup
        state.effects.append(Effect("windup", monster.x, monster.y,
                                    windup, windup))


def _rock_fits(state: State, px: float, py: float, rock: float) -> bool:
    """Return True when a barricade may legally appear at this spot.

    Every clause here is a bug that was reported from play.

    *Not on Gretel* — a rock there walls her off and makes the night
    unloseable, the same failure the map validator exists to catch.

    *Not on the player* — he ends up **inside** the new obstacle, and ``slide``
    refuses every direction from inside one, so he is sealed in place with no
    way out.  That was the "I get shut in" report.

    *Not against another rock* — two that touch start a wall, and a barricade
    monster left alone long enough will close a ring around her that neither the
    player nor the other monsters can cross.  Keeping them a body's width apart
    means the barricade always reshapes the field without ever sealing it.
    """
    if g.distance(px, py, C.SISTER_X, C.SISTER_Y) <= rock + C.SISTER_REACH + 12:
        return False
    if g.distance(px, py, state.player.x, state.player.y) \
            <= rock + C.PLAYER_RADIUS + C.ROCK_CLEAR_PLAYER:
        return False
    live = [o for o in state.obstacles if o.kind == "rock"]
    if len(live) >= C.ROCK_LIMIT:
        return False
    for other in state.obstacles:
        gap = C.ROCK_CLEAR_ROCK if other.kind == "rock" else 4.0
        if g.distance(px, py, other.x, other.y) <= rock + other.radius + gap:
            return False
    return True


@behaviour("burrow", label="挖洞",
           note="鑽到地底靠近葛蕾特再冒出來；在地底時法術打不到",
           params={"dig_after": (1.5, "走多久之後鑽進地底"),
                   "surface_at": (90.0, "距離葛蕾特多遠冒出來")})
def burrow(state: State, monster: Monster, dt: float) -> None:
    """Travel underground, surface near Gretel.

    Spells cannot touch it while it is down, so a player who has been clearing
    the field with lightning has to physically go back and stand guard.  It
    punishes exactly the habit the other monsters reward.
    """
    spec = _spec(monster)
    surface_at = param(spec, "burrow", "surface_at")

    if monster.buried > 0:
        monster.buried -= dt
        # It keeps travelling while under, faster and untouchable.
        _walk_toward(state, monster, C.SISTER_X, C.SISTER_Y, dt,
                     monster.speed * 1.35)
        if g.distance(monster.x, monster.y, C.SISTER_X, C.SISTER_Y) <= surface_at:
            monster.buried = 0.0
            state.effects.append(Effect("surface", monster.x, monster.y, 0.5, 0.5))
            state.emit(f"surface:{spec.key}")
        return

    monster.memory["above"] = monster.memory.get("above", 0.0) + dt
    if monster.memory["above"] >= param(spec, "burrow", "dig_after") \
            and g.distance(monster.x, monster.y,
                           C.SISTER_X, C.SISTER_Y) > surface_at + 40:
        monster.buried = 20.0
        state.effects.append(Effect("dig", monster.x, monster.y, 0.4, 0.4))
        state.emit(f"burrow:{spec.key}")
        return
    _walk_toward(state, monster, C.SISTER_X, C.SISTER_Y, dt)


@behaviour("lurk", label="埋伏",
           note="在邊緣等，同類夠多了才一起衝",
           params={"pack": (4.0, "湊到幾隻才動")})
def lurk(state: State, monster: Monster, dt: float) -> None:
    """Hold at the edge until the pack is big enough, then charge together."""
    spec = _spec(monster)
    needed = int(param(spec, "lurk", "pack"))
    if monster.memory.get("committed", 0.0) > 0:
        _walk_toward(state, monster, C.SISTER_X, C.SISTER_Y, dt)
        return
    waiting = sum(1 for other in state.monsters
                  if other.spec == monster.spec
                  and not other.memory.get("committed"))
    if waiting >= needed:
        for other in state.monsters:
            if other.spec == monster.spec:
                other.memory["committed"] = 1.0
        state.emit(f"pack:{spec.key}")


@behaviour("still", label="不動", note="完全不移動；給場景物件與測試用")
def still(state: State, monster: Monster, dt: float) -> None:
    return


# ── traits: tick ─────────────────────────────────────────────────────
@trait("shy_of_light", "tick", label="怕光",
       note="站在提燈光裡就定住不動")
def shy_of_light(state: State, monster: Monster, payload: float = 0.0) -> None:
    """Freeze while standing in the lantern's light.

    Turns the light radius from a passive "how far can I see" number into an
    active weapon, and makes losing the lantern genuinely frightening.
    """
    monster.frozen = is_lit(state, monster.x, monster.y, lantern_only=True)


@trait("fades", "tick", label="隱形",
       note="完全看不見，只有地上的白色腳印會出賣牠；被光照到就現形",
       params={"fade": (1.0, "看不見的程度，1 是完全透明"),
               "step_every": (0.26, "多久留一個腳印"),
               "step_life": (2.4, "腳印多久淡掉"),
               "step_spread": (5.0, "左右腳分開多遠")})
def fades(state: State, monster: Monster, payload: float = 0.0) -> None:
    """Gone from sight until light falls on it — but it still leaves prints.

    Invisible *and* untraceable would be unfair, so the body goes and the tracks
    stay: white footprints pressed into the ground behind it, one every stride.
    That turns finding it from a perception test into a reading test, which is a
    thing a player can get better at.

    The prints are ordinary world objects, so the lantern has to reach them.
    That is the point rather than a limitation: this is the one monster that
    makes the player sweep the light across empty ground.
    """
    spec = _spec(monster)
    lit = (is_lit(state, monster.x, monster.y, lantern_only=True)
           or state.reveal_ticks > 0)
    monster.faded = 0.0 if lit else param(spec, "fades", "fade")
    if lit or monster.stunned > 0 or monster.buried > 0:
        return

    every = param(spec, "fades", "step_every")
    monster.memory["step"] = monster.memory.get("step", 0.0) + C.FIXED_DT
    if monster.memory["step"] < every:
        return
    monster.memory["step"] = 0.0
    # Left and right alternate, offset across the direction of travel, so the
    # trail reads as something walking rather than as a dotted line.
    monster.memory["foot"] = -monster.memory.get("foot", 1.0)
    dx, dy = g.normalise(C.SISTER_X - monster.x, C.SISTER_Y - monster.y)
    side = param(spec, "fades", "step_spread") * monster.memory["foot"]
    state.effects.append(Effect(
        "ghost_step", monster.x - dy * side, monster.y + dx * side,
        param(spec, "fades", "step_life"),
        param(spec, "fades", "step_life")))


@trait("mud_trail", "tick", label="留泥",
       note="走過的地面留下泥巴，踩到的人會越走越慢",
       params={"mud_every": (0.45, "多久留一攤"),
               "mud_radius": (26.0, "泥巴大小"),
               "mud_slow": (0.55, "踩到剩幾成速度"),
               "mud_life": (6.0, "多久乾掉")})
def mud_trail(state: State, monster: Monster, payload: float = 0.0) -> None:
    """Leave a slowing trail.

    It never has to catch the player; it makes everything after it harder.  Best
    dealt with head-on, which is the one approach the player instinctively
    avoids.
    """
    spec = _spec(monster)
    every = param(spec, "mud_trail", "mud_every")
    monster.memory["mud"] = monster.memory.get("mud", 0.0) + C.FIXED_DT
    if monster.memory["mud"] < every:
        return
    monster.memory["mud"] = 0.0
    state.puddles.append(Puddle(
        x=monster.x, y=monster.y,
        radius=param(spec, "mud_trail", "mud_radius"),
        kind="mud", slow=param(spec, "mud_trail", "mud_slow"),
        life=param(spec, "mud_trail", "mud_life")))


# ── traits: hurt ─────────────────────────────────────────────────────
@trait("frenzy", "hurt", label="狂化", note="受傷之後變快",
       params={"frenzy_factor": (1.35, "速度倍率")})
def frenzy(state: State, monster: Monster, payload: float = 0.0) -> None:
    spec = _spec(monster)
    monster.speed *= param(spec, "frenzy", "frenzy_factor")
    state.effects.append(Effect("frenzy", monster.x, monster.y, 0.4, 0.4))


# ── traits: death ────────────────────────────────────────────────────
@trait("splits", "death", label="分裂",
       note="死掉時裂成幾隻小的，要全部清掉才算",
       params={"split_count": (2.0, "裂成幾隻"),
               "split_delay": (0.2, "裂開多久之後小的才會動")})
def splits(state: State, monster: Monster, payload: float = 0.0) -> None:
    """Break into smaller monsters when killed.

    Means "clear the field" is not automatically right, and gives the player
    something to plan around: kill these early, or kill them last.
    """
    spec = _spec(monster)
    child_key = str(spec.params.get("split_into", "child"))
    count = int(param(spec, "splits", "split_count"))
    child = MONSTERS.get(child_key)
    if child is None:
        return
    for i in range(count):
        angle = (i / max(count, 1)) * math.tau + state.rng.random() * 0.6
        state.monsters.append(Monster(
            spec=child_key,
            x=g.clamp(monster.x + math.cos(angle) * 20, 8, C.WIDTH - 8),
            y=g.clamp(monster.y + math.sin(angle) * 20, 8, C.HEIGHT - 8),
            hp=child.hp, speed=child.speed,
            # A beat before they move.  Splitting used to hand the player two
            # live monsters on the same frame the parent died, inside the swing
            # they had already committed to — the punishment landed before the
            # cause was legible.  Two tenths of a second is enough to read it.
            wake=param(spec, "splits", "split_delay"),
            armour=int(child.param("armour"))))
    state.effects.append(Effect("split", monster.x, monster.y, 0.4, 0.4))
    state.emit(f"split:{spec.key}")


@trait("revives", "death", label="復活",
       note="會爬起來一次，要再打一次才真的死",
       params={"revive_hp": (0.6, "復活後剩幾成血"),
               "revive_delay": (0.5, "倒下多久才爬起來")})
def revives(state: State, monster: Monster, payload: float = 0.0) -> None:
    """Get back up once.

    Deliberately visible: it collapses, lies there, and stands again, so the
    player learns the rule by watching rather than by being surprised twice.
    """
    if monster.revives <= 0:
        return
    spec = _spec(monster)
    monster.revives -= 1
    state.monsters.append(Monster(
        spec=monster.spec, x=monster.x, y=monster.y,
        hp=max(1, int(spec.hp * param(spec, "revives", "revive_hp"))),
        speed=monster.speed, revives=monster.revives,
        wake=param(spec, "revives", "revive_delay"),
        armour=int(spec.param("armour"))))
    state.effects.append(Effect("revive", monster.x, monster.y, 0.6, 0.6))
    state.emit(f"revive:{spec.key}")


@trait("bursts", "death", label="自爆",
       note="被打死會炸開；在葛蕾特旁邊殺它會炸到她",
       params={"blast_radius": (72.0, "爆炸範圍"),
               "blast_damage": (1.0, "炸到葛蕾特扣多少")})
def bursts(state: State, monster: Monster, payload: float = 0.0) -> None:
    """Explode where it died.

    The only monster in the game whose *kill* is the danger.  It makes position
    matter at the moment the player is least thinking about it, and it is the
    one enemy the shove answers better than the lantern does.
    """
    spec = _spec(monster)
    radius = param(spec, "bursts", "blast_radius")
    damage = int(param(spec, "bursts", "blast_damage"))

    state.effects.append(Effect("blast", monster.x, monster.y, 0.5, 0.5, radius))
    state.feedback.bump(shake=9.0)
    state.emit("burst")

    if g.distance(monster.x, monster.y, C.SISTER_X, C.SISTER_Y) <= radius:
        state.meta.sister_hp = max(0, state.meta.sister_hp - damage)
        state.stats.reached_sister += 1
        state.feedback.bump(shake=12.0, hurt=0.9)
        state.emit("sister_burned")

    player = state.player
    if g.distance(monster.x, monster.y, player.x, player.y) <= radius:
        from .rules import hurt_player
        hurt_player(state, damage)


@trait("decoy", "death", label="假糖霜",
       note="死掉時掉出會扣血的假糖霜",
       params={"decoys": (1.0, "掉幾顆"), "decoy_damage": (1.0, "撿到扣多少")})
def decoy(state: State, monster: Monster, payload: float = 0.0) -> None:
    spec = _spec(monster)
    for _ in range(int(param(spec, "decoy", "decoys"))):
        angle = state.rng.random() * math.tau
        state.drops.append(Drop(
            x=g.clamp(monster.x + math.cos(angle) * 26, 10, C.WIDTH - 10),
            y=g.clamp(monster.y + math.sin(angle) * 26, 10, C.HEIGHT - 10),
            value=int(param(spec, "decoy", "decoy_damage")), fake=True))


# ── traits: contact ──────────────────────────────────────────────────
@trait("douses", "touch_player", label="潑燈",
       note="碰到玩家會把提燈潑熄一陣子",
       params={"douse_seconds": (4.0, "熄滅幾秒")})
def douses(state: State, monster: Monster, payload: float = 0.0) -> None:
    spec = _spec(monster)
    state.player.doused = max(state.player.doused,
                              param(spec, "douses", "douse_seconds"))
    state.effects.append(Effect("douse", state.player.x, state.player.y, 0.5, 0.5))
    state.emit("doused")


@trait("clings", "touch_player", label="纏住",
       note="碰到玩家會黏住他，而不是把他彈開",
       params={"cling_seconds": (0.45, "定身幾秒")})
def clings(state: State, monster: Monster, payload: float = 0.0) -> None:
    spec = _spec(monster)
    state.player.stun = max(state.player.stun,
                            param(spec, "clings", "cling_seconds"))
    state.player.knock_x = 0.0
    state.player.knock_y = 0.0
    state.emit("clung")


@trait("steals", "reach_sister", label="偷糖霜",
       note="摸到葛蕾特時順便偷走糖霜",
       params={"steal": (2.0, "偷幾顆")})
def steals(state: State, monster: Monster, payload: float = 0.0) -> None:
    spec = _spec(monster)
    taken = min(state.meta.sugar, int(param(spec, "steals", "steal")))
    state.meta.sugar -= taken
    if taken:
        state.emit(f"stolen:{taken}")


# ── traits: spawn ────────────────────────────────────────────────────
@trait("armoured", "spawn", label="盔甲",
       note="要先打掉護甲才傷得到本體",
       params={"armour": (2.0, "護甲點數")})
def armoured(state: State, monster: Monster, payload: float = 0.0) -> None:
    """Give this one its armour when it arrives.

    Armour is per-individual because it is consumed; the spec only says how much
    it starts with.  Applied at spawn so a split or a revival gets its own.
    """
    spec = _spec(monster)
    if monster.armour <= 0:
        monster.armour = int(param(spec, "armoured", "armour"))


@trait("reflects", "spawn", label="鏡子",
       note="正面打不動，要繞到背後才打得到",
       params={"reflect_arc": (1.5, "正面免疫的角度（弧度，單邊）")})
def reflects(state: State, monster: Monster, payload: float = 0.0) -> None:
    """Marker only.

    The actual test lives in the swing resolution, because it needs the angle of
    the incoming hit.  Registering it here is what puts it in the codex and what
    lets the validator accept the name.
    """
    return


@trait("elite_aura", "spawn", label="精英", note="體型與數值都被強化過")
def elite_aura(state: State, monster: Monster, payload: float = 0.0) -> None:
    state.effects.append(Effect("elite", monster.x, monster.y, 0.8, 0.8))
    state.emit(f"elite:{monster.spec}")


def escalate_speed(monster: Monster, elapsed: float) -> None:
    """Apply the night's rising pressure to one monster's speed.

    A plain function rather than a trait because it applies to everything,
    always — opt-in would mean every content row had to remember it.
    """
    monster.speed += int(elapsed / C.WAVE_SECONDS) * C.SPEED_PER_WAVE
