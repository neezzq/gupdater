"""Riot Client: ``RiotClientInstalls.json`` and per-game ``*.product_settings.yaml``."""

from __future__ import annotations

import json
from pathlib import Path

from gupdater.core.context import SystemContext
from gupdater.core.models import Game, GameStatus, LauncherScan
from gupdater.launchers.base import Launcher, check_paths, exe_from_command, protocol_exe

KNOWN_NAMES = {
    "valorant": "VALORANT",
    "league_of_legends": "League of Legends",
    "bacon": "Legends of Runeterra",
}
_UNINSTALL_PREFIX = "riot game "
_NOTE = "Riot Client обновляет игру сам, когда открыт"


def read_simple_yaml(path: Path) -> dict[str, str]:
    """Top-level ``key: value`` pairs; enough for Riot's settings files."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line[0].isspace() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class Riot(Launcher):
    id = "riot"
    name = "Riot Client"
    process_names = ("riotclientservices.exe", "riot client.exe", "riotclientux.exe")
    program_names = ("riot client",)
    helper_processes = ("riotclientuxrender.exe",)

    def _scan(self, ctx: SystemContext, result: LauncherScan) -> None:
        riot_data = ctx.env_path("PROGRAMDATA", "Riot Games")
        exe_paths: list[Path | None] = []
        installs = check_paths(result, [riot_data / "RiotClientInstalls.json" if riot_data else None], "RiotClientInstalls.json")
        if installs:
            data = json.loads(installs.read_text(encoding="utf-8-sig", errors="replace"))
            for key in ("rc_default", "rc_live", "rc_beta"):
                if data.get(key):
                    exe_paths.append(Path(data[key]))
        exe_paths.append(protocol_exe(ctx, "riotclient"))
        exe_paths += [
            exe_from_command(e.uninstall_string)
            for e in ctx.uninstall_entries
            if e.key.lower().startswith(_UNINSTALL_PREFIX)
        ]
        exe_paths += ctx.drive_paths("Riot Games", "Riot Client", "RiotClientServices.exe")
        exe = check_paths(result, exe_paths, "RiotClientServices.exe")
        if exe:
            result.exe_path = str(exe)

        # "Riot Game valorant.live" -> "VALORANT"
        uninstall_names = {
            e.key[len(_UNINSTALL_PREFIX):].lower(): e
            for e in ctx.uninstall_entries
            if e.key.lower().startswith(_UNINSTALL_PREFIX)
        }

        found: dict[str, Game] = {}
        metadata = riot_data / "Metadata" if riot_data else None
        if metadata and metadata.is_dir():
            for settings_file in sorted(metadata.glob("*/*.product_settings.yaml")):
                product_full = settings_file.parent.name.lower()  # e.g. "valorant.live"
                product = product_full.split(".")[0]
                if product == "riot_client":
                    continue
                settings = read_simple_yaml(settings_file)
                entry = uninstall_names.get(product_full)
                shortcut = settings.get("shortcut_name", "").removesuffix(".lnk")
                found[product_full] = Game(
                    name=(entry.display_name if entry else "") or KNOWN_NAMES.get(product) or shortcut or product,
                    game_id=product_full,
                    install_path=settings.get("product_install_full_path") or None,
                    version=(entry.display_version if entry else "") or None,
                    status=GameStatus.UNKNOWN,
                    note=_NOTE,
                )
        for product_full, entry in uninstall_names.items():
            if product_full not in found and not product_full.startswith("riot_client"):
                found[product_full] = Game(
                    name=entry.display_name,
                    game_id=product_full,
                    install_path=entry.install_location or None,
                    version=entry.display_version or None,
                    size_bytes=entry.size_bytes,
                    note=_NOTE,
                )
        result.games.extend(found.values())
        # Games whose folders are gone are dropped afterwards; with no client
        # and no games left Riot counts as not installed.
        result.installed = exe is not None or bool(found)

        if not result.installed:
            return
        private = ctx.env_path("LOCALAPPDATA", "Riot Games", "Riot Client", "Data", "RiotGamesPrivateSettings.yaml")
        has_login = bool(private and private.is_file())
        result.notes.append(f"Сохранённый вход Riot: {'есть' if has_login else 'нет'}")
