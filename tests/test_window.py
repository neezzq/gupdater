import os
from pathlib import Path

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
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == ["Обновление", "Входы", "Игры", "Настройки"]
    tree = window.games.tree
    assert tree.topLevelItemCount() == 8
    assert tree.topLevelItem(0).text(0) == "Steam"
    assert "обновить: 1" in tree.topLevelItem(0).text(1)
    assert "отчёт разведки" in window.games.report_text
    assert list(window.autopilot.rows) == ["steam", "epic", "vkplay", "battlenet", "riot", "ea", "lesta", "iccup"]
    assert window.autopilot.rows["steam"].subtitle.text() == "4 игры"
    assert window.autopilot.rows["lesta"].subtitle.text() == "1 игра"
    assert window.autopilot.warning.isVisibleTo(window)  # the demo PC has Shadow Defender


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
    assert tab.rows["steam"].state.text() == "Обновлено"
    reports = list(reports_dir().glob("автопилот-*.txt"))
    assert len(reports) == 1
    # The games tab rescans after the run: Steam no longer waits for updates.
    _wait(app, window.scan_finished)
    assert "обновить" not in window.games.tree.topLevelItem(0).text(1)


def test_unchecked_launcher_is_skipped_and_order_is_saved(demo_window):

    from gupdater.settings import load_settings

    app, window = demo_window
    tab = window.autopilot
    tab.rows["epic"].check.setChecked(False)
    tab.move("steam", 1)  # Steam goes below Epic
    assert list(tab.rows)[:2] == ["epic", "steam"]
    assert tab.rows["epic"].state.text() == "Выключен"
    saved = load_settings()
    assert saved.disabled == ["epic"]
    assert saved.ordered_ids()[:2] == ["epic", "steam"]


def test_club_login_end_to_end_in_demo(demo_window):
    """Stage 3 on the demo PC: the wizard saves Steam's club login, the autopilot uses it."""
    from gupdater.autopilot.login_wizard import LoginWizard
    from gupdater.launchers.steam import Steam
    from gupdater.logins import Vault
    from gupdater.settings import logins_dir

    app, window = demo_window
    runtime = window.runtime
    local_vdf = None
    wizard = LoginWizard(Steam(), runtime.context_factory, runtime.system_factory(), runtime.registry_factory(),
                         Vault(logins_dir()))
    wizard.prepare()
    wizard.open_launcher()  # in the demo, starting Steam "signs in" (writes local.vdf)
    spec = wizard.finish()
    local_vdf = next(f for f in spec.files if f.endswith("local.vdf"))
    assert not Path(local_vdf).exists()  # club login taken out again: there was none before
    assert Vault(logins_dir()).has_club("steam")

    window.logins.refresh()
    assert window.logins.rows["steam"].subtitle.text().startswith("запомнен")

    tab = window.autopilot
    tab.start()
    _wait(app, tab.run_finished)
    log = tab.log.toPlainText()
    assert "Steam: подставил вход клуба" in log
    assert "убрал вход клуба" in log
    assert not Path(local_vdf).exists()  # and taken out after the update


def test_single_launcher_run(demo_window):
    app, window = demo_window
    tab = window.autopilot
    tab.start(only="epic")
    _wait(app, tab.run_finished)
    log = tab.log.toPlainText()
    assert "только Epic Games" in log
    assert "Epic Games: запускаю" in log and "Steam:" not in log
    assert tab.rows["epic"].state.text() == "Обновлять нечего"
