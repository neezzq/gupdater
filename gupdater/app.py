"""Start GUpdater: the window by default, or a report file with ``--report``."""

from __future__ import annotations

import argparse
import atexit
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from gupdater import __version__


def _ensure_streams() -> None:
    # A windowed .exe has no console: argparse would crash writing to None.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="GUpdater", description="Обновление игр в лаунчерах для ПК-клуба")
    parser.add_argument("--version", action="version", version=f"GUpdater {__version__}")
    parser.add_argument("--report", metavar="ФАЙЛ", help="без окна: найти лаунчеры и игры и записать отчёт в файл")
    parser.add_argument("--autopilot", action="store_true",
                        help="обновить игры и закрыться (так запускает планировщик Windows); "
                             "сначала ждёт, пока за компьютером никого нет")
    parser.add_argument("--now", action="store_true", help="вместе с --autopilot: не ждать, начать сразу")
    parser.add_argument("--demo", action="store_true", help="показать ненастоящие данные (для проверки)")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--updated-from", metavar="ВЕРСИЯ", help=argparse.SUPPRESS)
    parser.add_argument("--selftest-update", nargs=2, metavar=("НОВЫЙ_EXE", "ОТЧЁТ"), help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def build_runtime(demo: bool):
    from gupdater.ui.runtime import Runtime

    if not demo:
        from gupdater.autopilot.system import RealSystem
        from gupdater.core.context import SystemContext

        return Runtime(context_factory=SystemContext.detect, system_factory=RealSystem)

    from gupdater.demo import DemoWorld
    from gupdater.settings import set_data_dir

    folder = Path(tempfile.mkdtemp(prefix="gupdater-demo-"))
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    speed = float(os.environ.get("GUPDATER_DEMO_SPEED", "100"))
    world = DemoWorld(folder, speed=speed)
    set_data_dir(folder / "data")
    return Runtime(context_factory=world.context, system_factory=lambda: world.system, demo=True)


def write_report(path: Path, runtime) -> None:
    from gupdater.report import build_report, run_scan

    ctx = runtime.context_factory()
    path.write_text(build_report(run_scan(ctx), ctx), encoding="utf-8-sig")


def selftest_update(new_exe: Path, report: Path) -> int:
    """Used by the build check: replace the running exe and start the new one."""
    from gupdater import selfupdate

    exe = selfupdate.running_exe()
    if exe is None:
        return 4
    selfupdate.install(new_exe, exe)
    selfupdate.restart(exe, ["--report", str(report)])
    return 0


def run_window(runtime, args: argparse.Namespace) -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from gupdater.settings import load_settings
    from gupdater.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("GUpdater")
    window = MainWindow(runtime, load_settings(), updated_from=args.updated_from)
    window.show()

    if args.smoke_test:
        # Used by the build check: the window must open, scan and close by itself.
        outcome = {"code": 2}

        def finished() -> None:
            outcome["code"] = 0 if window.games.tree.topLevelItemCount() else 3
            QTimer.singleShot(100, app.quit)

        window.scan_finished.connect(finished)
        QTimer.singleShot(60_000, app.quit)
        app.exec()
        return outcome["code"]

    if args.autopilot:
        QTimer.singleShot(500, lambda: window.autopilot.start(scheduled=not args.now, quit_after=True))
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    _ensure_streams()
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    from gupdater import selfupdate

    if selfupdate.running_exe() is not None:
        threading.Thread(target=selfupdate.cleanup_old_versions, daemon=True).start()
    if args.selftest_update:
        return selftest_update(Path(args.selftest_update[0]), Path(args.selftest_update[1]))

    runtime = build_runtime(args.demo)
    if args.report:
        write_report(Path(args.report), runtime)
        return 0
    return run_window(runtime, args)
