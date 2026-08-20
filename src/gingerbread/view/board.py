"""The playfield renderer.

Read-only.  It observes a ``State`` and paints it; it never changes a score, a
position or an outcome.  If drawing could change a rule, the same run would
produce different results with the display switched off, and the headless check
would be worthless.

Two rules govern the whole file.

**An entity may allocate a surface proportional to its own size, never
proportional to the screen.**  A previous version allocated a full 900×520
surface *per villager* to draw one dashed line, which measured as 56% of the
entire day frame.  Every full-screen layer here is allocated once and reused.

**Presentation state is allowed; rule state is not.**  Footprints and drifting
embers live here because nothing in the rules can see them.  Anything the rules
read — where a light is, how far it reaches — comes from the model, so what the
player sees and what the game decides can never drift apart.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Final

import pygame

from ..model import Phase, State, lights_of
from ..model import constants as C
from ..model.content import BOSSES, MONSTERS
from ..model.content import SPELLS as SPELL_TABLE_VIEW
from . import figures as F
from . import palette as P
from .assets import AssetLibrary
from .fonts import FontBook
from .lighting import Darkness

#: Pre-blended so it can be passed as a 3-tuple.  ``pygame.draw.*`` silently
#: discards a 4th component on a surface without an alpha channel — measured,
#: no warning, no exception — which drew this ring at full brightness instead of
#: the intended dim grey.
_DASH_RING: Final = (93, 87, 85)

#: Which humanoid proportion each species is drawn with.  Everything is a
#: person; only the build differs.
_BUILD: Final = {"villager": "adult", "brute": "heavy", "child": "small"}


def _clamp_colour(colour, alpha: float | None = None):
    return F.clamp_colour(colour, alpha)


class Board:
    """Draws the world onto a fixed-size surface."""

    #: How many footprints to keep behind the player.
    TRACK_LIMIT: Final = 42

    def __init__(self, surface: pygame.Surface, book: FontBook,
                 assets: AssetLibrary) -> None:
        self.surface = surface
        self.book = book
        self.assets = assets
        self.darkness = Darkness(surface.get_size())

        # Reusable full-screen layers.  Cleared and redrawn, never reallocated.
        self._fx = pygame.Surface(surface.get_size(), pygame.SRCALPHA).convert_alpha()
        self._paths = pygame.Surface(surface.get_size(), pygame.SRCALPHA).convert_alpha()
        self._paths_key: tuple | None = None

        self._grounds: dict[str, pygame.Surface] = {}
        self._vignette = self._bake_vignette()
        #: Scratch for scaling the vignette without rebuilding it.
        self._surge = pygame.Surface(surface.get_size()).convert()

        # ── presentation-only state ──────────────────────────────────
        #: Where the player has walked, newest last.  Pure decoration, and the
        #: strongest movement feedback available in a dark scene: it turns "am I
        #: moving?" into something visible behind you, with no asset at all.
        self._tracks: deque[tuple[float, float, int]] = deque(maxlen=self.TRACK_LIMIT)
        self._last_track: tuple[float, float] | None = None
        #: Embers drifting up off the lantern, as [x, y, life].
        self._embers: list[list[float]] = []

    def warm_up(self) -> None:
        self.darkness.warm_up()

    # ── ground ───────────────────────────────────────────────────────
    def _ground(self, stage: str) -> pygame.Surface:
        """Return the floor for a stage: art if it exists, else drawn."""
        found = self._grounds.get(stage)
        if found is not None:
            return found

        art = self.assets.scaled(f"ground.{stage}", self.surface.get_size())
        if art is not None:
            self._grounds[stage] = art.convert()
            return art

        built = pygame.Surface(self.surface.get_size()).convert()
        built.fill(P.INK)
        cx, cy = int(C.SISTER_X), int(C.SISTER_Y)

        # A narrow pool of trodden snow around Gretel.  An earlier version
        # graded all the way out to 340 px, which the lantern then revealed as
        # one enormous soft grey disc — the ground read as fog rather than as a
        # place.  Ground should give the eye edges; let the light do the softness.
        for radius in range(150, 20, -5):
            t = 1 - (radius - 20) / 130
            pygame.draw.circle(built, P.mix(P.INK, P.PANEL, t * 0.5),
                               (cx, cy), radius)

        # Snow.  Deterministic scatter, bright enough to actually register under
        # a lamp — the previous pass was so subtle it was invisible, so moving
        # through the dark gave no sense of motion at all.
        for i in range(900):
            x = (i * 313 + (i * i) % 271) % C.WIDTH
            y = (i * 197 + (i * i * 3) % 331) % C.HEIGHT
            size = 1 + (i % 7 == 0)
            shade = P.mix(P.INK, P.BONE, 0.10 + (i % 4) * 0.045)
            pygame.draw.circle(built, shade, (x, y), size)

        # Drifts: a few long pale streaks so the eye has something to travel
        # along, rather than a field of even noise.
        for i in range(26):
            x = (i * 419) % C.WIDTH
            y = (i * 271) % C.HEIGHT
            length = 30 + (i % 5) * 22
            pygame.draw.line(built, P.mix(P.INK, P.BONE, 0.07),
                             (x, y), (x + length, y + (i % 3) - 1), 2)

        # An engraved treeline, so the edges read as somewhere rather than as a
        # boundary.  Outlined, or it vanishes into the dark it is drawn on.
        for i in range(46):
            x = (i * 137.5) % C.WIDTH
            edge = x < 92 or x > C.WIDTH - 92
            y = (i * 61) % C.HEIGHT if edge else (-8 if i % 2 else C.HEIGHT + 8)
            h = 54 + (i % 5) * 24
            shape = [(x, y - h / 2), (x - 19, y + h / 2), (x + 19, y + h / 2)]
            pygame.draw.polygon(built, P.VOID, shape)
            pygame.draw.polygon(built, P.mix(P.VOID, P.PANEL, 0.55), shape, 2)

        self._grounds[stage] = built
        return built

    def _bake_vignette(self) -> pygame.Surface:
        """A red edge for surges, carrying its strength in its own colour.

        **Premultiplied and additive, never ``set_alpha``.**  This layer used to
        be a per-pixel-alpha surface faded with ``set_alpha(int(255 * k))``, and
        at full strength that argument is 255 — at which point pygame stops
        blending and copies the surface wholesale.  The band arrived as flat
        opaque red and the transparent middle arrived as **solid black**: for
        about a second every surge, the entire playfield went black inside a red
        rectangle.  It survived a headless check because the dummy video driver
        blends it correctly; only a real display shows it.

        So the alpha lives in the RGB values instead, exactly as the lantern
        glows in ``lighting.py`` do, and the layer is added rather than blended.
        Black adds nothing, so the middle of the screen cannot be touched by
        this layer no matter what goes wrong with it.
        """
        layer = pygame.Surface(self.surface.get_size())
        layer.fill((0, 0, 0))
        for i in range(64):
            level = (1 - i / 64) ** 1.6 * (72 / 255)
            pygame.draw.rect(layer, (int(P.BLOOD[0] * level),
                                     int(P.BLOOD[1] * level),
                                     int(P.BLOOD[2] * level)),
                             pygame.Rect(i, i, C.WIDTH - 2 * i, C.HEIGHT - 2 * i), 1)
        return layer.convert()

    # ── entry point ──────────────────────────────────────────────────
    def draw(self, state: State, ticks: int) -> None:
        shake_x, shake_y = self._shake(state, ticks)
        self.surface.blit(self._ground(state.stage), (shake_x, shake_y))

        self._remember_track(state, ticks)
        self._draw_tracks(ticks)
        self._draw_obstacles(state)

        if state.phase is Phase.DAY:
            self._draw_paths(state)
            self._draw_sleepers(state)

        self._draw_puddles(state, ticks)
        self._draw_drops(state, ticks)
        self._draw_hazards(state, ticks)
        self._draw_sister(state, ticks)
        self._draw_monsters(state, ticks)
        self._draw_projectiles(state)
        self._draw_player(state, ticks)
        self._draw_effects(state)

        if state.dark:
            self.darkness.draw(self.surface, lights_of(state), state.dusk, ticks)
            self._draw_warnings(state, ticks)

        if state.feedback.surge_flash > 0:
            self._draw_surge(state)
        if state.feedback.hurt_flash > 0:
            self._draw_hurt(state)

    def _shake(self, state: State, ticks: int) -> tuple[int, int]:
        """Return this frame's screen offset.

        Read from ``state.feedback``, which the rules decay every tick without
        exception.  In the web prototype the decay sat inside the hit-stop
        branch, so once a freeze ended the shake never decayed again and the
        screen juddered for the rest of the night.
        """
        magnitude = state.feedback.shake
        if magnitude <= 0:
            return (0, 0)
        return (int(math.sin(ticks * 1.7) * magnitude),
                int(math.cos(ticks * 2.3) * magnitude))

    # ── footprints ───────────────────────────────────────────────────
    def _remember_track(self, state: State, ticks: int) -> None:
        if state.phase is not Phase.NIGHT:
            self._tracks.clear()
            self._last_track = None
            return
        p = state.player
        if self._last_track is None:
            self._last_track = (p.x, p.y)
            return
        if math.hypot(p.x - self._last_track[0], p.y - self._last_track[1]) < 15:
            return
        self._last_track = (p.x, p.y)
        self._tracks.append((p.x, p.y, ticks))

    def _draw_tracks(self, ticks: int) -> None:
        if not self._tracks:
            return
        self._fx.fill((0, 0, 0, 0))
        drawn = False
        for x, y, born in self._tracks:
            fade = 1.0 - (ticks - born) / 220.0
            if fade <= 0:
                continue
            F.footprint(self._fx, x, y, fade)
            drawn = True
        if drawn:
            self.surface.blit(self._fx, (0, 0))

    # ── pieces ───────────────────────────────────────────────────────
    def _draw_obstacles(self, state: State) -> None:
        for block in state.obstacles:
            pos = (int(block.x), int(block.y))
            pygame.draw.circle(self.surface, (14, 12, 22), pos, int(block.radius))
            pygame.draw.circle(self.surface, P.mix(P.INK, P.PANEL_HI, 0.5),
                               pos, int(block.radius), 3)
            pygame.draw.circle(self.surface, F.OUTLINE, pos, int(block.radius), 1)
            if block.life <= 0:
                continue
            # A dropped rock is temporary and has to say so, or the player plans
            # a route around scenery that is about to stop existing.  The rim
            # burns down like a fuse: full circle when fresh, gone as it goes.
            span = max(0.05, min(1.0, block.life / C.ROCK_LIFE))
            pygame.draw.arc(self.surface, P.EMBER_DARK,
                            pygame.Rect(pos[0] - int(block.radius) - 3,
                                        pos[1] - int(block.radius) - 3,
                                        int(block.radius) * 2 + 6,
                                        int(block.radius) * 2 + 6),
                            math.pi / 2, math.pi / 2 + math.tau * span, 2)

    def _draw_paths(self, state: State) -> None:
        """Show where each sleeper will walk when it turns.

        Rebuilt only when the cast changes.  Nobody moves during the day, so
        redrawing this every frame was pure waste — and it was the single most
        expensive thing in the day frame.
        """
        key = tuple(state.sleepers)
        if key != self._paths_key:
            self._paths_key = key
            self._paths.fill((0, 0, 0, 0))
            for _spec, x, y, _wake in state.sleepers:
                self._dash_into(self._paths, (x, y), (C.SISTER_X, C.SISTER_Y),
                                _clamp_colour(P.BLOOD, 88))
        self.surface.blit(self._paths, (0, 0))

    @staticmethod
    def _dash_into(layer, a, b, colour) -> None:
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy) or 1.0
        steps = max(1, int(length / 13))
        for i in range(0, steps, 2):
            t0, t1 = i / steps, (i + 0.62) / steps
            pygame.draw.line(layer, colour,
                             (a[0] + dx * t0, a[1] + dy * t0),
                             (a[0] + dx * t1, a[1] + dy * t1), 1)

    def _person(self, key: str, x: float, y: float, radius: float,
                colour, *, moving: bool, squash: float = 0.0,
                facing=(0.0, 1.0), build: str | None = None,
                hair=None, skirt: bool = False, ticks: int = 0,
                speed: float = 0.0,
                lamp: tuple[float, float] | None = None) -> None:
        """Draw a figure: sprite if the art exists, else the drawn humanoid."""
        # Scaled to the radius the *rules* use, never blitted at native size.
        # Art arrives at whatever resolution it was drawn at — the four that
        # landed first are 600 px tall for a monster the rules give a radius of
        # eleven — so a raw blit puts a sprite sixty times too big on the field.
        span = max(8, int(radius * 3.4))
        art = self.assets.fitted(f"monster.{key}", span) if key else None
        F.shadow(self.surface, x, y, radius)
        if art is not None:
            # Lifted so the feet sit on the shadow rather than the waist.
            self.surface.blit(art, art.get_rect(
                midbottom=(int(x), int(y + radius * 0.9))))
            return
        rim = None
        if lamp is not None:
            rim = (lamp[0] - x, lamp[1] - y)
        F.humanoid(self.surface, x, y, radius, colour,
                   build=build or "adult",
                   phase=F.walk_phase(ticks, speed, x, y), moving=moving,
                   squash=squash, facing=facing, hair=hair,
                   skirt=skirt, rim_from=rim)

    @staticmethod
    def _lamp(state: State) -> tuple[float, float]:
        """Where the light is coming from, for rim lighting."""
        return (state.player.x, state.player.y)

    def _draw_sleepers(self, state: State) -> None:
        for key, x, y, _wake in state.sleepers:
            spec = MONSTERS.get(key)
            if spec is None:
                continue
            self._person(key, x, y, spec.radius, P.DAYTIME_FOLK,
                         moving=False, build=_BUILD.get(spec.silhouette),
                         facing=(0.0, 1.0), lamp=self._lamp(state))
            label = self.book.render(spec.name, "small", P.DAYTIME_FOLK)
            self.surface.blit(label, label.get_rect(
                center=(int(x), int(y + spec.radius + 22))))

    def _draw_monsters(self, state: State, ticks: int) -> None:
        for monster in state.monsters:
            spec = MONSTERS.get(monster.spec)
            if spec is None:
                continue
            if monster.wake > 0:
                self._person(monster.spec, monster.x, monster.y, spec.radius,
                             P.ASLEEP, moving=False,
                             build=_BUILD.get(spec.silhouette),
                             ticks=ticks, speed=monster.speed,
                             lamp=self._lamp(state))
                continue

            # Fully faded means *not drawn*.  ``faded`` was computed every tick
            # by the trait and read by nobody, so the one monster whose entire
            # identity is being unseen was rendered at full opacity.  Its
            # footprints are effects, so they keep showing after this skips it.
            if monster.faded >= 0.999:
                continue

            colour = P.BONE if monster.hit_flash > 0 else spec.colour
            if monster.frozen:
                colour = P.mix(spec.colour, P.MOON, 0.55)
            elif monster.faded > 0:
                colour = P.mix(colour, P.INK, monster.faded)

            # They are walking toward Gretel, so that is where they look.
            fx = C.SISTER_X - monster.x
            fy = C.SISTER_Y - monster.y
            length = math.hypot(fx, fy) or 1.0

            self._person(monster.spec, monster.x, monster.y, spec.radius,
                         colour, moving=monster.active,
                         squash=min(1.0, monster.hit_flash / 0.12),
                         facing=(fx / length, fy / length),
                         build=_BUILD.get(spec.silhouette),
                         ticks=ticks, speed=monster.speed,
                         lamp=self._lamp(state))

            if monster.elite:
                pygame.draw.circle(self.surface, P.EMBER,
                                   (int(monster.x), int(monster.y)),
                                   int(spec.radius + 8), 2)
            if monster.hp < spec.hp:
                self._hp_pip(monster.x, monster.y, spec.radius,
                             monster.hp / spec.hp)

        for boss in state.bosses:
            spec = BOSSES.get(boss.spec)
            if spec is None:
                continue
            colour = P.BONE if boss.hit_flash > 0 else spec.colour
            fx = C.SISTER_X - boss.x
            fy = C.SISTER_Y - boss.y
            length = math.hypot(fx, fy) or 1.0
            self._person(boss.spec, boss.x, boss.y, spec.radius, colour,
                         moving=boss.active,
                         squash=min(1.0, boss.hit_flash / 0.12),
                         facing=(fx / length, fy / length), build="tall",
                         ticks=ticks, speed=boss.speed,
                         lamp=self._lamp(state))
            pygame.draw.circle(self.surface, P.BOSS,
                               (int(boss.x), int(boss.y)),
                               int(spec.radius + 10), 2)
            self._seal(boss, spec, ticks)
            if boss.stunned > 0:
                # 頭上轉圈圈。被暈住的王站著不動，沒有這個的話畫面上它跟
                # 「正在瞄準」長得一模一樣，玩家不知道現在是不是他的機會。
                for i in range(3):
                    a = ticks / 7.0 + i * math.tau / 3
                    pygame.draw.circle(
                        self.surface, P.SUGAR_BRIGHT,
                        (int(boss.x + math.cos(a) * 15),
                         int(boss.y - spec.radius - 16
                             + math.sin(a) * 5)), 3)
            self._hp_pip(boss.x, boss.y, spec.radius,
                         boss.hp / max(1, boss.max_hp), width=72)

    def _seal(self, boss, spec, ticks: int) -> None:
        """Show whether a gated boss can currently be hurt.

        The ash hob takes nothing at all until water has been thrown on it.
        That is a fine rule and an unplayable one if the only way to learn it is
        to swing eight times and watch the health bar not move — so the state
        has to be on the boss, not in the manual: a shivering ring of embers
        while it is sealed, and a clean blue ring for the three seconds it is
        open.
        """
        if "needs_soak" not in getattr(spec, "traits", ()):
            return
        pos = (int(boss.x), int(boss.y))
        if boss.memory.get("exposed", 0.0) > 0:
            pygame.draw.circle(self.surface, (150, 205, 255), pos,
                               int(spec.radius + 15), 3)
            return
        # Sealed: a ragged, flickering shell that reads as "not now".
        for i in range(8):
            a = ticks / 9.0 + i * math.tau / 8
            wob = 1.0 + math.sin(ticks / 4.0 + i) * 0.10
            r = (spec.radius + 14) * wob
            pygame.draw.circle(
                self.surface, P.EMBER,
                (int(boss.x + math.cos(a) * r), int(boss.y + math.sin(a) * r)),
                2)

    def _hp_pip(self, x: float, y: float, radius: float, fraction: float,
                width: int | None = None) -> None:
        span = width if width is not None else int(radius * 2.2)
        left = int(x - span / 2)
        top = int(y - radius * 2.1)
        pygame.draw.rect(self.surface, F.OUTLINE,
                         pygame.Rect(left - 1, top - 1, span + 2, 5))
        filled = max(0, int(span * max(0.0, min(1.0, fraction))))
        if filled:
            pygame.draw.rect(self.surface, P.BONE,
                             pygame.Rect(left, top, filled, 3))

    def _draw_drops(self, state: State, ticks: int) -> None:
        for drop in state.drops:
            if drop.heal > 0:
                # A heart, and unmistakably not sugar: this is the one pickup
                # worth crossing the field for, and it must never be mistaken
                # for the crystals the player is already sweeping up in passing.
                bob = math.sin(ticks / 12.0 + drop.x) * 2.0
                cx, cy = int(drop.x), int(drop.y + bob)
                F.shadow(self.surface, drop.x, drop.y + 6, 7)
                for dx in (-3, 3):
                    pygame.draw.circle(self.surface, P.BLOOD, (cx + dx, cy - 2), 4)
                pygame.draw.polygon(self.surface, P.BLOOD, [
                    (cx - 6, cy - 1), (cx + 6, cy - 1), (cx, cy + 7)])
                pygame.draw.circle(self.surface, P.BONE, (cx - 3, cy - 4), 1)
                continue
            twinkle = math.sin(ticks / 11.0 + drop.x * 0.3) * 0.5 + 0.5
            colour = P.BLOOD if drop.fake else P.SUGAR_BRIGHT
            F.crystal(self.surface, drop.x, drop.y, 5.0, colour, twinkle)

    #: Ground colour per puddle kind.  Mud slows, syrup slows harder, fire burns.
    _GROUND = {"mud": (74, 58, 38), "syrup": (108, 70, 34), "fire": (176, 70, 34)}

    def _draw_puddles(self, state: State, ticks: int) -> None:
        """Draw what has been left on the ground.

        This layer did not exist.  The rules have always slowed anything
        standing in mud, and the mudling has always laid a trail of it — but
        nothing drew a single pixel of it, so the player walked into an
        invisible tar pit and concluded the controls had gone wrong.  A rule the
        player cannot see is not a mechanic, it is a fault.
        """
        if not state.puddles:
            return
        self._fx.fill((0, 0, 0, 0))
        for pool in state.puddles:
            base = self._GROUND.get(pool.kind, self._GROUND["mud"])
            # A finite pool dries out; fading it makes the edge of its
            # usefulness visible rather than something discovered by dying.
            left = 1.0 if pool.life < 0 else max(0.15, min(1.0, pool.life / 6.0))
            radius = max(3, int(pool.radius))
            pygame.draw.circle(self._fx, _clamp_colour(base, 150 * left),
                               (int(pool.x), int(pool.y)), radius)
            pygame.draw.circle(self._fx, _clamp_colour(base, 215 * left),
                               (int(pool.x), int(pool.y)), radius, 2)
            if pool.kind == "fire":
                flare = 0.5 + math.sin(ticks / 5.0 + pool.x) * 0.5
                pygame.draw.circle(
                    self._fx, _clamp_colour(P.EMBER, 130 * flare * left),
                    (int(pool.x), int(pool.y)), max(2, int(radius * 0.45)))
        self.surface.blit(self._fx, (0, 0))

    def _meteor(self, hazard, pos, radius: int, ticks: int) -> None:
        """The circle a rock is about to land in, and the rock coming down.

        Everything here is read off ``hazard.life``, which is the same number
        the rules use to decide when it lands — so the ring can never close
        early or late.  A telegraph the player cannot trust is worse than none:
        they stop reading it and start guessing.
        """
        # Ground ring, filling in as the moment approaches.
        share = max(0.0, min(1.0, 1.0 - hazard.life / 1.15))
        self._fx.fill((0, 0, 0, 0))
        pygame.draw.circle(self._fx, _clamp_colour(P.ARCANE_BRIGHT, 55),
                           pos, radius)
        pygame.draw.circle(self._fx, _clamp_colour(P.ARCANE_BRIGHT, 210),
                           pos, radius, 2)
        inner = max(2, int(radius * share))
        pygame.draw.circle(self._fx, _clamp_colour(P.EMBER, 120), pos, inner)
        self.surface.blit(self._fx, (0, 0))

        # The rock itself, falling from off the top of the screen into the
        # centre of the ring.  Without it the ring is a mystery rather than a
        # warning — the player has to be able to see the cause coming.
        drop = pos[1] - int((1.0 - share) * 260)
        size = max(3, int(6 + 7 * share))
        pygame.draw.circle(self.surface, P.EMBER_CORE, (pos[0], drop), size + 2)
        pygame.draw.circle(self.surface, (240, 226, 255), (pos[0], drop), size)

    def _draw_hazards(self, state: State, ticks: int) -> None:
        """The twister and the water trap.

        Both are read straight off the model's circle, so what the player aims
        at is what the rules test.  Nothing here invents a size.
        """
        for hazard in state.hazards:
            pos = (int(hazard.x), int(hazard.y))
            radius = int(hazard.radius)
            if hazard.kind == "meteor":
                self._meteor(hazard, pos, radius, ticks)
                continue
            if hazard.kind == "wave":
                # 半徑讀 hazard.reach —— 那是規則這一幀真正清掉東西的範圍。
                # 自己算一份的話，畫出來的圈遲早會跟判定對不上，而一個看起來
                # 已經掃過你卻沒作用的水波，比沒有水波更糟。
                span = max(2, int(hazard.reach))
                self._fx.fill((0, 0, 0, 0))
                fade = max(0.0, min(1.0, hazard.life / max(0.01,
                                                           hazard.hold_life)))
                for i in range(3):
                    pygame.draw.circle(
                        self._fx,
                        _clamp_colour((150, 205, 255), (210 - i * 55) * fade),
                        pos, max(1, span - i * 4), 2)
                pygame.draw.circle(self._fx,
                                   _clamp_colour((110, 168, 232), 46 * fade),
                                   pos, span)
                self.surface.blit(self._fx, (0, 0))
                continue
            if hazard.kind == "twister":
                # A stack of offset ellipses, each turning faster than the one
                # below it: the shear is what reads as a funnel rather than as
                # a spinning disc.
                for i in range(5):
                    t = i / 4.0
                    spin = ticks / (4.0 - t * 2.0) + i
                    wide = int(radius * (0.45 + t * 0.75))
                    tall = max(3, int(wide * 0.34))
                    off_x = int(math.cos(spin) * radius * 0.16)
                    lift = int(-t * radius * 0.55)
                    rect = pygame.Rect(pos[0] + off_x - wide,
                                       pos[1] + lift - tall, wide * 2, tall * 2)
                    pygame.draw.ellipse(
                        self.surface,
                        _clamp_colour(P.mix(P.MOON, P.ARCANE_BRIGHT, t))[:3],
                        rect, 2)
            else:
                swell = 1.0 + math.sin(ticks / 14.0) * 0.06
                held = hazard.sprung or hazard.charges == 0
                skin = P.SUGAR_BRIGHT if held else (110, 168, 232)
                self._fx.fill((0, 0, 0, 0))
                pygame.draw.circle(self._fx, _clamp_colour(skin, 46), pos,
                                   int(radius * swell))
                self.surface.blit(self._fx, (0, 0))
                pygame.draw.circle(self.surface, skin, pos,
                                   int(radius * swell), 2)
                # One highlight, up and to the left, so it reads as a bubble
                # with a surface rather than as a flat ring on the floor.
                pygame.draw.circle(self.surface, P.SUGAR_BRIGHT,
                                   (pos[0] - radius // 3, pos[1] - radius // 3),
                                   max(2, radius // 6), 1)

    def _ward(self, state: State, ticks: int) -> None:
        """聖癒's shield, as a dome the player can see is still up.

        Drawn thinning as it runs out, because the decision it drives is "do I
        have time to get back" — and that question needs a countdown, not an
        on/off light.
        """
        if state.ward <= 0:
            return
        left = min(1.0, state.ward / 8.0)
        radius = int(34 + 4 * math.sin(ticks / 9.0))
        self._fx.fill((0, 0, 0, 0))
        pygame.draw.circle(self._fx, _clamp_colour((196, 224, 255), 40 * left),
                           (int(C.SISTER_X), int(C.SISTER_Y)), radius)
        for i in range(3):
            pygame.draw.circle(
                self._fx, _clamp_colour((214, 238, 255), (150 - i * 40) * left),
                (int(C.SISTER_X), int(C.SISTER_Y)), radius - i * 3, 1)
        # Sparks running round the rim, so it reads as held rather than painted.
        for i in range(7):
            a = ticks / 15.0 + i * math.tau / 7
            pygame.draw.circle(
                self._fx, _clamp_colour(P.MOON, 220 * left),
                (int(C.SISTER_X + math.cos(a) * radius),
                 int(C.SISTER_Y + math.sin(a) * radius)), 2)
        self.surface.blit(self._fx, (0, 0))

    def _draw_sister(self, state: State, ticks: int) -> None:
        bob = math.sin(ticks / 37.0) * 1.2
        x, y = C.SISTER_X, C.SISTER_Y + bob
        # Scaled to her radius rather than blitted at whatever size the file
        # happens to be.  ``image`` put a 720 px drawing on a 13 px girl.
        art = self.assets.fitted("char.gretel", 44)
        if art is not None:
            F.shadow(self.surface, x, y, 14)
            self.surface.blit(art, art.get_rect(midbottom=(int(x), int(y + 13))))
        else:
            F.shadow(self.surface, x, y, 13)
            # She is the only pale figure on the field and the only one with
            # hair drawn in — the player must never lose track of what he is
            # standing between.
            F.humanoid(self.surface, x, y, 13, (240, 232, 212),
                       build="small", phase=0.0, moving=False,
                       facing=(0.0, 1.0), hair=(196, 142, 68), skirt=True,
                       rim_from=(state.player.x - x, state.player.y - y))

        self._ward(state, ticks)

        hearts = state.meta.max_sister_hp // 2
        for i in range(hearts):
            hx = int(x - (hearts - 1) * 7 + i * 14)
            hy = int(y - 40)
            remaining = state.meta.sister_hp - i * 2
            colour = (P.BLOOD if remaining >= 2
                      else P.mix(P.BLOOD, P.BLOOD_DARK, 0.5) if remaining == 1
                      else P.BLOOD_DARK)
            self._heart(hx, hy, 5, colour)

    @staticmethod
    def _heart_points(x: float, y: float, size: float):
        return [(x, y + size),
                (x - size, y - size * 0.25),
                (x - size * 0.5, y - size),
                (x, y - size * 0.35),
                (x + size * 0.5, y - size),
                (x + size, y - size * 0.25)]

    def _heart(self, x: float, y: float, size: float, colour) -> None:
        """A heart, not a dot.  The shape carries the meaning at a glance."""
        points = self._heart_points(x, y, size)
        pygame.draw.polygon(self.surface, F.OUTLINE,
                            self._heart_points(x, y, size + 1.4))
        pygame.draw.polygon(self.surface, _clamp_colour(colour), points)

    def _draw_projectiles(self, state: State) -> None:
        """The shot, plus the line it is travelling along.

        A dot crossing a dark field is almost impossible to read: by the time
        the player has seen it and worked out where it is heading, it has
        arrived.  Drawing the line *ahead* of it — where it will be, not where
        it has been — turns "something hit me" into "that one is going to hit
        me unless I move", which is the only version a player can answer.

        The line is computed from the shot's own velocity, so it cannot promise
        a path the projectile will not take.
        """
        for shot in state.projectiles:
            pos = (int(shot.x), int(shot.y))
            speed = math.hypot(shot.vx, shot.vy)
            if speed > 1.0:
                ahead = 190.0 / speed
                tip = (int(shot.x + shot.vx * ahead),
                       int(shot.y + shot.vy * ahead))
                back = (int(shot.x - shot.vx * 0.09),
                        int(shot.y - shot.vy * 0.09))
                self._fx.fill((0, 0, 0, 0))
                # Faint forward, brighter behind: the bright end is the arrow,
                # the faint end is the warning.
                pygame.draw.line(self._fx, _clamp_colour(P.BLOOD, 70), pos, tip,
                                 max(1, 2))
                pygame.draw.line(self._fx, _clamp_colour(P.EMBER, 170), back, pos,
                                 max(1, 3))
                self.surface.blit(self._fx, (0, 0))
            if shot.kind == "fireball":
                # A lump of flame with a shimmering corona, so it is never
                # mistaken for the archer's arrow — they are answered
                # differently and must not look alike.
                flare = 0.5 + math.sin(shot.life * 11.0) * 0.5
                pygame.draw.circle(self.surface, P.EMBER_CORE, pos,
                                   int(shot.radius + 3 + flare * 2))
                pygame.draw.circle(self.surface, (255, 226, 150), pos,
                                   max(2, int(shot.radius - 1)))
                continue
            pygame.draw.circle(self.surface, F.OUTLINE, pos,
                               int(shot.radius) + 2)
            pygame.draw.circle(self.surface, P.EMBER_CORE, pos, int(shot.radius))

    def _draw_player(self, state: State, ticks: int) -> None:
        from ..model import derive

        p = state.player
        stats = derive(state)

        if p.swing_anim > 0:
            self._draw_swing(p, stats, ticks)

        if p.downed > 0:
            F.shadow(self.surface, p.x, p.y, 15)
            pygame.draw.circle(self.surface, F.OUTLINE, (int(p.x), int(p.y)), 16)
            pygame.draw.circle(self.surface, P.BLOOD_DARK, (int(p.x), int(p.y)), 14)
            pygame.draw.circle(self.surface, P.BLOOD, (int(p.x), int(p.y)), 14, 2)
            return

        if p.aura > 0:
            # 雷鳴 — a crackling ring that shrinks as the five seconds run out,
            # so the player can see how long they may keep being reckless.
            span = int(50 * (0.55 + 0.45 * min(1.0, p.aura / 5.0)))
            for i in range(3):
                a = ticks / 6.0 + i * math.tau / 3
                pygame.draw.circle(
                    self.surface, P.ARCANE_BRIGHT,
                    (int(p.x + math.cos(a) * span * 0.5),
                     int(p.y + math.sin(a) * span * 0.5)), max(2, 3))
            pygame.draw.circle(self.surface, P.ARCANE, (int(p.x), int(p.y)),
                               span, 1)
        if p.haste > 0:
            for i in range(4):
                trail = 6 + i * 7
                pygame.draw.circle(
                    self.surface, _clamp_colour((178, 232, 218), 150 - i * 32)[:3],
                    (int(p.x - p.face_x * trail), int(p.y - p.face_y * trail)),
                    max(1, 5 - i))
        if p.holy > 0 or p.mending > 0:
            spec = SPELL_TABLE_VIEW.get("holy")
            radius = int(spec.params.get("radius", 80.0)) if spec else 80
            pygame.draw.circle(self.surface, (250, 232, 168),
                               (int(p.x), int(p.y)), radius, 1)
        if p.charging:
            # The charge, drawn as it grows.  Releasing early is allowed, so the
            # player has to be able to see what they would be releasing.
            grow = min(1.0, p.charge_time / C.CHARGE_MAX)
            pygame.draw.circle(self.surface, P.ARCANE_BRIGHT, (int(p.x), int(p.y)),
                               int(26 + 24 * grow), 2)
            pygame.draw.arc(self.surface, P.EMBER,
                            pygame.Rect(int(p.x) - 34, int(p.y) - 34, 68, 68),
                            0.0, math.tau * grow, 3)

        if p.guarding:
            # A ring around him, breathing.  It reads as a *state* rather than
            # as a swing, which is the whole difference between this key and J —
            # and unlike the arc it used to draw, it never suggests that
            # anything is being pushed anywhere.
            grow = min(1.0, p.guard / C.GUARD_FADE)
            radius = int(20 + 4 * grow + math.sin(ticks / 7.0) * 1.6)
            self._fx.fill((0, 0, 0, 0))
            pygame.draw.circle(self._fx, _clamp_colour(P.MOON, 44 * grow),
                               (int(p.x), int(p.y)), radius)
            self.surface.blit(self._fx, (0, 0))
            pygame.draw.circle(self.surface, P.MOON, (int(p.x), int(p.y)),
                               radius, 2)

        art = self.assets.fitted("char.hansel", 46)
        blink = p.invulnerable > 0 and (ticks // 5) % 2
        coat = (74, 88, 126)          # cold blue: nothing hunting her is cold
        body = P.mix(coat, P.PANEL, 0.55) if blink else coat
        if p.stun > 0:
            body = (232, 144, 138)

        moving = abs(p.knock_x) + abs(p.knock_y) > 2 or p.dash > 0 or True
        F.shadow(self.surface, p.x, p.y, C.PLAYER_RADIUS, lift=p.dash * 30)

        if art is not None:
            # Feet on the shadow, like every monster sprite — a sprite centred
            # on the rules' point stands with its waist on the ground.
            self.surface.blit(art, art.get_rect(
                midbottom=(int(p.x), int(p.y + C.PLAYER_RADIUS))))
        else:
            # Hansel wears cold colours; everything hunting Gretel is warm-red.
            # Two seconds into the first night the player can already tell which
            # shape is his without reading anything.
            F.humanoid(self.surface, p.x, p.y, C.PLAYER_RADIUS, body,
                       build="tall",
                       phase=F.walk_phase(ticks, stats.move_speed, p.x, p.y),
                       moving=True, squash=0.0,
                       facing=(p.face_x, p.face_y), hair=(96, 74, 52),
                       rim_from=(p.face_x, p.face_y))

        self._draw_lantern(state, p, stats, ticks)

        if p.dash_cooldown > 0:
            fraction = 1 - p.dash_cooldown / C.DASH_COOLDOWN
            pygame.draw.arc(self.surface, _DASH_RING,
                            pygame.Rect(p.x - 22, p.y - 22, 44, 44),
                            -math.pi / 2, -math.pi / 2 + math.tau * fraction, 2)

    def _draw_lantern(self, state, p, stats, ticks: int) -> None:
        """The lantern itself, plus the embers coming off it.

        Held out along the facing direction, so the player can see which way he
        will swing before he swings — with movement-derived facing that is the
        only cue he gets.
        """
        lx = p.x + p.face_x * 17
        ly = p.y + p.face_y * 17
        ready = p.swing_cooldown <= 0

        core = P.EMBER if ready else P.EMBER_DARK
        if p.doused > 0:
            core = P.mix(P.EMBER_DARK, P.VOID, 0.6)

        pygame.draw.line(self.surface, F.OUTLINE,
                         (int(p.x), int(p.y - 4)), (int(lx), int(ly)), 4)
        pygame.draw.circle(self.surface, F.OUTLINE, (int(lx), int(ly)), 7)
        flicker = 1.0 + math.sin(ticks / 6.0) * 0.12
        pygame.draw.circle(self.surface, _clamp_colour(core),
                           (int(lx), int(ly)), max(2, int(5 * flicker)))
        if ready and p.doused <= 0:
            pygame.draw.circle(self.surface, P.EMBER_CORE,
                               (int(lx), int(ly)), 2)

        # Embers.  Purely decorative, so they live in the renderer; they are the
        # only thing on screen that moves when the player does not, which stops
        # a held position from looking like a frozen frame.
        if state.phase is Phase.NIGHT and p.doused <= 0 and ticks % 7 == 0:
            self._embers.append([lx, ly, 1.0])
        alive = []
        for ember in self._embers:
            ember[1] -= 0.7
            ember[0] += math.sin(ember[2] * 9.0) * 0.5
            ember[2] -= 0.02
            if ember[2] > 0:
                alive.append(ember)
                pygame.draw.circle(
                    self.surface,
                    _clamp_colour(P.mix(P.EMBER, P.BLOOD_DARK, 1 - ember[2])),
                    (int(ember[0]), int(ember[1])),
                    1 + (ember[2] > 0.6))
        self._embers = alive[-40:]

    def _draw_swing(self, p, stats, ticks: int) -> None:
        """The lantern arc: a bright leading edge with a fading wake."""
        k = p.swing_anim / C.SWING_ANIM
        facing = math.atan2(p.face_y, p.face_x)
        self._fx.fill((0, 0, 0, 0))

        points = [(p.x, p.y)]
        for i in range(17):
            a = facing - C.SWING_ARC + (2 * C.SWING_ARC) * i / 16
            points.append((p.x + math.cos(a) * stats.swing_range,
                           p.y + math.sin(a) * stats.swing_range))
        if len(points) >= 3:
            pygame.draw.polygon(self._fx, _clamp_colour(P.EMBER, 70 * k), points)

        # A hard bright rim on the outside of the sweep reads as the swing's
        # edge; a filled wedge alone reads as a glow and gives no sense of reach.
        rim = [(p.x + math.cos(facing - C.SWING_ARC + (2 * C.SWING_ARC) * i / 16)
                * stats.swing_range,
                p.y + math.sin(facing - C.SWING_ARC + (2 * C.SWING_ARC) * i / 16)
                * stats.swing_range) for i in range(17)]
        if len(rim) >= 2:
            pygame.draw.lines(self._fx, _clamp_colour(P.EMBER_CORE, 210 * k),
                              False, rim, 3)
        self.surface.blit(self._fx, (0, 0))

    def _draw_warnings(self, state: State, ticks: int) -> None:
        """Telegraphs pierce the darkness on purpose: readable beats surprising."""
        pulse = 0.45 + math.sin(ticks / 5.0) * 0.35
        for warn in state.warnings:
            alpha = int(255 * pulse)
            colour = _clamp_colour(P.EMBER if warn.surge else P.BLOOD, alpha)[:3]
            centre = (int(warn.x), int(warn.y))
            grow = 21 + (C.WARN_SECONDS - warn.left) * 16
            pygame.draw.circle(self.surface, colour, centre, 21, 3)
            pygame.draw.circle(self.surface, colour, centre, max(1, int(grow)), 1)
            # An arrow toward Gretel: the warning says *where from*, and this
            # says *toward what*, which is what the player actually needs.
            # Drawn clear of the ring.  Overlapping it turned the telegraph into
            # something that read as a "no entry" sign rather than as "coming
            # from here, heading that way".
            angle = math.atan2(C.SISTER_Y - warn.y, C.SISTER_X - warn.x)
            base_x = warn.x + math.cos(angle) * 27
            base_y = warn.y + math.sin(angle) * 27
            tip = (base_x + math.cos(angle) * 16, base_y + math.sin(angle) * 16)
            left = (base_x + math.cos(angle + 2.4) * 9,
                    base_y + math.sin(angle + 2.4) * 9)
            right = (base_x + math.cos(angle - 2.4) * 9,
                     base_y + math.sin(angle - 2.4) * 9)
            pygame.draw.polygon(self.surface, colour, [tip, left, right])

    def _draw_effects(self, state: State) -> None:
        for effect in state.effects:
            k = effect.left / effect.life if effect.life else 0.0
            centre = (int(effect.x), int(effect.y))
            if effect.kind == "burst":
                # Death: a ring plus shards flying out, so a kill reads as an
                # event rather than as something quietly ceasing to be drawn.
                pygame.draw.circle(self.surface, P.EMBER, centre,
                                   max(1, int(30 * (1 - k))), 2)
                for i in range(7):
                    a = i * math.tau / 7 + effect.x
                    reach = 10 + (1 - k) * 26
                    pygame.draw.circle(
                        self.surface, _clamp_colour(P.EMBER)[:3],
                        (int(effect.x + math.cos(a) * reach),
                         int(effect.y + math.sin(a) * reach)),
                        max(1, int(3 * k)))
            elif effect.kind in ("bolt", "tornado"):
                pygame.draw.circle(self.surface, P.ARCANE_BRIGHT, centre,
                                   max(1, int(300 * (1 - k))), 3)
            elif effect.kind == "windup":
                # A ring closing in on it: the shrinking gap *is* the timer, so
                # the player reads how long they have without reading a number.
                pygame.draw.circle(self.surface, P.BLOOD, centre,
                                   max(2, int(14 + 46 * k)), 2)
                pygame.draw.circle(self.surface, P.EMBER, centre, 4)
            elif effect.kind == "spoiled":
                pygame.draw.circle(self.surface, P.MOON, centre,
                                   max(1, int(26 * (1 - k))), 2)
            elif effect.kind == "guard_hit":
                pygame.draw.circle(self.surface, P.MOON, centre,
                                   max(1, int(14 * (1 - k))), 2)
            elif effect.kind == "cage_burst":
                pygame.draw.circle(self.surface, (110, 168, 232), centre,
                                   max(2, int(effect.magnitude * (1.2 - k))), 3)
            elif effect.kind == "surge_wave":
                for ring in (1.0, 0.66, 0.33):
                    pygame.draw.circle(
                        self.surface, (96, 150, 220), centre,
                        max(2, int(effect.magnitude * (1.4 - k) * ring)), 2)
            elif effect.kind == "aura":
                pygame.draw.circle(self.surface, P.ARCANE_BRIGHT, centre,
                                   max(2, int(effect.magnitude * (0.6 + k))), 2)
            elif effect.kind == "gale":
                pygame.draw.circle(self.surface, (178, 232, 218), centre,
                                   max(2, int(22 * (1 - k))), 2)
            elif effect.kind == "mend":
                pygame.draw.circle(self.surface, P.BLOOD, centre,
                                   max(2, int(26 * (1 - k))), 2)
            elif effect.kind == "ghost_step":
                # White, and deliberately not the dark print the player leaves.
                # This is the only thing on screen saying where an invisible
                # thing went, so it must not read as the player's own trail.
                self._fx.fill((0, 0, 0, 0))
                pygame.draw.ellipse(
                    self._fx, _clamp_colour(P.SUGAR_BRIGHT, 190 * k),
                    pygame.Rect(int(effect.x) - 4, int(effect.y) - 3, 8, 6))
                self.surface.blit(self._fx, (0, 0))
            elif effect.kind == "taken":
                pygame.draw.circle(self.surface, P.BLOOD, centre,
                                   max(1, int(44 * (1 - k))), 3)
            else:
                pygame.draw.circle(self.surface, P.BONE_DIM, centre,
                                   max(1, int(12 * (1 - k))), 1)

    def _draw_surge(self, state: State) -> None:
        k = max(0.0, min(1.0, state.feedback.surge_flash))
        if k <= 0:
            return
        # Scale by multiplying the colour down, then add it.  Two extra
        # full-screen passes, but only during the second or so a surge flashes.
        level = int(255 * k)
        self._surge.blit(self._vignette, (0, 0))
        self._surge.fill((level, level, level), special_flags=pygame.BLEND_RGB_MULT)
        self.surface.blit(self._surge, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

    def _draw_hurt(self, state: State) -> None:
        k = max(0.0, min(1.0, state.feedback.hurt_flash))
        self._fx.fill(_clamp_colour(P.BLOOD, 70 * k))
        self.surface.blit(self._fx, (0, 0))
