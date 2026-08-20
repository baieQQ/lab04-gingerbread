"""The seven nights.

Each row's cast honours the availability the design document specifies —
mirror / slinger / splitter / mudling from night one, archer and faint from
two, armoured and bomber from three, digger and riser from four — so a night
never asks for a lesson the player has not been given.

``recipe`` is who is already standing in the square at dusk, **in the order they
wake**.  That ordering is the night's opening script: the player sees these
people during the day and watches them turn one at a time.  Reinforcements from
the edges are the director's job, not this table's.
"""

from __future__ import annotations

from typing import Final

from ..specs import StageSpec

STAGES: Final[dict[int, StageSpec]] = {

    1: StageSpec(
        night=1, map_key="village_square",
        # 投石怪與泥巴怪照設定文件從第一夜就在場。投石怪原本一個關卡都沒排
        # 到——寫好了、註冊了、圖鑑查得到，但玩家永遠遇不到。
        recipe=("villager", "villager", "child", "mirror",
                "mudling", "slinger", "villager", "splitter"),
        surges=(32.0,),
        boss=None, elites=0,
        # The tutorial is paced by hand.  On the default curve a careful player
        # was measured leaking exactly six — the entire heart budget — with the
        # collapse arriving at second 26, so the night taught nothing except
        # that it was over.
        spawn_interval=6.4,
        tagline="村民熱烈迎接。有人好奇，有人議論。"),

    2: StageSpec(
        night=2, map_key="mill",
        recipe=("villager", "archer", "mirror", "child", "faint",
                "splitter", "villager"),
        surges=(18.0, 38.0),
        boss="slime", elites=1,
        spawn_interval=5.2,
        tagline="好奇的村民靠得更近了。"),

    3: StageSpec(
        night=3, map_key="forest_edge",
        # 盔甲怪與自爆怪照設定文件從第三夜開始，原本要到第四夜。
        recipe=("archer", "faint", "villager", "mudling", "brute",
                "armoured", "bomber", "child", "mirror"),
        surges=(15.0, 30.0, 44.0),
        boss="shade_archer", elites=1,
        tagline="敵人已經不只是躲在森林裡。"),

    4: StageSpec(
        night=4, map_key="market",
        recipe=("faint", "bomber", "villager", "armoured",
                "child", "mudling", "brute"),
        surges=(12.0, 26.0, 40.0),
        boss="mist_reaper", elites=2,
        tagline="霧裡的人影一閃而過。那張臉像極了村民。"),

    5: StageSpec(
        night=5, map_key="chapel",
        recipe=("bomber", "armoured", "child", "mudling",
                "faint", "brute", "splitter", "archer", "villager"),
        surges=(12.0, 24.0, 36.0, 48.0),
        boss="ash_hob", elites=2,
        tagline="火焰封鎖了去路。"),

    6: StageSpec(
        night=6, map_key="butchery",
        recipe=("armoured", "brute", "bomber",
                "armoured", "child", "mirror", "villager", "brute"),
        surges=(10.0, 20.0, 32.0, 44.0),
        boss="moonfall", elites=3,
        tagline="村莊陷入火海。他已經分不清自己在逃還是在追。"),

    7: StageSpec(
        night=7, map_key="deep_forest",
        recipe=("brute", "faint", "armoured", "bomber", "archer", "splitter", "mudling", "child"),
        surges=(8.0, 18.0, 28.0, 38.0, 48.0),
        boss="witch", elites=3,
        tagline="所有身影融合成同一個存在。"),
}


def stage_for(night: int) -> StageSpec:
    """Return the stage for ``night``, repeating the last one past the end.

    Repeating rather than raising means a save from a longer campaign, or a
    debug jump to night 12, still produces a playable night instead of a crash.
    """
    if night in STAGES:
        return STAGES[night]
    return STAGES[max(STAGES)]
