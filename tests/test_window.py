import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["GUPDATER_DEMO_SPEED"] = "5000"
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


def _wait(app, signal, timeout_ms=60_000):
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    signal.connect(loop.quit)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()


@pytest.fixture
def demo_window():
    from gupdater.app import build_runtime
    from gupdater.settings import load_settings
    from gupdater.ui.main_window import MainWindow

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(build_runtime(demo=True), load_settings())
    _wait(app, window.scan_finished)
    yield app, window
    window.close()


def test_window_shows_version_tabs_and_scan(demo_window):
    from gupdater import __version__

    app, window = demo_window
    assert __version__ in window.windowTitle()
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == ["Автопилот", "Игры на этом ПК"]
    tree = window.games.tree
    assert tree.topLevelItemCount() == 8
    assert tree.topLevelItem(0).text(0) == "Steam"
    assert "обновить: 1" in tree.topLevelItem(0).text(1)
    assert "отчёт разведки" in window.games.report_text
    assert window.autopilot.table.rowCount() == 8
    assert window.autopilot.table.item(0, 1).text() == "Установлен · игр: 4"


def test_autopilot_runs_in_demo_and_updates_steam(demo_window):
    from gupdater.settings import reports_dir

    app, window = demo_window
    tab = window.autopilot
    tab.start()
    assert tab.is_running
    _wait(app, tab.run_finished)
    assert not tab.is_running
    log = tab.log.toPlainText()
    assert "Dota 2: 18690011 → 18712345" in log
    assert "Готово: обновлено 4" in log
    assert tab.table.item(0, 2).text() == "Обновлено"
    reports = list(reports_dir().glob("автопилот-*.txt"))
    assert len(reports) == 1
    # The games tab rescans after the run: Steam no longer waits for updates.
    _wait(app, window.scan_finished)
    assert "обновить" not in window.games.tree.topLevelItem(0).text(1)


def test_unchecked_launcher_is_skipped_and_order_is_saved(demo_window):
    from PySide6.QtCore import Qt

    from gupdater.settings import load_settings

    app, window = demo_window
    tab = window.autopilot
    tab.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)  # Epic Games
    tab.table.selectRow(0)
    tab._move(1)  # Steam goes below Epic
    saved = load_settings()
    assert saved.disabled == ["epic"]
    assert saved.ordered_ids()[:2] == ["epic", "steam"]
