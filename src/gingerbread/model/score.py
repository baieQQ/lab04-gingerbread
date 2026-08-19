"""How well the night went, as a number the player can argue with.

A single grade nobody can account for is worse than no grade: the player reads
"C" and learns nothing except that they are being judged.  So the grade is
always handed over **with its parts**, and every part is one sentence naming a
thing the player did or failed to do.

Nothing here changes an outcome.  It reads the night's tally and returns a
report — the same inputs always give the same report, which is what lets it be
compared across runs and checked headlessly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .state import State


@dataclass(frozen=True, slots=True)
class Line:
    """One scored component, with enough detail to explain itself."""

    label: str
    detail: str
    points: int
    out_of: int

    @property
    def fraction(self) -> float:
        return self.points / self.out_of if self.out_of else 1.0


@dataclass(frozen=True, slots=True)
class Report:
    """The whole verdict for one night."""

    grade: str
    points: int
    out_of: int
    lines: tuple[Line, ...]
    #: The single weakest component, for the one-line summary.
    weakest: Line | None


#: Grade thresholds as a fraction of the total.  Deliberately generous at the
#: bottom: the grade is feedback, not a gate, and a player who survived a night
#: they nearly lost should not be told they failed it.
BANDS: Final = ((0.94, "S"), (0.84, "A"), (0.70, "B"), (0.52, "C"), (0.0, "D"))


def _band(fraction: float) -> str:
    for floor, letter in BANDS:
        if fraction >= floor:
            return letter
    return "D"


def _cap(value: float, out_of: int) -> int:
    return max(0, min(out_of, int(round(value))))


def grade_night(state: State) -> Report:
    """Score the night that has just ended.

    The weights say what the game is about.  Gretel is worth more than
    everything else combined, because keeping her is the whole job; sugar and
    combos are worth little, because a night spent farming them is a night spent
    away from her.  A player who reads this table learns what the game wants.
    """
    s = state.stats
    meta = state.meta
    lines: list[Line] = []

    # ── 40 · Gretel, who is the point ────────────────────────────────
    hearts = meta.sister_hp / max(1, meta.max_sister_hp)
    lines.append(Line(
        "葛蕾特", f"還剩 {meta.sister_hp}/{meta.max_sister_hp}",
        _cap(hearts * 40, 40), 40))

    # ── 20 · how many got past you at all ────────────────────────────
    # Scored against arrivals rather than against a fixed number, so a heavy
    # night and a light one are judged by the same standard: what fraction of
    # the people who came did you stop.
    arrivals = max(1, s.arrivals)
    leaked = min(s.reached_sister, arrivals)
    lines.append(Line(
        "攔截", f"{arrivals - leaked}/{arrivals} 沒能碰到她",
        _cap((1.0 - leaked / arrivals) * 20, 20), 20))

    # ── 15 · what it cost you ────────────────────────────────────────
    hurt = s.damage_taken + s.downs * 3
    lines.append(Line(
        "漢賽爾", ("毫髮無傷" if hurt == 0
                 else f"受傷 {s.damage_taken} 次" +
                      (f"、倒下 {s.downs} 次" if s.downs else "")),
        _cap(15 * (0.86 ** hurt), 15), 15))

    # ── 10 · did you actually clear the field ────────────────────────
    lines.append(Line(
        "清場", f"打倒 {s.kills}/{arrivals}",
        _cap(min(1.0, s.kills / arrivals) * 10, 10), 10))

    # ── 10 · the sugar you did not leave in the snow ─────────────────
    total_sugar = s.sugar_picked + s.sugar_left
    got = 1.0 if total_sugar == 0 else s.sugar_picked / total_sugar
    lines.append(Line(
        "糖霜", (f"撿了 {s.sugar_picked}，留下 {s.sugar_left}"
                if total_sugar else "這一夜沒有掉落"),
        _cap(got * 10, 10), 10))

    # ── 5 · rhythm, worth almost nothing on purpose ──────────────────
    lines.append(Line(
        "連段", f"最高 {s.best_combo} 連",
        _cap(min(1.0, s.best_combo / 8.0) * 5, 5), 5))

    points = sum(line.points for line in lines)
    out_of = sum(line.out_of for line in lines)
    weakest = min(lines, key=lambda line: line.fraction) if lines else None
    if weakest is not None and weakest.fraction >= 0.95:
        weakest = None                      # nothing worth pointing at
    return Report(_band(points / out_of if out_of else 1.0),
                  points, out_of, tuple(lines), weakest)
