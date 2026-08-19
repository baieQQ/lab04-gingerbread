"""The rules layer.

**This package must stay importable without pygame.**  Nothing under
``model/`` may import the display, the mixer, the event queue or a clock.  That
is not tidiness: it is what lets the whole game be simulated headlessly, which
is what makes ``--check`` meaningful and what makes a failure reproducible.

Importing this package registers every behaviour, trait, spell and event, then
validates the content tables against them.  A misspelled name in a content file
therefore fails here, at startup, with a message naming the row — rather than
silently doing nothing until someone notices a monster that never behaves.
"""

from __future__ import annotations

# Importing for side effects: each of these registers its functions by name.
# The order matters — content validation needs the registries populated first.
from . import behaviours as _behaviours     # noqa: F401
from . import effects as _effects           # noqa: F401
from .content import check as _check
from .constants import (ACTION_POINTS, CAMPAIGN_NIGHTS, DAY_SECONDS, FIXED_DT,
                        HEIGHT, NIGHT_SECONDS, SISTER_MAX_HP, SISTER_X,
                        SISTER_Y, WIDTH)
from .contract import (ActionError, apply_action, is_terminal, new_game,
                       parse_action, run_script, snapshot, snapshot_brief)
from .derive import Derived, derive, is_lit, light_level, lights_of
from .score import Line, Report, grade_night
from .director import director_for
from .entities import (Boss, Drop, Effect, Light, Monster, Obstacle, Player,
                       Projectile, Warning)
from .state import Meta, Mode, Phase, State, Stats, to_ticks

_check()

__all__ = [
    # contract
    "new_game", "apply_action", "is_terminal", "snapshot",
    "snapshot_brief", "parse_action", "run_script", "ActionError",
    # state
    "State", "Meta", "Mode", "Phase", "Stats", "to_ticks",
    # entities
    "Player", "Monster", "Boss", "Drop", "Warning", "Projectile",
    "Obstacle", "Effect", "Light",
    # derived
    "derive", "Derived", "lights_of", "is_lit", "light_level",
    "grade_night", "Report", "Line",
    "director_for",
    # constants worth re-exporting
    "WIDTH", "HEIGHT", "SISTER_X", "SISTER_Y", "FIXED_DT",
    "DAY_SECONDS", "NIGHT_SECONDS", "ACTION_POINTS", "SISTER_MAX_HP",
    "CAMPAIGN_NIGHTS",
]
