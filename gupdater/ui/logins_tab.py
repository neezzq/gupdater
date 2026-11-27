"""Tab "Входы": the club's saved logins (stage 3) and the wizard that saves them."""

from __future__ import annotations

import time
import traceback
from typing import Callable

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gupdater.autopilot.engine import close_launcher
from gupdater.autopilot.login_wizard import LoginWizard, WizardError
from gupdater.launchers import ALL_LAUNCHERS
from gupdater.launchers.base import Launcher
from gupdater.logins import Logins, Vault
from gupdater.report import ScanResult
from gupdater.settings import Settings, logins_dir, save_settings
from gupdater.ui.runtime import Runtime
from gupdater.ui.style import GREEN, MUTED
from gupdater.ui.theme import dark_title_bar

_BY_ID = {launcher.id: launcher for launcher in ALL_LAUNCHERS}
_KNOWN = {"steam", "epic", "riot", "battlenet"}


def make_logins(runtime: Runtime, settings: Settings) -> Logins:
    return Logins(Vault(logins_dir()), runtime.registry_factory(), enabled=settings.use_club_logins)


def recover_logins(runtime: Runtime, settings: Settings, log: Callable[[str], None]) -> list[str]:
    """Put back what a crashed update left with the club's login in it."""
    logins = make_logins(runtime, settings)
    if not logins.vault.pending_aside():
        return []
    system = runtime.system_factory()

    def close(launcher_id: str) -> None:
        launcher = _BY_ID.get(launcher_id)
        if launcher is None:
            return
        ctx = runtime.context_factory()
        spec = launcher.launch_spec(ctx, launcher.scan(ctx))
        if spec:
            close_launcher(system, spec, log)

    return logins.recover(close, log)


class _Job(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, work: Callable[[], object]) -> None:
        super().__init__()
        self._work = work

    def run(self) -> None:
        try:
            self.done.emit(self._work())
        except WizardError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("Что-то пошло не так:\n" + traceback.format_exc(limit=3))


class LoginWizardDialog(QDialog):
    """Two steps: GUpdater notes the launcher as it is; the admin signs in with the club account."""

    def __init__(self, launcher: Launcher, runtime: Runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Запомнить вход — {launcher.name}")
        self.setMinimumWidth(520)
        self.launcher = launcher
        self.wizard = LoginWizard(
            launcher, runtime.context_factory, runtime.system_factory(), runtime.registry_factory(), Vault(logins_dir())
        )
        self._job: _Job | None = None
        self._stage = "start"

        self.step = QLabel()
        font = self.step.font()
        font.setPointSizeF(font.pointSizeF() + 4)
        font.setBold(True)
        self.step.setFont(font)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.hide()
        self.cancel_button = QPushButton("Отмена")
        self.next_button = QPushButton()
        self.next_button.setObjectName("Primary")
        self.cancel_button.clicked.connect(self._cancel)
        self.next_button.clicked.connect(self._next)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.next_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        layout.addWidget(self.step)
        layout.addWidget(self.body)
        layout.addWidget(self.busy)
        layout.addStretch(1)
        layout.addLayout(buttons)
        self._show_start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        dark_title_bar(self)

    def _show(self, step: str, body: str, next_text: str | None, cancel: bool = True) -> None:
        self.step.setText(step)
        self.body.setText(body)
        self.busy.hide()
        self.next_button.setVisible(next_text is not None)
        if next_text:
            self.next_button.setText(next_text)
            self.next_button.setEnabled(True)
        self.cancel_button.setVisible(cancel)
        self.cancel_button.setEnabled(True)

    def _working(self, text: str) -> None:
        self.body.setText(text)
        self.busy.show()
        self.next_button.setEnabled(False)
        self.cancel_button.setEnabled(False)

    def _run(self, work: Callable[[], object], done: Callable[[object], None]) -> None:
        self._job = _Job(work)
        self._job.done.connect(done)
        self._job.failed.connect(self._failed)
        self._job.start()

    def _show_start(self) -> None:
        name = self.launcher.name
        self._stage = "start"
        self._show(
            "Шаг 1 из 2",
            f"GUpdater закроет {name} и запомнит, как он выглядит сейчас — с аккаунтом игрока или без него. "
            "Ничего не удаляется, никто не выходит из аккаунта.",
            "Начать",
        )

    def _next(self) -> None:
        name = self.launcher.name
        if self._stage == "start":
            self._working(f"Закрываю {name} и запоминаю его состояние…")

            def work():
                self.wizard.prepare()
                self.wizard.open_launcher()

            self._run(work, lambda _: self._show_sign_in())
        elif self._stage == "sign_in":
            self._working(f"Закрываю {name} и сохраняю вход клуба…")
            self._run(self.wizard.finish, self._show_done)
        else:
            self.accept()

    def _show_sign_in(self) -> None:
        self._stage = "sign_in"
        self._show(
            "Шаг 2 из 2",
            f"{self.launcher.name} открыт. {self.launcher.login_hint}\n\n"
            "Когда вход выполнен и видна библиотека игр, подождите 10 секунд и нажмите «Готово». "
            "Выходить из аккаунта не нужно — GUpdater сам уберёт вход клуба из лаунчера.",
            "Готово",
        )

    def _show_done(self, spec) -> None:
        self._stage = "done"
        parts = [f"{len(spec.files)} файл(ов)"]
        if spec.registry_values:
            parts.append(f"{len(spec.registry_values)} значений реестра")
        self._show(
            "Вход клуба запомнен",
            f"Сохранено зашифрованным: {', '.join(parts)}. {self.launcher.name} снова в прежнем состоянии — "
            "игроки вход клуба не увидят. При обновлении GUpdater подставит его сам и потом уберёт.",
            "Закрыть",
            cancel=False,
        )

    def _failed(self, message: str) -> None:
        stage = self._stage
        self._stage = "done"
        self._show("Не получилось", message, "Закрыть", cancel=False)
        if stage == "sign_in":
            # Make sure no fresh club login is left in the launcher.
            self._run(self.wizard.cancel, lambda _: None)

    def _cancel(self) -> None:
        if self._stage == "sign_in":
            self._working("Отменяю: возвращаю лаунчер в прежнее состояние…")
            self._run(self.wizard.cancel, lambda _: self.reject())
        else:
            self.reject()

    def reject(self) -> None:
        if self._job and self._job.isRunning():
            return  # wait for the current step to finish
        super().reject()


class LoginsTab(QWidget):
    def __init__(self, runtime: Runtime, settings: Settings, status: Callable[[str], None]) -> None:
        super().__init__()
        self._runtime = runtime
        self.settings = settings
        self._status = status
        self._installed: dict[str, bool] = {}

        intro = QLabel(
            "Игроки сидят в лаунчерах под своими аккаунтами. GUpdater подставляет вход клуба только на время "
            "обновления и потом возвращает лаунчер в прежнее состояние. Вход хранится зашифрованным: прочитать его "
            "может только этот пользователь Windows на этом компьютере."
        )
        intro.setWordWrap(True)
        intro.setObjectName("Muted")
        self.use = QCheckBox("Подставлять вход клуба при обновлении")
        self.use.setChecked(settings.use_club_logins)
        self.use.toggled.connect(self._toggle_use)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Лаунчер", "Вход клуба", "Как ищется", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(3, 330)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(intro)
        layout.addWidget(self.use)
        layout.addWidget(self.table, 1)
        self.refresh()

    def _toggle_use(self, on: bool) -> None:
        self.settings.use_club_logins = on
        save_settings(self.settings)

    def set_scan(self, result: ScanResult) -> None:
        self._installed = {scan.launcher_id: scan.installed for scan in result.scans}
        self.refresh()

    def refresh(self) -> None:
        vault = Vault(logins_dir())
        ids = self.settings.ordered_ids()
        self.table.setRowCount(len(ids))
        for row, launcher_id in enumerate(ids):
            launcher = _BY_ID[launcher_id]
            installed = self._installed.get(launcher_id, True)
            info = vault.info(launcher_id)
            self.table.setItem(row, 0, QTableWidgetItem(launcher.name))
            if info:
                saved = time.strftime("%d.%m.%Y %H:%M", time.localtime(info.get("saved_at", 0)))
                text = f"Запомнен {saved}"
                if info.get("refreshed_at"):
                    text += time.strftime(" · обновлён %d.%m %H:%M", time.localtime(info["refreshed_at"]))
                color = GREEN
            else:
                text, color = ("Не запомнен" if installed else "Лаунчер не найден"), MUTED
            state = QTableWidgetItem(text)
            state.setForeground(QColor(color))
            self.table.setItem(row, 1, state)
            how = QTableWidgetItem("известно где" if launcher_id in _KNOWN else "найдёт мастер")
            how.setForeground(QColor(MUTED))
            how.setToolTip(
                "Где этот лаунчер хранит вход, известно заранее." if launcher_id in _KNOWN else
                "Мастер сравнит папки лаунчера до и после входа и запомнит то, что изменилось."
            )
            self.table.setItem(row, 2, how)

            cell = QWidget()
            buttons = QHBoxLayout(cell)
            buttons.setContentsMargins(4, 4, 4, 4)
            remember = QPushButton("Запомнить вход…" if not info else "Запомнить заново…")
            remember.setMinimumWidth(190)
            # In the demo only Steam pretends to sign in.
            remember.setEnabled(installed and (not self._runtime.demo or launcher_id == "steam"))
            remember.clicked.connect(lambda _=False, lid=launcher_id: self.remember(lid))
            forget = QPushButton("Забыть")
            forget.setEnabled(bool(info))
            forget.clicked.connect(lambda _=False, lid=launcher_id: self.forget(lid))
            buttons.addWidget(remember)
            buttons.addWidget(forget)
            self.table.setCellWidget(row, 3, cell)

    def remember(self, launcher_id: str) -> None:
        dialog = LoginWizardDialog(_BY_ID[launcher_id], self._runtime, self)
        dialog.exec()
        self.refresh()

    def forget(self, launcher_id: str) -> None:
        name = _BY_ID[launcher_id].name
        answer = QMessageBox.question(self, "Забыть вход", f"Забыть сохранённый вход клуба для {name}?")
        if answer == QMessageBox.StandardButton.Yes:
            Vault(logins_dir()).forget(launcher_id)
            self._status(f"Вход клуба для {name} забыт")
            self.refresh()

