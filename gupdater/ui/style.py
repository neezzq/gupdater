"""Colours shared by the tabs."""

from gupdater.autopilot.engine import Outcome
from gupdater.core.models import GameStatus

MUTED = "#8a8f98"
GREEN = "#1a7f37"
ORANGE = "#c05600"
BLUE = "#0b62d6"
RED = "#c62828"

STATUS_COLORS = {
    GameStatus.OK: GREEN,
    GameStatus.UPDATE_REQUIRED: ORANGE,
    GameStatus.UPDATING: BLUE,
    GameStatus.BROKEN: RED,
    GameStatus.UNKNOWN: MUTED,
}

OUTCOME_COLORS = {
    Outcome.UPDATED: GREEN,
    Outcome.NOTHING: GREEN,
    Outcome.NOT_FINISHED: ORANGE,
    Outcome.TIMEOUT: ORANGE,
    Outcome.FAILED: RED,
    Outcome.SKIPPED: MUTED,
    Outcome.STOPPED: ORANGE,
}
