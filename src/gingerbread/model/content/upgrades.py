"""The upgrade table.

Four axes, from the design document, all **multiplicative** — +12% attack speed,
+20° arc, +20% light — which is why ``derive.py`` keeps percentage stats apart
from flat ones.  Percentages compound, so late levels are worth more than early
ones, and the shop stays interesting after night three.

Healing is the one consumable, and it is priced below every permanent upgrade
because Gretel's damage carries between nights: sugar spent staying alive is
sugar not spent getting stronger, and the player has to keep choosing.
"""

from __future__ import annotations

from typing import Final

from ..specs import UpgradeSpec

#: Kept as names so old save files and old action strings resolve to nothing
#: instead of raising.  The day no longer sells temporary buffs at all: it sells
#: permanent upgrades and lets the player swap skills, which is one clear idea
#: instead of two competing ones.
TONIGHT_ATTACK: Final = "tonight_attack"
TONIGHT_LIGHT: Final = "tonight_light"

UPGRADES: Final[dict[str, UpgradeSpec]] = {

    # ── 連續數值：十等，每一等都吃得到 ─────────────────────────────
    #
    # Ten levels each, at roughly half the old per-level value, so a maxed
    # Hansel is about as strong as a maxed Hansel used to be — the change is
    # that getting there now takes the whole campaign instead of three nights.
    #
    # Every ceiling below is measured against the cap the stat actually has,
    # not chosen to look tidy.  The old 攻擊範圍 sold four levels of +20° into
    # 47° of headroom: levels three and four were priced, bought, displayed —
    # and did nothing at all.  A shop that charges for a number it will not
    # apply is worse than a shop with fewer things in it.

    "haste": UpgradeSpec(
        key="haste", name="攻擊頻率",
        description="揮燈速度 +5%",
        base_cost=4, max_level=10,
        stat="swing_speed_pct", per_level=0.05),

    "reach": UpgradeSpec(
        key="reach", name="攻擊範圍",
        # 4.5° × 10 = 45°, against 47° of headroom before SWING_ARC_CAP.
        description="揮燈角度 +4.5 度",
        base_cost=3, max_level=10,
        stat="swing_arc_deg", per_level=4.5),

    "shade": UpgradeSpec(
        key="shade", name="光罩範圍",
        description="光照範圍 +8%",
        base_cost=3, max_level=10,
        stat="light_pct", per_level=0.08),

    "focus": UpgradeSpec(
        key="focus", name="技能冷卻",
        description="所有技能冷卻 −5%（最多 −50%）",
        base_cost=4, max_level=10,
        stat="cooldown_pct", per_level=0.05),

    # ── 整數數值：等級數受限於數字本身 ─────────────────────────────
    #
    # These two cannot honestly have ten levels.  Hansel's health is an integer
    # capped at ten and he starts on five, so there are exactly five purchases
    # to make; damage is an integer compared against monster health, so a tenth
    # level of it would either do nothing or break the game in half.  Selling
    # ten levels of either would mean selling levels that do not exist.

    "vigour": UpgradeSpec(
        key="vigour", name="生命",
        description="漢賽爾生命 +1",
        base_cost=6, max_level=5,
        stat="player_hp", per_level=1.0),

    "lantern": UpgradeSpec(
        key="lantern", name="鍛造提燈",
        # Two levels, and expensive.  Four levels took attack to five against a
        # bestiary whose toughest member had four health, so a maxed lantern
        # deleted every species in the game in one swing and the night stopped
        # being about positioning.  Capped at three, the light trash still dies
        # instantly and everything with a mechanic takes two — which is a rule
        # the player can learn and play around.
        description="攻擊力 +1",
        base_cost=16, max_level=2,
        stat="attack", per_level=1.0),

    "mend": UpgradeSpec(
        key="mend", name="熱湯與繃帶",
        description="替葛蕾特補回半顆心",
        base_cost=4, max_level=99,
        stat="sister_heal", per_level=1.0,
        consumable=True),
}

#: Shown in the between-nights shop, in this order.  The day-only pair is
#: excluded: those are spent with action points, not sugar.

SHOP_ORDER: Final[tuple[str, ...]] = (
    "focus",
    "mend", "lantern", "haste", "reach", "shade", "vigour")

#: Offered mid-run in endless, which has no shop.
ENDLESS_OFFER: Final[tuple[str, ...]] = (
    "lantern", "haste", "reach", "shade", "vigour", "mend")
