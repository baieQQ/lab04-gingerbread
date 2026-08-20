"""Immutable descriptions of content.

This is the schema the game's content is written in.  The engine reads these
records; it never hard-codes a monster, a boss, a map or an upgrade.  That is
what lets content arrive as data — a new plain monster is **one row** in
``content/monsters.py`` and no engine change at all.

How behaviour stays data-driven
-------------------------------
A spec never holds a function.  It holds *names*:

``behaviour``
    One name from the behaviour registry.  It decides how the thing moves each
    tick.  Most monsters use ``"charge"`` and never name anything else.

``traits``
    Zero or more names from the trait registry.  Traits hook fixed moments —
    on death, on touching the player, on touching Gretel — and they **compose**,
    so a monster can both fear light and split when killed without either trait
    knowing the other exists.

``params``
    A flat mapping of numbers those behaviours and traits read, with defaults.
    Keeping tuning in data rather than in the function body means balancing is
    editing a table.

Every field is a plain built-in, so any of these tables could be moved to JSON
or TOML later without touching the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

RGB = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class MonsterSpec:
    """One species.

    Minimum viable row::

        MonsterSpec("villager", "村民", hp=2, speed=38, radius=10, sugar=1)
    """

    key: str
    name: str
    hp: int
    speed: float
    radius: float
    sugar: int

    #: Radius this monster lights up while it is winding something up; 0 for
    #: the ones that give no tell.  A light rather than a renderer flourish so
    #: the rules and the screen cannot disagree about where it is.
    charge_light: float = 0.0
    #: False for anything too heavy to shove — the reason brutes must be
    #: walked around rather than fought head-on.
    knockable: bool = True

    #: Half-hearts taken from Gretel on contact.  Two is a butcher; one is
    #: everyone else.
    contact_damage: int = 1

    behaviour: str = "charge"
    traits: tuple[str, ...] = ()
    params: Mapping[str, float] = field(default_factory=dict)

    #: The element this one is the answer to, if any.  A spell of a matching
    #: element hits it for ``WEAKNESS_MULTIPLIER`` and, on a boss, opens it up.
    weakness: str | None = None

    # ── presentation (the renderer's only input; never read by a rule) ──
    colour: RGB = (192, 58, 46)
    #: Which procedural body to draw when no sprite exists yet.  Sprites will
    #: replace these, but the game must look deliberate before they arrive.
    silhouette: str = "villager"
    #: Asset key, e.g. "monster.villager".  Absent art falls back to the
    #: silhouette, so declaring this early costs nothing.
    sprite: str | None = None
    #: Footstep identity.  In near-total darkness, telling a brute from a child
    #: by sound is a real skill — so every species must sound different.
    step_hz: float = 420.0
    step_stride: float = 20.0

    def param(self, name: str, default: float = 0.0) -> float:
        return float(self.params.get(name, default))


@dataclass(frozen=True, slots=True)
class BossPhase:
    """One stage of a boss fight.

    A boss is a sequence of these.  Crossing a health threshold advances to the
    next, which is what makes a fight feel like it has chapters instead of just
    a longer health bar.
    """

    #: Advance to the next phase when HP falls to this fraction or below.
    until_hp: float
    behaviour: str
    params: Mapping[str, float] = field(default_factory=dict)
    #: Monsters this phase keeps summoning, as (monster key, seconds between).
    summons: tuple[tuple[str, float], ...] = ()
    #: Multiplier on every light radius while this phase runs — the fog phases.
    fog: float = 1.0
    #: Shown once when the phase begins.  This is where a fight teaches its own
    #: weakness: an element the player cannot discover is a damage number they
    #: never earn.
    announce: str | None = None


@dataclass(frozen=True, slots=True)
class BossSpec:
    """A boss.  Phases and a script, not merely bigger numbers."""

    key: str
    name: str
    title: str
    hp: int
    speed: float
    radius: float
    sugar: int
    phases: tuple[BossPhase, ...]

    #: Seconds into the night before it appears; the first half is still mobs.
    #: Traits, exactly as on a monster.  A boss that leaves syrup and a mudling
    #: that leaves mud are the same mechanic at different scales, so they read
    #: the same row rather than each having their own code path.
    traits: tuple[str, ...] = ()
    params: Mapping[str, float] = field(default_factory=dict)

    entrance: float = 35.0
    #: Bosses are knockable on purpose — an unstoppable one leaves the player
    #: no way to buy space, which reads as unfair rather than hard.
    knockable: bool = True
    contact_damage: int = 2
    #: Fraction of normal damage a spell deals.  Without this, stockpiling two
    #: lightning bolts skips every boss the game has.
    spell_resistance: float = 0.15

    #: The element that answers this fight.  Every boss has one, and the phase
    #: announcements are what teach it — a weakness the player cannot discover
    #: is just a damage number they never earn.
    weakness: str | None = None

    colour: RGB = (214, 74, 122)
    silhouette: str = "brute"
    sprite: str | None = None

    def param(self, name: str, default: float = 0.0) -> float:
        """Same accessor a monster row has, so shared traits can read either."""
        return float(self.params.get(name, default))


@dataclass(frozen=True, slots=True)
class UpgradeSpec:
    """One purchasable improvement.

    ``stat`` and ``per_level`` cover every numeric upgrade without code: the
    rules read the accumulated total, so "attack +1 per level" needs no
    special case anywhere.
    """

    key: str
    name: str
    description: str
    base_cost: int
    max_level: int

    #: Which derived stat this feeds, e.g. "attack", "light", "swing_range",
    #: "swing_speed", "move_speed", "defence", "player_hp".
    stat: str
    per_level: float

    #: Permanent upgrades get dearer as they stack; consumables stay flat.
    consumable: bool = False
    #: Campaign night this first appears in the shop.
    unlock_night: int = 1
    icon: str | None = None

    def cost(self, level: int, step: int) -> int:
        """Price of the next level given how many are already owned."""
        if self.consumable:
            return self.base_cost
        return self.base_cost + level * step


@dataclass(frozen=True, slots=True)
class SpellSpec:
    """A one-shot prepared in daylight and spent at night."""

    key: str
    name: str
    description: str
    #: Action points to prepare one during the day.
    prepare_cost: int = 1
    unlock_night: int = 1
    #: One of the four elements: "thunder", "light", "wind", "water".
    element: str = "thunder"
    #: Points to learn it, **from its own tier's pool**.  One each: the tiers
    #: no longer compete for the same currency, so a price difference between
    #: them would only mean "this shelf refills slower", which is a worse way to
    #: say the same thing than simply granting fewer points.
    cost: int = 1
    #: Seconds before it can be used again.  Skills are unlimited: what makes
    #: them a decision is *when*, not *how many are left*.  A stock of charges
    #: turns every cast into "am I allowed to enjoy this yet", which is the
    #: opposite of what a panic button should feel like.
    cooldown: float = 14.0
    #: Seconds the effect lasts; 0 for instantaneous ones.
    duration: float = 0.0
    #: Behaviour name that resolves the spell when cast.
    effect: str = "smite"
    params: Mapping[str, float] = field(default_factory=dict)
    #: Whether casting into an empty field should be refused.  True for
    #: everything that acts on what is already there — a wasted panic button is
    #: a bad press, and the rules protect the player from it.  False for a trap,
    #: whose entire point is being set down *before* anything arrives; refusing
    #: that cast would forbid the only way it is meant to be used.
    needs_target: bool = True
    #: 1 or 2 — how many skill points, and which shelf it sits on in the shop.
    tier: int = 1
    #: Whether holding the key charges it before it fires.
    charge: bool = False
    icon: str | None = None
    colour: RGB = (142, 107, 214)


@dataclass(frozen=True, slots=True)
class EventSpec:
    """A mid-night twist.

    Events exist so two runs of the same night are not the same night.  They
    are announced, never silent — an unexplained change reads as a bug.
    """

    key: str
    name: str
    description: str
    duration: float
    #: Name in the event registry that applies and removes the effect.
    effect: str
    params: Mapping[str, float] = field(default_factory=dict)
    #: Never fires before this night, so the tutorial stays legible.
    min_night: int = 2
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class MapSpec:
    """The space a night is fought in.

    A map must change *how the space plays*, not merely what it looks like —
    six backdrops with identical geometry are one map with six wallpapers.
    """

    key: str
    name: str
    #: Circular blockers as (x, y, radius, blocks_sight).
    obstacles: tuple[tuple[float, float, float, bool], ...] = ()
    #: Standing lights that are not the player's, as (x, y, radius).
    lights: tuple[tuple[float, float, float], ...] = ()
    #: Restrict arrivals to these edge points; empty means the whole perimeter.
    spawn_points: tuple[tuple[float, float], ...] = ()
    ground: str | None = None       # asset key for the floor texture
    ambient: str | None = None      # asset key for the looping ambience


@dataclass(frozen=True, slots=True)
class StageSpec:
    """One night of the campaign: who comes, when, and where it happens."""

    night: int
    map_key: str
    #: The people standing in the square at dusk, in the order they wake.
    recipe: tuple[str, ...]
    #: Seconds into the night when three arrive at once.
    surges: tuple[float, ...]
    boss: str | None = None
    #: How many elites to mix in tonight.
    elites: int = 0
    duration: float | None = None   # defaults to the normal night length
    #: Seconds between edge reinforcements.  ``None`` uses the default curve.
    #: Exposed per night because pacing is a *design* decision — the tutorial
    #: needs room to teach, and a late night needs none — and burying it in the
    #: director means a designer cannot change it without touching the engine.
    spawn_interval: float | None = None
    #: Shown on the day screen: the night's own one-line pitch.
    tagline: str = ""
