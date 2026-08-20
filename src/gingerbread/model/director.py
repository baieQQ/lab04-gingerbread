"""Directors: the part that decides what a night *is*.

The rules know how a monster moves and how a swing resolves.  They do not know
how many monsters there should be, when a boss arrives, or when a run ends.
That belongs to a director, and swapping the director is what turns the seven
night campaign into the endless mode — not a fork through the rules.

Two exist:

``CampaignDirector``
    Reads ``content/stages.py``.  Seven nights, a day phase between each, a boss
    from night two, a fixed ending.

``EndlessDirector``
    No day phase and no ending.  Pressure rises with the clock instead of with a
    night number, upgrades are chosen mid-run rather than bought in a shop, and
    the score is how long the player lasted.

Anything either of them decides randomly draws from ``state.streams.spawn`` or
``state.streams.events`` — never from the shared stream — so that re-tuning one
director cannot shift the other's rolls.
"""

from __future__ import annotations

import math
from typing import Protocol

from . import constants as C
from . import geometry as g
from . import rules
from .content import EVENTS, MAPS, stage_for
from .content.maps import ENDLESS_ROTATION
from .content.monsters import ENDLESS_POOL
from .content.spells import SPELLS
from .content.upgrades import ENDLESS_OFFER, UPGRADES
from .state import Mode, Phase, State, to_ticks


class Director(Protocol):
    """What the rules need from whoever is running the night."""

    mode: Mode

    def begin_night(self, state: State) -> None: ...
    def spawn(self, state: State, dt: float) -> None: ...
    def check_end(self, state: State) -> None: ...


# ── shared helpers ───────────────────────────────────────────────────
def _place_warning(state: State, key: str, *, surge: bool = False) -> None:
    """Telegraph an arrival at a legal entry point for this map."""
    # 一律從場地邊緣進來。
    #
    # 地圖可以自己指定進場點，而其中好幾個在場中央 —— 從那裡冒出來的怪，玩家
    # 沒有時間差可以反應：它出現的位置已經在葛蕾特和他之間了。守方遊戲的公平
    # 性建立在「威脅從外面來、你有一段路可以攔」上面，中場生怪把那段路拿掉。
    x, y = g.edge_point(state.streams.spawn)
    rules.add_warning(state, key, x, y, surge=surge)


def _roll_event(state: State) -> None:
    """Pick one event for tonight, respecting each event's minimum night.

    Night one draws nothing, because the tutorial has exactly one idea to teach
    and a twist on top of it would bury the idea.  That rule is expressed by the
    event data's ``min_night``, not by an ``if night == 1`` here, so a designer
    can move it without touching the engine.
    """
    stream = state.streams.events
    eligible = [(key, spec.weight) for key, spec in EVENTS.items()
                if state.meta.night >= spec.min_night]
    if not eligible:
        state.event_pending = None
        return
    eligible.sort()                      # stable order, independent of dict
    state.event_pending = stream.weighted(eligible)

    # Fire somewhere in the middle of the night: early enough to matter, late
    # enough that the player has already read the field once.
    span = max(1, state.ticks_total)
    state.event_at = int(span * stream.between(0.25, 0.65))


def _fire_pending_event(state: State) -> None:
    """Deliver tonight's rolled event once its moment arrives."""
    if state.event_pending is None or state.ticks_elapsed < state.event_at:
        return
    key, state.event_pending = state.event_pending, None
    rules.trigger_event(state, key)


# ── the seven-night campaign ─────────────────────────────────────────
class CampaignDirector:
    """The story mode.  Everything it does comes from the stage table."""

    mode = Mode.CAMPAIGN

    def begin_night(self, state: State) -> None:
        stage = stage_for(state.meta.night)
        rules.load_map(state, stage.map_key)

        spec = MAPS.get(stage.map_key)
        state.map_lights = spec.lights if spec else ()

        length = stage.duration
        if length is None:
            length = C.BOSS_NIGHT_SECONDS if stage.boss else C.NIGHT_SECONDS
        state.ticks_total = to_ticks(length)
        state.ticks_left = state.ticks_total
        state.ticks_elapsed = 0

        state.surges = [to_ticks(t) for t in stage.surges]
        state.boss_key = stage.boss
        state.boss_sent = stage.boss is None
        state.boss_tick = to_ticks(
            0.0 if stage.boss is None else _boss_entrance(stage.boss))

    def spawn(self, state: State, dt: float) -> None:
        rules.sleepers_wake(state, dt)
        rules.resolve_warnings(state, dt)
        _fire_pending_event(state)

        if state.hush_ticks > 0 or state.overtime:
            return                  # in overtime it is just the two of them

        # Reinforcements from the edges, at a pace that tightens by night —
        # unless this stage names its own, which is how the tutorial gets room
        # to teach without a special case in here.
        stage = stage_for(state.meta.night)
        seconds = (stage.spawn_interval if stage.spawn_interval is not None
                   else max(1.4, 4.2 - state.meta.night * 0.28))
        seconds *= float(state.meta.dials["spawn_gap"])
        interval = to_ticks(seconds)
        state.spawn_ticks += 1
        if state.spawn_ticks >= interval and state.ticks_elapsed > to_ticks(3.0):
            state.spawn_ticks = 0
            _place_warning(state, self._pick_kind(state))

        self._surges(state)
        self._boss(state)

    def _pick_kind(self, state: State) -> str:
        """Draw a reinforcement from the species already appearing tonight.

        Restricting reinforcements to tonight's cast keeps a night coherent: the
        player learns one map's worth of threats rather than being handed a
        random sample of the whole bestiary.
        """
        stage = stage_for(state.meta.night)
        return state.streams.spawn.pick(stage.recipe)

    def _surges(self, state: State) -> None:
        """Warn, then deliver, the moments when three arrive at once.

        The warning is the point.  A surge with no tell is the single most
        dangerous thing in a night arriving unannounced, which reads as the game
        cheating rather than as a spike the player failed to prepare for.
        """
        if not state.surges:
            return
        due = state.surges[0]
        remaining = due - state.ticks_elapsed

        if remaining == to_ticks(C.SURGE_TELL_SECONDS):
            state.surge_tell = to_ticks(C.SURGE_TELL_SECONDS)
            state.feedback.bump(surge=1.0)
            state.emit("surge_incoming")
        if state.surge_tell > 0:
            state.surge_tell -= 1

        if remaining <= 0:
            state.surges.pop(0)
            state.feedback.bump(surge=1.1, shake=5.0)
            for _ in range(3):
                _place_warning(state, self._pick_kind(state), surge=True)
            state.emit("surge")

    def _boss(self, state: State) -> None:
        if state.boss_sent or state.boss_key is None:
            return
        # Also sent the moment the clock runs out, whatever its entrance says.
        # Without this a stage whose boss enters late could reach dawn with the
        # boss unsent, and the night would wait forever for something that was
        # never coming.
        if state.ticks_elapsed >= state.boss_tick or state.ticks_left <= 0:
            state.boss_sent = True
            rules.spawn_boss(state, state.boss_key)

    def check_end(self, state: State) -> None:
        if state.ticks_left > 0:
            return
        # Dawn is not enough on a boss night: the boss has to be down.
        #
        # This is what makes a boss the night's *subject* rather than a large
        # thing that wandered through it.  Before, a player could keep away from
        # it for the last thirty seconds and be handed the night anyway, which
        # meant the correct play against every boss was to ignore it.  Killing
        # it early does not end the night early either — the clock still has to
        # run out — so the reward for a fast kill is a quiet field to gather
        # sugar in, not a shorter night.
        if state.overtime:
            return
        state.stats.sugar_left = sum(d.value for d in state.drops if not d.fake)
        state.meta.best_night = max(state.meta.best_night, state.meta.night)
        from .score import grade_night, stars_for

        state.meta.award_stars(state.meta.night,
                               stars_for(grade_night(state).grade))
        if state.meta.night >= C.CAMPAIGN_NIGHTS:
            state.phase = Phase.VICTORY
            state.emit("victory")
        else:
            state.phase = Phase.SHOP
            state.emit("dawn")


def _boss_entrance(key: str) -> float:
    from .content import BOSSES
    spec = BOSSES.get(key)
    return spec.entrance if spec else 35.0


# ── endless ──────────────────────────────────────────────────────────
class EndlessDirector:
    """One night that never ends, getting worse on a curve.

    Three things keep a long run from degenerating.

    **A cap on live monsters** that converts overflow into *stronger* monsters
    rather than into fewer.  Silently declining to spawn would make the game
    easier the worse the player is doing, which is exactly backwards.

    **Upgrades offered mid-run**, since there is no shop to visit.  Every
    ``ENDLESS_CHOICE_EVERY`` kills the player picks one of three.

    **A rotating map**, so a twenty-minute run is not twenty minutes of one
    room.
    """

    mode = Mode.ENDLESS

    def begin_night(self, state: State) -> None:
        rules.load_map(state, ENDLESS_ROTATION[0])
        spec = MAPS.get(state.stage)
        state.map_lights = spec.lights if spec else ()

        # There is no clock to run out; ``ticks_left`` counts up as a score
        # instead, and the HUD shows elapsed time rather than time remaining.
        state.ticks_total = 0
        state.ticks_left = 0
        state.ticks_elapsed = 0
        state.surges = []

        state.meta.sister_hp = C.ENDLESS_SISTER_HP

        # Stand-in for the four action points a campaign night opens with.
        # Clamped, because a lost endless run is retried by rebuilding the state
        # from the carried meta — so without a ceiling four retries walked the
        # lantern to level five on a spec whose maximum is four.
        for key, levels in C.ENDLESS_STARTING_KIT:
            spec = UPGRADES.get(key)
            if spec is not None:
                state.meta.upgrades[key] = min(
                    spec.max_level, state.meta.level(key) + levels)

        self._grant_default_skills(state)

    @staticmethod
    def _grant_default_skills(state: State) -> None:
        """Hand endless its two skills outright, one per shelf.

        Learning and equipping are both gated on the day phase, and endless
        never leaves ``NIGHT`` — so the mode shipped with a HUD advertising
        skill points that no input could ever spend, and two dead keys.  Rather
        than punch a hole in that gate (which exists to keep the campaign's
        choices in daylight where the player can think), endless simply starts
        with its loadout already decided.  Choosing skills is the campaign's
        game; surviving with them is this one's.
        """
        for key in C.ENDLESS_DEFAULT_SKILLS:
            spec = SPELLS.get(key)
            if spec is None:
                continue
            if key not in state.meta.skills:
                state.meta.skills.append(key)
            slot = 0 if spec.tier == 1 else 1
            if slot < len(state.meta.slots) and state.meta.slots[slot] is None:
                state.meta.slots[slot] = key
        # The points were never spendable here; showing them was the bug.
        state.meta.skill_points_1 = 0
        state.meta.skill_points_2 = 0

    # ── the curve ────────────────────────────────────────────────────
    @staticmethod
    def pressure(minutes: float) -> float:
        """Return a difficulty multiplier that rises without ever exploding.

        Logarithmic, and deliberately gentle.  The first version reached 4.4×
        by minute six, which is an arrival every 0.73 seconds — far past what a
        single defender can answer no matter how well upgraded, so every run
        ended at the same wall regardless of skill.  A slower climb keeps the
        curve *the* difficulty rather than a cliff at a fixed clock time.
        """
        return 1.0 + math.log1p(minutes * 0.85) * 0.62

    def _interval_ticks(self, state: State) -> int:
        """Ticks between arrivals, shrinking toward a floor.

        The first minute is deliberately slack — the player has to be allowed to
        learn the field and bank an upgrade or two before pressure means
        anything.  Measured at the old opening rate, an average run ended in
        twenty-seven seconds.
        """
        minutes = state.ticks_elapsed * C.FIXED_DT / 60.0
        opening = (C.ENDLESS_OPENING_INTERVAL if minutes < 1.0
                   else C.ENDLESS_BASE_INTERVAL)
        seconds = (max(C.ENDLESS_MIN_INTERVAL, opening / self.pressure(minutes))
                   * float(state.meta.dials["spawn_gap"]))
        return max(1, to_ticks(seconds))

    def _pool(self, state: State) -> list[tuple[str, float]]:
        """Re-weight the bestiary over time toward the heavier species.

        Early minutes are mostly villagers and children so the player can learn
        to read the field; later ones lean on brutes and butchers, which changes
        what the player has to do rather than only how often they must do it.
        """
        minutes = state.ticks_elapsed * C.FIXED_DT / 60.0
        shift = min(1.0, minutes / 8.0)
        out: list[tuple[str, float]] = []
        for key, weight in ENDLESS_POOL:
            # Rare species start near zero and grow; common ones decay.
            if weight >= 3.0:
                out.append((key, weight * (1.0 - 0.6 * shift)))
            else:
                out.append((key, weight * (0.4 + 1.8 * shift)))
        return out

    def spawn(self, state: State, dt: float) -> None:
        rules.resolve_warnings(state, dt)
        self._rotate_map(state)
        self._roll_endless_event(state)

        if state.hush_ticks > 0:
            return

        if state.ticks_elapsed < to_ticks(C.ENDLESS_GRACE):
            return

        live = len(state.monsters) + len(state.warnings)
        state.spawn_ticks += 1
        if state.spawn_ticks < self._interval_ticks(state):
            return
        state.spawn_ticks = 0

        key = state.streams.spawn.weighted(self._pool(state))

        # At the cap, arrivals become elites instead of stopping.  Pressure has
        # to keep rising even when the field is full, or a struggling player is
        # rewarded with a quieter game.
        if live >= C.ENDLESS_MONSTER_CAP:
            weakest = min(state.monsters, key=lambda m: m.hp, default=None)
            if weakest is not None:
                state.monsters.remove(weakest)
            _place_warning(state, key, surge=True)
            return

        _place_warning(state, key)

    def _roll_endless_event(self, state: State) -> None:
        """Fire an event roughly every forty seconds, forever.

        Endless has no night boundary to hang a twist on, so events become the
        rhythm section: they are what stops minute twelve from feeling like
        minute four with bigger numbers.
        """
        if state.event is not None:
            return
        every = to_ticks(40.0)
        if state.ticks_elapsed == 0 or state.ticks_elapsed % every:
            return
        stream = state.streams.events
        eligible = sorted((key, spec.weight) for key, spec in EVENTS.items())
        if eligible:
            rules.trigger_event(state, stream.weighted(eligible))

    def _rotate_map(self, state: State) -> None:
        """Change map every two minutes, at a moment the field is quiet-ish."""
        every = to_ticks(120.0)
        index = (state.ticks_elapsed // every) % len(ENDLESS_ROTATION)
        target = ENDLESS_ROTATION[index]
        if target == state.stage:
            return
        rules.load_map(state, target)
        spec = MAPS.get(target)
        state.map_lights = spec.lights if spec else ()
        state.feedback.bump(surge=1.0)
        state.emit(f"map:{target}")

    # ── mid-run upgrades ─────────────────────────────────────────────
    def offer(self, state: State) -> None:
        """Put three upgrades in front of the player, if one is earned.

        Earned by kills *or* by time.  The timer matters more than it looks: a
        player who is being overwhelmed kills less, so a kills-only gate hands
        out the most help to whoever needs it least.
        """
        if state.pending_choice:
            return
        by_kills = state.kills_since_choice >= C.ENDLESS_CHOICE_EVERY
        by_time = (state.ticks_elapsed - state.last_offer_tick
                   >= to_ticks(C.ENDLESS_CHOICE_SECONDS))
        if not (by_kills or by_time):
            return
        state.kills_since_choice = 0
        state.last_offer_tick = state.ticks_elapsed

        available = [key for key in ENDLESS_OFFER
                     if state.meta.level(key) < UPGRADES[key].max_level]
        if not available:
            return
        stream = state.streams.loot
        picks: list[str] = []
        pool = list(available)
        for _ in range(min(C.ENDLESS_CHOICES, len(pool))):
            choice = pool.pop(stream.below(len(pool)))
            picks.append(choice)
        state.pending_choice = picks
        state.emit("offer")

    def check_end(self, state: State) -> None:
        self.offer(state)
        # Endless has no dawn: the run ends only when Gretel is taken, which
        # ``rules._resolve_ending`` has already checked before calling here.
        best = state.meta.best_endless_ticks
        state.meta.best_endless_ticks = max(best, state.ticks_elapsed)
        state.meta.best_endless_kills = max(state.meta.best_endless_kills,
                                            state.stats.kills)


def director_for(mode: Mode) -> Director:
    """Return the director that runs ``mode``."""
    return EndlessDirector() if mode is Mode.ENDLESS else CampaignDirector()
