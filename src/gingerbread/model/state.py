"""Run state: what carries between nights, and what exists during one.

Two records matter here.

``Meta`` is progress that **survives** a night — the night counter, sugar,
upgrade levels, Gretel's remaining hearts.  It is what makes preparation
compound, and it is the only thing a save file needs.

``State`` is one night (or one day) in flight.  It holds every entity and every
timer, and it is what ``apply_action`` copies and returns.

Two decisions here are load-bearing for the determinism contract.

**Time is counted in integer ticks.**  Accumulating ``1/60`` as a float reaches
49.999999999998444 after 3000 steps, so a fifty-second night ran fifty seconds
*and one tick*, and the spawn-interval formula was fed a value that drifted all
night.  Seconds are derived for display and never accumulated.

**Upgrade levels are a dict, not fields.**  A new upgrade must cost one row in
``content/upgrades.py`` and zero changes here.  The moment upgrades become
fields, every new one touches the state, the copy, the snapshot and the save
format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from . import constants as C
from .entities import (Boss, Drop, Effect, Feedback, Hazard, Monster, Obstacle, Player,
                       Projectile, Puddle, Warning)
from .rng import Rng, Streams


def to_ticks(seconds: float) -> int:
    """Convert a duration in seconds to whole ticks, rounding to nearest."""
    return int(round(seconds / C.FIXED_DT))


class Phase(str, Enum):
    """Where a run currently is.  The ``str`` mixin keeps snapshots JSON-safe."""

    DAY = "day"
    NIGHT = "night"
    SHOP = "shop"          # survived; spending happens in its own phase
    LOST = "lost"          # Gretel was taken; the run is over
    VICTORY = "victory"    # campaign only: the seventh night is behind you


class Mode(str, Enum):
    """Which director drives the run.

    CAMPAIGN is the seven-night story: day and night alternate, a boss from
    night two, a fixed ending.  ENDLESS has no day phase and no ending —
    pressure rises forever and the run is scored by how long it held.
    """

    CAMPAIGN = "campaign"
    ENDLESS = "endless"


@dataclass(slots=True)
class Meta:
    """Everything that survives a night.

    This is the compounding layer: the reason a well-prepared night three is
    survivable and an unprepared one is not.
    """

    mode: Mode = Mode.CAMPAIGN
    #: 難度代號，見 constants.DIFFICULTIES。存進 meta 而不是存在殼層，因為
    #: 快照要看得到它 —— 一個看不見的難度會讓兩局完全不同的遊戲在無頭比對裡
    #: 長得一模一樣。
    difficulty: str = C.DEFAULT_DIFFICULTY

    @property
    def dials(self) -> dict:
        """這一局的難度數值。"""
        return C.difficulty(self.difficulty)

    #: Testing switch: nothing can hurt Hansel or Gretel.  It lives on the run
    #: rather than on the night so a night can be replayed with it on, and it is
    #: written into the snapshot — a cheat that a headless comparison could not
    #: see would make two different runs look identical.
    godmode: bool = False

    #: 開圖：整片場地永遠亮著。跟 godmode 一樣寫在 meta 上而不是殼層，因為
    #: 一個快照看不見的作弊，會讓兩局完全不同的遊戲在無頭比對裡長得一樣。
    seeall: bool = False
    night: int = 1
    sugar: int = 0

    #: Gretel's hearts, in half-heart units, carried across nights.  Never
    #: refilled by dawn — healing costs sugar, which is what makes damage hurt.
    sister_hp: int = C.SISTER_MAX_HP

    #: upgrade key -> how many times it has been bought.  See content/upgrades.
    upgrades: dict[str, int] = field(default_factory=dict)

    #: 每一夜挑戰過幾次。索引就是夜數。
    #:
    #: 一份只有「你過了」的成績單，講不出這一輪是怎麼過的 —— 第一次就過的第
    #: 三夜，跟打了七次才過的第三夜，是兩段完全不同的經歷，而遊戲結束的時候
    #: 應該記得那個差別。
    night_tries: list[int] = field(
        default_factory=lambda: [0] * (C.CAMPAIGN_NIGHTS + 1))

    #: 每一夜拿到幾顆星（0 = 還沒過）。索引就是夜數。
    #:
    #: 單夜的評分只在天亮那一頁出現一次，看完就沒了 —— 玩家沒有任何地方能
    #: 看到「我這一輪整體打得怎樣」。星等把七次評分留下來，變成一張可以回頭
    #: 看、可以想再刷一次的成績單。
    night_stars: list[int] = field(
        default_factory=lambda: [0] * (C.CAMPAIGN_NIGHTS + 1))

    #: Sugar already paid out by each night, indexed by night number.  A list
    #: rather than a dict so the snapshot stays JSON-safe without key coercion.
    #: See ``constants.NIGHT_SUGAR_BUDGET`` for why this is tracked at all.
    night_sugar: list[int] = field(
        default_factory=lambda: [0] * (C.CAMPAIGN_NIGHTS + 1))

    #: Skills learned, in learn order.  Once learned, always usable.
    skills: list[str] = field(default_factory=list)
    #: Unspent skill points.  One arrives each day.
    #: One pool per shelf.  A single pool meant the two-point skills were
    #: bought by *not* buying one-point ones, so the first tier quietly became
    #: the thing you skip.  Separate pools make them two independent choices,
    #: which is what having two slots was for.
    skill_points_1: int = 0
    skill_points_2: int = 0

    def points_for(self, tier: int) -> int:
        return self.skill_points_1 if tier == 1 else self.skill_points_2

    def spend_point(self, tier: int, amount: int = 1) -> None:
        if tier == 1:
            self.skill_points_1 -= amount
        else:
            self.skill_points_2 -= amount

    #: The two carried skills, in slot order.  Two rather than four so the
    #: decision is made *before* the night, in the shop, where the player can
    #: think — rather than during it, where they cannot.
    slots: list[str | None] = field(default_factory=lambda: [None, None])

    # ── records, for the menu and the share text ─────────────────────
    best_night: int = 0
    best_endless_ticks: int = 0
    best_endless_kills: int = 0

    def level(self, key: str) -> int:
        """How many times ``key`` has been bought.  Absent means zero."""
        return self.upgrades.get(key, 0)

    def count_try(self, night: int) -> None:
        """記下這一夜又被挑戰了一次。"""
        while len(self.night_tries) <= night:
            self.night_tries.append(0)
        self.night_tries[night] += 1

    @property
    def total_tries(self) -> int:
        return sum(self.night_tries)

    def award_stars(self, night: int, stars: int) -> None:
        """記下這一夜的星等，只往上不往下。

        重打一夜是為了拿更好的成績，不是為了把已經拿到的弄丟 —— 一次失手就
        把三顆星洗成一顆，玩家學到的是不要再挑戰。
        """
        while len(self.night_stars) <= night:
            self.night_stars.append(0)
        self.night_stars[night] = max(self.night_stars[night], int(stars))

    @property
    def total_stars(self) -> int:
        return sum(self.night_stars)

    def sugar_left_tonight(self, night: int) -> int:
        """How much more sugar this night may still drop.

        Unlimited in endless, which has no nights to budget and whose whole
        pressure curve assumes the player keeps being paid.
        """
        if self.mode is not Mode.CAMPAIGN:
            return 10 ** 9
        if not 0 <= night < len(C.NIGHT_SUGAR_BUDGET):
            return 10 ** 9
        while len(self.night_sugar) <= night:
            self.night_sugar.append(0)
        return max(0, C.NIGHT_SUGAR_BUDGET[night] - self.night_sugar[night])

    def bank_night_sugar(self, night: int, amount: int) -> None:
        """Record that ``night`` has now paid out ``amount`` more."""
        if self.mode is not Mode.CAMPAIGN or amount <= 0:
            return
        while len(self.night_sugar) <= night:
            self.night_sugar.append(0)
        self.night_sugar[night] += amount

    @property
    def max_sister_hp(self) -> int:
        """Gretel's ceiling, which differs by mode.

        Endless has no dawn to heal at, so its allowance has to be larger — see
        ``constants.ENDLESS_SISTER_HP`` for the measurement behind that.
        """
        base = (C.ENDLESS_SISTER_HP if self.mode is Mode.ENDLESS
                else C.SISTER_MAX_HP)
        return max(2, base + int(self.dials["sister_bonus"]))

    def clear_nightly(self) -> None:
        """Drop the day-only upgrades.

        Whetting the lantern and adding oil are stored as upgrade levels so they
        flow through the same summation as permanent growth.  The cost of that
        convenience is that someone has to clear them, and this is the one
        place that does.
        """
        from .content.upgrades import UPGRADES

        for key, spec in UPGRADES.items():
            if spec.consumable and spec.base_cost == 0:
                self.upgrades.pop(key, None)


@dataclass(slots=True)
class Stats:
    """Per-night tally.  Read by the result screen, never by a rule."""

    #: Everyone who turned up tonight, however they arrived — the denominator
    #: for every rate on the report card.  Counted rather than estimated: a
    #: night's body count varies by more than a factor of two with the seed, so
    #: scoring against a fixed expectation would grade the roll, not the player.
    arrivals: int = 0
    kills: int = 0
    kills_by_lantern: int = 0
    kills_by_spell: int = 0
    reached_sister: int = 0
    sugar_picked: int = 0
    sugar_left: int = 0
    damage_taken: int = 0
    downs: int = 0
    best_combo: int = 0
    boss_killed: bool = False


@dataclass(slots=True)
class State:
    """One day or night in flight.  Never holds a pygame object."""

    phase: Phase
    seed: int
    meta: Meta
    player: Player

    action_points: int = C.ACTION_POINTS

    #: Steps simulated since this state was created.  Distinct from
    #: ``ticks_elapsed``, which restarts with each phase.
    tick: int = 0

    #: Phase length and remaining time, both in whole ticks.
    ticks_left: int = 0
    ticks_total: int = 0
    #: Ticks since this phase began.
    ticks_elapsed: int = 0
    #: Ticks since the run began; the endless mode's real clock.
    ticks_total_run: int = 0

    #: 0 at nightfall, 1 once fully dark.  No monster acts until it reaches 1.
    dusk: float = 0.0

    #: Which map this night uses; a key into the map table.
    stage: str = "village_square"

    monsters: list[Monster] = field(default_factory=list)
    bosses: list[Boss] = field(default_factory=list)
    warnings: list[Warning] = field(default_factory=list)
    drops: list[Drop] = field(default_factory=list)
    obstacles: list[Obstacle] = field(default_factory=list)
    projectiles: list[Projectile] = field(default_factory=list)
    #: Mud, syrup, fire — anything on the ground that acts on whoever stands in it.
    puddles: list[Puddle] = field(default_factory=list)
    #: Twisters and water traps: the things the player's skills leave behind.
    hazards: list[Hazard] = field(default_factory=list)
    effects: list[Effect] = field(default_factory=list)

    #: The daylight version of tonight's monsters — the same people, still
    #: human — as (spec, x, y, wake_ticks), so the day view and the night spawn
    #: cannot disagree about who is coming.
    sleepers: list[tuple[str, float, float, int]] = field(default_factory=list)

    spawn_ticks: int = 0
    #: Surge times, in ticks from nightfall, soonest first.
    surges: list[int] = field(default_factory=list)
    #: Ticks until the next surge lands, while its warning is showing.
    surge_tell: int = 0

    #: Whether tonight's boss has already been sent in.  This lives in the
    #: state, not on the director, because a director is rebuilt on every
    #: ``apply_action`` — anything it remembered between calls would be lost,
    #: and worse, would not be copied or replayed with the rest of the run.
    boss_sent: bool = False
    #: Tick at which the boss enters, resolved once at nightfall.
    boss_tick: int = 0
    #: Tonight's boss key, or None.
    boss_key: str | None = None

    #: Active night event and how many ticks it has left.
    event: str | None = None
    event_ticks: int = 0
    #: Tonight's rolled event and the tick it fires on.  Rolled at nightfall so
    #: the whole night is decided by the seed, but delivered part-way through so
    #: it lands as a turn in the night rather than as a starting condition.
    event_pending: str | None = None
    event_at: int = 0

    #: Multiplier on every light radius, owned by night events.  It lives in
    #: state rather than in the renderer because the rules read light too — a
    #: light-fearing monster must freeze in exactly the area the player sees
    #: lit, and it cannot if the two sides compute the radius differently.
    light_scale: float = 1.0

    #: The same multiplier, owned by boss phases instead of by events.  Kept
    #: apart from ``light_scale`` because both can be in force at once: a single
    #: field meant whichever wrote last silently cancelled the other, and a fog
    #: phase that ended never handed the light back at all.
    fog_scale: float = 1.0

    #: Extra lights this map contributes, frozen at nightfall as (x, y, radius).
    #: Frozen rather than re-read from the map table each frame so ``lights_of``
    #: stays a pure function of state and replays keep matching.
    map_lights: tuple[tuple[float, float, float], ...] = ()

    #: Ticks of moonlight remaining: reveals the field without freezing anything
    #: that fears the lantern.  Kept apart from ``map_lights`` for that reason.
    reveal_ticks: int = 0

    #: Ticks during which no new arrival is scheduled (the "hush" event).
    hush_ticks: int = 0

    #: Ticks of 怒潮's mist, which slows every monster on the map.  A field
    #: rather than a puddle because the design says *the whole map* — a puddle
    #: big enough would have to be drawn as one, and a screen-filling circle
    #: reads as a bug rather than as weather.
    mist_ticks: int = 0

    #: Seconds of 聖癒's shield left on Gretel.  While this is above zero
    #: nothing reaches her at all — it lives on the state rather than on the
    #: player because it protects *her*, and she is not an entity the rules
    #: carry a body for.
    ward: float = 0.0

    combo: int = 0
    combo_ticks: int = 0

    #: Ticks remaining before each skill can be used again.  Lives in the state
    #: rather than in Meta because it is a fact about tonight, and it resets
    #: with the night.
    cooldowns: dict[str, int] = field(default_factory=dict)

    #: Endless mode: kills banked toward the next upgrade offer, and the offer
    #: itself while the player is choosing.
    pending_choice: list[str] = field(default_factory=list)
    kills_since_choice: int = 0
    #: Tick of the last upgrade offer, so one can also be granted on a timer.
    last_offer_tick: int = 0

    feedback: Feedback = field(default_factory=Feedback)
    stats: Stats = field(default_factory=Stats)

    #: Things that happened this tick, as flat strings.  The shell reads these
    #: to trigger sounds; nothing in the rules ever reads them back.  Cleared at
    #: the start of every ``apply_action``.
    events: list[str] = field(default_factory=list)

    #: Named random substreams, all seeded from ``seed``.  The placeholder
    #: default exists only so the dataclass is constructible; every real path
    #: goes through ``new_game``, which seeds it properly.
    streams: Streams = field(default_factory=lambda: Streams(0, 0),
                             repr=False, compare=False)

    # ── derived time ─────────────────────────────────────────────────
    @property
    def rng(self) -> Rng:
        """The general-purpose stream.

        Subsystems with their own stream — spawning, events, loot, bosses —
        should name it instead, so changing one subsystem's content cannot
        shift another's rolls and invalidate a recorded seed.
        """
        return self.streams.misc

    @property
    def elapsed(self) -> float:
        """Seconds elapsed this phase, derived rather than accumulated."""
        return self.ticks_elapsed * C.FIXED_DT

    @property
    def timer(self) -> float:
        """Seconds left in this phase."""
        return self.ticks_left * C.FIXED_DT

    @property
    def timer_max(self) -> float:
        return self.ticks_total * C.FIXED_DT

    @property
    def timer_fraction(self) -> float:
        """How much of the phase is left, from 1 down to 0."""
        return self.ticks_left / self.ticks_total if self.ticks_total else 0.0

    # ── derived state ────────────────────────────────────────────────
    @property
    def over(self) -> bool:
        return self.phase in (Phase.SHOP, Phase.LOST, Phase.VICTORY)

    @property
    def overtime(self) -> bool:
        """True when dawn has come and the night's boss is still standing.

        A property rather than a stored flag because it is a *reading* of two
        other facts, and a stored copy of a reading is a copy that can be wrong.
        """
        if self.boss_key is None:
            return False
        if self.ticks_left > 0:
            return False
        return not self.boss_sent or any(b.hp > 0 for b in self.bosses)

    @property
    def dark(self) -> bool:
        """True once it is night and the fade has begun.

        ``LOST`` counts.  A run only ends at night, and dropping the darkness on
        the frame Gretel is taken switched every light in the forest on at the
        exact moment the player lost — so the last thing they saw was a bright,
        unfamiliar field rather than the dark one they had just failed in.
        Dawn is something the player earns; it is not what losing looks like.
        """
        if self.meta.seeall:
            return False              # 開圖：不畫黑暗遮罩
        return self.phase in (Phase.NIGHT, Phase.LOST) and self.dusk > 0

    def emit(self, name: str) -> None:
        """Record that something happened, for the shell to react to."""
        self.events.append(name)
