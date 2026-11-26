"""Tab "Игры на этом ПК": launchers and games found, and the recon report."""

from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gupdater.core.context import SystemContext
from gupdater.core.models import GameStatus, LauncherScan, format_size
from gupdater.report import ScanResult, build_report, default_report_name, run_scan
from gupdater.ui.runtime import Runtime
from gupdater.ui.style import MUTED, STATUS_COLORS


class ScanThread(QThread):
    done = Signal(object, object)  # (SystemContext, ScanResult)
    failed = Signal(str)

    def __init__(self, runtime: Runtime) -> None:
        super().__init__()
        self._runtime = runtime

    def run(self) -> None:
        try:
            ctx = self._runtime.context_factory()
            self.done.emit(ctx, run_scan(ctx))
        except Exception:
            self.failed.emit(traceback.format_exc())


class GamesTab(QWidget):
    scanned = Signal(object)  # ScanResult
    scan_finished = Signal()

    def __init__(self, runtime: Runtime, status: callable) -> None:
        super().__init__()
        self._runtime = runtime
        self._status = status
        self._thread: ScanThread | None = None
        self._report = ""
        self._result: ScanResult | None = None

        hint = QLabel(
            "Что установлено на этом компьютере. Отчёт можно сохранить и прислать в чат — "
            "в нём нет имён аккаунтов, почты и данных входа."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {MUTED};")

        self.rescan_button = QPushButton("Сканировать заново")
        self.save_button = QPushButton("Сохранить отчёт…")
        self.copy_button = QPushButton("Скопировать отчёт")
        self.rescan_button.clicked.connect(self.rescan)
        self.save_button.clicked.connect(self.save_report)
        self.copy_button.clicked.connect(self.copy_report)
        self.summary = QLabel()

        buttons = QHBoxLayout()
        for button in (self.rescan_button, self.save_button, self.copy_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self.summary)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Лаунчер / игра", "Статус", "Версия", "Размер", "Где находится"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        head = self.tree.header()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        head.setStretchLastSection(True)
        for column, width in enumerate((270, 330, 130, 80)):
            self.tree.setColumnWidth(column, width)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.addWidget(hint)
        layout.addLayout(buttons)
        layout.addWidget(self.tree, 1)
        self._set_busy(True)

    @property
    def report_text(self) -> str:
        return self._report

    @property
    def result(self) -> ScanResult | None:
        return self._result

    def rescan(self) -> None:
        if self._thread and self._thread.isRunning():
            return
        self._set_busy(True)
        self._status("Ищу лаунчеры и игры…")
        self._thread = ScanThread(self._runtime)
        self._thread.done.connect(self._on_done)
        self._thread.failed.connect(self._on_failed)
        self._thread.start()

    def _set_busy(self, busy: bool) -> None:
        self.rescan_button.setEnabled(not busy)
        self.save_button.setEnabled(not busy and bool(self._report))
        self.copy_button.setEnabled(not busy and bool(self._report))

    def _on_done(self, ctx: SystemContext, result: ScanResult) -> None:
        self._result = result
        self._report = build_report(result, ctx)
        self._populate(result)
        found = sum(1 for s in result.scans if s.installed)
        games = sum(len(s.games) for s in result.scans)
        updates = sum(s.updates_needed for s in result.scans)
        self.summary.setText(
            f"Лаунчеров: {found} из {len(result.scans)} · игр: {games}"
            + (f" · нужно обновить: {updates}" if updates else "")
        )
        self._status(f"Поиск игр закончен ({result.finished_at:%H:%M})")
        self._set_busy(False)
        self.scanned.emit(result)
        self.scan_finished.emit()

    def _on_failed(self, details: str) -> None:
        self._set_busy(False)
        self._status("Поиск игр завершился с ошибкой")
        QMessageBox.critical(self, "Ошибка", f"Не удалось выполнить поиск:\n\n{details}")
        self.scan_finished.emit()

    def _populate(self, result: ScanResult) -> None:
        self.tree.clear()
        bold = QFont(self.tree.font())
        bold.setBold(True)
        for scan in result.scans:
            item = QTreeWidgetItem([scan.name, launcher_state(scan), "", "", scan.exe_path or "не найден"])
            item.setFont(0, bold)
            if not scan.installed:
                for col in range(5):
                    item.setForeground(col, QBrush(QColor(MUTED)))
            elif scan.error:
                item.setForeground(1, QBrush(QColor(STATUS_COLORS[GameStatus.BROKEN])))
            tips = scan.notes + ([f"Ошибка: {scan.error}"] if scan.error else [])
            if tips:
                item.setToolTip(0, "\n".join(tips))
                item.setToolTip(1, "\n".join(tips))
            item.setToolTip(4, scan.exe_path or "")
            self.tree.addTopLevelItem(item)

            for game in scan.games:
                child = QTreeWidgetItem(
                    [game.name, game.status.text, game.version or "", format_size(game.size_bytes), game.install_path or ""]
                )
                child.setForeground(1, QBrush(QColor(STATUS_COLORS[game.status])))
                if game.note:
                    child.setToolTip(1, game.note)
                child.setToolTip(2, game.version or "")
                child.setToolTip(4, game.install_path or "")
                item.addChild(child)
            for note in scan.notes:
                child = QTreeWidgetItem(["ℹ " + note])
                child.setForeground(0, QBrush(QColor(MUTED)))
                item.addChild(child)
                child.setFirstColumnSpanned(True)  # only works once the item is in the tree
            item.setExpanded(scan.installed)

    def save_report(self) -> None:
        if not self._result:
            return
        desktop = Path.home() / "Desktop"
        folder = desktop if desktop.is_dir() else Path.home()
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить отчёт", str(folder / default_report_name(self._result)), "Текстовый файл (*.txt)"
        )
        if not path:
            return
        try:
            Path(path).write_text(self._report, encoding="utf-8-sig")
        except OSError as exc:
            QMessageBox.warning(self, "Не удалось сохранить", str(exc))
            return
        self._status(f"Отчёт сохранён: {path}")
        QMessageBox.information(self, "Отчёт сохранён", f"Отчёт сохранён в файл:\n{path}\n\nПришлите этот файл в чат.")

    def copy_report(self) -> None:
        if self._report:
            QGuiApplication.clipboard().setText(self._report)
            self._status("Отчёт скопирован — вставьте его в чат (Ctrl+V)")


def launcher_state(scan: LauncherScan) -> str:
    if not scan.installed:
        return "Не найден"
    parts = ["Установлен"]
    if scan.running:
        parts.append("запущен")
    parts.append(f"игр: {len(scan.games)}")
    if scan.updates_needed:
        parts.append(f"обновить: {scan.updates_needed}")
    if scan.error:
        parts.append("есть ошибка")
    return " · ".join(parts)
