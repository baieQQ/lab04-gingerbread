"""Tuning constants for 《糖果屋之後》.

Every number the rules depend on lives here, so balancing never means hunting
through logic.  This module imports nothing from the rest of the game — it is
the bottom of the dependency graph and must stay that way.

Values are frozen by ``遊戲設計定案.md`` v2.0.  When that document and this
file disagree, the document wins and this file is wrong.
"""

from __future__ import annotations

from typing import Final

# ── world ────────────────────────────────────────────────────────────
WIDTH: Final = 900
HEIGHT: Final = 520
SISTER_X: Final = WIDTH / 2
SISTER_Y: Final = HEIGHT / 2

#: One simulation step.  Fixed on purpose: a variable step would make replays
#: diverge, and the whole determinism contract rests on this being constant.
FIXED_DT: Final = 1.0 / 60.0

#: How far from the playfield edge the player's centre may travel.
PLAY_MARGIN: Final = 16.0

# ── phase lengths ────────────────────────────────────────────────────
DAY_SECONDS: Final = 35.0
NIGHT_SECONDS: Final = 50.0
BOSS_NIGHT_SECONDS: Final = 70.0
ACTION_POINTS: Final = 0

#: Nightfall fade.  No monster acts until this completes, so the player is
#: never hit by something that spawned while the screen was still going dark.
DUSK_SECONDS: Final = 1.2

# ── Gretel: the failure condition ────────────────────────────────────
#: Internal units are *half hearts*, so a half-heart heal is an integer.
SISTER_MAX_HP: Final = 6          # displayed as 3 hearts
SISTER_REACH: Final = 26.0        # monsters this close take her
SISTER_LIGHT_RADIUS: Final = 44.0

# ── Hansel: the endurance resource ───────────────────────────────────
PLAYER_RADIUS: Final = 13.0
PLAYER_START_HP: Final = 5
PLAYER_MAX_HP_CAP: Final = 10

WALK_SPEED: Final = 196.0
WALK_SPEED_CAP: Final = 296.0
DASH_SPEED: Final = 560.0
DASH_TIME: Final = 0.16
DASH_COOLDOWN: Final = 1.4

#: Swing geometry.  Range and cooldown are both upgrade axes, so these are the
#: *starting* values, not the only ones — see ``content/upgrades.py``.
SWING_RANGE: Final = 60.0
SWING_RANGE_CAP: Final = 120.0
SWING_ARC: Final = 0.78           # radians either side of facing
SWING_ARC_CAP: Final = 1.60       # +20 degrees a level, four levels
SWING_COOLDOWN: Final = 0.55
#: Four levels of +12% attack speed compound to 0.55 / 1.12**4.
SWING_COOLDOWN_CAP: Final = 0.30
SWING_ANIM: Final = 0.16
SWING_SLOWDOWN: Final = 0.42      # movement multiplier during the swing

#: Getting shoved.  The brief invulnerability exists so a crowd cannot lock the
#: player in place forever — without it, one bad step is an unrecoverable loop.
STUN_TIME: Final = 0.12
INVULNERABLE_TIME: Final = 1.2
KNOCKBACK_SPEED: Final = 260.0
KNOCKBACK_DECAY: Final = 0.86     # per-frame multiplier on residual knockback

#: Being caught douses the lantern: light drops to this fraction for a while.
DOUSE_SECONDS: Final = 2.0
DOUSE_FACTOR: Final = 0.55

# ── guarding ─────────────────────────────────────────────────────────
# Held, with no cooldown and no window to time.  Every version with a rhythm to
# catch was reported as unusable, and the honest reading of "he does not lose
# health on contact" is a state, not a move.  The cost is built in rather than
# bolted on: a guarding Hansel cannot swing, so holding K means the monsters
# walking past him toward Gretel keep walking.
GUARD_FADE: Final = 0.12          # seconds the shield takes to appear
#: How far a body bounces off the guard — the same 26 a lantern hit gives, so
#: contact feels the same whichever way it happens.  It is a nudge, not the old
#: shove: large knockback from a defensive key is what drove monsters into
#: Gretel, because the player guarding is standing between her and them.
GUARD_NUDGE: Final = 26.0

# ── skills ───────────────────────────────────────────────────────────
#: Seconds a chargeable skill may be held.  Charging is on the skill's own key
#: (L or ；) rather than on K: K is the guard, and a player holding it to charge
#: lightning would also be refusing to swing without being told why.
CHARGE_MAX: Final = 3.0
#: The most 技能冷卻 can take off: half, and no further.
COOLDOWN_FLOOR: Final = 0.5
#: How long a charged key must go unseen before it counts as released.  Longer
#: than one tick because movement and casting arrive as separate actions, so a
#: held key is genuinely absent on roughly half of all ticks.
CHARGE_RELEASE: Final = 0.10
#: Slow applied by 怒潮's mist — two thirds of normal speed.
MIST_SLOW: Final = 2.0 / 3.0

# ── mending ──────────────────────────────────────────────────────────
#: Chance a kill leaves a heart behind, rolled **only while Hansel is hurt**.
#: A drop rather than a trickle of regeneration on purpose: regeneration quietly
#: undoes a mistake while the player is doing nothing, which teaches nothing and
#: removes the one thing his health bar was for.  A heart on the ground makes
#: the same recovery a decision — it is lying somewhere, and going to fetch it
#: means leaving her side, which is the trade this whole game is built on.
HEART_DROP_CHANCE: Final = 0.14
#: 補葛蕾特的心的掉落機率。比補漢賽爾的低，因為她的血是勝負本身 —— 但不能是
#: 零，否則前幾夜的失誤會鎖死整局。
SISTER_HEART_CHANCE: Final = 0.07
#: Half-hearts one restores.
HEART_VALUE: Final = 1

# ── barricades ───────────────────────────────────────────────────────
#: Seconds a monster-dropped rock lasts.  Rocks used to be permanent, and a
#: single barricade monster could spend a night walling the field in: the player
#: was sealed in a pocket he could not leave and the other monsters jammed
#: against the rubble.  A rock is now a temporary problem, like everything else
#: in a night.
ROCK_LIFE: Final = 9.0
#: How many monster-made rocks may exist at once, across every barricade
#: monster on the field.
ROCK_LIMIT: Final = 3
#: Clearance a new rock needs from the player, on top of both radii.  Dropping
#: one on his head was the trapping bug: he was inside it before it existed, and
#: ``slide`` refuses every direction from inside an obstacle.
ROCK_CLEAR_PLAYER: Final = 30.0
#: Clearance a new rock needs from another rock.  Two rocks that touch begin a
#: wall; keeping them apart guarantees a gap wide enough to walk through.
ROCK_CLEAR_ROCK: Final = 54.0

# ── elements ─────────────────────────────────────────────────────────
#: Damage multiplier when a spell hits something it is the answer to.
WEAKNESS_MULTIPLIER: Final = 3.0
#: Seconds a boss stays open after its weakness lands.
WEAKNESS_WINDOW: Final = 3.0

#: 聖光亮著的時候，所有敵人剩幾成速度。
HOLY_SLOW: Final = 0.72
#: 王被打斷之後，多久之內不會再被打斷。
BOSS_FLINCH_GAP: Final = 2.0
#: 有王的夜晚，生怪間隔乘上這個數 —— 王和它的護衛已經是那一夜的壓力來源。
BOSS_NIGHT_SPAWN_GAP: Final = 1.55
#: 接觸類技能（疾風、雷鳴）對王的傷害間隔。
CONTACT_GAP: Final = 0.9

#: 一次疾風／一次雷鳴，最多能打中同一隻王幾下。
#:
#: 節流閥管每秒幾下，這個管一次施法總共幾下。沒有它的話，疾風六秒可以磨掉迷
#: 霧死神 93% 的血 —— 貼著王來回蹭，不該是這款遊戲對王的正解。
GALE_BOSS_HITS: Final = 2
AURA_BOSS_HITS: Final = 2

#: 只能從左右兩側進場的怪。場地寬 900、高 520，從上下來的路程只有一半多，
#: 而需要繞背的怪需要那段路程。
SIDE_ONLY_SPAWNS: Final = ("mirror",)

#: Shot kinds that rebound off the walls instead of expiring at them, and leave
#: a patch of fire wherever they finally stop.
BOUNCING_SHOTS: Final = ("fireball",)
#: Shot kinds that pass straight through Gretel.  The hob and the moon-mage
#: are fights *with Hansel*: if their attacks also ate her health the correct
#: answer would be to fight them from the far corner of the map, which is the
#: one thing this game must never reward.
SPARES_SISTER: Final = ("fireball", "meteor")

#: How often a patch of fire can take a half-heart off whoever stands in it.
BURN_INTERVAL: Final = 0.75

#: How far a boss lights itself while channelling.  Small — it is a beacon to
#: walk toward, not a lamp that undoes the fog it just made.
CHANNEL_LIGHT_RADIUS: Final = 58.0

#: How hard 聖癒's shield throws off whatever walks into it.
WARD_PUSH: Final = 150.0

#: 一般擊退的速度，跟原本寫死在 _apply_knockback 裡的一樣。
KNOCK_SPEED: Final = 150.0
#: 疾風把人捲飛的速度。460 像素用 150 要飄三秒，讀起來像卡住。
TORNADO_SPEED: Final = 620.0
#: 閃電把人震開的速度。要像衝擊波，不像走開。
BOLT_SPEED: Final = 430.0
#: Damage multiplier while a boss is in that open state.
EXPOSED_MULTIPLIER: Final = 2.0

# ── downed state ─────────────────────────────────────────────────────
#: Hansel at zero HP goes down rather than dying, so the cost of his mistake is
#: paid in Gretel's hearts — the thing the player actually cares about.  Set
#: DOWNED_ENABLED False to make zero HP end the night immediately instead;
#: the rules read this flag rather than assuming either policy.
DOWNED_ENABLED: Final = True
DOWNED_SECONDS: Final = 5.0
#: Still enough to see the ground and whatever is standing over you.
#: At 30 the screen read as solid black, which players reported as the
#: game breaking rather than as a state they were in.
DOWNED_LIGHT_RADIUS: Final = 78.0
DOWNED_REVIVE_FRACTION: Final = 0.5   # of max HP

#: Downs allowed per night before the night ends anyway.
#:
#: This is deliberately far above what any night can reach, which is a way of
#: saying: **going down never ends the night by itself.**  An earlier version
#: allowed one, and simulation showed the result immediately — across three
#: scripted skill levels and three seeds, every single loss came from Hansel
#: going down twice, and none from Gretel running out of hearts.  That inverts
#: the whole point of the game.  The run is supposed to end because the person
#: you were protecting was taken, not because you got tired.
#:
#: Going down is still severe: five seconds of near-total darkness with nobody
#: guarding her costs hearts on its own.  Letting that consequence do the work
#: keeps one failure condition instead of two competing ones.
DOWNED_ALLOWANCE: Final = 999

# ── lantern light ────────────────────────────────────────────────────
# 132 was too dark to read the layout at a glance; 198 lit so much of the field
# that the darkness stopped being a rule at all.  168 keeps the shape of the
# ground visible around him without handing him the whole square.
START_LIGHT: Final = 168.0
LIGHT_CAP: Final = 392.0

#: Fraction of the radius that counts as "properly lit" for rules that ask
#: (the light-fearing monster).  The rim is dim, so it should not count.
LIT_FRACTION: Final = 0.82

# ── night pressure ───────────────────────────────────────────────────
WARN_SECONDS: Final = 1.05         # telegraph before a spawn arrives
SURGE_TELL_SECONDS: Final = 2.5    # advance warning before a surge
SPAWN_EDGE_INSET: Final = 26.0
DROP_PICKUP_RADIUS: Final = 24.0

#: Speed bonus applied as the night wears on: +SPEED_PER_WAVE every
#: WAVE_SECONDS.  Keeps late-night pressure rising without new monster types.
WAVE_SECONDS: Final = 12.0
SPEED_PER_WAVE: Final = 2.0

# ── combo ────────────────────────────────────────────────────────────
COMBO_WINDOW: Final = 2.5
#: Above this, kills drop one extra sugar.  Without a payout the counter is
#: decoration; the JS build shipped it as decoration and it read as a bug.
COMBO_BONUS_AT: Final = 5

# ── economy ──────────────────────────────────────────────────────────
#: Permanent upgrades get more expensive as they stack; consumables do not.
UPGRADE_PRICE_STEP: Final = 2

# ── seven-nights campaign ────────────────────────────────────────────
CAMPAIGN_NIGHTS: Final = 7

#: 難度。四段，調的是**壓力**，不是漢賽爾。
#:
#: 刻意不動玩家的移動速度。角色的手感是整款遊戲裡最不該隨難度改變的東西 ——
#: 一個從簡單升上一般的玩家，如果連走路都要重新學，那他學會的東西就沒有帶
#: 上去。所以四段共用同一個漢賽爾，變的是他面對的世界。
#:
#: 每一欄各自負責一種「難」：
#:   monster_speed —— 反應時間。撐不住的玩家缺的通常不是手速，是看到之後
#:                    還來不及做決定。
#:   spawn_gap     —— 同時要處理幾件事。這是最有效的一根槓桿。
#:   sister_bonus  —— 容錯額度。允許犯幾次錯才結束這一局。
#:   light         —— 資訊量。看得到就不算被偷襲。
#:   sugar         —— 只有困難有加成。簡單不該同時也比較好賺，否則它會變成
#:                    最划算的練功模式，而不是給打不過的人的一條路。
DIFFICULTIES: Final = (
    ("gentle", "超簡單", "給第一次拿起鍵盤的人",
     {"monster_speed": 0.70, "spawn_gap": 1.45, "sister_bonus": 4,
      "light": 1.30, "sugar": 1.00}),
    ("easy", "簡單", "想把七夜走完，但不想被逼",
     {"monster_speed": 0.85, "spawn_gap": 1.20, "sister_bonus": 2,
      "light": 1.15, "sugar": 1.00}),
    ("normal", "一般", "設計時預設的樣子",
     {"monster_speed": 1.00, "spawn_gap": 1.00, "sister_bonus": 0,
      "light": 1.00, "sugar": 1.00}),
    ("hard", "困難", "怪更快、來得更密、看得更少",
     {"monster_speed": 1.15, "spawn_gap": 0.85, "sister_bonus": -2,
      "light": 0.90, "sugar": 1.25}),
)

#: key -> 那一段的數值。
DIFFICULTY_TABLE: Final = {key: values for key, _n, _d, values in DIFFICULTIES}
DEFAULT_DIFFICULTY: Final = "normal"


def difficulty(key: str) -> dict:
    """回傳一段難度的數值；認不得的名字退回一般。"""
    return DIFFICULTY_TABLE.get(key, DIFFICULTY_TABLE[DEFAULT_DIFFICULTY])
SPELL_UNLOCK_NIGHT: Final = 3

#: The most sugar a given night will ever pay out, across every attempt at it.
#:
#: Measured, not guessed.  A perfect clear used to drop 30 / 76 / 99 / 95 /
#: 146 / 121 / 185 — 752 over the campaign against 228 to buy literally
#: everything in the shop, so a competent player had the whole upgrade tree by
#: night four and the last three nights had no economy at all.
#:
#: The leak was worse than that: a lost night is retried with the sugar from
#: the failed attempt still in the bank, so the reliable way to get rich was to
#: play badly on purpose.  Budgeting *per night* rather than per attempt closes
#: that — night five is worth a hundred sugar whether you clear it first time
#: or fifth — and it is the only version of this rule that a player who fails a
#: lot is not punished by.
#:
#: Totals 594 against 584 to max the tree, so a perfect run that never buys a
#: bandage finishes the seventh night having just barely bought everything.
NIGHT_SUGAR_BUDGET: Final = (0, 30, 58, 74, 86, 100, 114, 132)
FIRST_BOSS_NIGHT: Final = 2        # night 1 is the tutorial

# ── endless mode ─────────────────────────────────────────────────────
ENDLESS_MONSTER_CAP: Final = 60
ENDLESS_CHOICES: Final = 3

#: Kills between upgrade offers.
#:
#: Was 12, which measured as unreachable: base attack kills a villager in two
#: seconds while arrivals came every three, so the player fell behind before
#: banking a single offer — needing upgrades to get kills and kills to get
#: upgrades.  Six is inside the first minute even for a struggling player.
ENDLESS_CHOICE_EVERY: Final = 6

#: An offer also arrives on this timer regardless of kills, so a player who is
#: losing still gets the tool that might turn it around.  A difficulty spiral
#: with no way out is just a countdown.
ENDLESS_CHOICE_SECONDS: Final = 45.0

#: Endless has no day phase, so it hands the player the rough equivalent of the
#: four action points a campaign night opens with — otherwise it is the same
#: game played permanently under-equipped, which measured as death in under
#: thirty seconds.
ENDLESS_STARTING_KIT: Final = (("lantern", 1), ("shade", 1))

#: The two skills an endless run opens with, one per shelf.
#:
#: Endless has no day, and learning a skill is gated on the day phase —
#: so without this the mode shipped with two permanently dead keys and a
#: HUD that promised skill points the player could never spend.  Granting
#: them at the start is the honest fix: the campaign is where *choosing*
#: skills is the game, and endless is where surviving with them is.
ENDLESS_DEFAULT_SKILLS: Final = ("bolt", "windrun")

#: Seconds of grace before arrivals begin, so the first thing a player sees is
#: the field rather than a monster already on top of them.
ENDLESS_GRACE: Final = 5.0

#: Seconds between arrivals before difficulty scaling is applied.  The first
#: minute is slacker so the player can learn the field and bank an upgrade
#: before pressure means anything.  Both are divided by ``pressure(minutes)``.
#: Measured with ``tools/balance.py``: 3.2 gave an average run of 2.2 minutes,
#: 4.4 gave 2.3, and 5.6 gave 3.6.  Still short of the 6–10 minute target, and
#: the reason is worth recording — a run ends with roughly thirty monsters alive
#: at once, i.e. the player's kill rate plateaus (swing cooldown floors at 0.5 s
#: and attack caps at 6) while arrivals keep accelerating.  Closing that gap
#: needs a *capability* the player does not have yet — a wider arc, a
#: multi-target hit, something — which is content design, not a constant.
ENDLESS_OPENING_INTERVAL: Final = 7.0
ENDLESS_BASE_INTERVAL: Final = 5.6
ENDLESS_MIN_INTERVAL: Final = 0.45

#: Gretel's hearts in endless.
#:
#: Larger than the campaign's, and not because endless is meant to be easier.
#: In the campaign a leaked monster costs half a heart that can be bought back
#: at dawn, and a night is only fifty seconds long.  Endless has no dawn and no
#: shop, so the campaign's six half-hearts are a hard budget of six mistakes for
#: an entire run — measured, that ended the average run in about a minute.  One
#: defender cannot cover four edges converging on a fixed point indefinitely;
#: the mode's difficulty has to come from the rising curve, not from an
#: allowance that never refills.
ENDLESS_SISTER_HP: Final = 14
