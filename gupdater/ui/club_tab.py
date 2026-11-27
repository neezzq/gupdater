"""Tab "Клуб": every club PC with GUpdater, and buttons to update them."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QSize, QThread, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gupdater.club.protocol import ClubClient, ClubError, discover
from gupdater.settings import Settings, save_settings
from gupdater.ui.launcher_row import LauncherRow
from gupdater.ui.style import BLUE, GREEN, MUTED, ORANGE, RED
from gupdater.ui.theme import app_icon


class _Poll(QThread):
    """Asks every PC for its state (or runs one command) off the window's thread."""

    result = Signal(str, object, str)  # address, status dict or None, error

    def __init__(self, key: str, addresses: list[str], action: Callable[[ClubClient, str], dict] | None = None) -> None:
        super().__init__()
        self._client = ClubClient(key, timeout=2.5)
        self._addresses = addresses
        self._action = action

    def run(self) -> None:
        for address in self._addresses:
            try:
                if self._action:
                    self._action(self._client, address)
                self.result.emit(address, self._client.status(address), "")
            except ClubError as exc:
                self.result.emit(address, None, str(exc))


class _Discover(QThread):
    found = Signal(object)

    def __init__(self, key: str) -> None:
        super().__init__()
        self._key = key

    def run(self) -> None:
        try:
            self.found.emit(discover(self._key))
        except OSError:
            self.found.emit([])


def describe(status: dict | None, error: str) -> tuple[str, str]:
    """State text and colour of one PC."""
    if status is None:
        return (error or "нет связи").capitalize(), RED if error == "неверный ключ клуба" else MUTED
    if status.get("running"):
        return status.get("current") or "Обновляет", BLUE
    if status.get("free"):
        return "Свободен", GREEN
    return "Занят", ORANGE


class ClubTab(QWidget):
    def __init__(self, settings: Settings, status: Callable[[str], None]) -> None:
        super().__init__()
        self.settings = settings
        self._status = status
        self._jobs: list[QThread] = []
        self.rows: dict[str, LauncherRow] = {}
        self.states: dict[str, dict | None] = {}

        self.update_all = QPushButton("Обновить все")
        self.update_all.setObjectName("Primary")
        self.update_all.setToolTip("Каждый ПК начнёт, когда за ним никого нет, и остановится, если сядут")
        self.update_all.clicked.connect(self.run_all)
        self.find = QPushButton("Найти ПК")
        self.find.setToolTip("Найти в локальной сети компьютеры с GUpdater и тем же ключом клуба")
        self.find.clicked.connect(self.discover)
        self.address = QLineEdit()
        self.address.setPlaceholderText("IP, например 192.168.1.7")
        self.address.setMaximumWidth(220)
        self.address.returnPressed.connect(self.add_typed)
        add = QPushButton("Добавить")
        add.clicked.connect(self.add_typed)
        top = QHBoxLayout()
        top.addWidget(self.update_all)
        top.addWidget(self.find)
        top.addStretch(1)
        top.addWidget(self.address)
        top.addWidget(add)

        self.hint = QLabel()
        self.hint.setObjectName("Warning")
        self.hint.setWordWrap(True)

        self.list = QListWidget()
        self.list.setObjectName("Cards")
        self.list.setSpacing(3)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(top)
        layout.addWidget(self.hint)
        layout.addWidget(self.list, 1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(10_000)
        self._fill()
        self.refresh()

    # --- helpers -------------------------------------------------------------

    @property
    def key(self) -> str:
        return self.settings.club_key

    def _save(self) -> None:
        save_settings(self.settings)

    def _start(self, job: QThread) -> None:
        self._jobs = [j for j in self._jobs if j.isRunning()] + [job]
        job.finished.connect(lambda: self._jobs.remove(job) if job in self._jobs else None)
        job.start()

    def _fill(self) -> None:
        self.list.clear()
        self.rows.clear()
        no_key = not self.key
        self.hint.setText("Задайте ключ клуба в «Настройках» — одинаковый на всех ПК." if no_key else "")
        self.hint.setVisible(no_key)
        for address in self.settings.club_hosts:
            run = QPushButton("▶")
            run.setObjectName("Round")
            run.setToolTip("Обновить сейчас")
            run.clicked.connect(lambda _=False, a=address: self.command(a, now=True))
            stop = QPushButton("■")
            stop.setObjectName("Round")
            stop.setToolTip("Остановить")
            stop.clicked.connect(lambda _=False, a=address: self.command(a, stop=True))
            remove = QPushButton("✕")
            remove.setObjectName("Round")
            remove.setToolTip("Убрать из списка")
            remove.clicked.connect(lambda _=False, a=address: self.remove(a))
            row = LauncherRow(address, address, app_icon() or QIcon(), buttons=[run, stop, remove])
            row.set_subtitle(address)
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 58))
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
            self.rows[address] = row
            self._show(address, self.states.get(address), "")

    def _show(self, address: str, status: dict | None, error: str) -> None:
        row = self.rows.get(address)
        if row is None:
            return
        self.states[address] = status
        text, color = describe(status, error)
        row.set_state(text, color)
        if status:
            row.name.setText(status.get("name") or address)
            details = [address, f"версия {status.get('version', '?')}"]
            if status.get("last"):
                details.append(f"последний запуск: {status['last']}")
            row.set_subtitle(" · ".join(details))

    # --- actions ---------------------------------------------------------------

    def add(self, address: str) -> None:
        address = address.strip()
        if address and address not in self.settings.club_hosts:
            self.settings.club_hosts.append(address)
            self._save()
            self._fill()
            self.refresh()

    def add_typed(self) -> None:
        self.add(self.address.text())
        self.address.clear()

    def remove(self, address: str) -> None:
        self.settings.club_hosts = [a for a in self.settings.club_hosts if a != address]
        self.states.pop(address, None)
        self._save()
        self._fill()

    def refresh(self) -> None:
        if not self.key or not self.settings.club_hosts or any(j.isRunning() for j in self._jobs):
            return
        job = _Poll(self.key, list(self.settings.club_hosts))
        job.result.connect(self._show)
        self._start(job)

    def discover(self) -> None:
        if not self.key:
            return
        self.find.setEnabled(False)
        job = _Discover(self.key)
        job.found.connect(self._found)
        self._start(job)

    def _found(self, answers: list[dict]) -> None:
        self.find.setEnabled(True)
        added = 0
        for answer in answers:
            address = f"{answer['host']}:{answer['port']}" if answer.get("port") not in (None, 47800) else answer["host"]
            if address not in self.settings.club_hosts:
                self.settings.club_hosts.append(address)
                added += 1
        if added:
            self._save()
            self._fill()
            self.refresh()
        self._status(f"Найдено ПК: {len(answers)}, новых: {added}")

    def command(self, address: str, now: bool = False, stop: bool = False) -> None:
        if not self.key:
            return
        action = (lambda client, a: client.stop(a)) if stop else (lambda client, a: client.run(a, now))
        job = _Poll(self.key, [address], action)
        job.result.connect(self._show)
        self._start(job)

    def run_all(self) -> None:
        if not self.key or not self.settings.club_hosts:
            return
        job = _Poll(self.key, list(self.settings.club_hosts), lambda client, a: client.run(a, False))
        job.result.connect(self._show)
        self._start(job)
        self._status(f"Команда отправлена на {len(self.settings.club_hosts)} ПК — обновятся, когда освободятся")

    def shutdown(self) -> None:
        self._timer.stop()
        for job in self._jobs:
            job.wait(3000)


