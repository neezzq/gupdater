"""Colours shared by the tabs (Apple's dark-mode system colours)."""

from gupdater.autopilot.engine import Outcome
from gupdater.core.models import GameStatus

MUTED = "#8E8E93"
GREEN = "#30D158"
ORANGE = "#FF9F0A"
BLUE = "#0A84FF"
RED = "#FF453A"

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
