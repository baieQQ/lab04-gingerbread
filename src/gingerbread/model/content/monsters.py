"""The monster codex.

Ten species, from the design document.  The rule this table is written to:
**every one must demand a different response.**  A monster that is only "the
villager with more health" adds a number, not a decision, and the player has no
reason to learn its name.

They are all people.  That is the story — what comes for Gretel at night is the
village, seen through Hansel's memory of the witch — so nothing here is a beast,
and the renderer draws them all as humanoids with something wrong.

Adding one
----------
A plain monster is a single row::

    "beggar": MonsterSpec("beggar", "乞丐", hp=3, speed=44, radius=11, sugar=1),

One that does something is that row plus a ``behaviour=`` or ``traits=`` name.
``python -m gingerbread --content`` prints every name available and every
parameter it reads, straight out of the registry — so that list is never stale.
"""

from __future__ import annotations

from typing import Final

from ..specs import MonsterSpec

MONSTERS: Final[dict[str, MonsterSpec]] = {

    # ── the plain villagers, for pacing and for teaching ─────────────
    "villager": MonsterSpec(
        key="villager", name="村民",
        hp=2, speed=38.0, radius=10.0, sugar=1,
        colour=(192, 58, 46), silhouette="villager",
        step_hz=420.0),

    "brute": MonsterSpec(
        key="brute", name="壯漢",
        hp=5, speed=29.0, radius=15.0, sugar=2,
        knockable=False,
        colour=(142, 42, 70), silhouette="brute",
        step_hz=110.0),

    "child": MonsterSpec(
        key="child", name="孩子",
        hp=1, speed=73.0, radius=8.0, sugar=1,
        colour=(220, 97, 82), silhouette="child",
        step_hz=900.0),

    # ── 1｜鏡子怪 ────────────────────────────────────────────────────
    "mirror": MonsterSpec(
        key="mirror", name="鏡子怪",
        # Half the speed of the others.  It has to be got behind, and a monster
        # that has to be walked around cannot also be one that outruns you —
        # the manoeuvre and the chase were competing for the same seconds.
        hp=4, speed=16.0, radius=11.0, sugar=2,
        # Cannot be knocked back, and that is forced by its own rule: it must be
        # struck from behind, which means the player stands on the far side from
        # Gretel, which means any knockback drives it *into* her.  Hitting it
        # correctly was making things worse.
        knockable=False,
        traits=("reflects",),
        params={"reflect_arc": 1.5},
        colour=(150, 168, 190), silhouette="villager",
        step_hz=520.0),

    # ── 2｜弓箭手 ───────────────────────────────────────────────────
    "archer": MonsterSpec(
        key="archer", name="弓箭手",
        hp=2, speed=30.0, radius=10.0, sugar=2,
        behaviour="standoff",
        # Everything here is the same trade made three ways: it has to come
        # close enough to be reachable (240 → 150), it has to hold the shot long
        # enough to be reached (2.0 → 3.4), and holding it lights it up so the
        # player can find it in the dark.  A ranged attacker the player cannot
        # get to in time is not difficulty, it is a tax.
        params={"standoff": 150.0, "windup": 3.4, "reload": 2.2,
                "shot_speed": 250.0, "shot_damage": 1},
        #: Glows while winding up, and the glow is a real light — so it is
        #: visible from anywhere on the field, the way Gretel always is.
        charge_light=96.0,
        colour=(168, 96, 48), silhouette="villager",
        step_hz=300.0),

    # ── 3｜投石怪 ───────────────────────────────────────────────────
    "slinger": MonsterSpec(
        key="slinger", name="投石怪",
        hp=3, speed=26.0, radius=12.0, sugar=2,
        behaviour="barricade",
        params={"standoff": 270.0, "windup": 3.0, "reload": 4.5,
                "rock_radius": 26.0},
        colour=(126, 118, 106), silhouette="brute",
        step_hz=180.0),

    # ── 4｜分裂怪 ───────────────────────────────────────────────────
    "splitter": MonsterSpec(
        key="splitter", name="分裂怪",
        hp=3, speed=34.0, radius=12.0, sugar=2,
        traits=("splits",),
        params={"split_into": "splitterling", "split_count": 2},
        colour=(176, 64, 88), silhouette="villager",
        step_hz=380.0),

    # ── 5｜挖洞怪 ───────────────────────────────────────────────────
    # 分裂怪裂出來的那一半：同一種東西，小一號、快一點、只有一滴血。
    # 原本裂出來的是「孩子」—— 一個外型完全不同的物種，所以「它裂開了」在
    # 畫面上讀起來像「它變成別的東西了」。
    "splitterling": MonsterSpec(
        key="splitterling", name="小分裂怪",
        hp=1, speed=44.0, radius=8.0, sugar=1,
        colour=(176, 64, 88), silhouette="villager",
        step_hz=440.0),

    "digger": MonsterSpec(
        key="digger", name="挖洞怪",
        hp=3, speed=40.0, radius=11.0, sugar=2,
        behaviour="burrow",
        params={"dig_after": 1.5, "surface_at": 92.0},
        colour=(120, 96, 62), silhouette="villager",
        step_hz=240.0),

    # ── 6｜復活怪 ───────────────────────────────────────────────────
    "riser": MonsterSpec(
        key="riser", name="復活怪",
        hp=4, speed=31.0, radius=11.0, sugar=3,
        traits=("revives",),
        params={"revive_hp": 0.6, "revive_delay": 1.6},
        colour=(108, 74, 118), silhouette="villager",
        step_hz=350.0),

    # ── 7｜隱形怪 ───────────────────────────────────────────────────
    "faint": MonsterSpec(
        key="faint", name="隱形怪",
        hp=2, speed=46.0, radius=10.0, sugar=3,
        traits=("fades",),
        # 1.0, not 0.86: at 0.86 it was a faint smudge, which asks the player to
        # squint at the dark rather than to read the ground.  Gone entirely, and
        # tracked by its prints, is both fairer and more frightening.
        params={"fade": 1.0, "step_every": 0.26, "step_life": 2.4,
                "step_spread": 5.0},
        weakness="light",
        colour=(96, 104, 128), silhouette="villager",
        step_hz=620.0),

    # ── 8｜盔甲怪 ───────────────────────────────────────────────────
    "armoured": MonsterSpec(
        key="armoured", name="盔甲怪",
        hp=4, speed=25.0, radius=14.0, sugar=3,
        knockable=False,
        traits=("armoured",),
        params={"armour": 3},
        colour=(112, 120, 132), silhouette="brute",
        step_hz=140.0),

    # ── 9｜泥巴怪 ───────────────────────────────────────────────────
    "mudling": MonsterSpec(
        key="mudling", name="泥巴怪",
        hp=3, speed=28.0, radius=12.0, sugar=2,
        traits=("mud_trail",),
        params={"mud_every": 0.45, "mud_radius": 26.0,
                "mud_slow": 0.55, "mud_life": 6.0},
        weakness="water",
        colour=(104, 84, 56), silhouette="villager",
        step_hz=200.0),

    # ── 小史萊姆 · 只有糖果史萊姆會生出來，不進一般生怪池 ──────────
    "slimeling": MonsterSpec(
        key="slimeling", name="小史萊姆",
        hp=2, speed=30.0, radius=9.0, sugar=1,
        traits=("mud_trail",),
        # A short, thin trail: the boss owns the wide sticky one, and eight
        # children each laying a boss-sized puddle would carpet the map inside
        # ten seconds and turn the fight into a slideshow.
        params={"mud_every": 0.6, "mud_radius": 20.0,
                "mud_slow": 0.7, "mud_life": 4.0},
        weakness="thunder",
        colour=(196, 108, 172), silhouette="villager",
        step_hz=300.0),

    # ── 10｜自爆怪 ──────────────────────────────────────────────────
    "bomber": MonsterSpec(
        key="bomber", name="自爆怪",
        hp=2, speed=52.0, radius=11.0, sugar=2,
        traits=("bursts",),
        params={"blast_radius": 72.0, "blast_damage": 1},
        colour=(214, 122, 40), silhouette="child",
        step_hz=760.0),
}

#: What endless may spawn, and how likely each is early on.  The director
#: re-weights this over time — see ``director.py``.
ENDLESS_POOL: Final[tuple[tuple[str, float], ...]] = (
    ("villager", 5.0), ("child", 3.0), ("brute", 2.0),
    ("splitter", 1.6), ("mirror", 1.4), ("bomber", 1.3),
    ("archer", 1.2), ("mudling", 1.2), ("faint", 1.0),
    ("digger", 1.0), ("riser", 0.9), ("slinger", 0.8), ("armoured", 0.7),
)

#: Elites are ordinary monsters with boosted numbers.
ELITE_HP_FACTOR: Final = 2.0
ELITE_SPEED_FACTOR: Final = 1.2
ELITE_SUGAR_FACTOR: Final = 3
