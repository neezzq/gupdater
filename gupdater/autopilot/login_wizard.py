"""The steps of "Запомнить вход", without the window (the window drives them)."""

from __future__ import annotations

from typing import Callable

from gupdater.autopilot.engine import close_launcher
from gupdater.autopilot.system import System
from gupdater.core.context import SystemContext
from gupdater.core.registry import WritableRegistry
from gupdater.launchers.base import Launcher, LaunchSpec
from gupdater.logins import SessionSpec, State, Vault, apply, capture, learn, merge, read_areas, restrict


class WizardError(Exception):
    pass


class LoginWizard:
    """1) close the launcher and note its state; 2) open it for the admin to sign in;
    3) close it, keep the club's login, put the launcher back the way it was."""

    def __init__(
        self,
        launcher: Launcher,
        ctx_factory: Callable[[], SystemContext],
        system: System,
        registry: WritableRegistry,
        vault: Vault,
        log: Callable[[str], None] = lambda text: None,
    ) -> None:
        self.launcher = launcher
        self.ctx_factory = ctx_factory
        self.system = system
        self.registry = registry
        self.vault = vault
        self.log = log
        self._launch: LaunchSpec | None = None
        self._known = SessionSpec()
        self._areas = None
        self._before: State | None = None

    def _read(self) -> State:
        return merge(read_areas(self._areas, self.registry), capture(self._known, self.registry))

    def _close(self) -> None:
        if self._launch:
            close_launcher(self.system, self._launch, self.log)

    def prepare(self) -> None:
        ctx = self.ctx_factory()
        scan = self.launcher.scan(ctx)
        if not scan.installed:
            raise WizardError(f"{self.launcher.name} не найден на этом компьютере")
        self._launch = self.launcher.launch_spec(ctx, scan)
        if self._launch is None:
            raise WizardError(f"Не найден файл запуска {self.launcher.name}")
        self._known = self.launcher.session_spec(ctx, scan)
        self._areas = self.launcher.learn_areas(ctx, scan)
        if not self._known and not self._areas.folders and not self._areas.registry_keys:
            raise WizardError(f"Для {self.launcher.name} пока неизвестно, где искать вход")
        self._close()
        self._before = self._read()

    def open_launcher(self) -> None:
        if self._launch is None:
            raise WizardError("Сначала нужен первый шаг")
        self.system.start(self._launch.command)

    def finish(self) -> SessionSpec:
        if self._before is None:
            raise WizardError("Сначала нужен первый шаг")
        self._close()
        after = self._read()
        learned = learn(self._before, after)
        if not learned:
            raise WizardError(
                "Вход не изменился. Похоже, вход не выполнен или не сохранён: "
                "проверьте галочку «Запомнить меня» и пройдите мастер заново."
            )
        spec = self._known | learned
        self.vault.save_club(self.launcher.id, capture(spec, self.registry), spec, learned=not self._known)
        apply(restrict(self._before, spec), self.registry)  # back to how it was, club login taken out
        self._before = None
        return spec

    def cancel(self) -> None:
        """Interrupted after the admin signed in: undo whatever changed."""
        if self._before is None:
            return
        self._close()
        changed = learn(self._before, self._read())
        if changed:
            apply(restrict(self._before, changed), self.registry)
        self._before = None
