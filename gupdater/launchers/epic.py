"""Epic Games Launcher: one JSON ``*.item`` manifest per installed game."""

from __future__ import annotations

import json
from pathlib import Path

from gupdater.core.context import SystemContext
from gupdater.core.models import Game, GameStatus, LauncherScan
from gupdater.core.registry import reg_str
from gupdater.launchers.base import Launcher, check_paths, find_entries

_EXE_TAIL = ("Launcher", "Portal", "Binaries")


class Epic(Launcher):
    id = "epic"
    name = "Epic Games"
    process_names = ("epicgameslauncher.exe",)
    helper_processes = ("epicwebhelper.exe",)
    start_args = ("-silent",)

    def _scan(self, ctx: SystemContext, result: LauncherScan) -> None:
        data_dir_reg = reg_str(ctx.registry, r"HKLM\SOFTWARE\WOW6432Node\Epic Games\EpicGamesLauncher", "AppDataPath")
        data_dir = check_paths(
            result,
            [Path(data_dir_reg) if data_dir_reg else None, ctx.env_path("PROGRAMDATA", "Epic", "EpicGamesLauncher", "Data")],
            "данные Epic",
        )

        bases = [ctx.env_path("PROGRAMFILES(X86)", "Epic Games"), ctx.env_path("PROGRAMFILES", "Epic Games")]
        bases += [Path(e.install_location) for e in find_entries(ctx, "epic games launcher") if e.install_location]
        exe_paths = [
            base.joinpath(*_EXE_TAIL, arch, "EpicGamesLauncher.exe")
            for base in bases
            if base
            for arch in ("Win64", "Win32")
        ]
        exe = check_paths(result, exe_paths, "EpicGamesLauncher.exe")

        manifests = data_dir / "Manifests" if data_dir else None
        result.installed = exe is not None or bool(manifests and manifests.is_dir())
        if exe:
            result.exe_path = str(exe)
        if manifests and manifests.is_dir():
            for item in sorted(manifests.glob("*.item")):
                game = self._parse_item(item, result)
                if game:
                    result.games.append(game)
            pending = manifests / "Pending"
            if pending.is_dir():
                result.evidence.append(f"Manifests\\Pending: файлов {len(list(pending.glob('*.item')))}")

        if result.installed:
            self._login_note(ctx, result)

    def _parse_item(self, item: Path, result: LauncherScan) -> Game | None:
        try:
            data = json.loads(item.read_text(encoding="utf-8-sig", errors="replace"))
        except (OSError, ValueError) as exc:
            result.evidence.append(f"не прочитан {item.name}: {exc}")
            return None
        app_name = data.get("AppName") or item.stem
        main_game = data.get("MainGameAppName")
        if main_game and main_game != app_name:
            return None  # DLC: updated together with its game
        categories = [str(c).lower() for c in data.get("AppCategories") or []]
        if categories and "games" not in categories:
            return None  # Unreal Engine, plugins and other non-games
        incomplete = bool(data.get("bIsIncompleteInstall"))
        return Game(
            name=data.get("DisplayName") or app_name,
            game_id=app_name,
            install_path=data.get("InstallLocation") or None,
            version=data.get("AppVersionString") or None,
            size_bytes=data.get("InstallSize") or None,
            status=GameStatus.BROKEN if incomplete else GameStatus.UNKNOWN,
            note="Epic: установка не завершена" if incomplete else "Epic сообщает об обновлениях только после входа",
        )

    def _login_note(self, ctx: SystemContext, result: LauncherScan) -> None:
        ini = ctx.env_path("LOCALAPPDATA", "EpicGamesLauncher", "Saved", "Config", "Windows", "GameUserSettings.ini")
        if not ini or not ini.is_file():
            result.notes.append("Сохранённый вход Epic: нет")
            return
        # Only look for the section header; its contents are a login token.
        text = ini.read_text(encoding="utf-8", errors="replace").lower()
        remembered = "[rememberme]" in text and "enable=true" in text
        result.notes.append(f"Сохранённый вход Epic: {'есть' if remembered else 'нет'}")
