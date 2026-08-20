"""Spell and night-event resolvers.

Registered by name, the same way monster behaviours are, so a new skill is a row
in ``content/spells.py`` plus — usually — nothing here at all, because an
existing resolver already does the job with different numbers.

Everything draws from a named substream and never from ``random``.
"""

from __future__ import annotations

import math

from . import constants as C
from . import geometry as g
from .content.monsters import MONSTERS
from .entities import Drop, Effect, Hazard, Monster, Puddle
from .registry import event, spell
from .state import State


def _targets(state: State):
    """Everything a skill may act on: awake, above ground, on the field.

    Buried monsters are excluded on purpose — that is the digger's whole point,
    and the reason a player who has been clearing with lightning has to walk
    back and stand guard instead.
    """
    return [x for x in list(state.monsters) + list(state.bosses)
            if x.awake and x.buried <= 0]


# ── skills ───────────────────────────────────────────────────────────
def _kill_within(state: State, x: float, y: float, radius: float,
                 element: str | None, *, push: float = 0.0,
                 boss: int = 0) -> int:
    """Empty the health bar of every *monster* inside a circle.

    Several skills are written as 清空血條 rather than as a number.  That is a
    different thing from "lots of damage", and it is written once, here.

    **A boss is never included.**  A night that now requires the boss to fall
    would otherwise be answered by standing next to it and pressing one key —
    the whole fight, every phase, every tell, deleted by a skill the player
    bought on night three.  Bosses take ``boss`` damage instead, which is large
    enough to be worth casting and small enough to leave a fight.

    Armour and the mirror's back-only rule still apply, through
    ``damage_target``: a skill that ignored them would quietly delete the two
    monsters the player was specifically taught to think about.
    """
    from .rules import _push as shove, damage_target

    hit = 0
    for target in _targets(state):
        if g.distance(target.x, target.y, x, y) > radius:
            continue
        amount = boss if target in state.bosses else 999
        if amount <= 0:
            continue
        if push:
            shove(target, x, y, push)
        damage_target(state, target, amount, element=element,
                      from_x=x, from_y=y)
        hit += 1
    return hit


# ── 一階 ─────────────────────────────────────────────────────────────
@spell("smite", label="閃電",
       note="立刻在腳下劈下閃電：震開周圍的敵人，並留下一片電焦的地面",
       params={"radius": (54.0, "打得到多寬"),
               "damage": (2.0, "扣多少血"),
               "push": (165.0, "擊退距離"),
               "slow": (0.4, "焦地上剩幾成速度"),
               "slow_life": (3.5, "焦地留多久"),
               "slow_radius": (66.0, "焦地多寬")})
def smite(state: State, spec) -> None:
    """雷 · 閃電 — control, not deletion.

    It used to empty the health bar of everything in the circle, and it was
    charged.  Both were wrong for the same reason: the skill answered the
    question "is the field clear yet" instead of "where do I want them to be".
    A charge asks the player to hold a key while eight things walk at their
    sister, which is the one moment in the game they cannot spare a thumb for.

    So it fires the instant it is pressed, kills almost nothing, and *moves*
    everything — a hard shove outward plus a patch of scorched ground that
    slows whatever tries to walk back in.  That turns it into space, which is
    the currency a defender actually spends.
    """
    from .rules import _push as shove, damage_target

    p = state.player
    radius = float(spec.params.get("radius", 54.0))
    damage = int(spec.params.get("damage", 2))
    push = float(spec.params.get("push", 165.0))
    boss_damage = int(spec.params.get("boss", 5))

    for target in _targets(state):
        if g.distance(target.x, target.y, p.x, p.y) > radius:
            continue
        shove(target, p.x, p.y, push)
        amount = boss_damage if target in state.bosses else damage
        if amount > 0:
            damage_target(state, target, amount, element=spec.element,
                          from_x=p.x, from_y=p.y)

    # The scorch is the half of the skill that lasts.  Reusing ``Puddle`` means
    # the slow flows through the same ``_ground_drag`` every other surface uses,
    # so nothing downstream has to learn about lightning.
    state.puddles.append(Puddle(
        x=p.x, y=p.y,
        radius=float(spec.params.get("slow_radius", 66.0)),
        kind="shock",
        slow=float(spec.params.get("slow", 0.4)),
        life=float(spec.params.get("slow_life", 3.5)),
        spares_player=True))

    state.effects.append(Effect("bolt", p.x, p.y, 0.35, 0.35, radius))
    state.feedback.bump(shake=10.0, freeze=0.07)
    _expose_matching(state, spec)


@spell("reveal_all", label="聖光", note="照亮全場並灼燒周圍的敵人",
       params={"radius": (80.0, "灼燒半徑"),
               "burn": (0.5, "每秒扣多少血")})
def reveal_all(state: State, spec) -> None:
    """光 · 聖光 — sight first, damage second.

    The reveal is the reason to bring it; the burn is what stops it being a
    button you press and then ignore for eight seconds.
    """
    p = state.player
    p.holy = float(spec.duration)
    p.holy_tick = 0.0
    state.reveal_ticks = max(1, int(round(spec.duration / C.FIXED_DT)))
    for target in _targets(state):
        target.faded = 0.0
    state.effects.append(Effect("holy", p.x, p.y, 0.6, 0.6, 760))
    state.feedback.bump(shake=3.0)
    _expose_matching(state, spec)


@spell("twister", label="龍捲風",
       note="往面對的方向放出一道龍捲風，沿路的怪被捲起來一起帶走",
       params={"speed": (150.0, "每秒前進幾像素"),
               "radius": (52.0, "捲得到多寬"),
               "hold": (2.5, "被放下之後還昏多久")})
def twister(state: State, spec) -> None:
    """風 · 龍捲風 — position control you have to aim."""
    p = state.player
    dx, dy = g.normalise(p.face_x, p.face_y)
    if dx == 0.0 and dy == 0.0:
        dx, dy = 1.0, 0.0
    speed = float(spec.params.get("speed", 150.0))
    state.hazards.append(Hazard(
        kind="twister", x=p.x + dx * 36.0, y=p.y + dy * 36.0,
        radius=float(spec.params.get("radius", 52.0)),
        life=float(spec.duration), vx=dx * speed, vy=dy * speed,
        hold=float(spec.params.get("hold", 2.5))))
    state.effects.append(Effect("tornado", p.x, p.y, 0.5, 0.5, 120))
    state.feedback.bump(shake=8.0)
    _expose_matching(state, spec)


@spell("cage", label="水牢", note="罩住一片地方，五秒後炸開並清空裡面的敵人",
       params={"radius": (80.0, "水牢半徑"),
               "push": (90.0, "炸開時的擊退")})
def cage(state: State, spec) -> None:
    """水 · 水牢 — a five-second sentence, then it is carried out.

    Placed on him rather than aimed: the interesting decision is *when* to let
    a crowd close in far enough to be worth catching, which is a question about
    nerve rather than about aim.
    """
    p = state.player
    state.hazards.append(Hazard(
        kind="cage", x=p.x, y=p.y,
        radius=float(spec.params.get("radius", 80.0)),
        life=float(spec.duration), hold=float(spec.duration),
        strength=float(spec.params.get("push", 90.0))))
    state.puddles = [pool for pool in state.puddles if pool.burn <= 0]
    state.effects.append(Effect("cage", p.x, p.y, 0.5, 0.5, 80))
    state.feedback.bump(shake=2.0)
    _expose_matching(state, spec)


# ── 二階 ─────────────────────────────────────────────────────────────
@spell("storm_armour", label="雷鳴", note="披上雷電護甲，反擊碰到你的人，結束時放電",
       params={"radius": (50.0, "反擊半徑"),
               "burst_radius": (80.0, "結束時的爆發半徑")})
def storm_armour(state: State, spec) -> None:
    """雷 · 雷鳴 — the only skill that rewards being hit.

    Everything else in this game is about not being touched.  This one inverts
    that for five seconds, which is why it is worth two skill points: it does
    not make the player stronger, it makes a different plan legal.
    """
    p = state.player
    p.aura = float(spec.duration)
    p.aura_hits = 0.0
    state.effects.append(Effect("aura", p.x, p.y, 0.5, 0.5,
                                float(spec.params.get("radius", 50.0))))
    state.feedback.bump(shake=5.0)
    _expose_matching(state, spec)


@spell("mend_light", label="聖癒",
       note="在葛蕾特身上罩一層護罩，期間任何東西都碰不到她；同時持續替兄妹回血",
       params={"every": (4.0, "幾秒回一滴血"),
               "push": (150.0, "撞上護罩被彈開多遠")})
def mend_light(state: State, spec) -> None:
    """光 · 聖癒 — a shield over the person, not a light over the field.

    It used to be 聖光 with healing bolted on: same eight seconds, same
    whole-map reveal, same element, same shelf.  Two skills that open with the
    identical screen-wide flash are one skill the player picks by reading the
    小字 — and nobody reads the 小字 at three in the morning with six monsters
    on the field.

    So it stops lighting anything.  It puts a wall around Gretel for eight
    seconds: nothing reaches her, everything that tries is thrown off.  That
    makes it the one skill that answers "I cannot get back in time", which is
    the failure state this whole game is built out of — and it does it without
    borrowing a single pixel from 聖光.
    """
    p = state.player
    p.mending = float(spec.duration)
    p.mend_tick = 0.0
    state.ward = float(spec.duration)
    state.effects.append(Effect("ward", C.SISTER_X, C.SISTER_Y, 0.7, 0.7, 90))
    state.feedback.bump(shake=2.0)
    _expose_matching(state, spec)


@spell("gale", label="疾風", note="六秒內高速移動，撞到的人直接被撞飛",
       params={"speed": (2.4, "移動速度倍率"), "push": (120.0, "撞飛距離")})
def gale(state: State, spec) -> None:
    """風 · 疾風 — the answer to a field you have already lost.

    Everything else clears a circle; this clears a *path*, repeatedly, for as
    long as the player keeps steering into people.
    """
    state.player.haste = float(spec.duration)
    state.effects.append(Effect("gale", state.player.x, state.player.y, 0.4, 0.4))
    state.feedback.bump(shake=4.0)
    _expose_matching(state, spec)


@spell("surge_wave", label="怒潮", note="炸開一片水，再讓全場起霧變慢",
       params={"radius": (50.0, "爆炸半徑"),
               "mist": (5.0, "水霧持續幾秒"),
               "push": (110.0, "爆炸擊退")})
def surge_wave(state: State, spec) -> None:
    """水 · 怒潮 — a small kill and a large inconvenience.

    The blast is the smallest of the second tier; the mist is the largest thing
    any skill does, and it is the part worth two points.  Everything on the map
    walks at two thirds speed, which does not save the player from anything —
    it gives them time to save themselves.
    """
    p = state.player
    _kill_within(state, p.x, p.y, float(spec.params.get("radius", 50.0)),
                 spec.element, push=float(spec.params.get("push", 110.0)),
                 boss=int(spec.params.get("boss", 16)))
    state.mist_ticks = max(state.mist_ticks,
                           int(round(float(spec.params.get("mist", 5.0))
                                     / C.FIXED_DT)))
    state.effects.append(Effect("surge_wave", p.x, p.y, 0.6, 0.6, 50))
    state.feedback.bump(shake=14.0, freeze=0.08)
    _expose_matching(state, spec)


def _expose_matching(state: State, spec) -> None:
    """Open a damage window on anything this element answers.

    A weakness that only multiplied the spell's own damage would be worth using
    once; opening a window means the *lantern* gets the payoff, so the skill is
    a setup and the fight stays a fight.
    """
    from .content import BOSSES

    for target in list(state.bosses) + list(state.monsters):
        if target in state.bosses:
            row = BOSSES.get(target.spec)
        else:
            row = MONSTERS.get(target.spec)
        weak = row.weakness if row else None
        if weak is not None and weak == spec.element:
            target.memory["exposed"] = C.WEAKNESS_WINDOW
            state.effects.append(Effect("exposed", target.x, target.y, 0.5, 0.5))
            state.emit(f"exposed:{target.spec}")


# ── night events ─────────────────────────────────────────────────────
@event("dim", label="變暗", note="縮小所有光源")
def dim(state: State, spec) -> None:
    state.light_scale = float(spec.params.get("factor", 0.7))


@event("reveal", label="月光", note="短暫照亮全場，但不會定住怕光的東西")
def reveal(state: State, spec) -> None:
    state.reveal_ticks = max(1, int(round(spec.duration / C.FIXED_DT)))


@event("douse", label="熄燈", note="提燈直接熄掉一段時間")
def douse(state: State, spec) -> None:
    state.player.doused = max(state.player.doused, spec.duration)


@event("hush", label="死寂", note="一段時間內不生新的敵人")
def hush(state: State, spec) -> None:
    state.hush_ticks = max(1, int(round(spec.duration / C.FIXED_DT)))


@event("spawn_burst", label="一擁而上", note="一次生出一群",
       params={"count": (5.0, "生幾隻")})
def spawn_burst(state: State, spec) -> None:
    from .rules import add_warning

    for _ in range(int(spec.params.get("count", 5))):
        x, y = g.edge_point(state.streams.events)
        add_warning(state, "child", x, y, surge=True)


@event("sugar_burst", label="糖霜雨", note="場上隨機掉一堆糖霜",
       params={"count": (8.0, "掉幾顆")})
def sugar_burst(state: State, spec) -> None:
    stream = state.streams.events
    for _ in range(int(spec.params.get("count", 8))):
        # Through the night's budget like every other crystal.  This was the
        # one sugar source that was not, which is why a measured perfect run
        # came out eight over its cap on exactly the nights this event rolled.
        if state.meta.sugar_left_tonight(state.meta.night) <= 0:
            break
        state.meta.bank_night_sugar(state.meta.night, 1)
        state.drops.append(Drop(x=stream.between(60.0, C.WIDTH - 60.0),
                                y=stream.between(60.0, C.HEIGHT - 60.0),
                                value=1))
