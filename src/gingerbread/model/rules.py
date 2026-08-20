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
def _accept_casts(state: State, inputs, dt: float) -> None:
    """把這一格按下的技能鍵處理掉。

    A held key does *not* arrive on every tick: the shell sends movement and
    casting as two separate actions, so the movement tick always looks like
    "the key is up".  Charging therefore ends only after several consecutive
    ticks with no cast — which is why holding the key used to fire instantly.
    """
    held = {w.split(":", 1)[1] for w in inputs if w.startswith("cast:")}
    p = state.player
    if p.charging:
        if p.charging in held:
            p.charge_idle = 0.0
        else:
            p.charge_idle += dt
            if p.charge_idle > C.CHARGE_RELEASE:
                release_charge(state)
    for key in held:
        cast(state, key)


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

    # 頓幀凍結的是**世界**，不是玩家的手。
    #
    # 這個 return 原本擋在施法之前，所以任何在頓幀期間按下的技能都會被整包丟
    # 掉 —— 而頓幀正好發生在最想按技能的那些時刻：王進場（0.12 秒）、每一次
    # 擊殺（0.035 秒）、怒潮爆炸（0.08 秒）。玩家按了，什麼都沒發生，然後怪
    # 到臉上。他學到的是「這技能有時候會失靈」。
    #
    # 施法搬到凍結判斷之前。技能在被凍住的那一格生效，世界下一格才恢復 ——
    # 兩三格的差別看不出來，按下去沒反應則是每次都看得出來。
    _accept_casts(state, inputs, dt)

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
        if pool.spares_player:
            continue
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

    if state.ward > 0:
        state.ward = max(0.0, state.ward - dt)
        if state.ward <= 0:
            state.effects.append(
                Effect("ward_off", C.SISTER_X, C.SISTER_Y, 0.5, 0.5, 70))
            state.emit("ward_off")

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
    #
    # 除非聖光正亮著。鏡子怪靠的是漢賽爾看不清楚自己站在它的哪一邊 —— 聖光
    # 把那個條件拿掉，所以照著的時候正面也打得進去。這是這款遊戲最直接的一組
    # 克制：光的技能，解掉靠黑暗吃飯的怪。
    #
    # 綁的是「聖光正在生效」，不是「場上剛好是亮的」。
    #
    # reveal_ticks 有兩個來源：聖光這個技能，以及「月光」這個夜間事件 —— 而
    # 月光的設計註解明寫著「不會定住怕光的東西」。用 reveal_ticks 當條件的
    # 話，一個隨機事件會把玩家花技能點換來的克制關係免費送出去十秒，還順便
    # 推翻那個事件自己的設計。player.holy 只有聖光會設。
    if ("reflects" in traits and from_x is not None
            and state.player.holy <= 0):
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

    # ── the hob: red hot, and nothing lands until it is put out ──────
    #
    # An ordinary weakness is an *incentive* — matching it hits harder.  This
    # one is a *gate*: the fight does not begin until the player brings water.
    # Written as a trait rather than as a rule about the ash hob so the witch
    # can wear the same armour in her fire phase without a second code path.
    #
    # The gate opens on ``exposed``, which is exactly what a matching-element
    # skill already sets — so 水牢 and 怒潮 unlock it and nothing else does,
    # without either spell needing to know this boss exists.
    if "needs_soak" in traits and target.memory.get("exposed", 0.0) <= 0:
        target.hit_flash = 0.10
        state.effects.append(Effect("clang", target.x, target.y, 0.3, 0.3))
        state.emit(f"armour:{target.spec}")
        return

    # ── weakness, and the window a matching skill opens ──────────────
    amount = int(round(amount * element_multiplier(
        element, getattr(spec, "weakness", None))))
    if target.memory.get("exposed", 0.0) > 0:
        amount = int(round(amount * C.EXPOSED_MULTIPLIER))

    # ── 王的上限：一次技能不准把一場戰鬥刪掉 ─────────────────────
    #
    # 放在克制與破綻視窗**之後**，因為要砍的正是那兩個乘起來的結果。放在護甲
    # 之前，因為護甲本來就該先吃。
    if not by_lantern and isinstance(target, Boss):
        share = float(getattr(spec, "spell_cap", 0.12))
        amount = min(amount, max(1, int(round(target.max_hp * share))))

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
    # 王也會被打斷 —— 但打斷過一次之後有一小段免疫。
    #
    # 原本王完全不會被打斷，理由是「一個能被永久打斷的王永遠放不出招」。那個
    # 顧慮是對的，解法不是。褪影射手站在遠處慢慢拉弓，玩家看得到蓄力光、跑過
    # 去、打中它 —— 然後箭照樣射出來。畫面上明明是一個「快去阻止它」的提示，
    # 而阻止它這件事實際上不存在，那個提示等於在騙人。
    #
    # 免疫窗口解決原本的顧慮：打斷一次要付出跑過去的代價，而它兩秒內不會再被
    # 打斷第二次，所以下一輪蓄力一定放得出來。
    interruptible = (target not in state.bosses
                     or target.memory.get("unflinch", 0.0) <= 0)
    if target.charge > 0 and interruptible:
        target.charge = 0.0
        target.memory["reload"] = max(target.memory.get("reload", 0.0), 0.8)
        if target in state.bosses:
            target.memory["unflinch"] = C.BOSS_FLINCH_GAP
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

    # Once tonight's budget is spent the bodies stop being worth anything.
    # Capped where the sugar is *created* rather than where it is picked up, so
    # what the player sees on the ground is always what they can still earn —
    # a crystal that pays nothing would read as a bug, not as a limit.
    payout = int(round(payout * float(state.meta.dials["sugar"])))
    payout = min(payout, state.meta.sugar_left_tonight(state.meta.night))
    if payout > 0:
        state.meta.bank_night_sugar(state.meta.night, payout)
        state.drops.append(Drop(x=target.x, y=target.y, value=payout))
    # Only ever rolled when he is actually hurt, so a full-health player never
    # walks past a heart they cannot use and never learns to ignore them.
    if state.player.hp < derive(state).max_hp \
            and state.streams.loot.random() < C.HEART_DROP_CHANCE:
        state.drops.append(Drop(x=target.x + 14.0, y=target.y - 10.0,
                                value=0, heal=C.HEART_VALUE))

    # 葛蕾特的血過去只有 聖癒 和白天買繃帶能補，所以一個前面幾夜掉了三顆心
    # 的玩家，等於帶著永久的傷走完剩下的四夜 —— 一次失誤決定了整局，而且是
    # 在他還沒學會怎麼玩的時候決定的。
    #
    # 同樣只在她真的受傷時才擲，機率更低、發光更亮。撿它要離開崗位走過去，
    # 所以它從來不是白拿的：那是一個「現在敢不敢離開她三秒」的決定。
    if state.meta.sister_hp < state.meta.max_sister_hp \
            and state.streams.loot.random() < C.SISTER_HEART_CHANCE:
        state.drops.append(Drop(x=target.x - 14.0, y=target.y - 10.0,
                                value=0, heal=C.HEART_VALUE, sister=True))
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
            survivors.append(monster)
            continue

        # Tick traits run before the behaviour so one of them (light-fear) can
        # veto movement this frame by setting ``frozen``.
        monster.frozen = False
        fire_traits("tick", spec.traits, state, monster)

        # Knockback outranks the stun.  Being thrown is not an action the
        # monster takes, so a stun should not cancel it — and ordered the other
        # way round it did: the stun check returned first, the body froze where
        # it stood, and the push it had just been handed was silently dropped
        # on the next frame.  Every skill that stunned *and* shoved therefore
        # only stunned, which is why 疾風 read as doing nothing at all.
        if monster.knockback > 0:
            _apply_knockback(state, monster, dt)
        elif monster.stunned > 0:
            survivors.append(monster)
            continue
        elif not monster.frozen:
            run_behaviour(spec.behaviour, state, monster, dt)

        if _touch_player(state, monster, spec):
            pass                      # contact resolved; the monster survives

        # 正在被擊退的身體不算「走到葛蕾特身上」。
        #
        # 它不是走過去的，是被扔過去的 —— 而扔它的人就是為了讓它離開才扔的。
        # 沒有這一條，任何把怪物推過場地中央的技能都會在半路上替玩家扣掉葛蕾
        # 特的血，於是「清場」這個動作本身變成一種風險，玩家學到的是不要用。
        if (monster.knockback <= 0
                and g.distance(monster.x, monster.y,
                               C.SISTER_X, C.SISTER_Y) < C.SISTER_REACH):
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
    travel = min(monster.knockback, max(60.0, monster.knock_speed) * dt)
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
    monster.knock_speed = C.KNOCK_SPEED


def _contact_ready(target: Monster, tag: str) -> bool:
    """接觸傷害對王的節流閥。回傳 True 代表這一次算數，並開始冷卻。

    ``_touch_player`` 是每一幀都會跑的 —— 只要身體還疊著，它就一直回報「碰
    到了」。對小怪無所謂（第一下就死了），對王是災難：貼著它來回蹭，六點傷
    害乘以每秒六十幀等於每秒三百六十，任何王都撐不過兩秒。

    ``memory`` 上的一個倒數計時器就夠了。它由 ``_advance_bosses`` 每格遞減，
    所以節流是照時間算的，不是照幀數 —— 換了更新率也還是同一個手感。
    """
    if target.memory.get(tag, 0.0) > 0:
        return False
    target.memory[tag] = C.CONTACT_GAP
    return True


def _boss_budget(target: Monster, tag: str, cap: int) -> bool:
    """這一次施法還打得動這隻王嗎？打得動就記一次。

    節流閥（``_contact_ready``）管的是「每秒最多幾下」，這個管的是「一次施法
    總共幾下」。兩個都需要：只有節流閥的話，疾風六秒仍然磨得掉 93% 的血 ——
    貼著王來回蹭這件事，不該是這款遊戲對王的正解。

    計數器記在王身上、由施法的那一刻清零，所以它天然跟著「一次施法」走，不
    需要在玩家身上再開一個欄位。
    """
    spent = target.memory.get(tag, 0.0)
    if spent >= cap:
        return False
    target.memory[tag] = spent + 1.0
    return True


def _touch_player(state: State, monster: Monster, spec) -> bool:
    """Resolve a monster bumping into Hansel.  Returns True when it happened."""
    p = state.player
    if p.downed > 0:
        return False
    reach = C.PLAYER_RADIUS
    if p.haste > 0:
        gale = SPELL_TABLE.get("windrun")
        reach = float(gale.params.get("sweep", 34.0)) if gale else 34.0
    if not g.circles_touch(monster.x, monster.y, spec.radius,
                           p.x, p.y, reach):
        return False

    # 疾風 — 漢賽爾本人變成一道旋風。
    #
    # 撞上去的東西會被**往他前進的方向**捲走，一路捲到場地邊上。方向取自他的
    # 移動方向而不是幾何上的推離，因為旋風就是這樣運作的 —— 玩家轉向哪裡，
    # 被捲的人就飛去哪裡，這是一條看一眼就懂的規則。
    #
    # 一開始的版本是從漢賽爾身上往外推，而他大半時間站在葛蕾特和怪物之間，
    # 所以「衝過去撞開它」的結果是把它撞到她身上。第二版改成一律推離葛蕾特，
    # 方向是安全了，但手感很怪：怪物會沿著一條跟玩家動作無關的線飛走。
    #
    # 真正該修的不是方向，是那條「被扔出去的身體照樣能傷到葛蕾特」的規則 ——
    # 見 _advance_monsters 裡的擊退判斷。修掉之後方向就自由了。
    if p.haste > 0:
        spec = SPELL_TABLE.get("windrun")
        push = float(spec.params.get("push", 460.0)) if spec else 460.0
        dx, dy = g.normalise(p.face_x, p.face_y)
        if dx == 0.0 and dy == 0.0:
            dx, dy = g.normalise(monster.x - p.x, monster.y - p.y)
        if dx == 0.0 and dy == 0.0:
            dx, dy = 1.0, 0.0
        monster.knock_x, monster.knock_y = dx, dy
        monster.knockback = max(monster.knockback, push)
        monster.knock_speed = C.TORNADO_SPEED
        monster.stunned = max(monster.stunned, 0.5)
        if (monster in state.bosses and _contact_ready(monster, "swept")
                and _boss_budget(monster, "swept_hits", C.GALE_BOSS_HITS)):
            damage_target(state, monster,
                          int(spec.params.get("boss", 6)) if spec else 6,
                          element="wind", from_x=p.x, from_y=p.y)
        state.effects.append(Effect("gale", monster.x, monster.y, 0.35, 0.35))
        state.emit("swept")
        return True

    # 雷鳴 — 碰到就死。
    #
    # 這才是「披上雷電護甲」該有的意思。原本一次只扣一滴血，對著三四滴血的
    # 怪等於什麼都沒發生，玩家看到的是自己被圍住、身上閃著紫光、然後照樣被
    # 推開。現在它是一堵會殺人的牆：站住不動就是這個技能的玩法。
    if p.aura > 0:
        if monster in state.bosses and not (
                _contact_ready(monster, "zapped")
                and _boss_budget(monster, "zapped_hits", C.AURA_BOSS_HITS)):
            return True               # 冷卻中或這一次施法的份額用完了
        p.aura_hits += 1.0
        spec = SPELL_TABLE.get("thunderclap")
        amount = (int(spec.params.get("boss", 18)) if spec and monster in
                  state.bosses else 999)
        damage_target(state, monster, amount, element="thunder",
                      from_x=p.x, from_y=p.y)
        state.effects.append(Effect("spark", monster.x, monster.y, 0.3, 0.3))
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
    if _warded(state, monster):
        return
    damage = getattr(spec, "contact_damage", 1)
    if not state.meta.godmode:
        state.meta.sister_hp = max(0, state.meta.sister_hp - damage)
    state.stats.reached_sister += 1
    state.feedback.bump(shake=6.0, hurt=0.8)
    state.effects.append(Effect("taken", C.SISTER_X, C.SISTER_Y, 0.6, 0.6))
    fire_traits("reach_sister", getattr(spec, "traits", ()), state, monster)
    state.emit("reached")


# ── bosses ───────────────────────────────────────────────────────────
def _warded(state: State, monster: Monster | None) -> bool:
    """True when 聖癒's shield is up — and it throws off whatever touched it.

    Absorbing silently would read as the hit missing.  The shove is what says
    *the shield did that*, which is the difference between a skill the player
    trusts and one they are not sure they cast.
    """
    if state.ward <= 0:
        return False
    if monster is not None:
        _push(monster, C.SISTER_X, C.SISTER_Y, C.WARD_PUSH)
    state.effects.append(Effect("ward_hit", C.SISTER_X, C.SISTER_Y, 0.3, 0.3, 44))
    state.emit("warded")
    return True


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
        if boss.memory.get("unflinch", 0.0) > 0:
            boss.memory["unflinch"] -= dt
        for tag in ("swept", "zapped"):
            if boss.memory.get(tag, 0.0) > 0:
                boss.memory[tag] -= dt
        fire_traits("tick", getattr(spec, "traits", ()), state, boss)
        if boss.memory.get("planted", 0.0) > 0:
            # Rooted while it channels something.  Set by the ``shrouds`` trait
            # and nothing else; the phase's behaviour is simply not run, rather
            # than the boss being stunned — a stun would skip the trait tick
            # above and the boss would stay planted forever.
            pass
        elif boss.knockback > 0:
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
    # 0.5 秒的頓幀讀起來不是「重擊感」，是遊戲當掉了。王每一夜都會出場，所以
    # 每一夜都會卡一次 —— 而卡住的那半秒正好是玩家最需要看清楚它從哪裡進場
    # 的半秒。留 0.12 秒：夠成為一個重音，短到不會被誤認成掉幀。
    state.feedback.bump(shake=20.0, freeze=0.12)
    state.effects.append(Effect("boss_enter", x, y, 1.2, 1.2))
    state.emit(f"boss_enter:{key}")


# ── projectiles, effects, pickups ────────────────────────────────────
def _bounce(shot: Projectile) -> bool:
    """Reflect a bouncing shot off the four walls.  False if it is elsewhere.

    Only the walls, and only for the kinds that ask for it.  A fireball that
    stops at the edge of the map is a fireball the player walks around; one
    that comes back is a thing they have to keep track of, which is the whole
    reason the hob throws them.
    """
    hit = False
    if shot.x < shot.radius:
        shot.x, shot.vx, hit = shot.radius, abs(shot.vx), True
    elif shot.x > C.WIDTH - shot.radius:
        shot.x, shot.vx, hit = C.WIDTH - shot.radius, -abs(shot.vx), True
    if shot.y < shot.radius:
        shot.y, shot.vy, hit = shot.radius, abs(shot.vy), True
    elif shot.y > C.HEIGHT - shot.radius:
        shot.y, shot.vy, hit = C.HEIGHT - shot.radius, -abs(shot.vy), True
    return hit


def _burn_out(state: State, shot: Projectile) -> None:
    """Leave a patch of fire where a fireball finished."""
    state.puddles.append(Puddle(
        x=shot.x, y=shot.y, radius=30.0, kind="fire",
        slow=1.0, burn=1.0, life=2.6))
    state.effects.append(Effect("blaze", shot.x, shot.y, 0.4, 0.4, 30))
    state.emit("blaze")


def _advance_projectiles(state: State, dt: float) -> None:
    alive: list[Projectile] = []
    for shot in state.projectiles:
        shot.life -= dt
        shot.x += shot.vx * dt
        shot.y += shot.vy * dt

        bouncy = shot.kind in C.BOUNCING_SHOTS
        if bouncy and shot.life > 0:
            if _bounce(shot):
                state.emit("bounce")

        if shot.life <= 0:
            if bouncy:
                _burn_out(state, shot)
            continue
        if not (0 <= shot.x <= C.WIDTH and 0 <= shot.y <= C.HEIGHT):
            continue
        if g.blocked_by(state.obstacles, shot.x, shot.y, shot.radius):
            state.effects.append(Effect("spark", shot.x, shot.y, 0.2, 0.2))
            if bouncy:
                _burn_out(state, shot)
            continue

        if not shot.friendly:
            # The hob's fire is aimed at Hansel and only Hansel.  A boss whose
            # attack also chews through Gretel would be won by standing far away
            # from her, which is the opposite of what this game asks for.
            if shot.kind not in C.SPARES_SISTER and g.circles_touch(
                    shot.x, shot.y, shot.radius,
                    C.SISTER_X, C.SISTER_Y, C.SISTER_REACH * 0.7):
                if _warded(state, None):
                    continue
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
                if shot.kind in C.BOUNCING_SHOTS:
                    _burn_out(state, shot)
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
            if hazard.kind == "meteor":
                _meteor_lands(state, hazard)
                continue
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

        if hazard.kind == "meteor":
            alive.append(hazard)        # a telegraph, not a thing that catches
            continue

        if hazard.kind == "wave":
            _advance_wave(state, hazard)
            alive.append(hazard)
            continue

        hazard.x += hazard.vx * dt
        hazard.y += hazard.vy * dt
        moving = hazard.vx != 0.0 or hazard.vy != 0.0
        if moving and not (0 <= hazard.x <= C.WIDTH and 0 <= hazard.y <= C.HEIGHT):
            continue

        for target in state.monsters:
            if not target.awake:
                continue
            if g.distance(target.x, target.y, hazard.x, hazard.y) > hazard.radius:
                continue
            # 龍捲風把躲在地底的挖洞怪直接吸出來。
            #
            # 挖洞怪的規則是「鑽下去之後打不到，只能等它自己冒出來」，而那個
            # 等待期間玩家什麼都做不了。風把它拔出來，等於給了這隻怪一個解 ——
            # 這是風系技能唯一能做、而別的元素做不到的事。
            if target.buried > 0:
                if hazard.kind != "twister":
                    continue
                target.buried = 0.0
                target.stunned = max(target.stunned, 0.5)
                state.effects.append(Effect("surface", target.x, target.y,
                                            0.4, 0.4))
                state.emit(f"uprooted:{target.spec}")
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
        #
        # 捲不動，但打得到。原本連傷害都沒有，所以龍捲風對六隻王的血條全部是
        # 零 —— 一個傷害技能對王完全沒有傷害，玩家讀不出那是設計。三道風共用
        # 同一份額度，所以一次施法就是一下。
        for boss in state.bosses:
            if g.distance(boss.x, boss.y, hazard.x, hazard.y) > hazard.radius:
                continue
            boss.stunned = max(boss.stunned, min(0.4, hazard.hold))
            if (hazard.kind == "twister" and hazard.strength > 0
                    and _boss_budget(boss, "whirled_hits", 1)):
                damage_target(state, boss, int(hazard.strength),
                              element="wind", from_x=hazard.x, from_y=hazard.y)

        if hazard.charges == 0:
            state.effects.append(Effect("trap_spring", hazard.x, hazard.y,
                                        0.4, 0.4, hazard.radius))
            continue
        alive.append(hazard)
    state.hazards = alive


def _advance_wave(state: State, hazard: Hazard) -> None:
    """怒潮的一圈水波：往外長，掃到什麼清什麼。

    半徑是從 ``life`` 反推的，所以動畫和判定共用同一個數字 —— 一個看起來已
    經掃過你、實際上還沒判定到的水波，比沒有水波更糟。

    ``hold`` 借來當擊退距離，``charges`` 借來當對王的傷害。兩個欄位在別的
    hazard 上是別的意思，但 Hazard 的存在理由就是「差別只有名字和兩個數字」
    —— 為了一個一次性的招式再開一張表，才是把這個設計拆掉。
    """
    from .effects import _kill_within

    span = max(0.0, min(1.0, 1.0 - hazard.life / max(0.01, hazard.hold_life)))
    hazard.reach = hazard.radius * (0.25 + 0.75 * span)
    _kill_within(state, hazard.x, hazard.y, hazard.reach, "water",
                 push=hazard.hold, boss=0)

    # 王另外算。水波每一格都在判定，把 charges 直接餵給 _kill_within 等於一
    # 秒扣六十次 —— 所以原本寫死 boss=0，而那讓怒潮對王完全沒有傷害（三圈水
    # 波打在王身上，血條一格都不動）。
    #
    # 一次施法只有最外圈帶傷害（見 surge_wave），而且同一圈只算一次。
    if hazard.charges > 0 and not hazard.sprung:
        for boss in state.bosses:
            if g.distance(boss.x, boss.y, hazard.x, hazard.y) > hazard.reach:
                continue
            hazard.sprung = True
            damage_target(state, boss, int(hazard.charges), element="water",
                          from_x=hazard.x, from_y=hazard.y)
            break


def _meteor_lands(state: State, hazard: Hazard) -> None:
    """Resolve one meteor: it hits whatever is standing where it was aimed.

    Whatever, deliberately — including the sorcerer who called it.  The whole
    fight is built on that: the moon-mage always drops them exactly where
    Hansel is standing, never where he is going, so stepping out of the circle
    at the last moment is not merely a dodge, it is an attack.  A boss whose
    own shot could not hurt it would make 疾風 a way to survive the fight
    rather than a way to win it.

    Gretel is untouched — ``SPARES_SISTER`` — for the same reason the hob's
    fire spares her: a boss that damaged her from range would be answered by
    standing as far from her as possible.
    """
    blast = hazard.radius
    state.effects.append(Effect("meteor_hit", hazard.x, hazard.y, 0.5, 0.5,
                                int(blast)))
    state.feedback.bump(shake=13.0, freeze=0.05)
    state.emit("meteor_hit")

    for target in list(state.monsters) + list(state.bosses):
        if g.distance(target.x, target.y, hazard.x, hazard.y) > blast:
            continue
        _push(target, hazard.x, hazard.y, 90.0)
        damage_target(state, target, int(hazard.strength) or 3,
                      element="fire", from_x=hazard.x, from_y=hazard.y)

    if g.distance(state.player.x, state.player.y, hazard.x, hazard.y) <= blast:
        hurt_player(state, 1)

    # Two to three seconds of burning ground, which is what turns a dodged
    # meteor into a piece of terrain the player still has to work around — and
    # what gives 水牢 and 怒潮 something to do on a night whose boss is not
    # otherwise a water puzzle.
    state.puddles.append(Puddle(
        x=hazard.x, y=hazard.y, radius=blast * 0.95, kind="fire",
        slow=1.0, burn=1.0, life=2.6))


def _advance_puddles(state: State, dt: float) -> None:
    """Age the ground, and let whatever is burning on it do its work.

    ``Puddle.burn`` was declared from the start and never read by anything: a
    patch of fire slowed nobody, hurt nobody, and existed only as an orange
    circle. Both the hob's fireballs and the moon-mage's craters are built on
    it, so it has to mean something before either fight can.
    """
    alive: list[Puddle] = []
    burning = False
    p = state.player
    for pool in state.puddles:
        if pool.life > 0:
            pool.life -= dt
            if pool.life <= 0:
                continue
        alive.append(pool)
        if (pool.burn > 0 and not pool.spares_player
                and g.distance(p.x, p.y, pool.x, pool.y) <= pool.radius):
            burning = True
    state.puddles = alive

    # One tick of damage per interval no matter how many patches overlap.  A
    # crater field of five meteors would otherwise take five half-hearts in the
    # same frame, and dying to arithmetic is not the same as dying to a boss.
    if not burning:
        p.burn_tick = 0.0
        return
    p.burn_tick += dt
    if p.burn_tick >= C.BURN_INTERVAL:
        p.burn_tick = 0.0
        state.effects.append(Effect("blaze", p.x, p.y, 0.25, 0.25, 18))
        hurt_player(state, 1)


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
        if drop.heal > 0 and drop.sister:
            state.meta.sister_hp = min(state.meta.max_sister_hp,
                                       state.meta.sister_hp + drop.heal)
            state.effects.append(Effect("mend", C.SISTER_X, C.SISTER_Y,
                                        0.6, 0.6))
            state.emit("sister_mended")
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
    if state.meta.freecast:
        # 娛樂存檔。設成 0 而不是不寫進去，因為 HUD 是照著 cooldowns 這張表
        # 畫冷卻圈的 —— 少了那一筆，圈圈會用上一次的值卡在那裡。
        state.cooldowns[key] = 0
        return
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
    state.meta.count_try(state.meta.night)
    state.dusk = 0.0
    state.fog_scale = 1.0
    state.hazards = []
    state.mist_ticks = 0
    p = state.player
    p.charging, p.charge_time = "", 0.0
    p.aura = p.aura_hits = p.haste = p.mending = p.holy = 0.0
    state.ward = 0.0
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
    speed = (spec.speed * (ELITE_SPEED_FACTOR if elite else 1.0)
             * float(state.meta.dials["monster_speed"]))
    monster = Monster(spec=key, x=x, y=y, hp=hp, speed=speed,
                      wake=wake, elite=elite)
    escalate_speed(monster, state.elapsed)
    state.stats.arrivals += 1
    # 出生就跑 spawn 特性 —— 那個掛勾的定義就是「它進入世界的那一刻」。
    #
    # 這一行原本不在。spawn 特性只在 _advance_monsters 裡、wake 倒數歸零的
    # 那一幀才觸發，而 make_monster 的 wake 預設是 0.0 —— 也就是說從警告圈
    # 生出來的怪一律不滿足 `wake > 0`，那個分支永遠不會進去。
    #
    # 後果：盔甲怪從來沒有穿過盔甲。它的血量、速度、圖示、圖鑑條目全都對，
    # 唯獨那 3 點護甲永遠是 0。設計文件裡「要打兩下才破甲」的那隻怪，實際
    # 上跟村民一樣脆。
    fire_traits("spawn", spec.traits, state, monster)
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
