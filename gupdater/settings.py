"""User settings, kept as JSON next to GUpdater.exe.

Club PCs often have the system disk frozen (changes on C: vanish after a
reboot), so the settings and reports live next to the program when that
folder is writable — put GUpdater on the games disk and they survive.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

DEFAULT_ORDER = ("steam", "epic", "vkplay", "battlenet", "riot", "ea", "lesta", "iccup")
SETTINGS_FILE = "GUpdater.settings.json"


@dataclass
class Settings:
    order: list[str] = field(default_factory=lambda: list(DEFAULT_ORDER))
    disabled: list[str] = field(default_factory=list)
    # Autopilot timings.
    # Seconds (0.2.x stored minutes under other names; those old values are ignored,
    # so everybody gets the faster timings).
    warmup_seconds: int = 120      # give the launcher time to start and find updates
    quiet_seconds: int = 90        # this long without downloading = finished
    max_minutes: int = 120         # give up on one launcher after this
    activity_kb_per_s: int = 1024  # below this the launcher counts as idle
    close_after: bool = True
    steam_validate_stuck: bool = True
    # Daily automatic run.
    schedule_enabled: bool = False
    schedule_time: str = "05:00"
    idle_minutes: int = 10         # nobody touched mouse/keyboard this long = PC is free
    wait_free_hours: int = 6       # how long a scheduled run waits for a free PC
    check_app_updates: bool = True
    # Stage 3: put the club's saved login in for the update, then take it out again.
    use_club_logins: bool = True
    # Stage 4: the club network.
    club_key: str = ""             # shared by all club PCs; signs the console's commands
    agent_enabled: bool = False    # this PC accepts commands from the console
    agent_autostart: bool = False  # start GUpdater minimised when Windows signs in
    club_hosts: list[str] = field(default_factory=list)  # PCs added by hand (IP or IP:port)

    def ordered_ids(self) -> list[str]:
        """Saved order, without unknown ids, plus launchers added in newer versions."""
        known = [i for i in self.order if i in DEFAULT_ORDER]
        return list(dict.fromkeys(known + [i for i in DEFAULT_ORDER if i not in known]))

    def is_enabled(self, launcher_id: str) -> bool:
        return launcher_id not in self.disabled

    def set_enabled(self, launcher_id: str, enabled: bool) -> None:
        if enabled:
            self.disabled = [i for i in self.disabled if i != launcher_id]
        elif launcher_id not in self.disabled:
            self.disabled.append(launcher_id)


def _is_writable(folder: Path) -> bool:
    probe = folder / ".gupdater-write-test"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


_data_dir_override: Path | None = None


def set_data_dir(path: Path | None) -> None:
    """Use another folder for settings and reports (the demo mode does)."""
    global _data_dir_override
    _data_dir_override = path


def data_dir() -> Path:
    """Folder for settings and reports."""
    override = _data_dir_override or os.environ.get("GUPDATER_DATA_DIR")
    if override:
        folder = Path(override)
    elif getattr(sys, "frozen", False) and _is_writable(Path(sys.executable).parent):
        folder = Path(sys.executable).parent
    elif os.environ.get("APPDATA"):
        folder = Path(os.environ["APPDATA"]) / "GUpdater"
    else:
        folder = Path.home() / ".config" / "gupdater"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def reports_dir() -> Path:
    folder = data_dir() / "GUpdater-отчёты"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def logins_dir() -> Path:
    return data_dir() / "GUpdater-входы"


def load_settings(path: Path | None = None) -> Settings:
    path = path or data_dir() / SETTINGS_FILE
    settings = Settings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return settings
    if not isinstance(raw, dict):
        return settings
    for f in fields(Settings):
        if f.name not in raw:
            continue
        value, default = raw[f.name], getattr(settings, f.name)
        # Keep the default when the file holds a value of the wrong type.
        if isinstance(default, bool):
            ok = isinstance(value, bool)
        elif isinstance(default, int):
            ok = isinstance(value, int) and not isinstance(value, bool) and value >= 0
        elif isinstance(default, list):
            ok = isinstance(value, list) and all(isinstance(v, str) for v in value)
        else:
            ok = isinstance(value, type(default))
        if ok:
            setattr(settings, f.name, value)
    return settings


def save_settings(settings: Settings, path: Path | None = None) -> None:
    path = path or data_dir() / SETTINGS_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
