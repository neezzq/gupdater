"""Tab "Входы": the club's saved logins (stage 3) and the wizard that saves them."""

from __future__ import annotations

import time
import traceback
from typing import Callable

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gupdater.autopilot.engine import close_launcher
from gupdater.autopilot.login_wizard import LoginWizard, WizardError
from gupdater.core.freeze import disk_freeze, freeze_advice
from gupdater.launchers import ALL_LAUNCHERS
from gupdater.launchers.base import Launcher
from gupdater.logins import Logins, Vault
from gupdater.report import ScanResult
from gupdater.settings import Settings, logins_dir, save_settings
from gupdater.ui.runtime import Runtime
from gupdater.ui.icons import launcher_icon
from gupdater.ui.launcher_row import LauncherRow
from gupdater.ui.style import GREEN
from gupdater.ui.theme import dark_title_bar
from gupdater.ui.warnings import environment_warning, short_warning

_BY_ID = {launcher.id: launcher for launcher in ALL_LAUNCHERS}
_KNOWN = {"steam", "epic", "riot", "battlenet"}


def make_logins(runtime: Runtime, settings: Settings) -> Logins:
    frozen = bool(disk_freeze(runtime.context_factory()))
    return Logins(Vault(logins_dir()), runtime.registry_factory(), enabled=settings.use_club_logins,
                  allow_refresh=not frozen)


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
        self._freeze = disk_freeze(runtime.context_factory())

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
        text = (f"GUpdater закроет {name} и запомнит, как он выглядит сейчас — с аккаунтом игрока или без него. "
                "Ничего не удаляется, никто не выходит из аккаунта.")
        if self._freeze:
            text += (f"\n\nНа этом ПК стоит {', '.join(self._freeze)}. Если защита сейчас включена, лучше сначала "
                     "выключить её: тогда сохранённый вход точно переживёт перезагрузку.")
        self._show("Шаг 1 из 2", text, "Начать")

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
        self._exe: dict[str, str | None] = {}
        self.rows: dict[str, LauncherRow] = {}

        self.use = QCheckBox("Подставлять вход клуба при обновлении")
        self.use.setChecked(settings.use_club_logins)
        self.use.setToolTip(
            "Игроки сидят под своими аккаунтами. GUpdater подставляет вход клуба только на время обновления\n"
            "и потом возвращает лаунчер как было — даже если после перезагрузки все вышли из аккаунтов.\n"
            "Вход хранится рядом с GUpdater, зашифрованный ключом этого компьютера."
        )
        self.use.toggled.connect(self._toggle_use)
        hint = QLabel("Только на время обновления — игроки вход клуба не видят.")
        hint.setObjectName("Muted")
        top = QHBoxLayout()
        top.addWidget(self.use)
        top.addSpacing(12)
        top.addWidget(hint, 1)

        self.warning = QLabel()
        self.warning.setObjectName("Warning")
        self.warning.setWordWrap(True)
        self.warning.hide()

        self.list = QListWidget()
        self.list.setObjectName("Cards")
        self.list.setSpacing(3)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(top)
        layout.addWidget(self.warning)
        layout.addWidget(self.list, 1)
        self.refresh()

    def _toggle_use(self, on: bool) -> None:
        self.settings.use_club_logins = on
        save_settings(self.settings)

    def set_scan(self, result: ScanResult) -> None:
        self._installed = {scan.launcher_id: scan.installed for scan in result.scans}
        self._exe = {scan.launcher_id: scan.exe_path for scan in result.scans}
        warning = environment_warning(result, self._runtime.demo)
        self.warning.setText(short_warning(result))
        self.warning.setToolTip(warning)
        self.warning.setVisible(bool(warning))
        self.refresh()

    def refresh(self) -> None:
        vault = Vault(logins_dir())
        self.list.clear()
        self.rows.clear()
        for launcher_id in self.settings.ordered_ids():
            launcher = _BY_ID[launcher_id]
            installed = self._installed.get(launcher_id, True)
            info = vault.info(launcher_id)
            remember = QPushButton("Запомнить заново" if info else "Запомнить")
            remember.setObjectName("" if info else "Primary")
            # In the demo only Steam pretends to sign in.
            remember.setEnabled(installed and (not self._runtime.demo or launcher_id == "steam"))
            remember.clicked.connect(lambda _=False, lid=launcher_id: self.remember(lid))
            forget = QPushButton("Забыть")
            forget.setVisible(bool(info))
            forget.clicked.connect(lambda _=False, lid=launcher_id: self.forget(lid))
            row = LauncherRow(launcher_id, launcher.name, launcher_icon(launcher_id, self._exe.get(launcher_id)),
                              buttons=[forget, remember])
            if info:
                saved = time.strftime("%d.%m в %H:%M", time.localtime(info.get("saved_at", 0)))
                row.set_subtitle(f"запомнен {saved}")
                row.set_state("Готов", GREEN)
            elif installed:
                row.set_subtitle("вход клуба не запомнен")
            else:
                row.set_subtitle("не найден на этом ПК")
            row.state.setToolTip(
                "Где лаунчер хранит вход, известно заранее" if launcher_id in _KNOWN
                else "Мастер сам найдёт, где лаунчер хранит вход"
            )
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 58))
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
            self.rows[launcher_id] = row

    def remember(self, launcher_id: str) -> None:
        dialog = LoginWizardDialog(_BY_ID[launcher_id], self._runtime, self)
        dialog.exec()
        self.refresh()

    def forget(self, launcher_id: str) -> None:
        name = _BY_ID[launcher_id].name
        answer = QMessageBox.question(self, "Забыть вход", f"Забыть вход клуба для {name}?")
        if answer == QMessageBox.StandardButton.Yes:
            Vault(logins_dir()).forget(launcher_id)
            self._status(f"Вход клуба для {name} забыт")
            self.refresh()
