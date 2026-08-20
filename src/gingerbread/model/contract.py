"""The four contract functions.

``new_game`` / ``apply_action`` / ``is_terminal`` / ``snapshot`` are the whole
public surface of the rules.  Everything above this layer — the renderer, the
input adapter, the tests — talks to the game through these and nothing else.

Two guarantees they keep:

* ``apply_action`` never changes the state it is handed.  It copies, mutates the
  copy, and returns it.
* the same seed plus the same action list produces a byte-identical
  ``snapshot``, on any platform.

The second is why ``snapshot`` is as detailed as it is.  A summary that only
counts monsters cannot see a divergence: two runs that had drifted apart by a
pixel, or drawn a different number of random values, compared equal for
thousands of ticks.  Evidence that cannot fail is not evidence.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from . import constants as C
from . import geometry as g
from . import rules
from .content import SPELLS as SPELL_TABLE
from .content import stage_for
from .content.upgrades import (SHOP_ORDER, TONIGHT_ATTACK, TONIGHT_LIGHT,
                               UPGRADES)
from .director import director_for
from .entities import Player
from .geometry import ring_offset
from .rng import Streams, seed_from
from .state import Meta, Mode, Phase, State, to_ticks

#: Movement words accepted inside ``move:``.  Parsed into a **sorted tuple**
#: rather than a set: iterating a set to accumulate a direction vector makes the
#: result depend on hash order, and while today's values (0 and ±1) add exactly
#: under IEEE 754, the first content-supplied speed modifier would turn that
#: into a bug that reproduces ninety-nine times in a hundred.
_MOVE_WORDS = ("up", "down", "left", "right", "swing", "dash", "guard")


class ActionError(ValueError):
    """Raised for an action string the rules cannot interpret.

    A distinct type because content and input tables will feed actions in, and
    a typo must fail loudly here rather than being silently treated as "do
    nothing" — which is what an over-permissive parser does, and it hides the
    mistake until someone notices a control that never worked.
    """


# ── new_game ─────────────────────────────────────────────────────────
def new_game(seed: int = 0, meta: Meta | None = None,
             mode: Mode | None = None) -> State:
    """Return a fresh state with no display or device dependency.

    Interface:
        seed: integer driving every random decision this run.
        meta: optional carried progress; a fresh ``Meta`` is used when omitted.
        mode: campaign or endless; taken from ``meta`` when omitted.
        return: a ``State`` ready for the first action — ``DAY`` in the
                campaign, ``NIGHT`` in endless, which has no day phase.

    Invariant: two calls with the same seed and equal meta produce equal
    snapshots.
    """
    carried = deepcopy(meta) if meta is not None else Meta()
    if mode is not None:
        carried.mode = mode
    carried.clear_nightly()

    state = State(
        phase=Phase.DAY if carried.mode is Mode.CAMPAIGN else Phase.NIGHT,
        seed=int(seed),
        meta=carried,
        player=Player(x=C.SISTER_X, y=C.SISTER_Y + 92.0),
        streams=Streams(seed_from(seed), carried.night),
    )

    from .derive import derive
    state.player.max_hp = derive(state).max_hp
    state.player.hp = state.player.max_hp

    # A point of each tier per day, granted on arrival — including the first,
    # so night one is played with a skill the player *chose* rather than one
    # handed to them.  Nothing is pre-equipped: picking the first two is the
    # first decision the game asks for, and it is a better opening than being
    # told what you already have.
    carried.skill_points_1 += 1
    carried.skill_points_2 += 1

    if carried.mode is Mode.CAMPAIGN:
        _lay_out_day(state)
    else:
        director_for(carried.mode).begin_night(state)
    return state


def _lay_out_day(state: State) -> None:
    """Place tonight's villagers around Gretel and stagger when each turns.

    They are visible all day.  That is the game's central promise — the people
    who come for her at night are the people standing in the square now — so
    this layout is deterministic and identical for every seed: which faces the
    player memorises must not be luck.
    """
    stage = stage_for(state.meta.night)
    rules.load_map(state, stage.map_key)

    # No clock: the day ends when the player presses for nightfall.
    state.ticks_total = 0
    state.ticks_left = 0
    state.ticks_elapsed = 0
    state.action_points = 0

    recipe = stage.recipe
    state.sleepers = []
    for index, key in enumerate(recipe):
        # 站在場邊，不是站在葛蕾特周圍。
        #
        # 原本排在她身邊 190–274 px 的環上，而這些村民是**就地變身**的 ——
        # 所以每一夜開頭都有一整圈怪直接出現在她跟漢賽爾之間，中間沒有任何
        # 可以攔截的距離。夜晚的生怪已經一律改成從場邊進來了，這條路是漏掉
        # 的第二條，而且它比另一條更近。
        x, y = g.perimeter_slot(index, len(recipe))
        state.sleepers.append((
            key, x, y,
            to_ticks(1.2 + index * (22.0 / max(1, len(recipe)))),
        ))


# ── is_terminal ──────────────────────────────────────────────────────
def is_terminal(state: State) -> bool:
    """Return True only when the run cannot continue without a new decision.

    Day and night are both in progress.  The shop is *not* terminal — it is a
    phase the player acts in — so buying is legal there and nowhere else.
    """
    return state.phase in (Phase.LOST, Phase.VICTORY)


# ── snapshot ─────────────────────────────────────────────────────────
def snapshot(state: State) -> dict[str, object]:
    """Return stable, comparable evidence for tests and debugging.

    Deep on purpose.  Floats are emitted through ``repr`` rather than rounded,
    because rounding is exactly what let two diverging runs keep comparing
    equal: a difference in the last bit of a coordinate is invisible at three
    decimal places and grows into a visible one within a minute.

    ``digest`` folds the whole structure into one hash, so a test can assert
    one value and a failure can still be read field by field.
    """
    body: dict[str, object] = {
        "phase": state.phase.value,
        "mode": state.meta.mode.value,
        "seed": state.seed,
        "night": state.meta.night,
        "stage": state.stage,
        "tick": state.tick,
        "ticks_elapsed": state.ticks_elapsed,
        "ticks_left": state.ticks_left,
        "action_points": state.action_points,
        "dusk": repr(round(state.dusk, 9)),

        "sister_hp": state.meta.sister_hp,
        "sugar": state.meta.sugar,
        "upgrades": dict(sorted(state.meta.upgrades.items())),
        "skills": list(state.meta.skills),
        "skill_points": [state.meta.skill_points_1,
                         state.meta.skill_points_2],
        "cooldowns": dict(sorted(state.cooldowns.items())),
        "slots": list(state.meta.slots),

        "player": _player_row(state.player),
        "monsters": [_monster_row(m) for m in state.monsters],
        "bosses": [_boss_row(b) for b in state.bosses],
        "warnings": [[w.spec, repr(round(w.x, 9)), repr(round(w.y, 9)),
                      repr(round(w.left, 9)), w.surge] for w in state.warnings],
        "drops": [[repr(round(d.x, 9)), repr(round(d.y, 9)), d.value, d.fake,
                   d.heal]
                  for d in state.drops],
        "projectiles": [[repr(round(p.x, 9)), repr(round(p.y, 9)),
                         repr(round(p.vx, 9)), repr(round(p.vy, 9)), p.damage]
                        for p in state.projectiles],
        "sleepers": [[k, repr(round(x, 9)), repr(round(y, 9)), t]
                     for k, x, y, t in state.sleepers],

        "hazards": [[h.kind, repr(round(h.x, 9)), repr(round(h.y, 9)),
                     repr(round(h.radius, 9)), repr(round(h.life, 9)),
                     repr(round(h.vx, 9)), repr(round(h.vy, 9)),
                     repr(round(h.charges, 9))] for h in state.hazards],
        "obstacles": [[o.kind, repr(round(o.x, 9)), repr(round(o.y, 9)),
                       repr(round(o.radius, 9)), repr(round(o.life, 9))]
                      for o in state.obstacles],

        "surges": list(state.surges),
        "spawn_ticks": state.spawn_ticks,
        "event": state.event,
        "event_ticks": state.event_ticks,
        "godmode": state.meta.godmode,
        "seeall": state.meta.seeall,
        "freecast": state.meta.freecast,
        "light_scale": repr(round(state.light_scale, 9)),
        "fog_scale": repr(round(state.fog_scale, 9)),
        "reveal_ticks": state.reveal_ticks,
        "hush_ticks": state.hush_ticks,
        "mist_ticks": state.mist_ticks,
        "combo": state.combo,

        "stats": [state.stats.arrivals,
                  state.stats.kills, state.stats.kills_by_lantern,
                  state.stats.kills_by_spell, state.stats.reached_sister,
                  state.stats.sugar_picked, state.stats.damage_taken,
                  state.stats.downs, state.stats.best_combo],

        # Stream positions make a divergence visible on the tick it happens,
        # instead of whenever it first moves something far enough to see.
        "streams": state.streams.snapshot(),
        "events": list(state.events),
    }
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    body["digest"] = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return body


def _player_row(p: Player) -> list[object]:
    return [repr(round(p.x, 9)), repr(round(p.y, 9)),
            repr(round(p.face_x, 9)), repr(round(p.face_y, 9)),
            p.hp, p.max_hp, p.downs,
            repr(round(p.swing_cooldown, 9)), repr(round(p.dash_cooldown, 9)),
            repr(round(p.stun, 9)), repr(round(p.invulnerable, 9)),
            repr(round(p.doused, 9)), repr(round(p.downed, 9)),
            repr(round(p.guard, 9)), p.charging,
            repr(round(p.charge_time, 9)), repr(round(p.aura, 9)),
            repr(round(p.haste, 9)), repr(round(p.mending, 9)),
            repr(round(p.holy, 9))]


def _monster_row(m) -> list[object]:
    # ``memory`` is a per-monster scratch dict whose key order depends on which
    # behaviour ran first, so it is emitted sorted.  Left raw, it would make two
    # identical runs produce different evidence.
    return [m.spec, repr(round(m.x, 9)), repr(round(m.y, 9)), m.hp,
            repr(round(m.speed, 9)), repr(round(m.wake, 9)),
            repr(round(m.knockback, 9)), m.frozen, m.elite,
            [[k, repr(round(v, 9))] for k, v in sorted(m.memory.items())]]


def _boss_row(b) -> list[object]:
    return _monster_row(b) + [b.phase_index, b.max_hp]


def snapshot_brief(state: State) -> dict[str, object]:
    """A small summary for the on-screen debug readout, not for tests."""
    return {
        "phase": state.phase.value,
        "night": state.meta.night,
        "tick": state.tick,
        "monsters": len(state.monsters),
        "sister_hp": state.meta.sister_hp,
        "player_hp": state.player.hp,
        "sugar": state.meta.sugar,
    }


# ── apply_action ─────────────────────────────────────────────────────
def parse_action(action: str) -> tuple[str, object]:
    """Validate an action string and return ``(verb, payload)``.

    Parsing happens **before** the state is copied, so a bad action costs
    nothing and raises immediately rather than after a deep copy.
    """
    if action in ("tick", "swing", "begin_night", "next_night", "retry",
                  "whet", "oil", "godmode", "seeall", "freecast",
                  "skipnight"):
        return (action, None)

    if action.startswith("move:"):
        words = tuple(sorted(w for w in action[5:].split("+") if w))
        if not words:
            raise ActionError("move: needs at least one direction")
        unknown = [w for w in words if w not in _MOVE_WORDS]
        if unknown:
            raise ActionError(f"move: unknown word(s) {unknown}")
        return ("move", words)

    if action.startswith("slot:"):
        raw = action[5:]
        index, _, key = raw.partition(":")
        if index not in ("0", "1") or key not in SPELL_TABLE:
            raise ActionError(f"bad slot assignment {action!r}")
        # One shelf per slot: L carries a first-tier skill, ；a second-tier one.
        # Without this the two-point skills simply replace the one-point ones
        # and the first tier stops existing after night four — the tiers have to
        # compete with *themselves* to both stay in the game.
        want = 1 if index == "0" else 2
        if SPELL_TABLE[key].tier != want:
            raise ActionError(f"{key} is tier {SPELL_TABLE[key].tier}, "
                              f"slot {index} takes tier {want}")
        return ("slot", (int(index), key))

    if action.startswith("goto:"):
        return ("goto", action[5:])

    for prefix, table, label in (("cast:", SPELL_TABLE, "spell"),
                                 ("prepare:", SPELL_TABLE, "spell"),
                                 ("learn:", SPELL_TABLE, "spell"),
                                 ("buy:", UPGRADES, "upgrade"),
                                 ("choose:", UPGRADES, "upgrade")):
        if action.startswith(prefix):
            key = action[len(prefix):]
            if key not in table:
                raise ActionError(f"unknown {label} {key!r}")
            return (prefix[:-1], key)

    raise ActionError(f"unknown action: {action!r}")


def apply_action(state: State, action: str) -> State:
    """Return the next state **without changing the supplied state**.

    Accepted actions::

        tick                      advance one step with no input
        move:<words>              advance one step; words joined by '+' from
                                  up/down/left/right/swing/dash
        swing                     advance one step swinging in place
        cast:<spell>              spend a prepared spell
        whet / oil                day: spend an action point on tonight's buff
        prepare:<spell>           day: spend an action point on a spell charge
        begin_night               day -> night
        buy:<upgrade>             shop: spend sugar
        choose:<upgrade>          endless: take one of the offered three
        next_night                shop -> the next day
        retry                     lost -> a fresh run

    An action that is not legal in the current phase is ignored and an
    unchanged copy is returned, so a caller can drive the model from a simple
    input mapping without checking the phase first.  An action that cannot be
    *parsed* raises :class:`ActionError` — that is a programming error, not a
    player mistake.
    """
    verb, payload = parse_action(action)

    nxt = deepcopy(state)
    nxt.events = []
    director = director_for(nxt.meta.mode)

    if verb == "tick":
        return rules.step(nxt, (), director)
    if verb == "swing":
        return rules.step(nxt, ("swing",), director)
    if verb == "move":
        return rules.step(nxt, payload, director)
    if verb == "cast":
        return rules.step(nxt, (f"cast:{payload}",), director)

    if verb in ("whet", "oil"):
        return _day_buff(nxt, verb)
    if verb == "prepare":
        return _prepare(nxt, str(payload))
    if verb == "learn":
        return _learn(nxt, str(payload))
    if verb == "slot":
        return _assign_slot(nxt, payload[0], payload[1])
    if verb == "begin_night":
        return _begin_night(nxt, director)
    if verb == "buy":
        return _buy(nxt, str(payload))
    if verb == "choose":
        return _choose(nxt, str(payload))
    if verb == "next_night":
        return _next_night(nxt)
    if verb == "retry":
        return new_game(nxt.seed, Meta(mode=nxt.meta.mode), nxt.meta.mode)
    if verb == "godmode":
        # A test switch, not a difficulty setting.  It goes through the action
        # layer like everything else so it is recorded in the snapshot and a
        # run played with it on can never be mistaken for a clean one.
        nxt.meta.godmode = not nxt.meta.godmode
        nxt.emit("godmode:on" if nxt.meta.godmode else "godmode:off")
        return nxt

    if verb == "goto":
        # 走去某一夜。地圖上選好之後按開始走的就是這條路。
        #
        # 跟 skipnight 一樣走 new_game 帶 meta 重開，所以選關拿到的白天跟正常
        # 過關拿到的是同一個東西 —— 不是另一條會慢慢長歪的路。
        try:
            want = int(payload)
        except ValueError:
            return nxt
        if nxt.meta.mode is not Mode.CAMPAIGN:
            return nxt
        want = max(1, min(C.CAMPAIGN_NIGHTS, want))
        if want == nxt.meta.night:
            return nxt
        carried = deepcopy(nxt.meta)
        carried.night = want
        carried.sister_hp = carried.max_sister_hp
        return new_game(nxt.seed, carried)

    if verb == "skipnight":
        # 跳到下一夜的白天。測試用 —— 第四夜以後的怪，不該每次都要從第一夜
        # 打一小時才看得到。
        if (nxt.meta.mode is not Mode.CAMPAIGN
                or nxt.meta.night >= C.CAMPAIGN_NIGHTS):
            return nxt
        # 走 _next_night 同一條路（new_game 帶著 meta 重開），所以跳關拿到的
        # 白天跟正常過關拿到的白天是同一個東西 —— 不是另一條會慢慢長歪的路。
        carried = deepcopy(nxt.meta)
        carried.night += 1
        carried.skill_points_1 += 1
        carried.skill_points_2 += 1
        carried.sugar += 40
        carried.sister_hp = carried.max_sister_hp
        return new_game(nxt.seed, carried)

    if verb == "seeall":
        # 開圖。跟 godmode 一樣走 model，所以 HUD 和快照都知道它開著。
        nxt.meta.seeall = not nxt.meta.seeall
        nxt.emit("seeall:on" if nxt.meta.seeall else "seeall:off")
        return nxt

    if verb == "freecast":
        # 娛樂模式：技能不用等。已經在等的那幾個也一起放掉，否則開關打開之後
        # 還要先把剩下的冷卻等完，看起來像是沒生效。
        nxt.meta.freecast = not nxt.meta.freecast
        if nxt.meta.freecast:
            nxt.cooldowns = {k: 0 for k in nxt.cooldowns}
        nxt.emit("freecast:on" if nxt.meta.freecast else "freecast:off")
        return nxt

    raise ActionError(f"unhandled verb {verb!r}")     # pragma: no cover


# ── day actions ──────────────────────────────────────────────────────
def _spend_point(state: State) -> State:
    state.action_points -= 1
    if state.action_points <= 0:
        state.emit("day_over")
    return state


def _day_buff(state: State, which: str) -> State:
    """Accepted and ignored.

    ``whet`` and ``oil`` were the day's temporary buffs; the day now sells
    permanent upgrades instead.  The verbs are still parsed so old scripts,
    saved replays and the existing tests do not raise — they simply do nothing.
    """
    return state


def _prepare(state: State, key: str) -> State:
    """Bank a one-shot spell for tonight."""
    spec = SPELL_TABLE[key]
    if state.phase is not Phase.DAY:
        return state
    if state.meta.night < spec.unlock_night:
        return state
    state.meta.spells[key] = state.meta.spells.get(key, 0) + 1
    state.emit(f"prepare:{key}")
    return state


def _learn(state: State, key: str) -> State:
    """Spend a skill point to learn a skill, and equip it if a slot is free.

    Auto-equipping is a small kindness with a real effect: a player who learns a
    skill, finds nothing happens because they never assigned it, and concludes
    the system is broken has learned the wrong lesson permanently.
    """
    if state.phase is not Phase.DAY:
        return state
    spec = SPELL_TABLE[key]
    if key in state.meta.skills \
            or state.meta.points_for(spec.tier) < spec.cost:
        return state

    state.meta.spend_point(spec.tier, spec.cost)
    state.meta.skills.append(key)
    # Into its own shelf's slot, if that one is empty.  Filling the first free
    # slot regardless of tier would put a second-tier skill on L, where the
    # player could never fire it as designed.
    home = 0 if spec.tier == 1 else 1
    if state.meta.slots[home] is None:
        state.meta.slots[home] = key
    state.emit(f"learned:{key}")
    return state


def _assign_slot(state: State, index: int, key: str) -> State:
    """Put a skill in one of the two slots, swapping if it is already in the other."""
    if state.phase not in (Phase.SHOP, Phase.DAY):
        return state
    if key not in state.meta.skills:
        return state
    other = 1 - index
    # No swapping between shelves any more — the tiers cannot trade places, so
    # the only thing an assignment can do is replace what is on its own shelf.
    state.meta.slots[index] = key
    state.emit(f"slot:{index}:{key}")
    return state


def _begin_night(state: State, director) -> State:
    """Player-triggered nightfall.  The rules own what actually happens."""
    return rules.begin_night(state, director)


# ── between nights ───────────────────────────────────────────────────
def _buy(state: State, key: str) -> State:
    """Spend sugar in the shop.

    Only in the shop phase.  Buying after Gretel is taken was possible in an
    earlier version, and it was a trap: the only button on that screen restarts
    the run, so anything bought was destroyed a moment later.
    """
    # Spending happens in daylight now.  An earlier version put it on a screen
    # between nights, which meant the player chose upgrades while still reading
    # the last night's ledger — the two decisions competed and neither got
    # thought about.
    if state.phase not in (Phase.DAY, Phase.SHOP) or key not in SHOP_ORDER:
        return state
    spec = UPGRADES[key]
    level = state.meta.level(key)
    if level >= spec.max_level:
        return state
    price = spec.cost(level, C.UPGRADE_PRICE_STEP)
    if state.meta.sugar < price:
        return state

    state.meta.sugar -= price
    _grant(state, key, spec)
    state.emit(f"bought:{key}")
    return state


def _choose(state: State, key: str) -> State:
    """Take one of the three upgrades offered mid-run in endless mode."""
    if key not in state.pending_choice:
        return state
    spec = UPGRADES[key]
    state.pending_choice = []
    _grant(state, key, spec)
    state.emit(f"chose:{key}")
    return state


def _grant(state: State, key: str, spec) -> None:
    """Apply one purchased upgrade, consumable or permanent."""
    if spec.stat == "sister_heal":
        state.meta.sister_hp = min(state.meta.max_sister_hp,
                                   state.meta.sister_hp + int(spec.per_level))
        return
    state.meta.upgrades[key] = state.meta.level(key) + 1
    if spec.stat == "player_hp":
        from .derive import derive
        state.player.max_hp = derive(state).max_hp


def _next_night(state: State) -> State:
    if state.phase is not Phase.SHOP:
        return state
    carried = deepcopy(state.meta)
    carried.night += 1
    return new_game(state.seed, carried)


# ── convenience for tests and the headless check ─────────────────────
def run_script(seed: int, actions: list[str], meta: Meta | None = None,
               mode: Mode | None = None) -> State:
    """Apply a fixed action list to a fresh game and return the final state."""
    state = new_game(seed, meta, mode)
    for action in actions:
        state = apply_action(state, action)
    return state
