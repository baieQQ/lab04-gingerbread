"""Drawing people.

Everything on this field is a person — that is the story.  The things coming for
Gretel are the villagers, seen through Hansel's memory of the witch, and the
ending turns on the player realising it.  So they are drawn as **humanoids with
something wrong**, never as blobs or beasts: same head, same shoulders, same
walk, and only the proportions and the colour differ.  A monster that reads as a
monster gives the ending away in the first ten seconds.

Three techniques do almost all of the work here, and none of them needs art.

**Outlines.**  Every figure is drawn twice — once fattened in near-black, then
the fill on top.  In a dark scene lit by one lamp this is the difference between
a shape and a smudge; it is the cheapest legibility win available.

**Contact shadows.**  A soft ellipse under the feet.  Without it figures float;
with it they stand on the ground.  Two draw calls.

**Motion derived from position, not from a clock.**  The walk cycle's phase
comes from ``x + y``, so a figure that moves bobs and a figure that stops holds
still, with no per-entity animation state anywhere.  That matters because
entities are deep-copied every simulation step and have no stable identity to
hang state on.
"""

from __future__ import annotations

import math
from typing import Final

import pygame

from . import palette as P

RGB = tuple[int, int, int]

#: The outline colour.  Not pure black: a hair of blue stops it punching a hole
#: in the warm lamplight.
OUTLINE: Final[RGB] = (9, 8, 16)

#: Distance travelled, in pixels, per full walk cycle.
STRIDE: Final = 26.0


def clamp_colour(colour, alpha: float | None = None):
    """Force a colour into the range ``pygame.draw`` accepts.

    Out-of-range components raise mid-frame, and content tables written by other
    people are about to start supplying colours, so the clamp lives here at the
    boundary rather than at forty call sites.
    """
    r, g, b = (max(0, min(255, int(v))) for v in colour[:3])
    if alpha is None:
        return (r, g, b)
    return (r, g, b, max(0, min(255, int(alpha))))


def walk_phase(ticks: int, speed: float, x: float, y: float) -> float:
    """Return the walk cycle's phase for a figure moving at ``speed``.

    **Driven by the clock, not by position.**  The previous version returned
    ``(x + y) / STRIDE``, on the reasoning that a figure which moves animates
    and a figure which stops freezes, with nothing to remember between frames.
    The reasoning is wrong, and measurably so: every function of position has
    level curves, and walking along one leaves the phase unchanged.  Here the
    level curves were the up-right and down-left diagonals, so on two of the
    eight directions the legs did not move **at all** — 0.0000 radians per
    frame against 0.7894 going straight — and the figure slid across the ground.
    The other two diagonals ran 41% fast.  No coefficient fixes that; the whole
    approach cannot work.

    Time has no null direction, so this is correct in all eight.  Scaling by
    ``speed`` keeps what the old version got right: a monster wading through mud
    takes slower steps, because its speed is what fell, not the clock.

    Position survives only as a small phase *offset*, so a crowd does not march
    in lockstep.  The coefficients are deliberately tiny — at walking pace they
    add about 3% to the step rate, which is invisible, while still spreading a
    full cycle across the width of the field.
    """
    return (ticks * speed / 60.0) / STRIDE * math.tau + x * 0.0073 + y * 0.0041


def shadow(surface: pygame.Surface, x: float, y: float, radius: float,
           lift: float = 0.0) -> None:
    """Draw the contact shadow under a figure.

    It shrinks as ``lift`` grows, which is what sells a hop or a knockback as
    leaving the ground rather than as sliding along it.
    """
    squeeze = max(0.4, 1.0 - lift * 0.06)
    width = max(3, int(radius * 1.8 * squeeze))
    height = max(2, int(radius * 0.55 * squeeze))
    pygame.draw.ellipse(surface, (12, 11, 20),
                        pygame.Rect(int(x - width / 2),
                                    int(y + radius * 0.72 - height / 2),
                                    width, height))


def _ellipse(surface, colour, cx, cy, rx, ry) -> None:
    if rx < 0.5 or ry < 0.5:
        return
    pygame.draw.ellipse(surface, colour,
                        pygame.Rect(int(cx - rx), int(cy - ry),
                                    max(1, int(rx * 2)), max(1, int(ry * 2))))


def humanoid(surface: pygame.Surface, x: float, y: float, radius: float,
             colour: RGB, *,
             build: str = "adult",
             phase: float = 0.0,
             moving: bool = True,
             squash: float = 0.0,
             lift: float = 0.0,
             facing: tuple[float, float] = (0.0, 1.0),
             hair: RGB | None = None,
             skirt: bool = False,
             rim_from: tuple[float, float] | None = None) -> None:
    """Draw one person.

    ``build`` changes proportion only — ``adult``, ``heavy``, ``small``,
    ``tall``.  They are the same creature at different sizes, which is the
    point: these are neighbours, not a bestiary.

    ``rim_from`` is a unit vector pointing at the light.  The side facing it is
    brightened and the far side darkened.

    That rim is doing the job a dark outline cannot.  An outline separates a
    figure from its background only when it *contrasts* with the background, and
    here the background is nearly black — the first version drew a near-black
    edge onto near-black ground and was invisible at every size.  A bright rim
    reads at ten pixels, and it also ties every figure to the one lamp the game
    is about.
    """
    # Head-to-body ratio does the identifying, not overall scale.  A child is a
    # big head on a small body; a brute is a small head on a huge one.  Two
    # figures that differ only in size are indistinguishable once one of them is
    # half in shadow, which at night is most of the time.
    if build == "heavy":
        brx, bry, hr, spread = 1.06, 0.80, 0.34, 0.54
    elif build == "small":
        brx, bry, hr, spread = 0.50, 0.48, 0.58, 0.34
    elif build == "tall":
        brx, bry, hr, spread = 0.58, 0.94, 0.40, 0.42
    else:
        brx, bry, hr, spread = 0.72, 0.72, 0.46, 0.44

    sx = 1.0 + squash * 0.35
    sy = 1.0 - squash * 0.35

    bob = math.sin(phase) * (radius * 0.11) if moving else 0.0
    swing = math.sin(phase) if moving else 0.0

    cy = y - lift + bob - radius * 0.30
    body_rx, body_ry = radius * brx * sx, radius * bry * sy
    head_r = radius * hr * (1.0 + squash * 0.15)
    head_y = cy - body_ry - head_r * 0.78

    base = clamp_colour(colour)
    dark = P.scale(base, 0.62)
    limb = P.scale(base, 0.78)        # limbs read only if they are not near-black
    lightened = P.mix(base, (255, 250, 235), 0.72)

    # ── legs, drawn first and *below* the body so they read ──────────
    foot_y = y - lift + radius * 0.62
    for side, motion in ((-1, swing), (1, -swing)):
        lx = x + side * radius * spread * 0.62
        ly = foot_y + motion * radius * 0.13
        _ellipse(surface, OUTLINE, lx, ly, radius * 0.20, radius * 0.17)
        _ellipse(surface, limb, lx, ly, radius * 0.15, radius * 0.13)

    # ── arms, at the sides and clear of the torso ────────────────────
    for side, motion in ((-1, -swing), (1, swing)):
        ax = x + side * (body_rx + radius * 0.16)
        ay = cy + radius * 0.06 + motion * radius * 0.16
        _ellipse(surface, OUTLINE, ax, ay, radius * 0.19, radius * 0.28)
        _ellipse(surface, limb, ax, ay, radius * 0.14, radius * 0.23)

    # ── torso ────────────────────────────────────────────────────────
    if skirt:
        # A triangle, not an oval.  Gretel has to be identifiable from her
        # outline alone at ten pixels across, in the dark, while the player is
        # busy — a different silhouette does that; a different colour does not.
        hem = body_rx * 1.55
        shape = [(x - hem, cy + body_ry * 1.15),
                 (x + hem, cy + body_ry * 1.15),
                 (x + body_rx * 0.55, cy - body_ry * 0.9),
                 (x - body_rx * 0.55, cy - body_ry * 0.9)]
        pygame.draw.polygon(surface, OUTLINE,
                            [(px + (2 if px > x else -2),
                              py + (2 if py > cy else -2)) for px, py in shape])
        pygame.draw.polygon(surface, base, shape)
    else:
        _ellipse(surface, OUTLINE, x, cy, body_rx + 2, body_ry + 2)
        _ellipse(surface, base, x, cy, body_rx, body_ry)

    # ── head, with a visible gap for the neck ────────────────────────
    pygame.draw.circle(surface, OUTLINE, (int(x), int(head_y)),
                       max(2, int(head_r + 2)))
    pygame.draw.circle(surface, base, (int(x), int(head_y)),
                       max(1, int(head_r)))

    if hair is not None:
        pygame.draw.circle(surface, clamp_colour(hair),
                           (int(x), int(head_y - head_r * 0.30)),
                           max(1, int(head_r * 0.95)))

    # ── rim light ────────────────────────────────────────────────────
    if rim_from is not None:
        rx, ry = rim_from
        length = math.hypot(rx, ry) or 1.0
        rx, ry = rx / length, ry / length

        # A crescent, not a spot.  Draw the lit shape, then redraw the base
        # shape shifted *away* from the light: what stays uncovered is a thin
        # arc along the lit edge.  The first version filled a circle at an
        # offset, which read as a white sticker on the chest rather than as
        # light catching a surface.
        shift = max(2.0, radius * 0.22)
        if not skirt:
            _ellipse(surface, lightened, x, cy, body_rx, body_ry)
            _ellipse(surface, base, x - rx * shift, cy - ry * shift,
                     body_rx, body_ry)

        pygame.draw.circle(surface, lightened, (int(x), int(head_y)),
                           max(1, int(head_r)))
        pygame.draw.circle(surface, base,
                           (int(x - rx * shift * 0.8),
                            int(head_y - ry * shift * 0.8)),
                           max(1, int(head_r)))
        if hair is not None:
            pygame.draw.circle(surface, clamp_colour(hair),
                               (int(x), int(head_y - head_r * 0.30)),
                               max(1, int(head_r * 0.95)))

    # ── eyes, toward the facing direction ────────────────────────────
    # Pale, not dark.  Dark eyes on a dark body merge into the outline and read
    # as a hole; pale ones read at any size — and on the villagers they give
    # exactly the wrongness the story wants, since these are supposed to be
    # people the player has already met in daylight.
    fx, fy = facing
    ex = x + fx * head_r * 0.24
    ey = head_y + fy * head_r * 0.20 + head_r * 0.10
    for side in (-1, 1):
        pygame.draw.circle(surface, OUTLINE,
                           (int(ex + side * head_r * 0.38), int(ey)),
                           max(1, int(head_r * 0.26)))
        pygame.draw.circle(surface, (236, 230, 214),
                           (int(ex + side * head_r * 0.38), int(ey)),
                           max(1, int(head_r * 0.15)))


def crystal(surface: pygame.Surface, x: float, y: float, size: float,
            colour: RGB, twinkle: float = 0.0) -> None:
    """Draw a sugar crystal: a small four-pointed shard.

    Deliberately small and warm.  An earlier version drew a white dot with a
    wide cold halo, and six of them lying on the ground lit the whole field —
    the loot was undoing the darkness the game is built on.
    """
    s = size * (1.0 + twinkle * 0.25)
    wide = s * 0.44
    outer = [(x, y - s - 1.6), (x + wide + 1.6, y),
             (x, y + s + 1.6), (x - wide - 1.6, y)]
    inner = [(x, y - s), (x + wide, y), (x, y + s), (x - wide, y)]
    pygame.draw.polygon(surface, OUTLINE, outer)
    pygame.draw.polygon(surface, clamp_colour(colour), inner)
    pygame.draw.line(surface, clamp_colour(P.scale(colour, 1.45)),
                     (x, y - s * 0.6), (x, y + s * 0.6), 1)


def footprint(surface: pygame.Surface, x: float, y: float, fade: float) -> None:
    """A single pressed mark in the snow, fading out.

    Footprints are the strongest movement feedback available in a dark scene:
    they turn "am I moving?" into something the player can see behind them
    without a single asset.
    """
    alpha = int(70 * max(0.0, min(1.0, fade)))
    if alpha <= 2:
        return
    pygame.draw.ellipse(surface, (16, 14, 24, alpha),
                        pygame.Rect(int(x - 3), int(y - 2), 6, 4))
