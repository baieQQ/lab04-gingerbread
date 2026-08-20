"""The skill codex.

Four skills, one per element, from the design document.  Each has a *job* rather
than a damage number — 清場 / 偵測 / 控位置 / 控單體 — because four skills that
all mean "deal damage" would only differ in how much, and the player would carry
the biggest one.

A skill is **learned once and then always available**, gated only by a
cooldown.  One skill point arrives each day, so the campaign hands out one new
skill per night survived.  Charges were the first design and they were wrong:
a stock turns every cast into "am I allowed to spend this yet", which is exactly
the wrong feeling for a panic button.  A cooldown asks *when*, which is a
question about the fight in front of you.

Two are carried at a time, so the choice of which is made in daylight.

Elements matter twice: a skill hits the thing it answers for
``WEAKNESS_MULTIPLIER`` damage, and on a boss it opens a window where everything
hurts more.  That is what turns "which skill do I bring" into a question with a
right answer the player has to have learned.
"""

from __future__ import annotations

from typing import Final

from ..specs import SpellSpec

SPELLS: Final[dict[str, SpellSpec]] = {

    # ── 一階 · 一點技能點 ───────────────────────────────────────────
    "bolt": SpellSpec(
        key="bolt", name="閃電", element="thunder", tier=1,
        description="範圍內的敵人被劈到只剩一滴血、護甲全碎，並被轟飛出去；"
                    "落點留下一片電焦的地面，走進去的只剩三成速度",
        cost=1, cooldown=16.0, duration=0.0,
        effect="smite",
        # 傷害 2 的時候，範圍內大部分的怪（3-5 滴血）被震開之後照樣活著，
        # 玩家看到的是「怪飛走了，沒人死」—— 那讀起來就是沒有傷害。3 讓輕的
        # 那一群當場清空，硬的那幾種還是要補第二下，跟提燈同一條規則。
        params={"radius": 62.0, "push": 210.0,
                "boss": 6.0, "slow": 0.3, "slow_life": 4.5,
                "slow_radius": 78.0},
        colour=(180, 140, 255)),

    "holy": SpellSpec(
        key="holy", name="聖光", element="light", tier=1,
        description="八秒內照亮全場，隱形的現形，全場敵人畏光減速三成，"
                    "周圍的敵人每秒被灼燒",
        cost=1, cooldown=22.0, duration=8.0,
        effect="reveal_all",
        params={"radius": 80.0, "burn": 0.5},
        colour=(250, 232, 168)),

    "tornado": SpellSpec(
        key="tornado", name="龍捲風", element="wind", tier=1,
        description="朝面對的方向放出三道呈扇形散開的龍捲風，"
                    "捲起沿路的怪一起帶走",
        cost=1, cooldown=16.0, duration=5.0,
        effect="twister",
        params={"speed": 150.0, "radius": 52.0, "hold": 2.5,
                "spread": 0.38},
        colour=(150, 214, 200)),

    "cage": SpellSpec(
        key="cage", name="水牢", element="water", tier=1,
        description="罩住腳下一片地方，裡面的敵人動不了；五秒後炸開，全部清空",
        cost=1, cooldown=18.0, duration=5.0,
        effect="cage", needs_target=False,
        params={"radius": 80.0, "push": 90.0, "boss": 6.0},
        colour=(110, 168, 232)),

    # ── 二階 · 兩點技能點 ───────────────────────────────────────────
    "thunderclap": SpellSpec(
        key="thunderclap", name="雷鳴", element="thunder", tier=2,
        description="披上雷電護甲五秒，碰到你的人當場被電死；"
                    "五秒結束時把累積的電一次放掉，大範圍清空",
        cost=1, cooldown=26.0, duration=5.0,
        effect="storm_armour", needs_target=False,
        # 對王 2。接觸傷害有 0.9 秒的節流，五秒的護甲最多打進五下，再加上
        # 結束時的放電 —— 18 的時候那是九十點，比第二到第六夜的每一隻王都多；
        # 5 實測還是能對非弱點的王打掉 46（58 血的迷霧死神剩 12）。一個 26 秒
        # 冷卻的技能不該一次帶走一隻王八成的血。
        params={"radius": 50.0, "burst_radius": 140.0, "boss": 2.0},
        colour=(196, 168, 255)),

    "blessing": SpellSpec(
        key="blessing", name="聖癒", element="light", tier=2,
        description="八秒內在葛蕾特身上罩一層護罩，任何東西都碰不到她，"
                    "撞上去的還會被彈開；期間每四秒替兄妹各回一滴血",
        cost=1, cooldown=30.0, duration=8.0,
        effect="mend_light", needs_target=False,
        params={"every": 4.0, "push": 150.0},
        colour=(255, 244, 206)),

    "windrun": SpellSpec(
        key="windrun", name="疾風", element="wind", tier=2,
        description="六秒內化成旋風，撞到的敵人會被捲著往你衝的方向飛到場邊；"
                    "期間照樣可以揮燈",
        cost=1, cooldown=24.0, duration=6.0,
        effect="gale", needs_target=False,
        # 2.4 倍速下，玩家從怪物旁邊呼嘯而過但一個都碰不到 —— 判定圈只有
        # 漢賽爾本人那麼大，而他一幀跑掉的距離比那個圈還寬。降速，並且在旋
        # 風狀態下把判定圈放大到 34：那才是一道旋風該有的作用範圍。
        params={"speed": 1.9, "push": 460.0, "boss": 6.0, "sweep": 34.0},
        colour=(178, 232, 218)),

    "riptide": SpellSpec(
        key="riptide", name="怒潮", element="water", tier=2,
        description="三圈水波由內往外推開，掃過的全部清空；之後全場起霧，"
                    "敵人走得更慢",
        cost=1, cooldown=28.0, duration=0.0,
        effect="surge_wave",
        params={"radius": 170.0, "mist": 5.0, "push": 110.0, "boss": 20.0},
        colour=(96, 150, 220)),
}
