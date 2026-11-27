"""Autopilot: open each launcher in turn, wait while it downloads, close it.

A launcher counts as busy while its processes read or write a lot (that is
what downloading and installing look like from outside) or while the
launcher itself says an update is running (Steam does, in its manifests).
Once it has been quiet for a while it is considered finished.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Sequence

from gupdater.autopilot.system import ProcInfo, System
from gupdater.core.context import SystemContext
from gupdater.core.models import GameStatus, LauncherScan, format_size
from gupdater.launchers.base import Launcher, LaunchSpec, Progress
from gupdater.logins import Logins
from gupdater.settings import Settings


class Outcome(str, Enum):
    UPDATED = "updated"
    NOTHING = "nothing"
    NOT_FINISHED = "not_finished"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"
    FAILED = "failed"
    STOPPED = "stopped"

    @property
    def text(self) -> str:
        return _OUTCOME_TEXT[self]


_OUTCOME_TEXT = {
    Outcome.UPDATED: "Обновлено",
    Outcome.NOTHING: "Обновлять нечего",
    Outcome.NOT_FINISHED: "Обновилось не всё",
    Outcome.TIMEOUT: "Не дождался конца",
    Outcome.SKIPPED: "Пропущен",
    Outcome.FAILED: "Ошибка",
    Outcome.STOPPED: "Остановлен",
}


@dataclass
class EngineSettings:
    warmup_s: float = 180
    quiet_s: float = 180
    max_s: float = 7200
    poll_s: float = 5
    activity_bytes_per_s: float = 1024 * 1024
    close_after: bool = True
    nudge_stuck: bool = True
    nudge_after_s: float = 60  # the launcher's start-up and login, before stuck games are watched
    stuck_s: float = 60        # pending but idle this long -> nudge the launcher
    max_nudges: int = 2        # per game; Steam may ignore a nudge that comes while it is busy
    close_wait_s: float = 30   # how long a launcher gets to quit politely
    # Written this much without a visible version change still counts as an update.
    heavy_write_bytes: int = 200 * 1024 * 1024
    # Launchers that report their own state (Steam) need much less waiting once signed in.
    login_settle_s: float = 30    # signed in this long = it has looked for updates
    precise_quiet_s: float = 30   # nothing pending and nothing running this long = finished

    @classmethod
    def from_settings(cls, s: Settings) -> "EngineSettings":
        return cls(
            warmup_s=s.warmup_seconds,
            quiet_s=s.quiet_seconds,
            max_s=s.max_minutes * 60,
            activity_bytes_per_s=s.activity_kb_per_s * 1024,
            close_after=s.close_after,
            nudge_stuck=s.steam_validate_stuck,
        )


@dataclass
class LauncherRun:
    launcher_id: str
    name: str
    phase: str = "В очереди"
    outcome: Outcome | None = None
    message: str = ""
    started_at: float | None = None   # wall clock
    finished_at: float | None = None
    io_bytes: int = 0
    written_bytes: int = 0
    rate: float = 0.0
    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        if self.started_at is None or self.finished_at is None:
            return 0.0
        return self.finished_at - self.started_at


class Stopped(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


class ActivityMeter:
    """Bytes read/written by a launcher's processes between two samples."""

    def __init__(self, spec: LaunchSpec) -> None:
        self.names = {n.lower() for n in spec.process_names}
        self.folders = [_norm(f) + os.sep for f in spec.folders if f]
        self._prev: dict[int, tuple[float, int, int]] = {}
        self._last_wall: float | None = None

    def matches(self, proc: ProcInfo) -> bool:
        if proc.name in self.names:
            return True
        return bool(proc.exe) and any(_norm(proc.exe).startswith(f) for f in self.folders)

    def matching(self, procs: Sequence[ProcInfo]) -> list[ProcInfo]:
        return [p for p in procs if self.matches(p)]

    def sample(self, procs: Sequence[ProcInfo], wall: float) -> tuple[int, int]:
        """(read, written) bytes since the previous sample."""
        current = {
            p.pid: (p.create_time, p.read_bytes, p.write_bytes)
            for p in self.matching(procs)
            if p.read_bytes is not None and p.write_bytes is not None
        }
        read = written = 0
        for pid, (created, r, w) in current.items():
            prev = self._prev.get(pid)
            if prev and prev[0] == created:
                read += max(0, r - prev[1])
                written += max(0, w - prev[2])
            elif self._last_wall is not None and created >= self._last_wall:
                read, written = read + r, written + w  # started since the last sample
        self._prev = current
        self._last_wall = wall
        return read, written


def version_changes(before: LauncherScan, after: LauncherScan) -> list[str]:
    old = {g.game_id: g for g in before.games}
    changes = []
    for game in after.games:
        prev = old.get(game.game_id)
        if prev and prev.version and game.version and prev.version != game.version:
            changes.append(f"{game.name}: {prev.version} → {game.version}")
    return changes


def size_warnings(before: LauncherScan, after: LauncherScan) -> list[str]:
    """Games that suddenly take far less space: worth a look by a human."""
    old = {g.game_id: g for g in before.games}
    warnings = []
    for game in after.games:
        prev = old.get(game.game_id)
        if prev and prev.size_bytes and game.size_bytes and prev.size_bytes > 1024**3 and game.size_bytes < prev.size_bytes / 2:
            warnings.append(
                f"«{game.name}» теперь занимает {format_size(game.size_bytes)} вместо {format_size(prev.size_bytes)} — "
                "проверьте, что игра на месте и запускается"
            )
    return warnings


def format_rate(bytes_per_s: float) -> str:
    if bytes_per_s >= 1024**2:
        return f"{bytes_per_s / 1024**2:.1f} МБ/с"
    return f"{bytes_per_s / 1024:.0f} КБ/с"


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600} ч {seconds % 3600 // 60} мин"
    if seconds >= 60:
        return f"{seconds // 60} мин {seconds % 60:02d} с"
    return f"{seconds} с"


class Autopilot:
    def __init__(
        self,
        launchers: Sequence[Launcher],
        ctx_factory: Callable[[], SystemContext],
        system: System,
        settings: EngineSettings,
        *,
        stop: threading.Event | None = None,
        on_update: Callable[[LauncherRun], None] | None = None,
        on_log: Callable[[str], None] | None = None,
        watch_user_input: bool = False,
        logins: "Logins | None" = None,
    ) -> None:
        self.launchers = list(launchers)
        self.ctx_factory = ctx_factory
        self.system = system
        self.s = settings
        self.stop = stop or threading.Event()
        self.on_update = on_update or (lambda run: None)
        self.on_log = on_log or (lambda line: None)
        self.watch_user_input = watch_user_input
        self.logins = logins
        self.log_lines: list[str] = []
        self.runs = [LauncherRun(l.id, l.name) for l in self.launchers]

    # --- helpers ----------------------------------------------------------

    def log(self, text: str, run: LauncherRun | None = None) -> None:
        stamp = time.strftime("%H:%M:%S", time.localtime(self.system.wall_time()))
        line = f"{stamp} {run.name + ': ' if run else ''}{text}"
        self.log_lines.append(line)
        self.on_log(line)

    def _set(self, run: LauncherRun, phase: str) -> None:
        if run.phase != phase:
            run.phase = phase
            self.on_update(run)

    def _finish(self, run: LauncherRun, outcome: Outcome, message: str = "") -> None:
        run.outcome = outcome
        run.message = message
        run.phase = outcome.text + (f": {message}" if message else "")
        run.finished_at = self.system.wall_time()
        self.log(run.phase, run)
        self.on_update(run)

    def _wait(self, seconds: float) -> None:
        if not self.system.sleep(seconds, self.stop):
            raise Stopped("остановлено вручную")
        if self.watch_user_input:
            idle = self.system.idle_seconds()
            if idle is not None and idle < min(seconds, self.s.poll_s) + 2:
                raise Stopped("за компьютер сели")

    # --- waiting for a free PC ---------------------------------------------

    def wait_for_free_pc(self, idle_needed_s: float, max_wait_s: float, game_folders: Sequence[str]) -> bool:
        """True once nobody has touched the PC for a while and no game runs."""
        folders = [_norm(f) + os.sep for f in game_folders if f]
        deadline = self.system.now() + max_wait_s
        announced = False
        while True:
            idle = self.system.idle_seconds()
            playing = [
                p.name for p in self.system.processes()
                if p.exe and any(_norm(p.exe).startswith(f) for f in folders)
            ]
            if (idle is None or idle >= idle_needed_s) and not playing:
                if announced:
                    self.log("компьютер свободен, начинаю")
                return True
            if not announced:
                reason = f"запущена игра ({playing[0]})" if playing else "за компьютером кто-то есть"
                self.log(f"жду, пока компьютер освободится: {reason}")
                announced = True
            if self.system.now() >= deadline:
                self.log("компьютер так и не освободился — обновление отложено")
                return False
            if not self.system.sleep(60, self.stop):
                raise Stopped("остановлено вручную")

    def skip_all(self, reason: str) -> None:
        for run in self.runs:
            if run.outcome is None:
                self._finish(run, Outcome.SKIPPED, reason)

    # --- the run -------------------------------------------------------------

    def run(self, enabled: Callable[[str], bool] = lambda launcher_id: True) -> list[LauncherRun]:
        for launcher, run in zip(self.launchers, self.runs):
            if self.stop.is_set():
                self._finish(run, Outcome.STOPPED, "остановлено вручную")
                continue
            if not enabled(launcher.id):
                self._finish(run, Outcome.SKIPPED, "выключен в настройках")
                continue
            try:
                self._run_one(launcher, run)
            except Stopped as stopped:
                self._finish(run, Outcome.STOPPED, stopped.reason)
                self.stop.set()
            except Exception as exc:  # one launcher must not break the whole run
                self._finish(run, Outcome.FAILED, f"{type(exc).__name__}: {exc}")
        return self.runs

    def _run_one(self, launcher: Launcher, run: LauncherRun) -> None:
        s, system = self.s, self.system
        run.started_at = system.wall_time()
        self._set(run, "Проверяю…")
        before = launcher.scan(self.ctx_factory())
        if not before.installed:
            self._finish(run, Outcome.SKIPPED, "не установлен")
            return
        if launcher.skip_without_games and not before.games:
            self._finish(run, Outcome.SKIPPED, "игр не найдено")
            return
        spec = launcher.launch_spec(self.ctx_factory(), before)
        if spec is None:
            self._finish(run, Outcome.SKIPPED, "не найден файл запуска")
            return

        meter = ActivityMeter(spec)
        was_running = bool(meter.matching(system.processes()))
        session = self.logins.session_for(launcher.id) if self.logins else None
        if session and was_running:
            self.log("закрываю, чтобы подставить вход клуба", run)
            self._close(spec, meter, run)
            was_running = False
        if session:
            try:
                session.swap_in()
            except Exception as exc:  # a broken vault must not stop the update
                self.log(f"не удалось подставить вход клуба: {exc}", run)
                session = None
            else:
                self.log("подставил вход клуба", run)

        login_failed = False
        try:
            outcome, message, login_failed = self._watch(launcher, run, spec, meter, before, was_running)
            launch_failed = outcome is Outcome.FAILED and message.startswith("не удалось запустить")
            # With the club's login in, the launcher must close so the login can be taken out.
            if not launch_failed and ((s.close_after and not was_running) or session):
                self._close(spec, meter, run)
        finally:
            if session:
                if meter.matching(system.processes()):
                    self._close(spec, meter, run)
                kept = session.swap_out(keep_renewed_login=not login_failed)
                self.log("убрал вход клуба, лаунчер снова в прежнем состоянии"
                         + (" (обновлённый вход клуба сохранён)" if kept else ""), run)
        if outcome is Outcome.FAILED and message.startswith("не удалось запустить"):
            self._finish(run, outcome, message)
            return

        after = launcher.scan(self.ctx_factory())
        game_changes = version_changes(before, after)
        self_changed = bool(before.version and after.version and before.version != after.version)
        run.changes = game_changes + ([f"{launcher.name} (сам лаунчер): {before.version} → {after.version}"] if self_changed else [])
        run.warnings = size_warnings(before, after)
        for line in run.changes:
            self.log(line, run)
        for line in run.warnings:
            self.log("⚠ " + line, run)
        if outcome is None:
            still = [g.name for g in after.games if g.status is GameStatus.UPDATE_REQUIRED]
            if still:
                outcome, message = Outcome.NOT_FINISHED, "ждут обновления: " + ", ".join(still)
            elif game_changes:
                outcome = Outcome.UPDATED
            elif self_changed:
                outcome, message = Outcome.UPDATED, "обновился сам лаунчер, версии игр прежние"
            elif run.written_bytes >= s.heavy_write_bytes:
                outcome = Outcome.UPDATED
                message = f"версии игр не изменились, но лаунчер записал ≈{format_size(run.written_bytes)}"
            else:
                outcome = Outcome.NOTHING
        self._finish(run, outcome, message)

    def _watch(
        self, launcher: Launcher, run: LauncherRun, spec: LaunchSpec, meter: ActivityMeter,
        before: LauncherScan, was_running: bool,
    ) -> tuple[Outcome | None, str, bool]:
        """Start the launcher (unless open) and wait until it is done: (outcome or None, message, login failed)."""
        s, system = self.s, self.system
        meter.sample(system.processes(), system.wall_time())
        if was_running:
            self.log("уже был открыт — жду, пока он докачает", run)
        else:
            self.log("запускаю", run)
            try:
                system.start(spec.command)
            except OSError as exc:
                return Outcome.FAILED, f"не удалось запустить: {exc}", False

        outcome: Outcome | None = None
        message = ""
        t0 = previous = system.now()
        last_active: float | None = None
        stuck_since: float | None = None
        nudges: dict[str, int] = {}
        progress = Progress()
        told_pending = told_login = False
        login_since: float | None = None
        while True:
            self._wait(s.poll_s)
            t = system.now()
            elapsed = t - t0
            read, written = meter.sample(system.processes(), system.wall_time())
            run.rate = (read + written) / max(t - previous, 1e-6)
            previous = t
            run.io_bytes += read + written
            run.written_bytes += written
            try:
                progress = launcher.progress(self.ctx_factory())
            except Exception:
                progress = Progress()

            busy = run.rate >= s.activity_bytes_per_s or progress.busy is True
            if busy:
                last_active = t
            if progress.logged_in and login_since is None:
                login_since = t
            # A launcher that reports what it does (Steam) is done waiting soon after sign-in.
            precise = progress.busy is not None and progress.logged_in is True
            warm_at = t0 + s.warmup_s
            if precise and login_since is not None:
                warm_at = min(warm_at, login_since + s.login_settle_s)
            warmed_up = t >= warm_at
            quiet_needed = s.precise_quiet_s if precise and not progress.pending else s.quiet_s
            if progress.logged_in and not told_login:
                self.log("вход в аккаунт выполнен", run)
                told_login = True
            if progress.pending and not told_pending:
                self.log("ждут обновления: " + ", ".join(name for _, name in progress.pending), run)
                told_pending = True

            if warmed_up and progress.logged_in is False:
                return Outcome.FAILED, "не выполнен вход в аккаунт, скачивать обновления некому", True

            stuck = [(gid, name) for gid, name in progress.pending if nudges.get(gid, 0) < s.max_nudges]
            if s.nudge_stuck and elapsed >= s.nudge_after_s and stuck and progress.busy is not True:
                stuck_since = stuck_since if stuck_since is not None else t
                if t - stuck_since >= s.stuck_s:
                    # One game at a time: Steam drops a second command that arrives while it is busy.
                    gid, name = stuck[0]
                    again = " (ещё раз)" if nudges.get(gid) else ""
                    for command, text in launcher.nudge_commands(self.ctx_factory(), before, [(gid, name)]):
                        self.log(text + again, run)
                        try:
                            system.start(command)
                        except OSError as exc:
                            self.log(f"не получилось: {exc}", run)
                    nudges[gid] = nudges.get(gid, 0) + 1
                    stuck_since = None
                    last_active = t  # give the launcher a full quiet period to react
            else:
                stuck_since = None

            quiet_since = max(last_active if last_active is not None else t0, warm_at)
            waiting = ", ".join(name for _, name in progress.pending)
            if busy:
                self._set(run, f"Скачивает · {format_rate(run.rate)}")
            elif stuck and s.nudge_stuck:
                if stuck_since is None:
                    self._set(run, f"Ждут обновления: {waiting} · жду, начнёт ли лаунчер сам")
                else:
                    left = max(0.0, s.stuck_s - (t - stuck_since))
                    self._set(run, f"Ждут обновления: {waiting} · если не начнёт сам, через {format_duration(left)} подтолкну")
            elif progress.pending:
                self._set(run, f"Ждут обновления: {waiting}")
            elif not warmed_up:
                self._set(run, "Запускается и ищет обновления…")
            else:
                left = max(0.0, quiet_needed - (t - quiet_since))
                self._set(run, f"Похоже, закончил · проверяю ещё {format_duration(left)}")

            waiting_for_nudge = s.nudge_stuck and bool(stuck)
            if warmed_up and t - quiet_since >= quiet_needed and progress.busy is not True and not waiting_for_nudge:
                break
            if elapsed >= s.max_s:
                outcome, message = Outcome.TIMEOUT, f"качал дольше {format_duration(s.max_s)}"
                break
        return outcome, message, False

    def _close(self, spec: LaunchSpec, meter: ActivityMeter, run: LauncherRun) -> None:
        self._set(run, "Закрываю…")
        close_launcher(self.system, spec, lambda text: self.log(text, run), self.s.close_wait_s)


def close_launcher(system: System, spec: LaunchSpec, log: Callable[[str], None], wait_s: float = 30) -> None:
    """Ask the launcher to quit; if it only hides in the tray, end it."""
    meter = ActivityMeter(spec)
    if not meter.matching(system.processes()):
        return
    names = {p.name for p in meter.matching(system.processes())} | set(meter.names)
    if spec.close_command:
        try:
            system.start(spec.close_command)
        except OSError:
            system.close(names, force=False)
    else:
        system.close(names, force=False)
    deadline = system.now() + wait_s
    while system.now() < deadline:
        if not system.sleep(2, threading.Event()):
            break
        if not meter.matching(system.processes()):
            log("закрыт")
            return
    left = {p.name for p in meter.matching(system.processes())}
    if left:
        log("сам не закрылся (видимо, свернулся в трей) — закрываю принудительно")
        system.close(left, force=True)
        # Give the system a moment to let the files go.
        system.sleep(2, threading.Event())
