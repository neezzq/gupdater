"""Start GUpdater: the window by default, or a report file with ``--report``."""

from __future__ import annotations

import argparse
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable

from gupdater import __version__
from gupdater.core.context import SystemContext


def _ensure_streams() -> None:
    # A windowed .exe has no console: argparse would crash writing to None.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _context_factory(demo: bool) -> Callable[[], SystemContext]:
    if not demo:
        return SystemContext.detect

    from gupdater.demo import build_demo_context

    folder = Path(tempfile.mkdtemp(prefix="gupdater-demo-"))
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    counter = iter(range(1_000_000))
    return lambda: build_demo_context(folder / str(next(counter)))


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="GUpdater", description="Обновление игр в лаунчерах для ПК-клуба")
    parser.add_argument("--version", action="version", version=f"GUpdater {__version__}")
    parser.add_argument("--report", metavar="ФАЙЛ", help="без окна: найти лаунчеры и игры и записать отчёт в файл")
    parser.add_argument("--demo", action="store_true", help="показать ненастоящие данные (для проверки)")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def write_report(path: Path, factory: Callable[[], SystemContext]) -> None:
    from gupdater.report import build_report, run_scan

    ctx = factory()
    path.write_text(build_report(run_scan(ctx), ctx), encoding="utf-8-sig")


def run_window(factory: Callable[[], SystemContext], demo: bool, smoke_test: bool = False) -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from gupdater.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("GUpdater")
    window = MainWindow(factory, demo=demo)
    window.show()

    if smoke_test:
        # Used by the build check: the window must open, scan and close by itself.
        outcome = {"code": 2}

        def finished() -> None:
            outcome["code"] = 0 if window.tree.topLevelItemCount() else 3
            QTimer.singleShot(100, app.quit)

        window.scan_finished.connect(finished)
        QTimer.singleShot(60_000, app.quit)
        app.exec()
        return outcome["code"]
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    _ensure_streams()
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    factory = _context_factory(args.demo)
    if args.report:
        write_report(Path(args.report), factory)
        return 0
    return run_window(factory, demo=args.demo, smoke_test=args.smoke_test)
