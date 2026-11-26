"""The autopilot engine against a simulated PC: a fake clock and fake launchers."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

import pytest

from gupdater.autopilot.engine import ActivityMeter, Autopilot, EngineSettings, Outcome
from gupdater.autopilot.system import ProcInfo
from gupdater.core.context import SystemContext
from gupdater.core.models import Game, GameStatus
from gupdater.core.registry import NullRegistry
from gupdater.launchers.base import Launcher, LaunchSpec, Progress

MB = 1024 * 1024


@dataclass
class FakeProc:
    pid: int
    name: str
    started: float
    # (from, to, read bytes/s, write bytes/s), times relative to the process start
    profile: list[tuple[float, float, float, float]]
    graceful: bool = True
    exe: str | None = None

    def counters(self, t: float) -> tuple[int, int]:
        age = t - self.started
        read = written = 0.0
        for start, end, r, w in self.profile:
            span = max(0.0, min(age, end) - start)
            read += span * r
            written += span * w
        return int(read), int(written)


@dataclass
class FakeSystem:
    t: float = 0.0
    epoch: float = 1_700_000_000.0
    procs: dict[int, FakeProc] = field(default_factory=dict)
    started: list[tuple[str, ...]] = field(default_factory=list)
    closed: list[tuple[frozenset, bool]] = field(default_factory=list)
    on_start: dict = field(default_factory=dict)
    idle: object = None
    next_pid: int = 100

    def now(self):
        return self.t

    def wall_time(self):
        return self.epoch + self.t

    def sleep(self, seconds, stop):
        if stop.is_set():
            return False
        self.t += seconds
        return not stop.is_set()

    def start(self, command):
        self.started.append(tuple(command))
        handler = self.on_start.get(command[0])
        if handler:
            handler(self, tuple(command))

    def add_proc(self, name, profile=(), graceful=True, exe=None):
        self.next_pid += 1
        self.procs[self.next_pid] = FakeProc(self.next_pid, name, self.t, list(profile), graceful, exe)

    def processes(self):
        result = []
        for p in self.procs.values():
            r, w = p.counters(self.t)
            result.append(ProcInfo(p.pid, p.name, p.exe, self.epoch + p.started, r, w))
        return result

    def close(self, names, force):
        names = frozenset(names)
        self.closed.append((names, force))
        for pid, p in list(self.procs.items()):
            if p.name in names and (force or p.graceful):
                del self.procs[pid]

    def idle_seconds(self):
        return self.idle(self.t) if callable(self.idle) else self.idle


class FakeLauncher(Launcher):
    id = "fake"
    name = "Fake"

    def __init__(self, tmp_path, system, lid="fake", installed=True, update_done_at=None, progress=None, nudge=False):
        self.id, self.name = lid, lid.capitalize()
        self.process_names = (f"{lid}.exe",)
        self.exe = tmp_path / f"{lid}.exe"
        self.exe.write_text("")
        self.system = system
        self.installed = installed
        self.update_done_at = update_done_at
        self.progress_fn = progress
        self.nudge = nudge

    def _scan(self, ctx, result):
        result.installed = self.installed
        if self.installed:
            result.exe_path = str(self.exe)
            done = self.update_done_at is not None and self.system.t >= self.update_done_at
            result.games.append(Game(name="Game", game_id="g1", version="2" if done else "1"))

    def progress(self, ctx):
        return self.progress_fn() if self.progress_fn else Progress()

    def nudge_commands(self, ctx, scan, pending):
        if not self.nudge:
            return []
        return [((str(self.exe), f"validate/{gid}"), f"nudge {name}") for gid, name in pending]


def ctx_factory():
    return SystemContext(registry=NullRegistry(), env={}, drives=[])


def make_pilot(launchers, system, **kwargs):
    settings = EngineSettings(warmup_s=180, quiet_s=180, max_s=7200, poll_s=10)
    return Autopilot(launchers, ctx_factory, system, settings, **kwargs)


def downloads_on_start(name, profile, graceful=True):
    def handler(system, command):
        if len(command) == 1:  # the launcher itself, not a nudge
            system.add_proc(name, profile, graceful)
    return handler


def test_launcher_that_downloads_is_waited_for_then_closed(tmp_path):
    system = FakeSystem()
    launcher = FakeLauncher(tmp_path, system, update_done_at=330)
    system.on_start[str(launcher.exe)] = downloads_on_start("fake.exe", [(30, 330, 0, 10 * MB)])
    run = make_pilot([launcher], system).run()[0]

    assert system.started == [(str(launcher.exe),)]
    assert run.outcome is Outcome.UPDATED
    assert run.changes == ["Game: 1 → 2"]
    assert 330 + 180 <= system.t < 330 + 180 + 60  # quiet period after the last download, then closing
    assert run.written_bytes == 300 * 10 * MB
    assert system.closed[0] == (frozenset({"fake.exe"}), False)
    assert not system.procs


def test_nothing_to_update_finishes_after_warmup_and_quiet(tmp_path):
    system = FakeSystem()
    launcher = FakeLauncher(tmp_path, system)
    system.on_start[str(launcher.exe)] = downloads_on_start("fake.exe", [(0, 20, 2 * MB, 0)])  # start-up reads
    run = make_pilot([launcher], system).run()[0]
    assert run.outcome is Outcome.NOTHING
    assert 360 <= system.t < 400


def test_endless_download_times_out(tmp_path):
    system = FakeSystem()
    launcher = FakeLauncher(tmp_path, system)
    system.on_start[str(launcher.exe)] = downloads_on_start("fake.exe", [(0, 10**9, 0, 5 * MB)])
    run = make_pilot([launcher], system).run()[0]
    assert run.outcome is Outcome.TIMEOUT
    assert system.closed  # still closed, so the next launcher gets the bandwidth


def test_missing_disabled_and_already_running_launchers(tmp_path):
    system = FakeSystem()
    missing = FakeLauncher(tmp_path, system, lid="missing", installed=False)
    disabled = FakeLauncher(tmp_path, system, lid="off")
    running = FakeLauncher(tmp_path, system, lid="open")
    system.add_proc("open.exe")
    runs = make_pilot([missing, disabled, running], system).run(enabled=lambda lid: lid != "off")

    assert [r.outcome for r in runs] == [Outcome.SKIPPED, Outcome.SKIPPED, Outcome.NOTHING]
    assert runs[0].message == "не установлен"
    assert runs[1].message == "выключен в настройках"
    assert system.started == []  # the open launcher was not started again...
    assert system.closed == []   # ...and is left open, as it was


def test_launcher_ignoring_close_is_killed(tmp_path):
    system = FakeSystem()
    launcher = FakeLauncher(tmp_path, system)
    system.on_start[str(launcher.exe)] = downloads_on_start("fake.exe", [], graceful=False)
    pilot = make_pilot([launcher], system)
    pilot.run()
    assert [force for _, force in system.closed] == [False, True]
    assert any("принудительно" in line for line in pilot.log_lines)


def test_close_command_is_used_when_launcher_has_one(tmp_path):
    system = FakeSystem()
    launcher = FakeLauncher(tmp_path, system)
    launcher.launch_spec = lambda ctx, scan: LaunchSpec(
        command=(str(launcher.exe),), process_names=frozenset({"fake.exe"}), close_command=(str(launcher.exe), "-shutdown")
    )

    def handler(sys_, command):
        if command[-1] == "-shutdown":
            sys_.procs.clear()
        else:
            sys_.add_proc("fake.exe")

    system.on_start[str(launcher.exe)] = handler
    make_pilot([launcher], system).run()
    assert system.started[-1] == (str(launcher.exe), "-shutdown")
    assert system.closed == []


def test_stop_button_stops_this_and_skips_the_rest(tmp_path):
    system = FakeSystem()
    first = FakeLauncher(tmp_path, system, lid="first")
    second = FakeLauncher(tmp_path, system, lid="second")
    system.on_start[str(first.exe)] = downloads_on_start("first.exe", [(0, 10**6, 0, 5 * MB)])
    stop = threading.Event()

    def on_update(run):
        if run.phase.startswith("Скачивает"):
            stop.set()

    runs = make_pilot([first, second], system, stop=stop, on_update=on_update).run()
    assert [r.outcome for r in runs] == [Outcome.STOPPED, Outcome.STOPPED]
    assert system.closed == []  # a stopped launcher keeps downloading


def test_scheduled_run_stops_when_someone_sits_down(tmp_path):
    system = FakeSystem(idle=lambda t: 3 if t >= 100 else 10_000)
    launcher = FakeLauncher(tmp_path, system)
    system.on_start[str(launcher.exe)] = downloads_on_start("fake.exe", [(0, 10**6, 0, 5 * MB)])
    run = make_pilot([launcher], system, watch_user_input=True).run()[0]
    assert run.outcome is Outcome.STOPPED
    assert run.message == "за компьютер сели"
    assert system.t == 100


def test_stuck_update_is_nudged_then_finishes(tmp_path):
    system = FakeSystem()
    state = {"nudged_at": None}

    def progress():
        nudged = state["nudged_at"]
        if nudged is None:
            return Progress(busy=False, pending=[("570", "Dota 2")], logged_in=True)
        if system.t < nudged + 200:
            return Progress(busy=True, pending=[("570", "Dota 2")], logged_in=True)
        return Progress(busy=False, pending=[], logged_in=True)

    launcher = FakeLauncher(tmp_path, system, progress=progress, nudge=True)

    def handler(sys_, command):
        if command[1:] == ("validate/570",):
            state["nudged_at"] = sys_.t
            launcher.update_done_at = sys_.t + 200
        else:
            sys_.add_proc("fake.exe")

    system.on_start[str(launcher.exe)] = handler
    pilot = make_pilot([launcher], system)
    run = pilot.run()[0]

    assert state["nudged_at"] == 120  # start-up (60 s) + stuck for 60 s
    log = "\n".join(pilot.log_lines)
    assert "ждут обновления: Dota 2" in log and "nudge Dota 2" in log
    assert run.outcome is Outcome.UPDATED
    assert 310 + 180 <= system.t < 310 + 180 + 40  # last busy poll + quiet period + closing


def test_waiting_games_and_the_nudge_countdown_are_shown(tmp_path):
    system = FakeSystem()
    launcher = FakeLauncher(tmp_path, system, nudge=True,
                            progress=lambda: Progress(busy=False, pending=[("570", "Dota 2"), ("271590", "GTA V")]))
    system.on_start[str(launcher.exe)] = downloads_on_start("fake.exe", [])
    phases = []
    make_pilot([launcher], system, on_update=lambda run: phases.append(run.phase)).run()
    assert "Ждут обновления: Dota 2, GTA V · жду, начнёт ли лаунчер сам" in phases
    assert any(p.startswith("Ждут обновления: Dota 2, GTA V · если не начнёт сам, через") for p in phases)


def test_launcher_without_games_is_skipped(tmp_path):
    system = FakeSystem()
    launcher = FakeLauncher(tmp_path, system)
    launcher._scan_orig = launcher._scan

    def no_games(ctx, result):
        launcher._scan_orig(ctx, result)
        result.games.clear()

    launcher._scan = no_games
    run = make_pilot([launcher], system).run()[0]
    assert (run.outcome, run.message) == (Outcome.SKIPPED, "игр не найдено")
    assert system.started == []


def test_logged_out_launcher_fails_after_warmup(tmp_path):
    system = FakeSystem()
    launcher = FakeLauncher(tmp_path, system, progress=lambda: Progress(logged_in=False))
    system.on_start[str(launcher.exe)] = downloads_on_start("fake.exe", [])
    run = make_pilot([launcher], system).run()[0]
    assert run.outcome is Outcome.FAILED
    assert "вход" in run.message
    assert 180 <= system.t < 220  # right after the warm-up, plus closing


def test_pending_after_finish_is_reported(tmp_path):
    system = FakeSystem()
    launcher = FakeLauncher(tmp_path, system)
    launcher._scan_orig = launcher._scan

    def scan_with_pending(ctx, result):
        launcher._scan_orig(ctx, result)
        result.games[0].status = GameStatus.UPDATE_REQUIRED

    launcher._scan = scan_with_pending
    run = make_pilot([launcher], system).run()[0]
    assert run.outcome is Outcome.NOT_FINISHED
    assert run.message == "ждут обновления: Game"


def test_crash_in_one_launcher_does_not_stop_the_others(tmp_path):
    system = FakeSystem()
    broken = FakeLauncher(tmp_path, system, lid="broken")
    fine = FakeLauncher(tmp_path, system, lid="fine")

    def explode(ctx, scan):
        raise RuntimeError("boom")

    broken.launch_spec = explode
    runs = make_pilot([broken, fine], system).run()
    assert runs[0].outcome is Outcome.FAILED and "boom" in runs[0].message
    assert runs[1].outcome is Outcome.NOTHING


@pytest.mark.parametrize(
    "idle, game_running, expected, waited",
    [
        (lambda t: 5 if t < 300 else 10_000, False, True, 300),
        (lambda t: 5, False, False, 600),
        (lambda t: 10_000, True, False, 600),
    ],
)
def test_waiting_for_a_free_pc(tmp_path, idle, game_running, expected, waited):
    system = FakeSystem(idle=idle)
    if game_running:
        system.add_proc("dota2.exe", exe=str(tmp_path / "games" / "dota" / "dota2.exe"))
    pilot = make_pilot([], system)
    assert pilot.wait_for_free_pc(600, 600, [str(tmp_path / "games" / "dota")]) is expected
    assert system.t == waited


def test_activity_meter_counts_new_processes_and_folders(tmp_path):
    spec = LaunchSpec(command=("x",), process_names=frozenset({"a.exe"}), folders=(str(tmp_path / "agent"),))
    meter = ActivityMeter(spec)
    a = ProcInfo(1, "a.exe", None, 100.0, 10, 20)
    assert meter.sample([a], wall=200.0) == (0, 0)  # first sample is the baseline
    a2 = ProcInfo(1, "a.exe", None, 100.0, 15, 30)
    helper = ProcInfo(2, "agent.exe", str(tmp_path / "agent" / "agent.exe"), 250.0, 7, 8)
    other = ProcInfo(3, "game.exe", str(tmp_path / "game.exe"), 250.0, 1000, 1000)
    assert meter.sample([a2, helper, other], wall=300.0) == (5 + 7, 10 + 8)


def test_stuck_games_are_nudged_one_at_a_time_and_retried_once(tmp_path):
    """From a real run: two validate commands sent at once, Steam acted on one."""
    system = FakeSystem()
    state = {"done": set(), "busy_until": -1.0}

    def progress():
        pending = [(gid, name) for gid, name in (("271590", "GTA V"), ("570", "Dota 2")) if gid not in state["done"]]
        return Progress(busy=system.t < state["busy_until"], pending=pending, logged_in=True)

    launcher = FakeLauncher(tmp_path, system, progress=progress, nudge=True)
    nudge_times = []

    def handler(sys_, command):
        if len(command) == 1:
            sys_.add_proc("fake.exe")
            return
        gid = command[1].rsplit("/", 1)[1]
        nudge_times.append((gid, sys_.t))
        if gid == "570" and sum(1 for g, _ in nudge_times if g == "570") == 1:
            return  # the first nudge for Dota 2 is ignored, like on the real PC
        state["busy_until"] = sys_.t + 100
        state["done"].add(gid)

    system.on_start[str(launcher.exe)] = handler
    pilot = make_pilot([launcher], system)
    run = pilot.run()[0]

    assert [gid for gid, _ in nudge_times] == ["271590", "570", "570"]
    assert nudge_times[1][1] - nudge_times[0][1] >= 100  # the second game waits for the first to finish
    assert "(ещё раз)" in "\n".join(pilot.log_lines)
    assert run.outcome is Outcome.NOTHING  # nothing pending any more; versions did not change in this fake


def test_launcher_self_update_and_shrunken_game_are_reported(tmp_path):
    from gupdater.core.models import Game

    system = FakeSystem()
    launcher = FakeLauncher(tmp_path, system)
    launcher._scan_orig = launcher._scan

    def scan(ctx, result):
        launcher._scan_orig(ctx, result)
        late = system.t > 100
        result.version = "26.2" if late else "26.1"
        result.games = [Game(name="GTA V", game_id="g1", version="1", size_bytes=272 * 1024**2 if late else 120 * 1024**3)]

    launcher._scan = scan
    system.on_start[str(launcher.exe)] = downloads_on_start("fake.exe", [(10, 40, 0, 10 * MB)])
    pilot = make_pilot([launcher], system)
    run = pilot.run()[0]
    assert run.outcome is Outcome.UPDATED
    assert run.message == "обновился сам лаунчер, версии игр прежние"
    assert run.changes == ["Fake (сам лаунчер): 26.1 → 26.2"]
    assert run.warnings and "272 МБ вместо 120.0 ГБ" in run.warnings[0]
