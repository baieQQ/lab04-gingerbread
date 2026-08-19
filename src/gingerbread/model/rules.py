"""The simulation: everything that changes the world.

One tick, one direction.  Nothing in this module reads a clock, opens a
display, or calls ``random`` directly — every roll goes through ``state.rng``,
which is what makes a run replayable and a bug report reproducible.

Order within a tick is fixed and load-bearing::

    decay timers -> player -> spawns -> monsters -> projectiles -> pickups -> end checks

Monsters move *after* the player so a swing resolves against where things were
when the player swung, not where they ended up; and pickups resolve *after*
movement so walking onto a crystal collects it on the same frame it looks like
it should.
"""

from __future__ import annotations

import math

from . import constants as C
from . import geometry as g
from .behaviours import escalate_speed
from .content import BOSSES, EVENTS, MAPS, MONSTERS, SPELLS as SPELL_TABLE
from .content.monsters import (ELITE_HP_FACTOR, ELITE_SPEED_FACTOR,
                               ELITE_SUGAR_FACTOR)
from .derive import derive, element_multiplier
from .entities import (Boss, Drop, Effect, Hazard, Monster, Obstacle, Projectile,
                       Puddle, Warning)
from .registry import EVENTS as EVENT_EFFECTS
from .registry import SPELLS as SPELL_EFFECTS
from .registry import fire_traits, run_behaviour
from .state import Mode, Phase, State

_DIRECTIONS = {
    "up": (0.0, -1.0),
    "down": (0.0, 1.0),
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
}


def spec_of(monster: Monster):
    """Return the spec row for a monster or boss."""
    if isinstance(monster, Boss):
        return BOSSES.get(monster.spec) or BOSSES[next(iter(BOSSES))]
    return MONSTERS.get(monster.spec) or MONSTERS["villager"]


# ── the tick ─────────────────────────────────────────────────────────
def step(state: State, inputs: set[str], director) -> State:
    """Advance exactly one fixed time step.  Mutates and returns ``state``.

    ``apply_action`` has already copied the caller's state, so mutating here is
    safe and avoids a second deep copy per frame.
    """
    dt = C.FIXED_DT
    state.tick += 1
    state.ticks_total_run += 1
    state.feedback.decay(dt)

    if state.phase is Phase.DAY:
        state.ticks_left = max(0, state.ticks_left - 1)
        state.ticks_elapsed += 1
        # The model decides when the day ends, not the shell.  An earlier
        # version only emitted an event here and left the phase alone, so the
        # pygame loop was the thing that actually started the night — one of the
        # game's rules living in the presentation layer, invisible to every
        # headless test of the day/night cycle.
        # The day does not end on its own.  It used to be a timed phase because
        # it rationed four action points; now it is a shop and a loadout screen,
        # and a countdown over a menu only punishes reading it.  Night falls
        # when the player says so.
        return state
        return state

    if state.phase is not Phase.NIGHT:
        return state

    # Hit-stop freezes the world but never the feedback decay above — putting
    # the decay inside this branch is exactly the bug that made the web build
    # shake forever once a freeze ended.
    if state.feedback.freeze > 0:
        return state

    state.ticks_left = max(0, state.ticks_left - 1)
    state.ticks_elapsed += 1
    state.dusk = min(1.0, state.dusk + dt / C.DUSK_SECONDS)

    _tick_combo(state)
    _tick_cooldowns(state)
    _tick_event(state)
    # Recomputed from scratch every tick, then written by whichever boss phase
    # is running.  A phase used to *set* the light scale and never hand it back,
    # so one fog phase dimmed the rest of the night — and the night after it.
    state.fog_scale = 1.0
    _move_player(state, inputs, dt)

    if "swing" in inputs:
        swing(state)

    # Charging is "the key is still down"; firing is "it no longer is".  The
    # shell already sends ``cast:`` on every frame the key is held, so holding
    # and releasing are readable here without a new action word — and a player
    # who taps still gets the un-charged version, which is what a tap means.
    held = {w.split(":", 1)[1] for w in inputs if w.startswith("cast:")}
    p = state.player
    # A held key does *not* arrive on every tick: the shell sends movement and
    # casting as two separate actions, so the movement tick always looks like
    # "the key is up".  Charging therefore ends only after several consecutive
    # ticks with no cast — which is why holding the key used to fire instantly.
    if p.charging:
        if p.charging in held:
            p.charge_idle = 0.0
        else:
            p.charge_idle += dt
            if p.charge_idle > C.CHARGE_RELEASE:
                release_charge(state)
    for key in held:
        cast(state, key)

    # Nothing arrives or acts until the screen has finished going dark, so the
    # player is never hit by something that spawned behind a fade.
    if state.dusk >= 1.0:
        director.spawn(state, dt)
        _advance_monsters(state, dt)
        _advance_bosses(state, dt)
    _advance_projectiles(state, dt)
    _advance_puddles(state, dt)
    _advance_hazards(state, dt)
    _advance_obstacles(state, dt)
    _advance_effects(state, dt)
    _collect_drops(state)

    _resolve_ending(state, director)
    return state


# ── player ───────────────────────────────────────────────────────────
def _move_player(state: State, inputs: set[str], dt: float) -> None:
    p = state.player
    stats = derive(state)

    p.swing_cooldown = max(0.0, p.swing_cooldown - dt)
    p.swing_anim = max(0.0, p.swing_anim - dt)
    p.dash = max(0.0, p.dash - dt)
    p.dash_cooldown = max(0.0, p.dash_cooldown - dt)
    p.stun = max(0.0, p.stun - dt)
    p.invulnerable = max(0.0, p.invulnerable - dt)
    p.doused = max(0.0, p.doused - dt)
    _tick_skills(state, dt)

    # Held, not pressed.  ``inputs`` is level-triggered, so this is simply
    # "is K down this tick" — there is no window to hit and nothing to time.
    if "guard" in inputs and not p.helpless:
        if p.guard <= 0:
            state.emit("guard")
        p.guard += dt
    else:
        p.guard = 0.0

    if p.downed > 0:
        p.downed = max(0.0, p.downed - dt)
        if p.downed == 0.0:
            p.hp = max(1, int(stats.max_hp * C.DOWNED_REVIVE_FRACTION))
            p.invulnerable = C.INVULNERABLE_TIME
            state.emit("revive")
        return

    # Residual knockback keeps pushing even while stunned; being shoved should
    # move you, not merely pause you.
    if abs(p.knock_x) + abs(p.knock_y) > 0.5:
        p.x = g.clamp(p.x + p.knock_x * dt, C.PLAY_MARGIN, C.WIDTH - C.PLAY_MARGIN)
        p.y = g.clamp(p.y + p.knock_y * dt, C.PLAY_MARGIN, C.HEIGHT - C.PLAY_MARGIN)
        p.knock_x *= C.KNOCKBACK_DECAY
        p.knock_y *= C.KNOCKBACK_DECAY

    if p.stun > 0:
        return

    vx = vy = 0.0
    for name in inputs:
        move = _DIRECTIONS.get(name)
        if move:
            vx += move[0]
            vy += move[1]

    vx, vy = g.normalise(vx, vy)
    if vx == 0.0 and vy == 0.0:
        return
    p.face_x, p.face_y = vx, vy

    if "dash" in inputs and p.dash_cooldown <= 0:
        p.dash = C.DASH_TIME
        p.dash_cooldown = C.DASH_COOLDOWN
        state.emit("dash")

    recover = C.SWING_SLOWDOWN if p.swing_anim > 0 else 1.0
    drag = 1.0
    for pool in state.puddles:
        if g.distance(p.x, p.y, pool.x, pool.y) <= pool.radius:
            drag = min(drag, pool.slow)
    rush = 1.0
    if p.haste > 0:
        spec = SPELL_TABLE.get("windrun")
        rush = float(spec.params.get("speed", 2.4)) if spec else 2.4
    speed = (C.DASH_SPEED if p.dash > 0
             else stats.move_speed * recover * drag * rush)
    p.x, p.y = g.slide(state.obstacles, p.x, p.y,
                       g.clamp(p.x + vx * speed * dt, C.PLAY_MARGIN, C.WIDTH - C.PLAY_MARGIN),
                       g.clamp(p.y + vy * speed * dt, C.PLAY_MARGIN, C.HEIGHT - C.PLAY_MARGIN),
                       C.PLAYER_RADIUS)


def _tick_skills(state: State, dt: float) -> None:
    """Run the carried-state skills: the burning light, the armour, the run.

    All four are timers on the player, counted in one place so a skill can
    never be left running by a code path that forgot about it.
    """
    p = state.player

    # 聖光 — burns whatever stands near him, half a heart a second.
    if p.holy > 0:
        p.holy = max(0.0, p.holy - dt)
        spec = SPELL_TABLE.get("holy")
        if spec is not None:
            p.holy_tick += dt
            step = 1.0 / max(0.01, float(spec.params.get("burn", 0.5)))
            if p.holy_tick >= step:
                p.holy_tick -= step
                radius = float(spec.params.get("radius", 80.0))
                for target in list(state.monsters) + list(state.bosses):
                    if not target.hittable:
                        continue
                    if g.distance(target.x, target.y, p.x, p.y) <= radius:
                        damage_target(state, target, 1, element="light",
                                      from_x=p.x, from_y=p.y)

    # 聖癒 — the only mid-night healing either of them gets.
    if p.mending > 0:
        p.mending = max(0.0, p.mending - dt)
        spec = SPELL_TABLE.get("blessing")
        every = float(spec.params.get("every", 4.0)) if spec else 4.0
        p.mend_tick += dt
        if p.mend_tick >= every:
            p.mend_tick -= every
            stats = derive(state)
            p.hp = min(stats.max_hp, p.hp + 1)
            state.meta.sister_hp = min(state.meta.max_sister_hp,
                                       state.meta.sister_hp + 1)
            state.effects.append(Effect("mend", p.x, p.y, 0.5, 0.5))
            state.effects.append(Effect("mend", C.SISTER_X, C.SISTER_Y, 0.5, 0.5))
            state.emit("mended")

    # 雷鳴 — and the discharge when it lapses.
    if p.aura > 0:
        p.aura = max(0.0, p.aura - dt)
        if p.aura <= 0:
            from .effects import _kill_within

            spec = SPELL_TABLE.get("thunderclap")
            radius = float(spec.params.get("burst_radius", 80.0)) if spec else 80.0
            burst = int(spec.params.get("boss", 16)) if spec else 16
            _kill_within(state, p.x, p.y, radius, "thunder", push=90.0,
                         boss=burst + int(min(6.0, p.aura_hits)))
            state.effects.append(Effect("bolt", p.x, p.y, 0.4, 0.4, radius))
            state.feedback.bump(shake=14.0, freeze=0.08)
            state.emit("thunderclap")

    if p.haste > 0:
        p.haste = max(0.0, p.haste - dt)

    if state.mist_ticks > 0:
        state.mist_ticks -= 1


def swing(state: State) -> None:
    """Swing the lantern in a cone.  Geometry finds targets; this resolves them."""
    p = state.player
    # Guarding is the whole cost of guarding.  Without this the key would be
    # free: hold it forever, swing anyway, never take a hit.
    if p.helpless or p.guarding or p.swing_cooldown > 0:
        return
    stats = derive(state)
    p.swing_cooldown = stats.swing_cooldown
    p.swing_anim = C.SWING_ANIM
    state.emit("swing")

    landed = False
    for target in list(state.monsters) + list(state.bosses):
        if not target.hittable:
            continue
        spec = spec_of(target)
        if not g.within_cone(p.x, p.y, p.face_x, p.face_y,
                             target.x, target.y, spec.radius,
                             stats.swing_range,
                             math.cos(stats.swing_arc),
                             math.sin(stats.swing_arc)):
            continue
        landed = True
        damage_target(state, target, stats.attack, by_lantern=True,
                      from_x=p.x, from_y=p.y)

    if not landed:
        state.emit("whiff")


def damage_target(state: State, target: Monster, amount: int, *,
                  by_lantern: bool = False,
                  element: str | None = None,
                  from_x: float | None = None,
                  from_y: float | None = None) -> None:
    """Apply damage to one target, through every rule that can modify it.

    One funnel for the lantern, every skill and every explosion, so armour,
    weakness and the mirror's back-only rule are each written once instead of
    once per damage source.
    """
    spec = spec_of(target)
    traits = getattr(spec, "traits", ())

    # ── the mirror: a hit from the front does nothing at all ─────────
    if "reflects" in traits and from_x is not None:
        arc = float(getattr(spec, "params", {}).get("reflect_arc", 1.5))
        facing_x = C.SISTER_X - target.x
        facing_y = C.SISTER_Y - target.y
        incoming_x, incoming_y = from_x - target.x, from_y - target.y
        fl = math.hypot(facing_x, facing_y) or 1.0
        il = math.hypot(incoming_x, incoming_y) or 1.0
        facing_dot = (facing_x * incoming_x + facing_y * incoming_y) / (fl * il)
        if facing_dot >= math.cos(arc):
            target.hit_flash = 0.10
            state.effects.append(Effect("reflect", target.x, target.y, 0.3, 0.3))
            state.emit(f"reflected:{target.spec}")
            return

    # ── weakness, and the window a matching skill opens ──────────────
    amount = int(round(amount * element_multiplier(
        element, getattr(spec, "weakness", None))))
    if target.memory.get("exposed", 0.0) > 0:
        amount = int(round(amount * C.EXPOSED_MULTIPLIER))

    # ── armour soaks before health does ──────────────────────────────
    if target.armour > 0:
        soaked = min(target.armour, amount)
        target.armour -= soaked
        amount -= soaked
        target.hit_flash = 0.12
        state.effects.append(Effect("clang", target.x, target.y, 0.25, 0.25))
        state.emit(f"armour:{target.spec}")
        if amount <= 0:
            return

    target.hp -= amount
    target.hit_flash = 0.12

    # Getting hit spoils whatever it was winding up.  Without this the wind-up
    # is only a countdown the player watches: reaching the archer in time
    # accomplishes nothing unless killing it outright, and "kill it or it fires"
    # is not a window, it is a deadline.  Bosses do not flinch — one that could
    # be permanently interrupted would never get a phase off.
    if target.charge > 0 and target not in state.bosses:
        target.charge = 0.0
        target.memory["reload"] = max(target.memory.get("reload", 0.0), 0.8)
        state.effects.append(Effect("spoiled", target.x, target.y, 0.35, 0.35))
        state.emit(f"interrupted:{target.spec}")
    if getattr(spec, "knockable", True) and from_x is not None:
        _push(target, from_x, from_y, 26.0)

    if target.hp > 0:
        state.feedback.bump(shake=3.0, freeze=0.035)
        fire_traits("hurt", traits, state, target, float(amount))
        state.emit(f"hit:{target.spec}")
        return

    _kill(state, target, by_lantern=by_lantern)


def _kill(state: State, target: Monster, *, by_lantern: bool) -> None:
    """Remove a monster, pay out, and fire its death traits."""
    spec = spec_of(target)
    payout = spec.sugar * (ELITE_SUGAR_FACTOR if target.elite else 1)

    # The combo pays out in sugar rather than in nothing.  The web build
    # counted combos and rewarded them with a number on screen, which reads as
    # an unfinished feature rather than as a reward.
    if state.combo >= C.COMBO_BONUS_AT:
        payout += 1

    state.drops.append(Drop(x=target.x, y=target.y, value=payout))
    # Only ever rolled when he is actually hurt, so a full-health player never
    # walks past a heart they cannot use and never learns to ignore them.
    if state.player.hp < derive(state).max_hp \
            and state.streams.loot.random() < C.HEART_DROP_CHANCE:
        state.drops.append(Drop(x=target.x + 14.0, y=target.y - 10.0,
                                value=0, heal=C.HEART_VALUE))
    state.effects.append(Effect("burst", target.x, target.y, 0.45, 0.45))

    state.stats.kills += 1
    if by_lantern:
        state.stats.kills_by_lantern += 1
        state.combo += 1
        state.combo_ticks = int(round(C.COMBO_WINDOW / C.FIXED_DT))
        state.stats.best_combo = max(state.stats.best_combo, state.combo)
        state.feedback.bump(shake=7.0, freeze=0.07)
    else:
        state.stats.kills_by_spell += 1

    fire_traits("death", getattr(spec, "traits", ()), state, target)

    if isinstance(target, Boss):
        state.bosses = [b for b in state.bosses if b is not target]
        state.feedback.bump(shake=20.0, freeze=0.3)
        state.emit(f"boss_down:{target.spec}")
    else:
        state.monsters = [m for m in state.monsters if m is not target]
        state.emit(f"kill:{target.spec}")

    if state.meta.mode is Mode.ENDLESS:
        state.kills_since_choice += 1


def hurt_player(state: State, amount: int) -> None:
    """Damage Hansel, and put him down rather than killing him.

    Zero HP costs the player five seconds of darkness while Gretel is
    undefended, so his mistake is paid for in the thing he is trying to
    protect.  Ending the run outright instead would quietly turn the game into
    "keep yourself alive", which is a different game and a worse one.
    ``C.DOWNED_ENABLED`` flips this back to instant loss if that call is
    reversed.
    """
    p = state.player
    if state.meta.godmode or p.guarding:
        state.feedback.bump(shake=2.0)     # still says a hit landed
        return
    if p.invulnerable > 0 or p.dash > 0 or p.downed > 0:
        return

    taken = max(1, int(amount))
    p.hp -= taken
    p.invulnerable = C.INVULNERABLE_TIME
    state.stats.damage_taken += taken
    state.feedback.bump(shake=4.0, hurt=0.35)
    state.emit("player_hurt")

    if p.hp > 0:
        return

    p.hp = 0
    p.downs += 1
    state.stats.downs += 1
    state.emit("player_down")
    state.feedback.bump(shake=16.0, freeze=0.3, hurt=0.9)

    if not C.DOWNED_ENABLED or p.downs > C.DOWNED_ALLOWANCE:
        state.phase = Phase.LOST
        state.emit("lost")
        return
    p.downed = C.DOWNED_SECONDS


# ── monsters ─────────────────────────────────────────────────────────
def _advance_monsters(state: State, dt: float) -> None:
    """Tick every monster: traits, behaviour, then contact."""
    p = state.player
    survivors: list[Monster] = []

    for monster in state.monsters:
        spec = spec_of(monster)
        monster.hit_flash = max(0.0, monster.hit_flash - dt)
        monster.stunned = max(0.0, monster.stunned - dt)
        if monster.memory.get("exposed", 0.0) > 0:
            monster.memory["exposed"] -= dt

        if monster.wake > 0:
            monster.wake -= dt
            if monster.wake <= 0:
                state.effects.append(Effect("wake", monster.x, monster.y, 0.4, 0.4))
                fire_traits("spawn", spec.traits, state, monster)
            survivors.append(monster)
            continue

        if monster.stunned > 0:
            survivors.append(monster)
            continue

        # Tick traits run before the behaviour so one of them (light-fear) can
        # veto movement this frame by setting ``frozen``.
        monster.frozen = False
        fire_traits("tick", spec.traits, state, monster)

        if monster.knockback > 0:
            _apply_knockback(state, monster, dt)
        elif not monster.frozen:
            run_behaviour(spec.behaviour, state, monster, dt)

        if _touch_player(state, monster, spec):
            pass                      # contact resolved; the monster survives

        if g.distance(monster.x, monster.y, C.SISTER_X, C.SISTER_Y) < C.SISTER_REACH:
            _reach_sister(state, monster, spec)
            continue

        survivors.append(monster)

    state.monsters = survivors


def _apply_knockback(state: State, monster: Monster, dt: float) -> None:
    """Slide a monster along the direction the hit came from.

    One routine for every source, so a shove and a lantern hit move a body in
    exactly the same way — which is the point: they should read as the same
    physical event, because they are.
    """
    dx, dy = monster.knock_x, monster.knock_y
    if dx == 0.0 and dy == 0.0:
        # No recorded direction (an older save, or a push with no attacker):
        # fall back to straight back from Gretel.
        dx, dy = g.normalise(monster.x - C.SISTER_X, monster.y - C.SISTER_Y)
    travel = min(monster.knockback, 150.0 * dt)
    radius = spec_of(monster).radius
    monster.x, monster.y = g.slide(
        state.obstacles, monster.x, monster.y,
        g.clamp(monster.x + dx * travel, 8, C.WIDTH - 8),
        g.clamp(monster.y + dy * travel, 8, C.HEIGHT - 8),
        radius)
    monster.knockback -= travel


def _push(monster: Monster, from_x: float, from_y: float,
          distance: float) -> None:
    """Knock a body directly away from whatever hit it."""
    dx, dy = g.normalise(monster.x - from_x, monster.y - from_y)
    if dx == 0.0 and dy == 0.0:
        dx, dy = g.normalise(monster.x - C.SISTER_X, monster.y - C.SISTER_Y)
    monster.knock_x, monster.knock_y = dx, dy
    monster.knockback = max(monster.knockback, distance)


def _touch_player(state: State, monster: Monster, spec) -> bool:
    """Resolve a monster bumping into Hansel.  Returns True when it happened."""
    p = state.player
    if p.downed > 0:
        return False
    if not g.circles_touch(monster.x, monster.y, spec.radius,
                           p.x, p.y, C.PLAYER_RADIUS):
        return False

    # 疾風 — he is the hazard now.  Checked before the guard because running
    # someone down is an attack, and an attack that lost to a defensive state
    # would make the two skills cancel each other for no reason a player could
    # guess.
    if p.haste > 0:
        spec = SPELL_TABLE.get("windrun")
        push = float(spec.params.get("push", 120.0)) if spec else 120.0
        _push(monster, p.x, p.y, push)
        damage_target(state, monster,
                      int(spec.params.get("boss", 5)) if spec and monster in
                      state.bosses else 999,
                      from_x=p.x, from_y=p.y)
        state.effects.append(Effect("gale", monster.x, monster.y, 0.3, 0.3))
        return True

    # 雷鳴 — the armour answers for him.  It costs the attacker a heart and a
    # moment, and stores the hit for the discharge when the five seconds lapse.
    if p.aura > 0:
        p.aura_hits += 1.0
        monster.stunned = max(monster.stunned, 0.45)
        damage_target(state, monster, 1, element="thunder",
                      from_x=p.x, from_y=p.y)
        state.effects.append(Effect("spark", monster.x, monster.y, 0.25, 0.25))
        state.emit("zapped")
        return True

    # Guarding: it bumps off him and he loses nothing.  The nudge is the same
    # small recoil a lantern hit gives, through the same routine, because
    # contact that moves nothing does not read as contact at all — but it stays
    # small, so guarding never becomes a way to push a crowd around.
    if p.guarding:
        _push(monster, p.x, p.y, C.GUARD_NUDGE)
        state.effects.append(Effect("guard_hit", monster.x, monster.y, 0.2, 0.2))
        state.emit("guarded")
        return True

    if p.invulnerable > 0 or p.dash > 0:
        return False

    push = g.distance(p.x, p.y, monster.x, monster.y) or 1.0
    p.stun = C.STUN_TIME
    p.knock_x = (p.x - monster.x) / push * C.KNOCKBACK_SPEED
    p.knock_y = (p.y - monster.y) / push * C.KNOCKBACK_SPEED
    monster.knockback = max(monster.knockback, 14.0)

    # Contact costs health and position — but deliberately *not* sight.  The
    # web prototype doused the lantern on every collision, which was fine when
    # the player had no health bar to lose.  Now that he has one, charging both
    # costs for one mistake reads as the game piling on, and it makes the
    # deacon's dousing trait indistinguishable from bumping into anyone.  One
    # threat, one cost; the trait is what takes your sight.

    fire_traits("touch_player", getattr(spec, "traits", ()), state, monster)
    hurt_player(state, 1)
    return True


def _reach_sister(state: State, monster: Monster, spec) -> None:
    """A monster got to Gretel.  This is the only way the run can be lost."""
    damage = getattr(spec, "contact_damage", 1)
    if not state.meta.godmode:
        state.meta.sister_hp = max(0, state.meta.sister_hp - damage)
    state.stats.reached_sister += 1
    state.feedback.bump(shake=6.0, hurt=0.8)
    state.effects.append(Effect("taken", C.SISTER_X, C.SISTER_Y, 0.6, 0.6))
    fire_traits("reach_sister", getattr(spec, "traits", ()), state, monster)
    state.emit("reached")


# ── bosses ───────────────────────────────────────────────────────────
def _advance_bosses(state: State, dt: float) -> None:
    for boss in list(state.bosses):
        spec = BOSSES.get(boss.spec)
        if spec is None:
            continue
        boss.hit_flash = max(0.0, boss.hit_flash - dt)
        boss.stunned = max(0.0, boss.stunned - dt)
        if boss.stunned > 0:
            continue

        phase = _boss_phase(state, boss, spec)
        # ``min`` rather than assignment: two bosses is not a case tonight, but
        # the thickest fog winning is the answer that stays right if it ever is.
        state.fog_scale = min(state.fog_scale, phase.fog)
        if boss.memory.get("exposed", 0.0) > 0:
            boss.memory["exposed"] -= dt
        fire_traits("tick", getattr(spec, "traits", ()), state, boss)
        if boss.knockback > 0:
            _apply_knockback(state, boss, dt)
        else:
            run_behaviour(phase.behaviour, state, boss, dt)

        _boss_summons(state, boss, phase, dt)

        if _touch_player(state, boss, spec):
            pass
        if g.distance(boss.x, boss.y, C.SISTER_X, C.SISTER_Y) < C.SISTER_REACH:
            _reach_sister(state, boss, spec)
            # The boss is pushed off rather than removed: a boss that vanishes
            # by touching Gretel would be a way to skip the fight.
            _push(boss, C.SISTER_X, C.SISTER_Y, 120.0)


def _boss_phase(state: State, boss: Boss, spec):
    """Return the boss's current phase, announcing a transition once."""
    fraction = boss.hp / max(1, boss.max_hp)
    index = 0
    for i, phase in enumerate(spec.phases):
        index = i
        if fraction > phase.until_hp:
            break
    else:
        index = len(spec.phases) - 1

    if index != boss.phase_index:
        boss.phase_index = index
        boss.memory.clear()
        announcement = spec.phases[index].announce
        if announcement:
            state.emit(f"boss_say:{announcement}")
        state.feedback.bump(shake=10.0)
    return spec.phases[boss.phase_index]


def _boss_summons(state: State, boss: Boss, phase, dt: float) -> None:
    """Keep the boss's escort coming, one timer per summon entry."""
    for key, every in phase.summons:
        slot = f"summon_{key}"
        boss.memory[slot] = boss.memory.get(slot, every) - dt
        if boss.memory[slot] > 0:
            continue
        boss.memory[slot] = every
        child = MONSTERS.get(key)
        if child is None:
            continue
        angle = state.rng.random() * math.tau
        state.monsters.append(
            Monster(spec=key,
                    x=g.clamp(boss.x + math.cos(angle) * 44, 10, C.WIDTH - 10),
                    y=g.clamp(boss.y + math.sin(angle) * 44, 10, C.HEIGHT - 10),
                    hp=child.hp, speed=child.speed)
        )


def spawn_boss(state: State, key: str) -> None:
    """Bring a boss in from the edge, loudly."""
    spec = BOSSES.get(key)
    if spec is None or any(b.spec == key for b in state.bosses):
        return
    x, y = g.edge_point(state.rng)
    state.bosses.append(
        Boss(spec=key, x=x, y=y, hp=spec.hp, speed=spec.speed,
             max_hp=spec.hp)
    )
    state.feedback.bump(shake=20.0, freeze=0.5)
    state.effects.append(Effect("boss_enter", x, y, 1.2, 1.2))
    state.emit(f"boss_enter:{key}")


# ── projectiles, effects, pickups ────────────────────────────────────
def _advance_projectiles(state: State, dt: float) -> None:
    alive: list[Projectile] = []
    for shot in state.projectiles:
        shot.life -= dt
        shot.x += shot.vx * dt
        shot.y += shot.vy * dt

        if shot.life <= 0 or not (0 <= shot.x <= C.WIDTH and 0 <= shot.y <= C.HEIGHT):
            continue
        if g.blocked_by(state.obstacles, shot.x, shot.y, shot.radius):
            state.effects.append(Effect("spark", shot.x, shot.y, 0.2, 0.2))
            continue

        if not shot.friendly:
            if g.circles_touch(shot.x, shot.y, shot.radius,
                               C.SISTER_X, C.SISTER_Y, C.SISTER_REACH * 0.7):
                if not state.meta.godmode:
                    state.meta.sister_hp = max(
                        0, state.meta.sister_hp - shot.damage)
                state.stats.reached_sister += 1
                state.feedback.bump(shake=5.0, hurt=0.6)
                state.emit("sister_hit")
                continue
            if g.circles_touch(shot.x, shot.y, shot.radius,
                               state.player.x, state.player.y, C.PLAYER_RADIUS):
                hurt_player(state, shot.damage)
                continue

        alive.append(shot)
    state.projectiles = alive


def _advance_obstacles(state: State, dt: float) -> None:
    """Crumble anything a monster built.  Map scenery has ``life`` below zero."""
    alive: list[Obstacle] = []
    for block in state.obstacles:
        if block.life > 0:
            block.life -= dt
            if block.life <= 0:
                state.effects.append(Effect("rock_gone", block.x, block.y,
                                            0.4, 0.4, block.radius))
                continue
        alive.append(block)
    state.obstacles = alive


def _advance_hazards(state: State, dt: float) -> None:
    """Move the twisters, spring the traps.

    Both kinds live here because both are the same shape of thing: a circle with
    a lifetime that does something to whatever is inside it.  What differs is
    whether the circle moves — and whether being caught means *travelling with
    it* or *being pinned where it stands*.
    """
    alive: list[Hazard] = []
    for hazard in state.hazards:
        hazard.life -= dt
        if hazard.life <= 0:
            # The water cage does not simply expire — it is a five-second
            # sentence, and this is the sentence being carried out.
            if hazard.kind == "cage":
                from .effects import _kill_within

                _kill_within(state, hazard.x, hazard.y, hazard.radius,
                             "water", push=hazard.strength,
                             boss=int(hazard.charges) if hazard.charges > 0
                             else 6)
                state.effects.append(Effect("cage_burst", hazard.x, hazard.y,
                                            0.5, 0.5, hazard.radius))
                state.feedback.bump(shake=12.0, freeze=0.06)
                state.emit("cage_burst")
            continue

        hazard.x += hazard.vx * dt
        hazard.y += hazard.vy * dt
        moving = hazard.vx != 0.0 or hazard.vy != 0.0
        if moving and not (0 <= hazard.x <= C.WIDTH and 0 <= hazard.y <= C.HEIGHT):
            continue

        for target in state.monsters:
            if not target.awake or target.buried > 0:
                continue
            if g.distance(target.x, target.y, hazard.x, hazard.y) > hazard.radius:
                continue
            if hazard.charges == 0:
                break
            hazard.sprung = True
            if hazard.charges > 0:
                hazard.charges -= 1
            if hazard.kind == "cage":
                # Refreshed every tick: whoever is inside stays inside, and
                # anyone who wanders in afterwards is caught too.
                target.stunned = max(target.stunned, hazard.life + 0.1)
                continue
            target.stunned = max(target.stunned, hazard.hold)
            target.knockback = 0.0
            if moving:
                # Carried, not pushed.  It is off the ground, so it travels
                # with the funnel and ignores the obstacles it passes over —
                # sliding it around scenery would drop it out of the twister
                # and read as the skill failing.
                target.x = g.clamp(target.x + hazard.vx * dt, 8, C.WIDTH - 8)
                target.y = g.clamp(target.y + hazard.vy * dt, 8, C.HEIGHT - 8)

        # A boss is too heavy to lift.  It still feels the wind — the element's
        # window opens — but a skill that could park a boss at the map edge for
        # five seconds would be the only skill anyone ever brought.
        for boss in state.bosses:
            if g.distance(boss.x, boss.y, hazard.x, hazard.y) <= hazard.radius:
                boss.stunned = max(boss.stunned, min(0.4, hazard.hold))

        if hazard.charges == 0:
            state.effects.append(Effect("trap_spring", hazard.x, hazard.y,
                                        0.4, 0.4, hazard.radius))
            continue
        alive.append(hazard)
    state.hazards = alive


def _advance_puddles(state: State, dt: float) -> None:
    """Age the ground.  Anything with a finite life eventually dries out."""
    alive: list[Puddle] = []
    for pool in state.puddles:
        if pool.life > 0:
            pool.life -= dt
            if pool.life <= 0:
                continue
        alive.append(pool)
    state.puddles = alive


def _advance_effects(state: State, dt: float) -> None:
    for effect in state.effects:
        effect.left -= dt
    state.effects = [e for e in state.effects if e.left > 0]


def _collect_drops(state: State) -> None:
    """Pick up sugar the player walks onto — and decoys, which bite."""
    p = state.player
    if p.downed > 0:
        return
    remaining: list[Drop] = []
    for drop in state.drops:
        if g.distance(drop.x, drop.y, p.x, p.y) >= C.DROP_PICKUP_RADIUS:
            remaining.append(drop)
            continue
        if drop.heal > 0:
            stats = derive(state)
            if p.hp >= stats.max_hp:
                remaining.append(drop)      # leave it for when it is needed
                continue
            p.hp = min(stats.max_hp, p.hp + drop.heal)
            state.effects.append(Effect("mend", p.x, p.y, 0.5, 0.5))
            state.emit("mended")
        elif drop.fake:
            hurt_player(state, drop.value)
            state.emit("decoy")
        else:
            state.meta.sugar += drop.value
            state.stats.sugar_picked += drop.value
            state.emit("picked")
    state.drops = remaining


def _tick_cooldowns(state: State) -> None:
    for key, left in list(state.cooldowns.items()):
        if left > 0:
            state.cooldowns[key] = left - 1


def _tick_combo(state: State) -> None:
    if state.combo <= 0:
        return
    state.combo_ticks -= 1
    if state.combo_ticks <= 0:
        state.combo = 0


# ── night events ─────────────────────────────────────────────────────
def _tick_event(state: State) -> None:
    """Count down the active event, and the two timed conditions it can set."""
    if state.reveal_ticks > 0:
        state.reveal_ticks -= 1
    if state.hush_ticks > 0:
        state.hush_ticks -= 1

    if state.event is None:
        return
    state.event_ticks -= 1
    if state.event_ticks <= 0:
        state.light_scale = 1.0        # whatever the event changed, undo it
        state.emit(f"event_over:{state.event}")
        state.event = None


def trigger_event(state: State, key: str) -> None:
    """Start a night event, announcing it.

    Announcing is not decoration.  A rule that changes without warning is
    indistinguishable from a bug, and a player who believes the game is broken
    stops trying to read it.
    """
    spec = EVENTS.get(key)
    if spec is None:
        return
    state.event = key
    state.event_ticks = max(1, int(round(spec.duration / C.FIXED_DT)))
    entry = EVENT_EFFECTS.get(spec.effect)
    if entry is not None:
        entry.fn(state, spec)
    state.emit(f"event:{key}")


# ── spells ───────────────────────────────────────────────────────────
def cast(state: State, key: str) -> None:
    """Use a learned skill, if it is off cooldown and would do anything."""
    if state.player.helpless:
        return                          # flat on his back, not chanting
    if key not in state.meta.skills or state.cooldowns.get(key, 0) > 0:
        return
    spec = SPELL_TABLE.get(key)
    if spec is None:
        return
    entry = SPELL_EFFECTS.get(spec.effect)
    if entry is None:
        return
    if spec.needs_target \
            and not any(m.active for m in state.monsters) and not state.bosses:
        return                          # never let a spell be wasted on nothing

    if getattr(spec, "charge", False):
        # Hold to build it.  The cooldown is not spent until it actually goes
        # off, so letting go early costs the charge, never the skill.
        p = state.player
        if p.charging != key:
            p.charging, p.charge_time = key, 0.0
            state.emit(f"charge:{key}")
        else:
            p.charge_time = min(C.CHARGE_MAX, p.charge_time + C.FIXED_DT)
        return

    _spend_cooldown(state, key, spec)
    entry.fn(state, spec)
    state.emit(f"cast:{key}")


def _spend_cooldown(state: State, key: str, spec) -> None:
    """Put a skill on cooldown, after the 技能冷卻 upgrade has had its say."""
    scale = derive(state).cooldown_scale
    state.cooldowns[key] = max(1, int(round(spec.cooldown * scale / C.FIXED_DT)))


def release_charge(state: State) -> None:
    """Let go of a charged skill and fire it at whatever it reached."""
    p = state.player
    key, p.charging = p.charging, ""
    spec = SPELL_TABLE.get(key)
    entry = SPELL_EFFECTS.get(spec.effect) if spec else None
    if spec is None or entry is None:
        p.charge_time = 0.0
        return
    _spend_cooldown(state, key, spec)
    entry.fn(state, spec)
    state.emit(f"cast:{key}")
    p.charge_time = 0.0


# ── stage setup ──────────────────────────────────────────────────────
def begin_night(state: State, director) -> State:
    """Hand the square over to the dark.

    Lives here rather than in the action layer so that both routes into night —
    the player pressing the button, and the day clock simply running out —
    produce exactly the same state.
    """
    if state.phase is not Phase.DAY:
        return state
    state.phase = Phase.NIGHT
    state.dusk = 0.0
    state.fog_scale = 1.0
    state.hazards = []
    state.mist_ticks = 0
    p = state.player
    p.charging, p.charge_time = "", 0.0
    p.aura = p.aura_hits = p.haste = p.mending = p.holy = 0.0
    # Dawn puts her back together.  Carrying her wounds forward meant one bad
    # night quietly decided the next three, and a run could be lost hours before
    # it ended — the player was still playing, but the game was already over.
    state.meta.sister_hp = state.meta.max_sister_hp
    director.begin_night(state)

    # Hansel is refreshed for the night; his health is the per-night resource.
    # Gretel's is not — hers carries, which is what makes damage to her matter.
    stats = derive(state)
    state.player.max_hp = stats.max_hp
    state.player.hp = stats.max_hp
    state.player.downs = 0
    state.player.doused = 0.0
    state.player.downed = 0.0
    state.player.x, state.player.y = C.SISTER_X, C.SISTER_Y + 92.0

    from .director import _roll_event
    _roll_event(state)
    state.emit("nightfall")
    return state


def load_map(state: State, key: str) -> None:
    """Install a map's geometry into the state."""
    spec = MAPS.get(key)
    state.stage = key
    state.obstacles = []
    if spec is None:
        return
    for x, y, radius, blocks in spec.obstacles:
        state.obstacles.append(Obstacle(x=x, y=y, radius=radius,
                                        blocks_sight=blocks))


def make_monster(state: State, key: str, x: float, y: float, *,
                 wake: float = 0.0, elite: bool = False) -> Monster:
    """Build one monster from its spec, applying the elite multipliers."""
    spec = MONSTERS.get(key) or MONSTERS["villager"]
    hp = int(spec.hp * (ELITE_HP_FACTOR if elite else 1.0))
    speed = spec.speed * (ELITE_SPEED_FACTOR if elite else 1.0)
    monster = Monster(spec=key, x=x, y=y, hp=hp, speed=speed,
                      wake=wake, elite=elite)
    escalate_speed(monster, state.elapsed)
    state.stats.arrivals += 1
    if elite:
        fire_traits("spawn", ("elite_aura",), state, monster)
    return monster


def add_warning(state: State, key: str, x: float, y: float, *,
                surge: bool = False) -> None:
    state.warnings.append(Warning(x=x, y=y, spec=key,
                                  left=C.WARN_SECONDS, surge=surge))


def resolve_warnings(state: State, dt: float) -> None:
    """Turn expired telegraphs into real monsters."""
    pending: list[Warning] = []
    for warning in state.warnings:
        warning.left -= dt
        if warning.left > 0:
            pending.append(warning)
            continue
        state.monsters.append(make_monster(state, warning.spec,
                                           warning.x, warning.y))
    state.warnings = pending


def sleepers_wake(state: State, dt: float) -> None:
    """Wake tonight's daylight villagers on their scheduled ticks.

    They are stored as plain tuples until they turn, so the day screen and the
    night spawn cannot disagree about who is coming — which is the whole point
    of showing them in daylight.
    """
    still_asleep: list[tuple[str, float, float, int]] = []
    for key, x, y, wake_tick in state.sleepers:
        if state.ticks_elapsed >= wake_tick:
            monster = make_monster(state, key, x, y)
            state.monsters.append(monster)
            state.emit(f"turn:{key}")
        else:
            still_asleep.append((key, x, y, wake_tick))
    state.sleepers = still_asleep


# ── endings ──────────────────────────────────────────────────────────
def _resolve_ending(state: State, director) -> None:
    """Decide whether the night is over, and how."""
    if state.meta.sister_hp <= 0:
        state.phase = Phase.LOST
        state.emit("lost")
        return
    if state.phase is Phase.LOST:
        return
    director.check_end(state)
