"""Tab "Настройки": timings, the daily schedule, the program itself."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QTime, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from gupdater.autopilot import scheduler
from gupdater.autopilot.system import start_detached
from gupdater.selfupdate import running_exe
from gupdater.settings import Settings, logins_dir, reports_dir, save_settings
from gupdater.ui.runtime import Runtime


def _spin(low: int, high: int, suffix: str, value: int, step: int = 1) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(low, high)
    spin.setSingleStep(step)
    spin.setSuffix(suffix)
    spin.setValue(min(max(value, low), high))
    spin.setMaximumWidth(150)
    return spin


class SettingsTab(QWidget):
    def __init__(self, runtime: Runtime, settings: Settings, status: Callable[[str], None]) -> None:
        super().__init__()
        self._runtime = runtime
        self.settings = settings
        self._status = status
        s = settings

        self.warmup = _spin(30, 900, " с", s.warmup_seconds, 15)
        self.warmup.setToolTip("Сколько ждать, пока лаунчер запустится и начнёт качать")
        self.quiet = _spin(30, 900, " с", s.quiet_seconds, 15)
        self.quiet.setToolTip("Столько секунд без загрузки — значит, лаунчер закончил")
        self.max_time = _spin(10, 600, " мин", s.max_minutes, 10)
        self.close_after = QCheckBox("Закрывать лаунчер после обновления")
        self.close_after.setChecked(s.close_after)
        self.steam_nudge = QCheckBox("Steam: подталкивать зависшие обновления")
        self.steam_nudge.setToolTip("Если игра ждёт обновления, а Steam сам не начал, запустить проверку её файлов")
        self.steam_nudge.setChecked(s.steam_validate_stuck)
        pilot = QFormLayout()
        pilot.setVerticalSpacing(10)
        pilot.addRow("Ждать запуска", self.warmup)
        pilot.addRow("Тишина до конца", self.quiet)
        pilot.addRow("Максимум на лаунчер", self.max_time)
        pilot.addRow(self.close_after)
        pilot.addRow(self.steam_nudge)
        pilot_box = QGroupBox("Автопилот")
        pilot_box.setLayout(pilot)

        self.schedule_on = QCheckBox("Каждый день в")
        self.schedule_on.setChecked(s.schedule_enabled)
        self.schedule_time = QTimeEdit(QTime.fromString(s.schedule_time, "HH:mm"))
        self.schedule_time.setDisplayFormat("HH:mm")
        self.schedule_time.setMaximumWidth(110)
        self.idle = _spin(1, 120, " мин", s.idle_minutes)
        self.idle.setToolTip("Компьютер считается свободным, если мышь и клавиатуру не трогали столько минут")
        self.wait_free = _spin(1, 24, " ч", s.wait_free_hours)
        self.apply_button = QPushButton("Применить")
        self.apply_button.clicked.connect(self.apply_schedule)
        self.task_state = QLabel()
        self.task_state.setObjectName("Muted")
        when = QHBoxLayout()
        when.addWidget(self.schedule_on)
        when.addWidget(self.schedule_time)
        when.addStretch(1)
        apply_row = QHBoxLayout()
        apply_row.addWidget(self.apply_button)
        apply_row.addWidget(self.task_state, 1)
        schedule = QFormLayout()
        schedule.setVerticalSpacing(10)
        schedule.addRow(when)
        schedule.addRow("Свободен, если мышь не трогали", self.idle)
        schedule.addRow("Ждать свободный ПК до", self.wait_free)
        schedule.addRow(apply_row)
        schedule_box = QGroupBox("Расписание")
        schedule_box.setLayout(schedule)

        self.check_app = QCheckBox("Проверять новые версии GUpdater")
        self.check_app.setChecked(s.check_app_updates)
        reports = QPushButton("Отчёты")
        reports.clicked.connect(lambda: self._open(reports_dir()))
        logins = QPushButton("Входы")
        logins.clicked.connect(lambda: self._open(logins_dir()))
        demo = QPushButton("Демо-режим")
        demo.setToolTip("Открыть GUpdater с ненастоящими лаунчерами — посмотреть, как всё работает")
        demo.clicked.connect(self.open_demo)
        demo.setEnabled(not runtime.demo)
        folders = QHBoxLayout()
        folders.addWidget(QLabel("Папки:"))
        folders.addWidget(reports)
        folders.addWidget(logins)
        folders.addStretch(1)
        folders.addWidget(demo)
        program = QVBoxLayout()
        program.setSpacing(10)
        program.addWidget(self.check_app)
        program.addLayout(folders)
        program_box = QGroupBox("Программа")
        program_box.setLayout(program)

        columns = QHBoxLayout()
        columns.setSpacing(14)
        left = QVBoxLayout()
        left.addWidget(pilot_box)
        left.addWidget(program_box)
        left.addStretch(1)
        right = QVBoxLayout()
        right.addWidget(schedule_box)
        right.addStretch(1)
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.addLayout(columns)

        for spin in (self.warmup, self.quiet, self.max_time, self.idle, self.wait_free):
            spin.valueChanged.connect(self._save)
        for box in (self.close_after, self.steam_nudge, self.check_app, self.schedule_on):
            box.toggled.connect(self._save)
        self.schedule_time.timeChanged.connect(self._save)

        self._heal_schedule()
        self._refresh_task_state()

    def _open(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _save(self) -> None:
        s = self.settings
        s.warmup_seconds = self.warmup.value()
        s.quiet_seconds = self.quiet.value()
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

    def open_demo(self) -> None:
        exe = running_exe()
        command = [str(exe), "--demo"] if exe else [sys.executable, "-m", "gupdater", "--demo"]
        start_detached(command)

    # --- schedule -------------------------------------------------------------

    def _heal_schedule(self) -> None:
        """A frozen system disk forgets the scheduled task on reboot: put it back."""
        exe = running_exe()
        if self._runtime.demo or exe is None or not self.settings.schedule_enabled:
            return
        try:
            if not scheduler.task_exists():
                scheduler.create_task(exe, self.settings.schedule_time)
                self._status("Задание расписания пропало (видимо, откат диска) — восстановил")
        except scheduler.SchedulerError as exc:
            self._status(f"Не удалось восстановить расписание: {exc}")

    def _refresh_task_state(self) -> None:
        if self._runtime.demo:
            self.task_state.setText("в демо не создаётся")
            return
        try:
            exists = scheduler.task_exists()
        except scheduler.SchedulerError as exc:
            self.task_state.setText(str(exc))
            return
        self.task_state.setText("задание создано" if exists else "задания нет")

    def apply_schedule(self) -> None:
        self._save()
        if self._runtime.demo:
            return
        exe = running_exe()
        if exe is None:
            QMessageBox.warning(self, "Расписание", "Расписание работает только в GUpdater.exe.")
            return
        try:
            if self.settings.schedule_enabled:
                scheduler.create_task(exe, self.settings.schedule_time)
                self._status(f"Расписание: каждый день в {self.settings.schedule_time}, когда ПК свободен")
            else:
                scheduler.delete_task()
                self._status("Расписание выключено")
        except scheduler.SchedulerError as exc:
            QMessageBox.warning(self, "Не получилось", str(exc))
        self._refresh_task_state()
