"""Mutable per-run entities.

These are the things that exist *during* a run and change every tick.  They are
deliberately separate from ``specs.py``, which holds the immutable descriptions
of what a thing *is*:

    ``MonsterSpec`` says a brute has 4 HP and cannot be knocked back.
    ``Monster``     says *this* brute is at (312, 88) with 2 HP left.

An entity refers to its spec by **key string**, never by holding the spec
object.  That keeps entities cheap to ``deepcopy`` (which ``apply_action`` does
on every call) and keeps the state trivially serialisable — a spec object in the
state would be copied thousands of times per second for no reason.

Nothing in this module imports pygame, and nothing reads a clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import constants as C


@dataclass(slots=True)
class Light:
    """One source of light in the world.

    Lighting lives in the model rather than the renderer because it is a
    **rule**, not decoration: a light-fearing monster freezes when lit, so the
    rules must be able to ask "is this point lit?".  If the renderer owned the
    lights, that answer would depend on the display being open, and the
    headless determinism check would stop being able to verify it.
    """

    x: float
    y: float
    radius: float
    #: Cold lights (Gretel, dropped sugar, a chapel candle) reveal the ground
    #: but are not the player's lantern; some rules only respect the lantern.
    cold: bool = False
    #: Identifies what cast it, so the renderer can style it and rules can
    #: filter it: "lantern", "sister", "drop", "map", or a boss effect name.
    source: str = "lantern"

    def covers(self, x: float, y: float, fraction: float = C.LIT_FRACTION) -> bool:
        """Return True when (x, y) is inside the *bright* part of this light.

        ``fraction`` trims the dim rim: standing where the glow merely reaches
        should not count as being lit, or light-fearing monsters would freeze
        far outside the area the player can actually see.
        """
        reach = self.radius * fraction
        dx, dy = x - self.x, y - self.y
        return dx * dx + dy * dy <= reach * reach


@dataclass(slots=True)
class Player:
    """Hansel.  Owns his position, cooldowns and condition — nothing else."""

    x: float
    y: float
    face_x: float = 0.0
    face_y: float = -1.0

    hp: int = C.PLAYER_START_HP
    max_hp: int = C.PLAYER_START_HP

    swing_cooldown: float = 0.0
    swing_anim: float = 0.0
    dash: float = 0.0
    dash_cooldown: float = 0.0
    stun: float = 0.0
    invulnerable: float = 0.0
    knock_x: float = 0.0
    knock_y: float = 0.0

    #: Seconds the lantern stays dimmed after being splashed.
    doused: float = 0.0
    #: Seconds remaining face-down.  While positive he cannot act at all.
    downed: float = 0.0
    #: How many times he has gone down tonight; the night ends past the allowance.
    downs: int = 0

    #: Seconds the guard has been held.  Kept as a duration rather than a flag
    #: only so the renderer can fade the shield in instead of popping it.
    guard: float = 0.0

    @property
    def helpless(self) -> bool:
        """True when the player cannot move, swing or dash this tick."""
        return self.downed > 0 or self.stun > 0

    @property
    def guarding(self) -> bool:
        """True while K is held: contact costs no health.

        Nothing else changes — monsters still collide with him exactly as they
        did, they simply cannot take anything off him.  An earlier version threw
        them back instead, which turned a defensive key into an attack and made
        the mirror-backed monsters unplayable, because being thrown *away from
        Hansel* meant being thrown *toward Gretel*.
        """
        return self.guard > 0 and self.downed <= 0


@dataclass(slots=True)
class Monster:
    """A turned villager, or anything else walking in from the dark.

    ``spec`` is the key into the monster table.  Everything variable about this
    individual lives here; everything constant about its species lives in the
    spec.
    """

    spec: str
    x: float
    y: float
    hp: int
    speed: float

    #: Seconds before this one wakes.  Asleep monsters are visible but inert —
    #: that is the whole "you saw these people in daylight" mechanic.
    wake: float = 0.0
    hit_flash: float = 0.0
    #: Distance still to travel while being knocked back.
    knockback: float = 0.0
    #: Which way that knockback goes, as a unit vector.
    #:
    #: Stored per hit rather than derived from Gretel's position.  Deriving it
    #: meant everything was always pushed *away from her*, which is right only
    #: when the attacker happens to be standing between them — and it is exactly
    #: wrong for the mirror, which must be struck from behind and was therefore
    #: shoved toward the player who hit it.
    knock_x: float = 0.0
    knock_y: float = 0.0
    #: Seconds of being flung by a spell; movement and contact are suspended.
    stunned: float = 0.0
    #: Set by the light-fearing behaviour so the renderer can show why it stopped.
    frozen: bool = False
    #: Free-form per-behaviour scratch space (cooldowns, phase counters).
    #: Kept as a plain dict so a new behaviour never needs a new field here.
    memory: dict[str, float] = field(default_factory=dict)
    #: Elites are ordinary monsters with boosted numbers and one borrowed trait.
    elite: bool = False

    #: Armour soaks hits before health does; nothing gets through until it is
    #: gone.  Stored per individual because it is consumed, not a species fact.
    armour: int = 0
    #: How many times this one can still get back up.
    revives: int = 0
    #: Seconds left underground.  Untargetable by spells while it lasts, which
    #: is the whole point of the digger: it forces the player back to his post.
    buried: float = 0.0
    #: 0 = fully visible, 1 = barely there.  Light burns it off.
    faded: float = 0.0
    #: Seconds of wind-up before this one looses whatever it is holding.
    charge: float = 0.0

    @property
    def awake(self) -> bool:
        return self.wake <= 0

    @property
    def active(self) -> bool:
        """Awake, not flung, and not frozen by light — i.e. actually a threat.

        Asks whether it can *act*.  Never use it to decide whether it can be
        *hit*: caging one made it untouchable, so the control skill protected
        its own target.
        """
        return self.wake <= 0 and self.stunned <= 0 and not self.frozen

    @property
    def hittable(self) -> bool:
        """Awake and above ground — i.e. something a swing can reach.

        Deliberately indifferent to ``stunned`` and ``frozen``.  A held monster
        is the one the player most wants to hit; that is the entire payoff of
        freezing it.
        """
        return self.wake <= 0 and self.buried <= 0


@dataclass(slots=True)
class Boss(Monster):
    """A boss.  A monster with phases and a script, not just bigger numbers.

    Subclassing keeps every existing loop over monsters working unchanged while
    letting the boss carry the extra fields its behaviours need.
    """

    phase_index: int = 0
    max_hp: int = 1
    #: Seconds until the next scripted action; behaviours own its meaning.
    timer: float = 0.0
    #: Set when the boss is briefly open to damage, for both rules and renderer.
    vulnerable: bool = True


@dataclass(slots=True)
class Warning:
    """A telegraphed arrival.

    Deliberately visible *through* the darkness: the player must always be able
    to learn where pressure is coming from before it arrives.  Surprise that
    cannot be prepared for is not difficulty.
    """

    x: float
    y: float
    spec: str
    left: float
    #: True for the extra warnings a surge produces, so they can be styled apart.
    surge: bool = False


@dataclass(slots=True)
class Drop:
    """Sugar on the ground.  Uncollected drops vanish at dawn — that is the
    pressure that makes the player leave Gretel's side."""

    x: float
    y: float
    value: int
    #: A baker's decoy: picking it up hurts instead of paying.
    fake: bool = False
    #: Half-hearts restored instead of sugar paid.  Zero for ordinary sugar.
    heal: int = 0


@dataclass(slots=True)
class Projectile:
    """Something thrown.

    Exists so a monster can threaten from outside the lantern's reach.  That
    forces the player to *leave* Gretel to deal with it, which is the only
    pressure in the game that pulls him away from his post — every other threat
    pulls him toward it.
    """

    x: float
    y: float
    vx: float
    vy: float
    radius: float = 5.0
    damage: int = 1
    #: Seconds before it expires on its own, so a stray shot cannot live forever.
    life: float = 4.0
    #: True when the player threw it; hostile shots are the normal case.
    friendly: bool = False
    kind: str = "stone"


@dataclass(slots=True)
class Puddle:
    """A patch on the ground that does something to whoever stands in it.

    Mud slows, syrup slows more, fire burns.  One entity covers all three
    because the only thing that differs is a name and two numbers — and a table
    can supply those.
    """

    x: float
    y: float
    radius: float
    kind: str = "mud"
    #: Movement multiplier for anything standing in it.
    slow: float = 0.55
    #: Damage per second to whoever stands in it.
    burn: float = 0.0
    #: Seconds before it dries out; negative means it never does.
    life: float = -1.0


@dataclass(slots=True)
class Hazard:
    """Something the player put on the field that acts on monsters by itself.

    One entity covers the twister and the water trap for the same reason one
    ``Puddle`` covers mud, syrup and fire: they differ by a name, a velocity and
    two numbers, and a table can supply those.

    A hazard never owns the things it catches.  A twister carrying three
    monsters is simply a twister that moves, plus three monsters that are inside
    it this tick — so nothing has to be un-linked when either side dies, and the
    snapshot stays a list of numbers.
    """

    kind: str
    x: float
    y: float
    radius: float
    life: float
    #: Travel per second.  A trap sits still and leaves these at zero.
    vx: float = 0.0
    vy: float = 0.0
    #: How long whatever it catches stays held after it lets go.
    hold: float = 0.0
    #: Catches left before it is spent.  Negative means unlimited.
    charges: float = -1.0
    #: Set once something has been caught, so a trap can be drawn as sprung.
    sprung: bool = False


@dataclass(slots=True)
class Obstacle:
    """A map feature that blocks movement and sight.

    Circles only, on purpose: circle-versus-circle is the collision test the
    rest of the game already uses, so map geometry needs no new maths and no
    new failure modes.
    """

    x: float
    y: float
    radius: float
    #: Blocks line of sight as well as movement (a mill wheel, not a low fence).
    blocks_sight: bool = True
    kind: str = "block"
    #: Seconds before it crumbles; negative means it is part of the map and
    #: stays all night.  Only monster-made rock uses a finite life — permanent
    #: barricades accumulate into a wall that boxes the player in, which is
    #: exactly what was reported.
    life: float = -1.0


@dataclass(slots=True)
class Effect:
    """A short-lived, purely cosmetic marker the renderer draws.

    Effects are in the model — not because rules read them, but because the
    renderer must never *decide* anything.  When a hit lands, the rules say so
    here; the renderer just draws what it is told.
    """

    kind: str
    x: float
    y: float
    left: float
    life: float
    magnitude: float = 1.0


@dataclass(slots=True)
class Feedback:
    """Screen-level feedback the rules requested this tick.

    Screen shake and hit-stop are gameplay feel, and feel has to be reproducible
    — so they are decided by the rules and merely obeyed by the shell.
    """

    shake: float = 0.0
    freeze: float = 0.0
    hurt_flash: float = 0.0
    surge_flash: float = 0.0

    def decay(self, dt: float) -> None:
        """Bleed every channel toward zero.

        Called unconditionally, once per tick.  In the web prototype the decay
        sat inside the hit-stop branch, so once hit-stop ended the shake stopped
        decaying and the screen shook forever — this method exists so that
        cannot happen again.
        """
        self.shake = max(0.0, self.shake - dt * 34.0)
        self.freeze = max(0.0, self.freeze - dt)
        self.hurt_flash = max(0.0, self.hurt_flash - dt * 1.6)
        self.surge_flash = max(0.0, self.surge_flash - dt)

    def bump(self, *, shake: float = 0.0, freeze: float = 0.0,
             hurt: float = 0.0, surge: float = 0.0) -> None:
        """Raise each channel to at least the requested value.

        ``max`` rather than ``+=`` so a burst of simultaneous hits cannot stack
        into an unreadable screen.
        """
        self.shake = max(self.shake, shake)
        self.freeze = max(self.freeze, freeze)
        self.hurt_flash = max(self.hurt_flash, hurt)
        self.surge_flash = max(self.surge_flash, surge)
