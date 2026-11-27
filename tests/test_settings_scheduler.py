import json
import sys
from pathlib import Path

import pytest

from gupdater.autopilot import scheduler
from gupdater.autopilot.engine import LauncherRun, Outcome
from gupdater.autopilot.report import build_run_report, latest_report, save_run_report, summary_line
from gupdater.settings import DEFAULT_ORDER, Settings, load_settings, save_settings


def test_settings_round_trip(tmp_path):
    path = tmp_path / "s.json"
    settings = Settings(order=["epic", "steam"], disabled=["iccup"], warmup_seconds=60, schedule_enabled=True)
    save_settings(settings, path)
    loaded = load_settings(path)
    assert loaded == settings
    assert loaded.ordered_ids()[:2] == ["epic", "steam"]
    assert set(loaded.ordered_ids()) == set(DEFAULT_ORDER)
    assert not loaded.is_enabled("iccup")


def test_broken_or_odd_settings_fall_back_to_defaults(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_settings(path) == Settings()
    path.write_text(json.dumps({"warmup_seconds": "five", "close_after": 1, "order": ["nope", "riot"],
                                "quiet_seconds": -3, "warmup_minutes": 3, "unknown": True}), encoding="utf-8")
    loaded = load_settings(path)
    assert loaded.warmup_seconds == Settings().warmup_seconds  # wrong type and old 0.2.x key both ignored
    assert loaded.close_after is True and loaded.quiet_seconds == Settings().quiet_seconds
    assert loaded.ordered_ids()[0] == "riot"


def test_enable_disable():
    s = Settings()
    s.set_enabled("steam", False)
    s.set_enabled("steam", False)
    assert s.disabled == ["steam"]
    s.set_enabled("steam", True)
    assert s.disabled == []


def test_scheduler_command_line():
    args = scheduler.create_args(Path(r"D:\Tools\GUpdater.exe"), "05:30")
    assert args[:6] == ["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST"]
    assert args[args.index("/TR") + 1] == r'"D:\Tools\GUpdater.exe" --autopilot'
    for bad in ("5:30", "24:00", "ab:cd"):
        with pytest.raises(scheduler.SchedulerError):
            scheduler.create_args(Path("x.exe"), bad)


@pytest.mark.skipif(sys.platform != "win32", reason="needs the Windows Task Scheduler")
def test_scheduler_creates_and_deletes_a_task(monkeypatch):
    monkeypatch.setattr(scheduler, "TASK_NAME", "GUpdater CI Test")
    scheduler.delete_task()
    scheduler.create_task(Path(sys.executable), "04:45")
    assert scheduler.task_exists()
    scheduler.delete_task()
    assert not scheduler.task_exists()


def test_run_report_and_summary(tmp_path):
    runs = [
        LauncherRun("steam", "Steam", outcome=Outcome.UPDATED, started_at=0, finished_at=600,
                    written_bytes=3 * 1024**3, changes=["Dota 2: 1 → 2"]),
        LauncherRun("epic", "Epic Games", outcome=Outcome.NOTHING, started_at=600, finished_at=960),
        LauncherRun("riot", "Riot Client", outcome=Outcome.FAILED, message="не удалось запустить"),
        LauncherRun("iccup", "iCCup", outcome=Outcome.SKIPPED, message="не установлен"),
    ]
    assert summary_line(runs) == "обновлено 1 · обновлять нечего 1 · ошибок 1 · пропущено 1"
    text = build_run_report(runs, ["05:00:00 Steam: запускаю"], 1_700_000_000, 1_700_000_960, "PC-07")
    assert "[Обновлено] Steam — 10 мин 00 с, записано на диск ≈3.0 ГБ" in text
    assert "    Dota 2: 1 → 2" in text
    assert "[Ошибка] Riot Client — не удалось запустить" in text
    assert "[Пропущен] iCCup — не установлен" in text
    path = save_run_report(text, tmp_path, 1_700_000_000)
    assert latest_report(tmp_path) == path
