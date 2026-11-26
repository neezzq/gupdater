"""What a scan finds: launchers and the games installed through them."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class GameStatus(str, Enum):
    OK = "ok"
    UPDATE_REQUIRED = "update_required"
    UPDATING = "updating"
    BROKEN = "broken"
    UNKNOWN = "unknown"

    @property
    def text(self) -> str:
        return _STATUS_TEXT[self]


_STATUS_TEXT = {
    GameStatus.OK: "Актуальна",
    GameStatus.UPDATE_REQUIRED: "Нужно обновление",
    GameStatus.UPDATING: "Обновляется",
    GameStatus.BROKEN: "Ошибка установки",
    GameStatus.UNKNOWN: "Неизвестно",
}


@dataclass
class Game:
    name: str
    game_id: str
    install_path: str | None = None
    version: str | None = None
    size_bytes: int | None = None
    status: GameStatus = GameStatus.UNKNOWN
    note: str = ""


@dataclass
class LauncherScan:
    launcher_id: str
    name: str
    installed: bool = False
    exe_path: str | None = None
    running: bool = False
    games: list[Game] = field(default_factory=list)
    # Plain-language observations shown to the user ("Сохранённый вход: есть").
    notes: list[str] = field(default_factory=list)
    # Which files/keys were checked, for tuning detection from a report.
    evidence: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def updates_needed(self) -> int:
        return sum(1 for g in self.games if g.status is GameStatus.UPDATE_REQUIRED)


def format_size(size_bytes: int | None) -> str:
    if not size_bytes:
        return ""
    gib = size_bytes / 1024**3
    if gib >= 1:
        return f"{gib:.1f} ГБ"
    return f"{size_bytes / 1024**2:.0f} МБ"
