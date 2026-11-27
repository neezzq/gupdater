"""Stage 3: the club's login is put in only for the update."""

from __future__ import annotations

import threading

from gupdater.core.registry import REG_BINARY, REG_DWORD, REG_SZ, DictRegistry
from gupdater.logins import (
    LearnAreas,
    Logins,
    SessionSpec,
    State,
    Vault,
    apply,
    capture,
    dumps,
    learn,
    loads,
    read_areas,
)
from tests.test_autopilot import MB, FakeLauncher, FakeSystem, downloads_on_start, make_pilot

KEY = r"HKCU\Software\Valve\Steam"


def test_capture_apply_and_serialize_round_trip(tmp_path):
    token = tmp_path / "cfg" / "token.vdf"
    token.parent.mkdir()
    token.write_bytes(b"club-token")
    reg = DictRegistry()
    reg.set_value(KEY, "AutoLoginUser", REG_SZ, "club")
    reg.set_value(KEY, "Blob", REG_BINARY, b"\x00\x01")
    spec = SessionSpec(files=(str(token), str(tmp_path / "missing.txt")),
                       registry_values=((KEY, "AutoLoginUser"), (KEY, "Blob"), (KEY, "Absent")))

    state = loads(dumps(capture(spec, reg)))
    assert state.files == {str(token): b"club-token", str(tmp_path / "missing.txt"): None}
    assert state.registry[(KEY, "Blob")] == (REG_BINARY, b"\x00\x01")
    assert state.registry[(KEY, "Absent")] is None

    # Somebody else signs in; applying the snapshot brings the club back exactly.
    token.write_bytes(b"player-token")
    (tmp_path / "missing.txt").write_text("player only")
    reg.set_value(KEY, "AutoLoginUser", REG_SZ, "player")
    reg.set_value(KEY, "Absent", REG_DWORD, 1)
    apply(state, reg)
    assert token.read_bytes() == b"club-token"
    assert not (tmp_path / "missing.txt").exists()
    assert reg.values(KEY) == {"AutoLoginUser": "club", "Blob": b"\x00\x01"}


def test_learning_finds_what_signing_in_changed(tmp_path):
    app = tmp_path / "Launcher"
    for rel, content in {
        "settings.ini": "lang=ru",
        "session.json": '{"token": null}',
        "launcher.exe": "MZ",                       # programs are never part of a login
        "Cache/data_1": "x",                         # caches neither
        "app.log": "started",                        # nor logs
        "Local Storage/leveldb/CURRENT": "MANIFEST-1",
        "Local Storage/leveldb/000003.log": "a",     # ...except inside a database folder
        "Local Storage/leveldb/MANIFEST-1": "m",
    }.items():
        path = app / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    reg = DictRegistry({r"HKCU\Software\Vendor\Launcher": {"Lang": "ru"}})
    areas = LearnAreas(folders=(str(app),), registry_keys=(r"HKCU\Software\Vendor",))

    before = read_areas(areas, reg)
    assert str(app / "launcher.exe") not in before.files and str(app / "Cache" / "data_1") not in before.files
    assert str(app / "app.log") not in before.files

    (app / "session.json").write_text('{"token": "abc"}')
    (app / "Cache" / "data_2").write_text("y")
    (app / "app.log").write_text("signed in")
    (app / "Local Storage" / "leveldb" / "000003.log").write_text("auth=1")
    (app / "new_cookie.db").write_text("c")
    reg.set_value(r"HKCU\Software\Vendor\Launcher\Auth", "Token", REG_BINARY, b"t")
    after = read_areas(areas, reg)

    spec = learn(before, after)
    assert set(spec.files) == {
        str(app / "session.json"),
        str(app / "new_cookie.db"),
        str(app / "Local Storage" / "leveldb" / "CURRENT"),
        str(app / "Local Storage" / "leveldb" / "000003.log"),
        str(app / "Local Storage" / "leveldb" / "MANIFEST-1"),
    }
    assert spec.registry_values == ((r"HKCU\Software\Vendor\Launcher\Auth", "Token"),)


def test_vault_keeps_logins_encrypted_and_tracks_set_aside_state(tmp_path):
    vault = Vault(tmp_path / "vault")
    spec = SessionSpec(files=("a",))
    vault.save_club("steam", State(files={"a": b"club"}), spec, learned=False)
    assert vault.has_club("steam") and vault.spec("steam") == spec
    raw = (tmp_path / "vault" / "steam.club").read_bytes()
    assert raw.startswith(b"GUPDATER-V2") and b"club" not in raw
    assert vault.load_club("steam").files == {"a": b"club"}

    vault.save_aside("steam", State(files={"a": b"player"}))
    assert vault.pending_aside() == ["steam"]
    vault.drop_aside("steam")
    assert vault.pending_aside() == []

    vault.forget("steam")
    assert not vault.has_club("steam")
    assert not list((tmp_path / "vault").glob("steam.club*"))


def _setup(tmp_path, token_text="player-token"):
    token = tmp_path / "launcher-data" / "token"
    token.parent.mkdir()
    token.write_text(token_text)
    reg = DictRegistry()
    vault = Vault(tmp_path / "vault")
    spec = SessionSpec(files=(str(token),))
    vault.save_club("fake", State(files={str(token): b"club-token"}), spec, learned=True)
    return token, reg, vault


def test_autopilot_puts_club_login_in_and_takes_it_out(tmp_path):
    token, reg, vault = _setup(tmp_path)
    system = FakeSystem()
    launcher = FakeLauncher(tmp_path, system, update_done_at=100)
    seen = {}

    def handler(sys_, command):
        seen["token_at_start"] = token.read_text()
        sys_.add_proc("fake.exe", [(10, 100, 0, 10 * MB)])
        token.write_text("club-token-renewed")  # the launcher renews its login while running

    system.on_start[str(launcher.exe)] = handler
    pilot = make_pilot([launcher], system, logins=Logins(vault, reg))
    run = pilot.run()[0]

    assert seen["token_at_start"] == "club-token"
    assert token.read_text() == "player-token"          # the player's state is back
    assert vault.pending_aside() == []
    assert vault.load_club("fake").files[str(token)] == b"club-token-renewed"  # renewed login kept
    log = "\n".join(pilot.log_lines)
    assert "подставил вход клуба" in log and "обновлённый вход клуба сохранён" in log
    assert run.changes == ["Game: 1 → 2"]


def test_open_launcher_is_closed_before_the_swap(tmp_path):
    token, reg, vault = _setup(tmp_path)
    system = FakeSystem()
    launcher = FakeLauncher(tmp_path, system)
    system.add_proc("fake.exe")  # a player's launcher is still open
    system.on_start[str(launcher.exe)] = downloads_on_start("fake.exe", [])
    pilot = make_pilot([launcher], system, logins=Logins(vault, reg))
    pilot.run()
    assert system.closed  # closed first, then started with the club's login
    assert system.started == [(str(launcher.exe),)]
    assert token.read_text() == "player-token"


def test_stopping_mid_update_still_takes_the_club_login_out(tmp_path):
    token, reg, vault = _setup(tmp_path)
    system = FakeSystem()
    launcher = FakeLauncher(tmp_path, system)
    system.on_start[str(launcher.exe)] = downloads_on_start("fake.exe", [(0, 10**6, 0, 5 * MB)])
    stop = threading.Event()
    pilot = make_pilot([launcher], system, stop=stop, logins=Logins(vault, reg),
                       on_update=lambda run: stop.set() if run.phase.startswith("Скачивает") else None)
    run = pilot.run()[0]
    assert run.outcome.name == "STOPPED"
    assert token.read_text() == "player-token"
    assert not system.procs  # the launcher had to close so the login could be taken out


def test_disabled_logins_change_nothing(tmp_path):
    token, reg, vault = _setup(tmp_path)
    system = FakeSystem()
    launcher = FakeLauncher(tmp_path, system)
    system.on_start[str(launcher.exe)] = lambda sys_, cmd: (seen.append(token.read_text()), sys_.add_proc("fake.exe"))
    seen: list[str] = []
    make_pilot([launcher], system, logins=Logins(vault, reg, enabled=False)).run()
    assert seen == ["player-token"]


def test_recovery_after_a_crash_mid_update(tmp_path):
    token, reg, vault = _setup(tmp_path)
    vault.save_aside("fake", State(files={str(token): b"player-token"}))
    token.write_text("club-token")  # GUpdater died with the club's login in place
    closed, lines = [], []
    recovered = Logins(vault, reg).recover(close=closed.append, log=lines.append)
    assert recovered == ["fake"] and closed == ["fake"]
    assert token.read_text() == "player-token"
    assert vault.pending_aside() == []


def _wizard_setup(tmp_path, player_token: str | None = "player-token"):
    from gupdater.autopilot.login_wizard import LoginWizard
    from gupdater.core.context import SystemContext
    from gupdater.core.registry import NullRegistry

    data = tmp_path / "AppData" / "Launcher"
    data.mkdir(parents=True)
    (data / "settings.ini").write_text("lang=ru")
    token = data / "session.dat"
    if player_token is not None:
        token.write_text(player_token)
    system = FakeSystem()
    launcher = FakeLauncher(tmp_path, system)
    launcher.learn_areas = lambda ctx, scan: LearnAreas(folders=(str(data),))
    system.add_proc("fake.exe")  # open with a player's login
    system.on_start[str(launcher.exe)] = lambda sys_, cmd: sys_.add_proc("fake.exe")
    reg = DictRegistry()
    vault = Vault(tmp_path / "vault")
    ctx_factory = lambda: SystemContext(registry=NullRegistry(), env={}, drives=[])
    wizard = LoginWizard(launcher, ctx_factory, system, reg, vault)
    return wizard, token, system, vault, launcher, reg


def test_wizard_learns_the_login_and_puts_the_launcher_back(tmp_path):
    wizard, token, system, vault, launcher, reg = _wizard_setup(tmp_path)
    wizard.prepare()
    assert not system.procs  # closed before taking the "before" picture
    wizard.open_launcher()
    token.write_text("club-token")  # the admin signs in with the club account
    spec = wizard.finish()

    assert spec.files == (str(token),)
    assert token.read_text() == "player-token"  # the launcher is back as it was
    assert vault.load_club("fake").files == {str(token): b"club-token"}
    assert vault.info("fake")["learned"] is True

    # The next autopilot run uses it.
    seen = []
    system.on_start[str(launcher.exe)] = lambda sys_, cmd: (seen.append(token.read_text()), sys_.add_proc("fake.exe"))
    make_pilot([launcher], system, logins=Logins(vault, reg)).run()
    assert seen == ["club-token"] and token.read_text() == "player-token"


def test_wizard_without_a_sign_in_saves_nothing(tmp_path):
    import pytest

    from gupdater.autopilot.login_wizard import WizardError

    wizard, token, system, vault, *_ = _wizard_setup(tmp_path)
    wizard.prepare()
    wizard.open_launcher()
    with pytest.raises(WizardError, match="Вход не изменился"):
        wizard.finish()
    assert not vault.has_club("fake")


def test_cancelled_wizard_takes_the_fresh_login_out(tmp_path):
    wizard, token, system, vault, *_ = _wizard_setup(tmp_path, player_token=None)
    wizard.prepare()
    wizard.open_launcher()
    token.write_text("club-token")
    wizard.cancel()
    assert not token.exists()  # nobody was signed in before, nobody is now
    assert not vault.has_club("fake")


def test_encryption_is_tied_to_this_computer_and_detects_tampering(monkeypatch):
    import pytest

    from gupdater.core import secret

    monkeypatch.setenv("GUPDATER_MACHINE_ID", "club-pc-07")
    data = b"club-token" * 1000
    blob = secret.protect(data)
    assert b"club-token" not in blob
    assert secret.unprotect(blob) == data
    assert secret.unprotect(secret.protect(b"")) == b""
    with pytest.raises(secret.SecretError):
        secret.unprotect(blob[:-1] + bytes([blob[-1] ^ 1]))  # one bit changed
    monkeypatch.setenv("GUPDATER_MACHINE_ID", "another-pc")
    with pytest.raises(secret.SecretError, match="другом компьютере"):
        secret.unprotect(blob)


def test_renewed_login_is_not_kept_on_a_frozen_disk(tmp_path):
    token, reg, vault = _setup(tmp_path)
    system = FakeSystem()
    launcher = FakeLauncher(tmp_path, system)

    def handler(sys_, command):
        sys_.add_proc("fake.exe")
        token.write_text("club-token-renewed")

    system.on_start[str(launcher.exe)] = handler
    make_pilot([launcher], system, logins=Logins(vault, reg, allow_refresh=False)).run()
    assert vault.load_club("fake").files[str(token)] == b"club-token"
    assert token.read_text() == "player-token"


def test_freeze_programs_are_recognised(tmp_path):
    from gupdater.core.context import SystemContext
    from gupdater.core.freeze import disk_freeze
    from gupdater.demo import UNINSTALL

    reg = DictRegistry({rf"{UNINSTALL}\SD": {"DisplayName": "Shadow Defender", "Publisher": "Shadow Defender"}})
    ctx = SystemContext(registry=reg, env={}, drives=[], running=frozenset({"dfserv.exe"}))
    assert disk_freeze(ctx) == ["Shadow Defender", "Deep Freeze"]
    assert disk_freeze(SystemContext(registry=DictRegistry(), env={}, drives=[])) == []
