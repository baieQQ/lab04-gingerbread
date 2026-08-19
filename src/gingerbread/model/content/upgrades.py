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

    "haste": UpgradeSpec(
        key="haste", name="攻擊頻率",
        description="揮燈速度 +12%",
        base_cost=5, max_level=4,
        stat="swing_speed_pct", per_level=0.12),

    "reach": UpgradeSpec(
        key="reach", name="攻擊範圍",
        description="揮燈角度 +20 度",
        base_cost=4, max_level=4,
        stat="swing_arc_deg", per_level=20.0),

    "shade": UpgradeSpec(
        key="shade", name="光罩範圍",
        description="光照範圍 +20%",
        base_cost=4, max_level=4,
        stat="light_pct", per_level=0.20),

    "vigour": UpgradeSpec(
        key="vigour", name="生命",
        description="漢賽爾生命 +1",
        base_cost=6, max_level=5,
        stat="player_hp", per_level=1.0),

    "mend": UpgradeSpec(
        key="mend", name="熱湯與繃帶",
        description="替葛蕾特補回半顆心",
        base_cost=4, max_level=99,
        stat="sister_heal", per_level=1.0,
        consumable=True),

    "lantern": UpgradeSpec(
        key="lantern", name="鍛造提燈",
        description="攻擊力 +1",
        base_cost=7, max_level=4,
        stat="attack", per_level=1.0),

    "focus": UpgradeSpec(
        key="focus", name="技能冷卻",
        description="所有技能冷卻 −10%（最多 −50%）",
        base_cost=6, max_level=5, stat="cooldown_pct", per_level=0.10),
}

#: Shown in the between-nights shop, in this order.  The day-only pair is
#: excluded: those are spent with action points, not sugar.

SHOP_ORDER: Final[tuple[str, ...]] = (
    "focus",
    "mend", "lantern", "haste", "reach", "shade", "vigour")

#: Offered mid-run in endless, which has no shop.
ENDLESS_OFFER: Final[tuple[str, ...]] = (
    "lantern", "haste", "reach", "shade", "vigour", "mend")
