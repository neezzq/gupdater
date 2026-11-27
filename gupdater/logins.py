"""Stage 3: the club's login, put into a launcher only for the time of an update.

Players sign in to the launchers with their own accounts, so the club's
login cannot simply stay there. Instead:

1. Once, with a wizard: GUpdater closes the launcher and notes its state, the
   admin signs in with the club account ("remember me"), GUpdater closes the
   launcher again, keeps what changed (the login) in an encrypted vault and
   puts the launcher back the way it was. Nobody is signed out on the
   server, so the saved login stays valid.
2. Before each update the current state (a player's login or none) is set
   aside, the club's login is put in, the update runs, the launcher is
   closed, and the previous state comes back. If GUpdater dies in between,
   the set-aside state is put back on its next start.

A login lives in a few files and registry values. For Steam, Epic, Riot and
Battle.net they are known; for the others the wizard finds them by comparing
the launcher's folders before and after signing in.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from gupdater.core import secret
from gupdater.core.registry import WritableRegistry


# --- what to look at --------------------------------------------------------

@dataclass(frozen=True)
class SessionSpec:
    """Where a launcher keeps its login."""

    files: tuple[str, ...] = ()
    registry_values: tuple[tuple[str, str], ...] = ()  # (key, value name)

    def __or__(self, other: "SessionSpec") -> "SessionSpec":
        return SessionSpec(
            files=tuple(dict.fromkeys(self.files + other.files)),
            registry_values=tuple(dict.fromkeys(self.registry_values + other.registry_values)),
        )

    def __bool__(self) -> bool:
        return bool(self.files or self.registry_values)

    def to_json(self) -> dict:
        return {"files": list(self.files), "registry_values": [list(v) for v in self.registry_values]}

    @classmethod
    def from_json(cls, data: dict) -> "SessionSpec":
        return cls(
            files=tuple(data.get("files", [])),
            registry_values=tuple(tuple(v) for v in data.get("registry_values", [])),
        )


@dataclass(frozen=True)
class LearnAreas:
    """Folders and registry keys where a launcher may keep its login."""

    folders: tuple[str, ...] = ()
    registry_keys: tuple[str, ...] = ()


# Folders and files that change all the time and never hold a login.
_SKIP_DIRS = {
    "cache", "code cache", "gpucache", "dawncache", "dawngraphitecache", "dawnwebgpucache", "grshadercache",
    "shadercache", "graphitedawncache", "htmlcache", "webcache", "service worker", "cachestorage", "blob_storage",
    "logs", "log", "crashes", "crashdumps", "crashreports", "crashpad", "dumps", "temp", "tmp", "updates",
    "update", "downloads", "steamapps", "depotcache", "appcache", "dumps", "pending",
}
_SKIP_EXT = {
    ".exe", ".dll", ".pak", ".tmp", ".dmp", ".pdb", ".msi", ".zip", ".7z", ".rar", ".ttf", ".otf", ".woff",
    ".woff2", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".mp4", ".webm", ".ogg", ".wav", ".mp3",
    ".bik", ".bk2", ".dat_old", ".old",
}
_MAX_FILE = 20 * 1024 * 1024
_MAX_FILES = 20_000


def _is_leveldb(folder: Path) -> bool:
    return (folder / "CURRENT").is_file()


def _wanted(path: Path, in_leveldb: bool) -> bool:
    name = path.name.lower()
    if path.suffix.lower() in _SKIP_EXT:
        return False
    # Log files are noise, except inside a database folder where they hold recent writes.
    if not in_leveldb and (path.suffix.lower() == ".log" or name in ("log", "log.old")):
        return False
    return True


def read_areas(areas: LearnAreas, registry: WritableRegistry) -> "State":
    """Contents of every candidate file and registry value (used by the wizard)."""
    state = State()
    count = 0
    for root in areas.folders:
        base = Path(root)
        if not base.is_dir():
            continue
        for folder, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d.lower() not in _SKIP_DIRS]
            here = Path(folder)
            leveldb = _is_leveldb(here)
            for name in files:
                path = here / name
                if not _wanted(path, leveldb):
                    continue
                try:
                    if path.stat().st_size > _MAX_FILE:
                        continue
                    state.files[str(path)] = path.read_bytes()
                except OSError:
                    continue
                count += 1
                if count >= _MAX_FILES:
                    return state
    for key in areas.registry_keys:
        for sub, values in _walk_registry(registry, key):
            for name, typed in values.items():
                state.registry[(sub, name)] = typed
    return state


def _walk_registry(registry: WritableRegistry, key: str, depth: int = 6) -> Iterable[tuple[str, dict]]:
    yield key, registry.typed_values(key)
    if depth > 0:
        for child in registry.subkeys(key):
            yield from _walk_registry(registry, f"{key}\\{child}", depth - 1)


def learn(before: "State", after: "State") -> SessionSpec:
    """What changed between "signed out" and "signed in with the club account"."""
    changed_files = sorted(p for p in set(before.files) | set(after.files) if before.files.get(p) != after.files.get(p))
    # A database folder only works as a whole: take all of it.
    extra: set[str] = set()
    for path in changed_files:
        folder = Path(path).parent
        if _is_leveldb(folder):
            extra.update(p for p in set(before.files) | set(after.files) if Path(p).parent == folder)
    changed_values = sorted(
        k for k in set(before.registry) | set(after.registry) if before.registry.get(k) != after.registry.get(k)
    )
    return SessionSpec(files=tuple(sorted(set(changed_files) | extra)), registry_values=tuple(changed_values))


# --- snapshots ----------------------------------------------------------------

@dataclass
class State:
    files: dict[str, bytes | None] = field(default_factory=dict)  # None: the file did not exist
    registry: dict[tuple[str, str], tuple[int, Any] | None] = field(default_factory=dict)
    created: float = field(default_factory=time.time)


def merge(*states: State) -> State:
    merged = State()
    for state in states:
        merged.files.update(state.files)
        merged.registry.update(state.registry)
    return merged


def capture(spec: SessionSpec, registry: WritableRegistry) -> State:
    state = State()
    for path in spec.files:
        try:
            state.files[path] = Path(path).read_bytes()
        except FileNotFoundError:
            state.files[path] = None
    for key, name in spec.registry_values:
        values = registry.typed_values(key)
        match = next((v for n, v in values.items() if n.lower() == name.lower()), None)
        state.registry[(key, name)] = match
    return state


def apply(state: State, registry: WritableRegistry) -> None:
    for path, content in state.files.items():
        target = Path(path)
        if content is None:
            target.unlink(missing_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".gupdater-tmp")
        tmp.write_bytes(content)
        os.replace(tmp, target)
    for (key, name), typed in state.registry.items():
        if typed is None:
            registry.delete_value(key, name)
        else:
            registry.set_value(key, name, typed[0], typed[1])


def restrict(state: State, spec: SessionSpec) -> State:
    """Only the parts of ``state`` that ``spec`` names (absent ones as "did not exist")."""
    return State(
        files={p: state.files.get(p) for p in spec.files},
        registry={k: state.registry.get(k) for k in spec.registry_values},
        created=state.created,
    )


def _encode_value(data: Any) -> Any:
    if isinstance(data, bytes):
        return {"b64": base64.b64encode(data).decode()}
    return data


def _decode_value(data: Any) -> Any:
    if isinstance(data, dict) and "b64" in data:
        return base64.b64decode(data["b64"])
    return data


def dumps(state: State) -> bytes:
    buffer = io.BytesIO()
    manifest = {"created": state.created, "files": {}, "registry": []}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, (path, content) in enumerate(state.files.items()):
            if content is None:
                manifest["files"][path] = None
            else:
                member = f"f{index:05d}"
                archive.writestr(member, content)
                manifest["files"][path] = member
        for (key, name), typed in state.registry.items():
            manifest["registry"].append(
                [key, name, None if typed is None else [typed[0], _encode_value(typed[1])]]
            )
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
    return buffer.getvalue()


def loads(blob: bytes) -> State:
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        files = {path: (archive.read(member) if member else None) for path, member in manifest["files"].items()}
    registry = {
        (key, name): (None if typed is None else (typed[0], _decode_value(typed[1])))
        for key, name, typed in manifest["registry"]
    }
    return State(files=files, registry=registry, created=manifest.get("created", 0.0))


def fingerprint(state: State) -> str:
    digest = hashlib.sha256()
    for path in sorted(state.files):
        digest.update(path.encode())
        digest.update(b"\0" if state.files[path] is None else hashlib.sha256(state.files[path]).digest())
    for key in sorted(state.registry):
        digest.update(repr((key, state.registry[key])).encode())
    return digest.hexdigest()


# --- the vault ------------------------------------------------------------------

class Vault:
    """Encrypted saved logins next to GUpdater.exe (``GUpdater-входы``)."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)
        self._index_path = folder / "index.json"

    def _index(self) -> dict:
        try:
            return json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write_index(self, index: dict) -> None:
        tmp = self._index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._index_path)

    def _write(self, path: Path, state: State) -> None:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(secret.protect(dumps(state)))
        os.replace(tmp, path)

    def _read(self, path: Path) -> State:
        return loads(secret.unprotect(path.read_bytes()))

    # club login
    def info(self, launcher_id: str) -> dict | None:
        entry = self._index().get(launcher_id)
        return entry if entry and (self.folder / f"{launcher_id}.club").is_file() else None

    def has_club(self, launcher_id: str) -> bool:
        return self.info(launcher_id) is not None

    def spec(self, launcher_id: str) -> SessionSpec:
        return SessionSpec.from_json((self.info(launcher_id) or {}).get("spec", {}))

    def save_club(self, launcher_id: str, state: State, spec: SessionSpec, learned: bool) -> None:
        club = self.folder / f"{launcher_id}.club"
        if club.is_file():
            os.replace(club, self.folder / f"{launcher_id}.club.prev")  # one step back, just in case
        self._write(club, state)
        index = self._index()
        index[launcher_id] = {"saved_at": time.time(), "spec": spec.to_json(), "learned": learned,
                              "files": len(spec.files), "registry_values": len(spec.registry_values)}
        self._write_index(index)

    def refresh_club(self, launcher_id: str, state: State) -> None:
        """The launcher renewed its login token during the update: keep the new one."""
        self._write(self.folder / f"{launcher_id}.club", state)
        index = self._index()
        if launcher_id in index:
            index[launcher_id]["refreshed_at"] = time.time()
            self._write_index(index)

    def load_club(self, launcher_id: str) -> State:
        return self._read(self.folder / f"{launcher_id}.club")

    def forget(self, launcher_id: str) -> None:
        for suffix in (".club", ".club.prev"):
            (self.folder / f"{launcher_id}{suffix}").unlink(missing_ok=True)
        index = self._index()
        index.pop(launcher_id, None)
        self._write_index(index)

    # the state set aside during an update
    def save_aside(self, launcher_id: str, state: State) -> None:
        self._write(self.folder / f"{launcher_id}.aside", state)

    def load_aside(self, launcher_id: str) -> State:
        return self._read(self.folder / f"{launcher_id}.aside")

    def drop_aside(self, launcher_id: str) -> None:
        (self.folder / f"{launcher_id}.aside").unlink(missing_ok=True)

    def pending_aside(self) -> list[str]:
        return sorted(p.stem for p in self.folder.glob("*.aside"))


# --- using it during an update ---------------------------------------------------------

class ClubSession:
    """Puts the club's login in for one update and takes it out again."""

    def __init__(self, vault: Vault, registry: WritableRegistry, launcher_id: str, allow_refresh: bool = True) -> None:
        self.vault = vault
        self.registry = registry
        self.launcher_id = launcher_id
        self.allow_refresh = allow_refresh
        self.spec = vault.spec(launcher_id)
        self._aside: State | None = None

    def swap_in(self) -> None:
        club = self.vault.load_club(self.launcher_id)  # fails early if it cannot be decrypted
        self._aside = capture(self.spec, self.registry)
        self.vault.save_aside(self.launcher_id, self._aside)
        apply(club, self.registry)

    def swap_out(self, keep_renewed_login: bool) -> bool:
        """Put the previous state back; returns True if a renewed club login was kept."""
        if self._aside is None:
            return False
        kept = False
        if keep_renewed_login and self.allow_refresh:
            now = capture(self.spec, self.registry)
            club = self.vault.load_club(self.launcher_id)
            # Only if the login files are still there (the launcher did not sign out).
            still_signed_in = all((now.files.get(p) is None) == (c is None) for p, c in club.files.items())
            if still_signed_in and fingerprint(now) != fingerprint(club):
                self.vault.refresh_club(self.launcher_id, now)
                kept = True
        apply(self._aside, self.registry)
        self.vault.drop_aside(self.launcher_id)
        self._aside = None
        return kept


class Logins:
    """What the autopilot needs: whether to swap, and how."""

    def __init__(self, vault: Vault, registry: WritableRegistry, enabled: bool = True, allow_refresh: bool = True) -> None:
        self.vault = vault
        self.registry = registry
        self.enabled = enabled
        # With a frozen system disk a login the launcher renews may be sealed with keys
        # that vanish on reboot; then the wizard's login is kept as it is.
        self.allow_refresh = allow_refresh

    def session_for(self, launcher_id: str) -> ClubSession | None:
        if self.enabled and self.vault.has_club(launcher_id):
            return ClubSession(self.vault, self.registry, launcher_id, self.allow_refresh)
        return None

    def recover(self, close: Callable[[str], None], log: Callable[[str], None]) -> list[str]:
        """After a crash mid-update: take the club's login out of the launchers again."""
        recovered = []
        for launcher_id in self.vault.pending_aside():
            try:
                close(launcher_id)
                apply(self.vault.load_aside(launcher_id), self.registry)
                self.vault.drop_aside(launcher_id)
                recovered.append(launcher_id)
                log(f"{launcher_id}: прошлое обновление прервалось — вход клуба убран, вернул как было")
            except (OSError, secret.SecretError, ValueError, KeyError, zipfile.BadZipFile) as exc:
                log(f"{launcher_id}: не удалось вернуть прежний вход: {exc}")
        return recovered
