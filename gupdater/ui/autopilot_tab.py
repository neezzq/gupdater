"""Tab "Автопилот": the launcher queue, its settings, the schedule and the log."""

from __future__ import annotations

import threading
import traceback
from dataclasses import replace

from PySide6.QtCore import QLockFile, Qt, QThread, QTime, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from gupdater.autopilot import scheduler
from gupdater.autopilot.engine import Autopilot, EngineSettings, LauncherRun, Outcome, Stopped
from gupdater.autopilot.report import build_run_report, latest_report, save_run_report, summary_line
from gupdater.launchers import ALL_LAUNCHERS
from gupdater.report import ScanResult, sanitize, scan_all
from gupdater.selfupdate import running_exe
from gupdater.settings import Settings, data_dir, reports_dir, save_settings
from gupdater.ui.runtime import Runtime
from gupdater.ui.style import BLUE, MUTED, OUTCOME_COLORS

_LAUNCHERS = {launcher.id: launcher for launcher in ALL_LAUNCHERS}


class AutopilotThread(QThread):
    run_changed = Signal(object)  # LauncherRun (a copy)
    log_line = Signal(str)
    done = Signal(object, str, str)  # runs, report path, summary

    def __init__(self, runtime: Runtime, settings: Settings, scheduled: bool) -> None:
        super().__init__()
        self._runtime = runtime
        self._settings = settings
        self._scheduled = scheduled
        self.stop_event = threading.Event()

    def run(self) -> None:
        try:
            self._run()
        except Exception:
            self.log_line.emit("Ошибка автопилота:\n" + traceback.format_exc())
            self.done.emit([], "", "автопилот завершился с ошибкой")

    def _run(self) -> None:
        settings, runtime = self._settings, self._runtime
        system = runtime.system_factory()
        pilot = Autopilot(
            [_LAUNCHERS[i] for i in settings.ordered_ids()],
            runtime.context_factory,
            system,
            EngineSettings.from_settings(settings),
            stop=self.stop_event,
            on_update=lambda run: self.run_changed.emit(replace(run, changes=list(run.changes))),
            on_log=self.log_line.emit,
            watch_user_input=self._scheduled,
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
            pilot.run(enabled=settings.is_enabled)
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
        self._found: dict[str, str] = {}
        self._loading = False

        intro = QLabel(
            "Автопилот по очереди открывает лаунчеры, ждёт, пока каждый скачает обновления, и закрывает его. "
            "Перед этим войдите в лаунчеры и включите в них автообновление игр."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {MUTED};")

        self.start_button = QPushButton("▶  Запустить сейчас")
        self.stop_button = QPushButton("■  Остановить")
        self.open_report_button = QPushButton("Открыть последний отчёт")
        self.open_folder_button = QPushButton("Папка с отчётами")
        self.start_button.clicked.connect(lambda: self.start())
        self.stop_button.clicked.connect(self.stop)
        self.open_report_button.clicked.connect(self.open_last_report)
        self.open_folder_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(reports_dir()))))
        self.stop_button.setEnabled(False)
        self.last_run = QLabel()

        top = QHBoxLayout()
        for button in (self.start_button, self.stop_button):
            top.addWidget(button)
        top.addSpacing(12)
        top.addWidget(self.last_run, 1)
        top.addWidget(self.open_report_button)
        top.addWidget(self.open_folder_button)

        # Queue of launchers.
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Лаунчер", "На этом ПК", "Состояние"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)
        self.up_button = QPushButton("↑ Выше")
        self.down_button = QPushButton("↓ Ниже")
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button.clicked.connect(lambda: self._move(1))
        order_buttons = QHBoxLayout()
        order_buttons.addWidget(QLabel("Галочка — обновлять. Порядок — кто первый:"))
        order_buttons.addStretch(1)
        order_buttons.addWidget(self.up_button)
        order_buttons.addWidget(self.down_button)
        queue_box = QGroupBox("Очередь")
        queue_layout = QVBoxLayout(queue_box)
        queue_layout.addWidget(self.table)
        queue_layout.addLayout(order_buttons)

        # Settings.
        self.warmup = self._spin(1, 30, " мин", settings.warmup_minutes)
        self.quiet = self._spin(1, 30, " мин", settings.quiet_minutes)
        self.max_time = self._spin(10, 600, " мин", settings.max_minutes)
        self.close_after = QCheckBox("Закрывать лаунчер, когда он закончит")
        self.close_after.setChecked(settings.close_after)
        self.steam_nudge = QCheckBox("Steam: если игра сама не обновляется — запустить проверку файлов")
        self.steam_nudge.setChecked(settings.steam_validate_stuck)
        self.check_app = QCheckBox("Проверять новые версии GUpdater при запуске")
        self.check_app.setChecked(settings.check_app_updates)
        form = QFormLayout()
        form.addRow("Ждать начала загрузки:", self.warmup)
        form.addRow("Закончил, если не качает:", self.quiet)
        form.addRow("Не дольше на один лаунчер:", self.max_time)
        form.addRow(self.close_after)
        form.addRow(self.steam_nudge)
        form.addRow(self.check_app)
        settings_box = QGroupBox("Настройки")
        settings_box.setLayout(form)

        # Schedule.
        self.schedule_on = QCheckBox("Запускать каждый день в")
        self.schedule_on.setChecked(settings.schedule_enabled)
        self.schedule_time = QTimeEdit(QTime.fromString(settings.schedule_time, "HH:mm"))
        self.schedule_time.setDisplayFormat("HH:mm")
        self.idle = self._spin(1, 120, " мин", settings.idle_minutes)
        self.wait_free = self._spin(1, 24, " ч", settings.wait_free_hours)
        self.apply_schedule_button = QPushButton("Применить расписание")
        self.apply_schedule_button.clicked.connect(self.apply_schedule)
        self.task_state = QLabel()
        self.task_state.setWordWrap(True)
        when = QHBoxLayout()
        when.addWidget(self.schedule_on)
        when.addWidget(self.schedule_time)
        when.addStretch(1)
        schedule_form = QFormLayout()
        schedule_form.addRow(when)
        schedule_form.addRow("ПК свободен, если мышь не трогали:", self.idle)
        schedule_form.addRow("Ждать свободный ПК не дольше:", self.wait_free)
        schedule_form.addRow(self.apply_schedule_button, self.task_state)
        schedule_box = QGroupBox("Каждый день автоматически")
        schedule_box.setLayout(schedule_form)

        right = QVBoxLayout()
        right.addWidget(settings_box)
        right.addWidget(schedule_box)
        right.addStretch(1)
        middle = QHBoxLayout()
        middle.addWidget(queue_box, 3)
        middle.addLayout(right, 2)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setPlaceholderText("Здесь будет видно, что делает автопилот.")
        log_box = QGroupBox("Журнал")
        log_layout = QVBoxLayout(log_box)
        log_layout.addWidget(self.log)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.addWidget(intro)
        layout.addLayout(top)
        layout.addLayout(middle)
        layout.addWidget(log_box, 1)

        for widget in (self.warmup, self.quiet, self.max_time, self.idle, self.wait_free):
            widget.valueChanged.connect(self._save)
        for box in (self.close_after, self.steam_nudge, self.check_app, self.schedule_on):
            box.toggled.connect(self._save)
        self.schedule_time.timeChanged.connect(self._save)

        self._fill_table()
        self._show_last_report()
        self._refresh_task_state()

    # --- widgets ------------------------------------------------------------

    @staticmethod
    def _spin(low: int, high: int, suffix: str, value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setSuffix(suffix)
        spin.setValue(min(max(value, low), high))
        return spin

    def _fill_table(self) -> None:
        self._loading = True
        ids = self.settings.ordered_ids()
        self.table.setRowCount(len(ids))
        for row, launcher_id in enumerate(ids):
            name = QTableWidgetItem(_LAUNCHERS[launcher_id].name)
            name.setData(Qt.ItemDataRole.UserRole, launcher_id)
            name.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
            name.setCheckState(Qt.CheckState.Checked if self.settings.is_enabled(launcher_id) else Qt.CheckState.Unchecked)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(self._found.get(launcher_id, "…")))
            state = QTableWidgetItem("" if self.settings.is_enabled(launcher_id) else "Выключен")
            state.setForeground(QBrush(QColor(MUTED)))
            self.table.setItem(row, 2, state)
        self._loading = False

    def _row_of(self, launcher_id: str) -> int:
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == launcher_id:
                return row
        return -1

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != 0:
            return
        launcher_id = item.data(Qt.ItemDataRole.UserRole)
        enabled = item.checkState() == Qt.CheckState.Checked
        self.settings.set_enabled(launcher_id, enabled)
        self._save()
        state = self.table.item(item.row(), 2)
        if state and not self.is_running:
            state.setText("" if enabled else "Выключен")

    def _move(self, step: int) -> None:
        row = self.table.currentRow()
        ids = self.settings.ordered_ids()
        target = row + step
        if row < 0 or not 0 <= target < len(ids) or self.is_running:
            return
        ids[row], ids[target] = ids[target], ids[row]
        self.settings.order = ids
        self._save()
        self._fill_table()
        self.table.selectRow(target)

    def set_scan(self, result: ScanResult) -> None:
        for scan in result.scans:
            if scan.installed:
                text = f"Установлен · игр: {len(scan.games)}"
            else:
                text = "Не найден"
            self._found[scan.launcher_id] = text
            row = self._row_of(scan.launcher_id)
            if row >= 0:
                item = self.table.item(row, 1)
                item.setText(text)
                if scan.installed:
                    item.setData(Qt.ItemDataRole.ForegroundRole, None)
                else:
                    item.setForeground(QBrush(QColor(MUTED)))

    def _save(self) -> None:
        if self._loading:
            return
        s = self.settings
        s.warmup_minutes = self.warmup.value()
        s.quiet_minutes = self.quiet.value()
        s.max_minutes = self.max_time.value()
        s.close_after = self.close_after.isChecked()
        s.steam_validate_stuck = self.steam_nudge.isChecked()
        s.check_app_updates = self.check_app.isChecked()
        s.schedule_enabled = self.schedule_on.isChecked()
        s.schedule_time = self.schedule_time.time().toString("HH:mm")
        s.idle_minutes = self.idle.value()
        s.wait_free_hours = self.wait_free.value()
        try:
            save_settings(s)
        except OSError as exc:
            self._status(f"Не удалось сохранить настройки: {exc}")

    # --- schedule -----------------------------------------------------------

    def _refresh_task_state(self) -> None:
        if self._runtime.demo:
            self.task_state.setText("В демо-режиме расписание не создаётся")
            return
        try:
            exists = scheduler.task_exists()
        except scheduler.SchedulerError as exc:
            self.task_state.setText(str(exc))
            return
        if exists:
            self.task_state.setText("В планировщике Windows задание есть")
        else:
            self.task_state.setText("Задания в планировщике Windows нет")

    def apply_schedule(self) -> None:
        self._save()
        if self._runtime.demo:
            QMessageBox.information(self, "Демо", "В демо-режиме расписание не создаётся.")
            return
        exe = running_exe()
        if exe is None:
            QMessageBox.warning(self, "Расписание", "Расписание можно включить только из GUpdater.exe.")
            return
        try:
            if self.settings.schedule_enabled:
                scheduler.create_task(exe, self.settings.schedule_time)
                message = (
                    f"Готово. Каждый день в {self.settings.schedule_time} GUpdater дождётся, пока за компьютером "
                    f"никого нет {self.settings.idle_minutes} мин, и обновит игры.\n\n"
                    "Компьютер должен быть включён, а пользователь Windows — в системе."
                )
            else:
                scheduler.delete_task()
                message = "Расписание выключено."
        except scheduler.SchedulerError as exc:
            QMessageBox.warning(self, "Не получилось", str(exc))
        else:
            QMessageBox.information(self, "Расписание", message)
        self._refresh_task_state()

    # --- running ------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.isRunning())

    def start(self, scheduled: bool = False, quit_after: bool = False) -> None:
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
        self._save()
        self._fill_table()
        for row in range(self.table.rowCount()):
            launcher_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if self.settings.is_enabled(launcher_id):
                self.table.item(row, 2).setText("В очереди")
        self.log.clear()
        self._append("Автопилот запущен" + (" по расписанию" if scheduled else ""))
        self._thread = AutopilotThread(self._runtime, self.settings, scheduled)
        self._thread.run_changed.connect(self._on_run_changed)
        self._thread.log_line.connect(self._append)
        self._thread.done.connect(self._on_done)
        self._thread.start()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        for widget in (self.up_button, self.down_button):
            widget.setEnabled(False)
        self._status("Автопилот работает…")
        self.running_changed.emit(True)

    def stop(self) -> None:
        if self.is_running:
            self._thread.stop_event.set()
            self.stop_button.setEnabled(False)
            self._append("Останавливаю…")

    def wait_finished(self, msecs: int) -> None:
        if self._thread:
            self._thread.wait(msecs)

    def _append(self, line: str) -> None:
        self.log.appendPlainText(line)

    def _on_run_changed(self, run: LauncherRun) -> None:
        row = self._row_of(run.launcher_id)
        if row < 0:
            return
        item = self.table.item(row, 2)
        item.setText(run.phase)
        color = OUTCOME_COLORS.get(run.outcome, BLUE) if run.outcome else BLUE
        item.setForeground(QBrush(QColor(color)))
        if run.changes:
            item.setToolTip("\n".join(run.changes))

    def _on_done(self, runs, report_path: str, summary: str) -> None:
        if self._lock:
            self._lock.unlock()
            self._lock = None
        self._append(f"Готово: {summary}")
        if report_path:
            self._append(f"Отчёт: {report_path}")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        for widget in (self.up_button, self.down_button):
            widget.setEnabled(True)
        self._show_last_report(summary)
        self._status(f"Автопилот закончил: {summary}")
        self.running_changed.emit(False)
        self.run_finished.emit()
        if self._quit_after:
            QTimer.singleShot(3000, QApplication.quit)

    def _show_last_report(self, summary: str = "") -> None:
        report = latest_report(reports_dir())
        self.open_report_button.setEnabled(report is not None)
        if report is None:
            self.last_run.setText("Автопилот ещё не запускался")
        else:
            stamp = report.stem.removeprefix("автопилот-")
            when = f"{stamp[6:8]}.{stamp[4:6]} {stamp[9:11]}:{stamp[11:13]}" if len(stamp) >= 13 else stamp
            self.last_run.setText(f"Последний запуск: {when}" + (f" — {summary}" if summary else ""))

    def open_last_report(self) -> None:
        report = latest_report(reports_dir())
        if report:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(report)))
