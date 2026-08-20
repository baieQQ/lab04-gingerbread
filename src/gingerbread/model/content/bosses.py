"""The boss codex.

Six fights, from the design document, one per night from the second.

Two rules every entry keeps.

**A boss never simply walks at Gretel.**  If it behaved like a big villager it
would be a health bar, not a fight — so no opening phase uses ``charge``, and a
test enforces that.

**A boss can be outlasted.**  Surviving to dawn without killing it still wins the
night, for much less sugar.  That keeps a hard fight from becoming a wall the
player bounces off until they quit.

``weakness`` is the element that answers the fight.  Matching it hits for triple
and opens a window where everything hurts double — and each boss's phase lines
are written to *say* which element that is, because a weakness the player cannot
discover is only a number they never earn.
"""

from __future__ import annotations

from typing import Final

from ..specs import BossPhase, BossSpec

BOSSES: Final[dict[str, BossSpec]] = {

    # 第二夜 — 教「元素有用」這件事本身
    "slime": BossSpec(
        key="slime", name="糖果史萊姆", title="第二夜",
        # Faster than it was.  At 24 px/s it crawled so slowly that its syrup
        # puddles landed on top of each other in one spot, so the trail — the
        # entire point of the fight — never got laid across the field at all.
        hp=46, speed=33.0, radius=28.0, sugar=18,
        weakness="thunder",
        traits=("mud_trail", "buds"),
        # Wider, stickier, and lasting nearly twice as long.  Seven seconds
        # sounds generous on paper and is not: the player walks through a given
        # patch once, five seconds after it was laid, by which time it had
        # already faded to nothing.  Syrup the player never stands in is not a
        # mechanic, it is decoration.
        params={"mud_every": 0.34, "mud_radius": 46.0,
                "mud_slow": 0.42, "mud_life": 13.0,
                "bud_into": "slimeling", "bud_every": 1.4,
                "bud_cap": 7, "bud_delay": 0.35},
        colour=(196, 108, 172),
        phases=(
            BossPhase(until_hp=0.55, behaviour="flank",
                      params={"orbit": 170.0, "patience": 99.0},
                      summons=(("splitter", 7.0),),
                      announce="每打它一下，就有一塊掉下來自己爬走。"),
            BossPhase(until_hp=0.0, behaviour="flank",
                      params={"orbit": 110.0, "patience": 3.0},
                      summons=(("splitter", 5.0),),
                      announce="它裂得更快了——最小的那些，得靠雷。"),
        )),

    # 第三夜 — 教「看不見的東西要用光找」
    "shade_archer": BossSpec(
        key="shade_archer", name="褪影射手", title="第三夜",
        hp=52, speed=36.0, radius=25.0, sugar=20,
        weakness="light",
        traits=("fades",),
        params={"fade": 0.8},
        colour=(92, 96, 122),
        phases=(
            BossPhase(until_hp=0.5, behaviour="standoff",
                      params={"standoff": 280.0, "windup": 1.5,
                              "reload": 2.0, "shot_speed": 260.0},
                      summons=(("archer", 7.0),),
                      announce="箭從看不見的地方射來。照亮它。"),
            BossPhase(until_hp=0.0, behaviour="standoff",
                      params={"standoff": 180.0, "windup": 1.2,
                              "reload": 1.4, "shot_speed": 300.0},
                      summons=(("archer", 4.0), ("faint", 6.0)),
                      announce="它不再躲了。"),
        )),

    # 第四夜 — 教「風可以撥開視野」
    "mist_reaper": BossSpec(
        key="mist_reaper", name="迷霧死神", title="第四夜",
        hp=58, speed=34.0, radius=27.0, sugar=22,
        weakness="wind",
        traits=("shrouds",),
        params={"shroud_every": 13.0, "shroud_hold": 11.0,
                "shroud_fog": 0.16, "shroud_cut": 3.0},
        colour=(126, 134, 148),
        # The permanent phase fog is gone.  Dimming the whole fight by 0.55 and
        # then 0.4 made every second of it slightly worse and no second of it
        # interesting; the dark is now something the boss *does*, at moments
        # the player can see coming and go and stop.
        phases=(
            BossPhase(until_hp=0.6, behaviour="flank",
                      params={"orbit": 200.0, "patience": 99.0},
                      summons=(("faint", 6.0),),
                      announce="它停下來，霧就湧上來——霧裡唯一亮著的就是它。"),
            BossPhase(until_hp=0.0, behaviour="charge",
                      summons=(("faint", 4.0), ("digger", 7.0)),
                      announce="它放得更勤了。要嘛救妹妹，要嘛去把它打斷。"),
        )),

    # 第五夜 — 教「水能清路，也能逼它現形」
    "ash_hob": BossSpec(
        key="ash_hob", name="灰燼灶鬼", title="第五夜",
        # Fewer hit points than it had, because the fight is now gated: every
        # point of damage costs the player a water cooldown to earn, so the old
        # 64 would have been four minutes of waiting for 水牢 to come back.
        hp=46, speed=30.0, radius=28.0, sugar=24,
        weakness="water",
        traits=("hurls_fire", "needs_soak"),
        params={"fire_every": 2.6, "fire_speed": 150.0,
                "fire_life": 5.0, "fire_spread": 0.35},
        colour=(214, 96, 44),
        phases=(
            BossPhase(until_hp=0.55, behaviour="flank",
                      params={"orbit": 150.0, "patience": 99.0},
                      summons=(("bomber", 6.0),),
                      announce="它燒得發紅，打上去只有火星——先用水澆熄它。"),
            BossPhase(until_hp=0.0, behaviour="charge",
                      summons=(("bomber", 4.0), ("brute", 6.0)),
                      announce="火燒穿了它的外殼——底下是木頭。"),
        )),

    # 第六夜 — 教「讓它自食惡果」
    "moonfall": BossSpec(
        key="moonfall", name="墜月法師", title="第六夜",
        hp=70, speed=32.0, radius=26.0, sugar=26,
        weakness="water",
        traits=("calls_meteors",),
        params={"meteor_every": 5.5, "meteor_min": 1, "meteor_max": 5,
                "meteor_fall": 1.15, "meteor_radius": 44.0,
                "meteor_spread": 52.0, "meteor_damage": 3},
        colour=(146, 118, 206),
        # It keeps its distance and does nothing at range but call rocks.  The
        # old build gave it ``standoff`` with arrows, which made the sixth-night
        # boss a slightly larger archer — the meteors were in the announcement
        # text and nowhere else in the game.
        phases=(
            BossPhase(until_hp=0.6, behaviour="flank",
                      params={"orbit": 240.0, "patience": 99.0},
                      summons=(("armoured", 8.0),),
                      announce="隕石總是砸向你「現在」站的地方。站好，然後閃開。"),
            BossPhase(until_hp=0.0, behaviour="flank",
                      params={"orbit": 175.0, "patience": 99.0},
                      summons=(("armoured", 6.0), ("riser", 7.0)),
                      announce="它砸得更快了——也更容易砸到自己。"),
        )),

    # 第七夜 — 全部一起來，因為她就是前面所有東西
    "witch": BossSpec(
        key="witch", name="糖果屋女巫", title="第七夜",
        hp=92, speed=31.0, radius=28.0, sugar=32,
        weakness=None,                       # 綜合：沒有單一解答
        traits=("fades", "mud_trail"),
        params={"fade": 0.7, "mud_every": 0.6, "mud_radius": 30.0,
                "mud_slow": 0.7, "mud_life": 5.0},
        entrance=28.0,
        colour=(150, 62, 120),
        phases=(
            BossPhase(until_hp=0.7, behaviour="flank",
                      params={"orbit": 230.0, "patience": 99.0},
                      summons=(("villager", 4.0),), fog=0.8,
                      announce="每一張熟悉的臉，都開始扭曲。"),
            BossPhase(until_hp=0.35, behaviour="standoff",
                      params={"standoff": 210.0, "windup": 1.6, "reload": 1.8},
                      summons=(("faint", 5.0), ("bomber", 6.0)), fog=0.6,
                      announce="分身、隱形、噴火、隕石——全部一起來。"),
            BossPhase(until_hp=0.0, behaviour="charge",
                      summons=(("brute", 4.0), ("armoured", 6.0)),
                      announce="只要妹妹還在身後，他就絕不後退。"),
        )),
}
