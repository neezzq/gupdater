import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


def test_window_scans_and_shows_launchers(qapp_demo_window):
    window = qapp_demo_window
    assert window.tree.topLevelItemCount() == 8
    steam = window.tree.topLevelItem(0)
    assert steam.text(0) == "Steam"
    assert "обновить: 1" in steam.text(1)
    assert window.save_button.isEnabled() and window.copy_button.isEnabled()
    assert "отчёт разведки" in window.report_text


@pytest.fixture
def qapp_demo_window():
    from PySide6.QtCore import QTimer

    from gupdater.app import _context_factory
    from gupdater.ui.main_window import MainWindow

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(_context_factory(True), demo=True)
    window.scan_finished.connect(app.quit)
    QTimer.singleShot(30_000, app.quit)
    app.exec()
    yield window
    window.close()
