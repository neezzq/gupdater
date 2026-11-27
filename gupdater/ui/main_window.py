"""Main window: header with the version and app updates, and two tabs."""

from __future__ import annotations

import os

from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gupdater import __version__
from gupdater import selfupdate
from gupdater.settings import Settings
from gupdater.ui.autopilot_tab import AutopilotTab
from gupdater.ui.games_tab import GamesTab
from gupdater.ui.logins_tab import LoginsTab, recover_logins
from gupdater.ui.runtime import Runtime
from gupdater.ui.club_tab import ClubTab
from gupdater.ui.settings_tab import SettingsTab
from gupdater.ui.style import GREEN, MUTED, RED
from gupdater.ui.theme import Backdrop, dark_title_bar, logo_pixmap


class UpdateCheckThread(QThread):
    done = Signal(object, str)  # Release or None, error text

    def run(self) -> None:
        try:
            self.done.emit(selfupdate.fetch_latest(), "")
        except selfupdate.UpdateError as exc:
            self.done.emit(None, str(exc))


class DownloadThread(QThread):
    progress = Signal(int, int)
    done = Signal(str, str)  # path, error text

    def __init__(self, release: selfupdate.Release, dest: Path) -> None:
        super().__init__()
        self._release = release
        self._dest = dest
        self.cancelled = False

    def run(self) -> None:
        try:
            path = selfupdate.download(
                self._release, self._dest, progress=self.progress.emit, cancelled=lambda: self.cancelled
            )
            self.done.emit(str(path), "")
        except selfupdate.UpdateError as exc:
            self.done.emit("", str(exc))


class MainWindow(QMainWindow):
    scan_finished = Signal()
    agent_requests = Signal(str, bool)  # ("run", now) / ("stop", False), from the agent's thread

    def __init__(self, runtime: Runtime, settings: Settings, updated_from: str | None = None) -> None:
        super().__init__()
        self.runtime = runtime
        self.settings = settings
        self._release: selfupdate.Release | None = None
        self._check_thread: UpdateCheckThread | None = None
        self._download: DownloadThread | None = None

        self.setWindowTitle(f"GUpdater {__version__}" + (" — демо" if runtime.demo else ""))
        self.resize(1280, 900)

        logo = QLabel()
        logo.setPixmap(logo_pixmap(46, self.devicePixelRatioF()))
        title = QLabel("GUpdater")
        title.setObjectName("Title")
        version = QLabel(f"версия {__version__}")
        version.setObjectName("Chip")
        demo = QLabel("ДЕМО: ненастоящие данные")
        demo.setObjectName("Chip")
        demo.setVisible(runtime.demo)
        self.update_status = QLabel()
        self.update_button = QPushButton("Проверить обновления")
        self.update_button.clicked.connect(self._on_update_button)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(logo)
        header.addWidget(title)
        for chip in (version, demo):
            chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            header.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)
        header.addWidget(self.update_status)
        header.addWidget(self.update_button)

        self.games = GamesTab(runtime, self._show_status)
        self.autopilot = AutopilotTab(runtime, settings, self._show_status)
        self.logins = LoginsTab(runtime, settings, self._show_status)
        self.settings_tab = SettingsTab(runtime, settings, self._show_status)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.autopilot, "Обновление")
        self.tabs.addTab(self.logins, "Входы")
        self.club = ClubTab(settings, self._show_status)
        self.tabs.addTab(self.games, "Игры")
        self.tabs.addTab(self.club, "Клуб")
        self.tabs.addTab(self.settings_tab, "Настройки")
        self.games.scanned.connect(self.autopilot.set_scan)
        self.games.scanned.connect(self.logins.set_scan)
        self.games.scan_finished.connect(self.scan_finished)
        self.autopilot.run_finished.connect(self.games.rescan)
        self.autopilot.running_changed.connect(lambda running: self.update_button.setEnabled(not running))

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 14, 20, 8)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self.tabs, 1)
        central = Backdrop()
        central.setLayout(layout)
        self.setCentralWidget(central)

        # If GUpdater died mid-update, the club's login may still be in a launcher.
        self.agent = None
        self.agent_requests.connect(self._agent_command)
        if settings.agent_enabled and settings.club_key and not runtime.demo:
            self._start_agent()

        if recover_logins(runtime, settings, self._show_status):
            self._show_status("Прошлое обновление прервалось: вход клуба убран из лаунчеров, всё как было")

        if updated_from:
            self._show_status(f"Программа обновлена: {updated_from} → {__version__}")
            self._set_update_status(f"Обновлено до {__version__}", GREEN)
        QTimer.singleShot(0, self.games.rescan)
        if settings.check_app_updates and not runtime.demo:
            QTimer.singleShot(1500, lambda: self.check_updates(silent=True))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        dark_title_bar(self)

    # --- status -------------------------------------------------------------

    def _show_status(self, text: str) -> None:
        self.statusBar().showMessage(text)

    def _set_update_status(self, text: str, color: str = MUTED) -> None:
        self.update_status.setText(text)
        self.update_status.setStyleSheet(f"color: {color};")

    # --- updating GUpdater itself --------------------------------------------

    def _on_update_button(self) -> None:
        if self._release and selfupdate.is_newer(self._release.version):
            self.install_update(self._release)
        else:
            self.check_updates(silent=False)

    def check_updates(self, silent: bool = False) -> None:
        if self._check_thread and self._check_thread.isRunning():
            return
        self.update_button.setEnabled(False)
        self._set_update_status("Проверяю…")
        self._check_thread = UpdateCheckThread()
        self._check_thread.done.connect(lambda release, error: self._on_checked(release, error, silent))
        self._check_thread.start()

    def _on_checked(self, release, error: str, silent: bool) -> None:
        self.update_button.setEnabled(not self.autopilot.is_running)
        if error:
            self._set_update_status("Не удалось проверить обновления", RED)
            self.update_status.setToolTip(error)
            if not silent:
                QMessageBox.warning(self, "Обновление программы", error)
            return
        self._release = release
        if selfupdate.is_newer(release.version):
            self._set_update_status(f"Доступна версия {release.version}", GREEN)
            self.update_button.setText(f"Обновить до {release.version}")
            self.update_button.setStyleSheet("font-weight: bold;")
        else:
            self._set_update_status("У вас последняя версия")
            self.update_button.setText("Проверить обновления")
            self.update_button.setStyleSheet("")

    def install_update(self, release: selfupdate.Release) -> None:
        if self.autopilot.is_running:
            QMessageBox.information(self, "Обновление программы", "Дождитесь, пока автопилот закончит.")
            return
        exe = selfupdate.running_exe()
        if exe is None:
            QMessageBox.information(
                self, "Обновление программы",
                "Обновление по кнопке работает в GUpdater.exe. Сейчас откроется страница загрузки.",
            )
            QDesktopServices.openUrl(QUrl(release.page_url))
            return
        answer = QMessageBox.question(
            self, "Обновление программы",
            f"Скачать и установить GUpdater {release.version}?\nПрограмма закроется и сразу откроется снова.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        dialog = QProgressDialog(f"Скачиваю GUpdater {release.version}…", "Отмена", 0, 100, self)
        dialog.setWindowTitle("Обновление программы")
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        self._download = DownloadThread(release, selfupdate.download_path(exe))
        self._download.progress.connect(
            lambda done, total: dialog.setValue(int(done * 100 / total) if total else 0)
        )
        dialog.canceled.connect(lambda: setattr(self._download, "cancelled", True))
        self._download.done.connect(lambda path, error: self._on_downloaded(path, error, exe, dialog))
        self._download.start()

    def _on_downloaded(self, path: str, error: str, exe: Path, dialog: QProgressDialog) -> None:
        dialog.close()
        if error:
            if error != "Загрузка отменена":
                QMessageBox.warning(self, "Обновление не установлено", error)
            return
        try:
            selfupdate.install(Path(path), exe)
            selfupdate.restart(exe, ["--updated-from", __version__])
        except (selfupdate.UpdateError, OSError) as exc:
            Path(path).unlink(missing_ok=True)
            QMessageBox.critical(self, "Обновление не установлено", str(exc))
            return
        QApplication.quit()

    # --- closing ------------------------------------------------------------

    # --- the club console talks to this PC ------------------------------------

    def _start_agent(self) -> None:
        from gupdater.club.agent import Agent

        self.agent = Agent(
            key=lambda: self.settings.club_key,
            status=self.agent_status,
            on_run=lambda now: self.agent_requests.emit("run", now),
            on_stop=lambda: self.agent_requests.emit("stop", False),
        )
        try:
            self.agent.start()
            self._show_status(f"Пульт клуба может управлять этим ПК (порт {self.agent.port})")
        except OSError as exc:
            self.agent = None
            self._show_status(f"Не удалось включить приём команд: {exc}")

    def agent_status(self) -> dict:
        """Called from the agent's thread: only reads simple values."""
        import socket

        system = self.runtime.system_factory()
        idle = system.idle_seconds()
        running = self.autopilot.is_running
        report = self.autopilot.last_run.text()
        return {
            "name": os.environ.get("COMPUTERNAME") or socket.gethostname(),
            "version": __version__,
            "idle_seconds": idle,
            "free": not running and (idle is None or idle >= self.settings.idle_minutes * 60),
            "running": running,
            "current": self.autopilot.current,
            "last": self.autopilot.last_summary or report.removeprefix("Последний запуск ").strip(),
        }

    def _agent_command(self, command: str, now: bool) -> None:
        if command == "run":
            self.autopilot.start(scheduled=not now)
        else:
            self.autopilot.stop()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.autopilot.is_running:
            answer = QMessageBox.question(self, "Автопилот работает", "Автопилот ещё работает. Остановить его и закрыть?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.autopilot.stop()
            self.autopilot.wait_finished(15_000)
        self.club.shutdown()
        if self.agent:
            self.agent.stop()
        event.accept()
