"""Steam: libraries from ``libraryfolders.vdf``, games from ``appmanifest_*.acf``.

Steam writes each game's state into its manifest, including whether an update
is waiting, so the status shown here is what Steam itself thinks.
"""

from __future__ import annotations

import os
from pathlib import Path

from gupdater.core import vdf
from gupdater.core.context import SystemContext
from gupdater.core.models import Game, GameStatus, LauncherScan
from gupdater.core.registry import reg_str, reg_value
from gupdater.launchers.base import Launcher, LaunchSpec, Progress, check_paths, protocol_exe

# EAppState bits from the Steam client.
UPDATE_REQUIRED = 2
FULLY_INSTALLED = 4
FILES_MISSING = 32
FILES_CORRUPT = 128
UPDATE_RUNNING = 256
UPDATE_PAUSED = 512
UPDATE_STARTED = 1024
VALIDATING = 1 << 17
ADDING_FILES = 1 << 18
PREALLOCATING = 1 << 19
DOWNLOADING = 1 << 20
STAGING = 1 << 21
COMMITTING = 1 << 22

_IN_PROGRESS = (
    UPDATE_RUNNING | UPDATE_STARTED | VALIDATING | ADDING_FILES | PREALLOCATING | DOWNLOADING | STAGING | COMMITTING
)

# Runtimes and redistributables that Steam installs like games.
_TOOL_APPIDS = {"228980", "1070560", "1391110", "1628350", "1493710"}
_TOOL_PREFIXES = ("proton ", "steam linux runtime", "steamworks common redistributables")


def _int(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def steam_status(
    flags: int, buildid: str, target_buildid: str, to_download: int, downloaded: int
) -> tuple[GameStatus, str]:
    if flags & (FILES_MISSING | FILES_CORRUPT):
        return GameStatus.BROKEN, "Steam: файлы игры повреждены или отсутствуют"
    if flags & UPDATE_PAUSED:
        return GameStatus.UPDATE_REQUIRED, "Steam: обновление на паузе"
    if flags & _IN_PROGRESS:
        return GameStatus.UPDATING, "Steam: идёт загрузка обновления"
    if flags & UPDATE_REQUIRED:
        return GameStatus.UPDATE_REQUIRED, "Steam: есть обновление"
    if target_buildid not in ("", "0") and buildid and target_buildid != buildid:
        return GameStatus.UPDATE_REQUIRED, f"Steam: ждёт сборку {target_buildid}"
    if to_download > downloaded:
        return GameStatus.UPDATE_REQUIRED, "Steam: обновление скачано не полностью"
    if flags & FULLY_INSTALLED:
        return GameStatus.OK, ""
    return GameStatus.UNKNOWN, f"Steam: StateFlags={flags}"


def _norm(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


class Steam(Launcher):
    id = "steam"
    name = "Steam"
    process_names = ("steam.exe",)
    program_names = ("steam",)
    helper_processes = ("steamservice.exe",)
    start_args = ("-silent",)

    def launch_spec(self, ctx: SystemContext, scan: LauncherScan) -> LaunchSpec | None:
        spec = super().launch_spec(ctx, scan)
        if spec is None:
            return None
        # Games live inside the Steam folder: only Steam's own processes count.
        return LaunchSpec(
            command=spec.command,
            process_names=spec.process_names,
            close_command=(spec.command[0], "-shutdown"),
        )

    def progress(self, ctx: SystemContext) -> Progress:
        scan = self.scan(ctx)
        active_user = reg_value(ctx.registry, r"HKCU\Software\Valve\Steam\ActiveProcess", "ActiveUser")
        return Progress(
            busy=any(g.status is GameStatus.UPDATING for g in scan.games),
            pending=[(g.game_id, g.name) for g in scan.games if g.status is GameStatus.UPDATE_REQUIRED],
            logged_in=None if active_user is None else bool(active_user),
        )

    def nudge_commands(self, ctx, scan, pending):
        # Verifying a game's files makes Steam download its update right away,
        # even when the game is set to update only when launched.
        if not scan.exe_path:
            return []
        return [
            ((scan.exe_path, f"steam://validate/{appid}"), f"Steam сам не начал обновлять «{name}» — запускаю проверку файлов")
            for appid, name in pending
        ]

    def find_root(self, ctx: SystemContext, result: LauncherScan) -> Path | None:
        reg = ctx.registry
        candidates = [
            reg_str(reg, r"HKCU\Software\Valve\Steam", "SteamPath"),
            reg_str(reg, r"HKLM\SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            reg_str(reg, r"HKLM\SOFTWARE\Valve\Steam", "InstallPath"),
        ]
        paths = [Path(c) for c in candidates if c]
        handler = protocol_exe(ctx, "steam")
        paths.append(handler.parent if handler else None)
        paths.append(ctx.env_path("PROGRAMFILES(X86)", "Steam"))
        if not ctx.is_windows:
            paths.append(ctx.env_path("HOME", ".steam", "steam"))
            paths.append(ctx.env_path("HOME", ".local", "share", "Steam"))
        return check_paths(result, paths, "папка Steam")

    def library_paths(self, root: Path, result: LauncherScan) -> list[Path]:
        libraries = [root]
        for vdf_path in (root / "steamapps" / "libraryfolders.vdf", root / "config" / "libraryfolders.vdf"):
            if not vdf_path.is_file():
                continue
            folders = vdf.load(vdf_path).get("libraryfolders", {})
            for key, value in folders.items():
                if not key.isdigit():
                    continue
                path = value.get("path") if isinstance(value, dict) else value
                if path:
                    libraries.append(Path(path))
            break
        unique: dict[str, Path] = {}
        for lib in libraries:
            unique.setdefault(_norm(lib), lib)
        for lib in unique.values():
            exists = (lib / "steamapps").is_dir()
            result.evidence.append(f"библиотека: {'есть' if exists else 'нет'} — {lib}")
        return list(unique.values())

    def parse_manifest(self, manifest: Path, library: Path) -> Game | None:
        state = vdf.load(manifest).get("appstate", {})
        appid = state.get("appid") or manifest.stem.removeprefix("appmanifest_")
        name = state.get("name") or f"Steam App {appid}"
        if appid in _TOOL_APPIDS or name.lower().startswith(_TOOL_PREFIXES):
            return None
        buildid = state.get("buildid", "")
        status, note = steam_status(
            flags=_int(state.get("stateflags")),
            buildid=buildid,
            target_buildid=state.get("targetbuildid", ""),
            to_download=_int(state.get("bytestodownload")),
            downloaded=_int(state.get("bytesdownloaded")),
        )
        installdir = state.get("installdir", "")
        return Game(
            name=name,
            game_id=appid,
            install_path=str(library / "steamapps" / "common" / installdir) if installdir else None,
            version=buildid or None,
            size_bytes=_int(state.get("sizeondisk")) or None,
            status=status,
            note=note,
        )

    def _scan(self, ctx: SystemContext, result: LauncherScan) -> None:
        root = self.find_root(ctx, result)
        if root is None:
            return
        exe = check_paths(result, [root / "steam.exe"], "steam.exe")
        result.installed = True
        result.exe_path = str(exe or root)

        seen_appids: set[str] = set()
        for library in self.library_paths(root, result):
            for manifest in sorted((library / "steamapps").glob("appmanifest_*.acf")):
                try:
                    game = self.parse_manifest(manifest, library)
                except (OSError, vdf.VdfError) as exc:
                    result.evidence.append(f"не прочитан {manifest}: {exc}")
                    continue
                if game and game.game_id not in seen_appids:
                    seen_appids.add(game.game_id)
                    result.games.append(game)

        self._login_notes(ctx, root, result)

    def _login_notes(self, ctx: SystemContext, root: Path, result: LauncherScan) -> None:
        # Only counts are reported: account names stay on the PC.
        login_file = root / "config" / "loginusers.vdf"
        if login_file.is_file():
            users = vdf.load(login_file).get("users", {})
            remembered = sum(
                1 for u in users.values() if isinstance(u, dict) and u.get("rememberpassword") == "1"
            )
            result.notes.append(f"Аккаунтов в Steam на этом ПК: {len(users)}, с сохранённым входом: {remembered}")
        else:
            result.notes.append("Сохранённых входов в Steam нет")
        auto_login = reg_str(ctx.registry, r"HKCU\Software\Valve\Steam", "AutoLoginUser")
        result.notes.append(f"Автовход Steam: {'включён' if auto_login else 'выключен'}")
