"""Tab "Обновление": the launcher queue, the big button and the log."""

from __future__ import annotations

import threading
import traceback
from dataclasses import replace

from PySide6.QtCore import QLockFile, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gupdater.autopilot.engine import Autopilot, EngineSettings, LauncherRun, Stopped
from gupdater.autopilot.report import build_run_report, latest_report, save_run_report, summary_line
from gupdater.launchers import ALL_LAUNCHERS
from gupdater.report import ScanResult, sanitize, scan_all
from gupdater.settings import Settings, data_dir, reports_dir, save_settings
from gupdater.ui.icons import launcher_icon
from gupdater.ui.launcher_row import LauncherRow, games_text
from gupdater.ui.runtime import Runtime
from gupdater.ui.style import BLUE, OUTCOME_COLORS
from gupdater.ui.warnings import environment_warning, short_warning

_LAUNCHERS = {launcher.id: launcher for launcher in ALL_LAUNCHERS}


class AutopilotThread(QThread):
    run_changed = Signal(object)  # LauncherRun (a copy)
    log_line = Signal(str)
    done = Signal(object, str, str)  # runs, report path, summary

    def __init__(self, runtime: Runtime, settings: Settings, scheduled: bool, only: str | None = None) -> None:
        super().__init__()
        self._runtime = runtime
        self._settings = settings
        self._scheduled = scheduled
        self._only = only
        self.stop_event = threading.Event()

    def run(self) -> None:
        try:
            self._run()
        except Exception:
            self.log_line.emit("Ошибка автопилота:\n" + traceback.format_exc())
            self.done.emit([], "", "автопилот завершился с ошибкой")

    def _run(self) -> None:
        settings, runtime = self._settings, self._runtime
        from gupdater.ui.logins_tab import make_logins, recover_logins

        recover_logins(runtime, settings, self.log_line.emit)
        system = runtime.system_factory()
        ids = [self._only] if self._only else settings.ordered_ids()
        pilot = Autopilot(
            [_LAUNCHERS[i] for i in ids],
            runtime.context_factory,
            system,
            EngineSettings.from_settings(settings),
            stop=self.stop_event,
            on_update=lambda run: self.run_changed.emit(replace(run, changes=list(run.changes))),
            on_log=self.log_line.emit,
            watch_user_input=self._scheduled,
            logins=make_logins(runtime, settings),
        )
        ctx = runtime.context_factory()
        started = system.wall_time()
        note = ""
        if self._scheduled:
            game_folders = [g.install_path for scan in scan_all(ctx) for g in scan.games if g.install_path]
            try:
                free = pilot.wait_for_free_pc(settings.idle_minutes * 60, settings.wait_free_hours * 3600, game_folders)
            except Stopped as stopped:
                free, note = False, stopped.reason
            if not free:
                note = note or "компьютер был занят"
                pilot.skip_all(note)
        if not note:
            pilot.run(enabled=(lambda launcher_id: True) if self._only else settings.is_enabled)
        text = build_run_report(pilot.runs, pilot.log_lines, started, system.wall_time(), ctx.computer_name, note)
        path = save_run_report(sanitize(text, ctx), reports_dir(), started)
        self.done.emit(pilot.runs, str(path), summary_line(pilot.runs))


class AutopilotTab(QWidget):
    running_changed = Signal(bool)
    run_finished = Signal()

    def __init__(self, runtime: Runtime, settings: Settings, status: callable) -> None:
        super().__init__()
        self._runtime = runtime
        self.settings = settings
        self._status = status
        self._thread: AutopilotThread | None = None
        self._lock: QLockFile | None = None
        self._quit_after = False
        self._scan: dict[str, tuple[bool, int, str | None]] = {}  # id -> (installed, games, exe)
        self.rows: dict[str, LauncherRow] = {}

        self.start_button = QPushButton("Обновить всё")
        self.start_button.setObjectName("Primary")
        self.start_button.setMinimumWidth(170)
        self.start_button.setToolTip(
            "По очереди открывает лаунчеры, ждёт, пока каждый скачает обновления, и закрывает его.\n"
            "Лаунчер без обновлений занимает 2–3 мин, Steam — около 1,5 мин. Лаунчеры без игр пропускаются."
        )
        self.start_button.clicked.connect(self._toggle)
        self.last_run = QLabel()
        self.last_run.setObjectName("Muted")
        self.report_button = QPushButton("Отчёт")
        self.report_button.clicked.connect(self.open_last_report)

        top = QHBoxLayout()
        top.addWidget(self.start_button)
        top.addSpacing(10)
        top.addWidget(self.last_run, 1)
        top.addWidget(self.report_button)

        self.warning = QLabel()
        self.warning.setObjectName("Warning")
        self.warning.setWordWrap(True)
        self.warning.hide()

        self.list = QListWidget()
        self.list.setObjectName("Cards")
        self.list.setSpacing(3)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setToolTip("Перетащите лаунчер, чтобы поменять порядок")
        self.list.model().rowsMoved.connect(lambda *args: QTimer.singleShot(0, self._order_changed))

        log_title = QLabel("Журнал")
        log_title.setObjectName("Section")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setMaximumHeight(120)
        self.log.setPlaceholderText("Здесь будет видно, что делает автопилот.")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(top)
        layout.addWidget(self.warning)
        layout.addWidget(self.list, 1)
        layout.addWidget(log_title)
        layout.addWidget(self.log)

        self._fill()
        self._show_last_report()

    # --- the list ---------------------------------------------------------

    def _fill(self) -> None:
        self.list.clear()
        self.rows.clear()
        for launcher_id in self.settings.ordered_ids():
            launcher = _LAUNCHERS[launcher_id]
            run_one = QPushButton("▶")
            run_one.setObjectName("Round")
            run_one.setToolTip(f"Обновить только {launcher.name}")
            run_one.clicked.connect(lambda _=False, lid=launcher_id: self.start(only=lid))
            exe = self._scan.get(launcher_id, (True, 0, None))[2]
            row = LauncherRow(launcher_id, launcher.name, launcher_icon(launcher_id, exe), checkable=True,
                              checked=self.settings.is_enabled(launcher_id), buttons=[run_one])
            row.toggled.connect(self._toggled)
            row.run_one = run_one
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, launcher_id)
            item.setSizeHint(QSize(0, 58))
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
            self.rows[launcher_id] = row
            self._show_found(launcher_id)
            if not self.settings.is_enabled(launcher_id):
                row.set_state("Выключен")

    def _show_found(self, launcher_id: str) -> None:
        row = self.rows.get(launcher_id)
        if row is None or launcher_id not in self._scan:
            return
        installed, games, exe = self._scan[launcher_id]
        row.set_subtitle(games_text(games) if installed else "не найден на этом ПК")
        row.set_icon(launcher_icon(launcher_id, exe))
        row.run_one.setEnabled(installed and not self.is_running)

    def _toggled(self, launcher_id: str, enabled: bool) -> None:
        self.settings.set_enabled(launcher_id, enabled)
        self._save()
        if not self.is_running:
            self.rows[launcher_id].set_state("" if enabled else "Выключен")

    def _order_changed(self) -> None:
        order = [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]
        self.settings.order = order
        self._save()
        self._fill()  # item widgets do not survive a drag, so the cards are rebuilt

    def move(self, launcher_id: str, index: int) -> None:
        order = [i for i in self.settings.ordered_ids() if i != launcher_id]
        order.insert(index, launcher_id)
        self.settings.order = order
        self._save()
        self._fill()

    def set_scan(self, result: ScanResult) -> None:
        for scan in result.scans:
            self._scan[scan.launcher_id] = (scan.installed, len(scan.games), scan.exe_path)
            self._show_found(scan.launcher_id)
        warning = environment_warning(result, self._runtime.demo)
        self.warning.setText(short_warning(result))
        self.warning.setToolTip(warning)
        self.warning.setVisible(bool(warning))

    def _save(self) -> None:
        try:
            save_settings(self.settings)
        except OSError as exc:
            self._status(f"Не удалось сохранить настройки: {exc}")

    # --- running ------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.isRunning())

    def _toggle(self) -> None:
        if self.is_running:
            self.stop()
        else:
            self.start()

    def start(self, scheduled: bool = False, quit_after: bool = False, only: str | None = None) -> None:
        if self.is_running:
            return
        self._quit_after = quit_after
        lock = QLockFile(str(data_dir() / "autopilot.lock"))
        if not lock.tryLock(100):
            self._append("Автопилот уже работает в другом окне GUpdater.")
            if quit_after:
                QTimer.singleShot(1000, QApplication.quit)
            return
        self._lock = lock
        for launcher_id, row in self.rows.items():
            if only:
                row.set_state("В очереди" if launcher_id == only else "")
            else:
                row.set_state("В очереди" if self.settings.is_enabled(launcher_id) else "Выключен")
            row.run_one.setEnabled(False)
        self.log.clear()
        name = _LAUNCHERS[only].name if only else ""
        self._append("Автопилот запущен" + (" по расписанию" if scheduled else "") + (f": только {name}" if only else ""))
        self._thread = AutopilotThread(self._runtime, self.settings, scheduled, only)
        self._thread.run_changed.connect(self._on_run_changed)
        self._thread.log_line.connect(self._append)
        self._thread.done.connect(self._on_done)
        self._thread.start()
        self.start_button.setText("Остановить")
        self.start_button.setObjectName("")
        self._restyle(self.start_button)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self._status("Автопилот работает…")
        self.running_changed.emit(True)

    def stop(self) -> None:
        if self.is_running:
            self._thread.stop_event.set()
            self.start_button.setEnabled(False)
            self._append("Останавливаю…")

    def wait_finished(self, msecs: int) -> None:
        if self._thread:
            self._thread.wait(msecs)

    @staticmethod
    def _restyle(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _append(self, line: str) -> None:
        self.log.appendPlainText(line)

    def _on_run_changed(self, run: LauncherRun) -> None:
        row = self.rows.get(run.launcher_id)
        if row is None:
            return
        color = OUTCOME_COLORS.get(run.outcome, BLUE) if run.outcome else BLUE
        text = run.outcome.text if run.outcome else run.phase
        tooltip = "\n".join([run.phase, *run.changes, *run.warnings])
        row.set_state(text, color, tooltip)

    def _on_done(self, runs, report_path: str, summary: str) -> None:
        if self._lock:
            self._lock.unlock()
            self._lock = None
        self._append(f"Готово: {summary}")
        self.start_button.setText("Обновить всё")
        self.start_button.setObjectName("Primary")
        self.start_button.setEnabled(True)
        self._restyle(self.start_button)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        for launcher_id in self.rows:
            self._show_found(launcher_id)
        self._show_last_report(summary)
        self._status(f"Автопилот закончил: {summary}")
        self.running_changed.emit(False)
        self.run_finished.emit()
        if self._quit_after:
            QTimer.singleShot(3000, QApplication.quit)

    def _show_last_report(self, summary: str = "") -> None:
        report = latest_report(reports_dir())
        self.report_button.setEnabled(report is not None)
        if report is None:
            self.last_run.setText("Ещё не запускался")
            return
        stamp = report.stem.removeprefix("автопилот-")
        when = f"{stamp[6:8]}.{stamp[4:6]} в {stamp[9:11]}:{stamp[11:13]}" if len(stamp) >= 13 else stamp
        self.last_run.setText(f"Последний запуск {when}" + (f" · {summary}" if summary else ""))

    def open_last_report(self) -> None:
        report = latest_report(reports_dir())
        if report:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(report)))
