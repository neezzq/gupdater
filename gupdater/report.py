"""The recon report: what was found on this PC, as plain text to send back.

The report must be safe to paste into a chat: it lists programs, folders and
counts, never account names, e-mails or login tokens, and the Windows user
folder is replaced with ``%USERPROFILE%``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from gupdater import __version__
from gupdater.core.context import SystemContext, UninstallEntry, disk_usage
from gupdater.core.models import GameStatus, LauncherScan, format_size
from gupdater.core.registry import reg_str
from gupdater.launchers import ALL_LAUNCHERS

# Programs, folders and processes worth showing in the technical section.
KEYWORDS = (
    "steam", "epic", "battle.net", "blizzard", "riot", "electronic arts", "ea app", "origin",
    "vk play", "vkplay", "gamecenter", "game center", "игровой центр", "mail.ru", "my.games",
    "lesta", "леста", "wargaming", "iccup", "warcraft", "smartshell",
)
_PROCESS_KEYWORDS = (
    "steam", "epic", "battle.net", "blizzard", "riot", "valorant", "league", "eadesktop",
    "eabackground", "origin", "gamecenter", "vkplay", "lgc", "lesta", "iccup", "war3", "smartshell",
)
_PROTOCOL_HINTS = (
    "steam", "epic", "battle", "blizzard", "riot", "origin", "link2ea", "eadm", "vkplay",
    "gamecenter", "lesta", "lgc", "wgc", "iccup", "mygames",
)
_FOLDER_ROOTS = ("PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA", "APPDATA")
# Only folder names like these go into the report: the rest of a disk is nobody's business.
_FOLDER_KEYWORDS = KEYWORDS + ("game", "игр", "riot", "astrum", "launcher", "лаунчер", "4game", "vk ")


@dataclass
class Inventory:
    computer: str = ""
    os_name: str = ""
    drives: list[tuple[str, int, int]] = field(default_factory=list)  # (root, total, free)
    smartshell: list[str] = field(default_factory=list)
    programs: list[UninstallEntry] = field(default_factory=list)
    processes: list[str] = field(default_factory=list)
    protocols: dict[str, str] = field(default_factory=dict)
    folders: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class ScanResult:
    scans: list[LauncherScan]
    inventory: Inventory
    finished_at: datetime


def scan_all(ctx: SystemContext) -> list[LauncherScan]:
    return [launcher.scan(ctx) for launcher in ALL_LAUNCHERS]


def collect_inventory(ctx: SystemContext) -> Inventory:
    inv = Inventory(computer=ctx.computer_name, os_name=ctx.os_name)
    for drive in ctx.drives:
        usage = disk_usage(drive)
        if usage:
            inv.drives.append((drive, *usage))

    inv.programs = sorted(
        (e for e in ctx.uninstall_entries if any(k in e.haystack for k in KEYWORDS)),
        key=lambda e: e.display_name.lower(),
    )
    inv.processes = sorted(p for p in ctx.running if any(k in p for k in _PROCESS_KEYWORDS))

    for scheme in ctx.registry.subkeys("HKCR"):
        lowered = scheme.lower()
        if not any(hint in lowered for hint in _PROTOCOL_HINTS):
            continue
        if "URL Protocol" not in ctx.registry.values(f"HKCR\\{scheme}"):
            continue
        inv.protocols[scheme] = reg_str(ctx.registry, f"HKCR\\{scheme}\\shell\\open\\command", "")

    for var in _FOLDER_ROOTS:
        base = ctx.env_path(var)
        if base and base.is_dir():
            inv.folders[f"%{var}%"] = _game_related(_list_names(base))
    for drive in ctx.drives:
        inv.folders[drive] = _game_related(_list_names(Path(drive)))

    inv.smartshell = (
        [f"программа: {e.display_name} — {e.install_location}" for e in inv.programs if "smartshell" in e.haystack]
        + [f"процесс: {p}" for p in inv.processes if "smartshell" in p]
        + [f"папка: {where}\\{name}" for where, names in inv.folders.items() for name in names if "smartshell" in name.lower()]
    )
    return inv


def _game_related(names: list[str]) -> list[str]:
    return [n for n in names if any(k in n.lower() for k in _FOLDER_KEYWORDS)]


def _list_names(folder: Path, limit: int = 1000) -> list[str]:
    try:
        names = sorted((p.name for p in folder.iterdir()), key=str.lower)
    except OSError:
        return []
    return names[:limit]


def run_scan(ctx: SystemContext) -> ScanResult:
    return ScanResult(scans=scan_all(ctx), inventory=collect_inventory(ctx), finished_at=datetime.now())


def _launcher_block(scan: LauncherScan) -> list[str]:
    lines = []
    if not scan.installed:
        lines.append(f"[ ] {scan.name} — не найден")
    else:
        state = " (запущен)" if scan.running else ""
        lines.append(f"[x] {scan.name} — {scan.exe_path or 'путь не определён'}{state}")
        updates = f", нужно обновить: {scan.updates_needed}" if scan.updates_needed else ""
        lines.append(f"    Игр найдено: {len(scan.games)}{updates}")
    for game in scan.games:
        parts = [game.name, f"id {game.game_id}"]
        if game.version:
            parts.append(f"версия {game.version}")
        if game.size_bytes:
            parts.append(format_size(game.size_bytes))
        parts.append(game.status.text if game.status is not GameStatus.UNKNOWN else "статус неизвестен")
        if game.install_path:
            parts.append(game.install_path)
        lines.append("    - " + " | ".join(parts))
    for note in scan.notes:
        lines.append(f"    * {note}")
    if scan.error:
        lines.append(f"    ! Ошибка при поиске: {scan.error}")
    return lines


def build_report(result: ScanResult, ctx: SystemContext) -> str:
    inv = result.inventory
    lines = [
        f"GUpdater {__version__} — отчёт разведки",
        f"Дата: {result.finished_at:%Y-%m-%d %H:%M}",
        f"Компьютер: {inv.computer}",
        f"Система: {inv.os_name}",
        "SmartShell: " + ("найден" if inv.smartshell else "не найден"),
    ]
    for drive, total, free in inv.drives:
        lines.append(f"Диск {drive} свободно {format_size(free)} из {format_size(total)}")

    total_games = sum(len(s.games) for s in result.scans)
    found = sum(1 for s in result.scans if s.installed)
    lines += ["", f"=== Лаунчеры: найдено {found} из {len(result.scans)}, игр: {total_games} ===", ""]
    for scan in result.scans:
        lines += _launcher_block(scan)
        lines.append("")

    lines += ["=== Технические данные (для настройки GUpdater) ===", ""]
    lines.append("-- Что проверялось --")
    for scan in result.scans:
        lines.append(f"[{scan.name}]")
        lines += [f"  {item}" for item in scan.evidence] or ["  (ничего)"]
    lines += ["", "-- SmartShell --"]
    lines += [f"  {item}" for item in inv.smartshell] or ["  (ничего)"]
    lines += ["", "-- Программы Windows, связанные с играми и лаунчерами --"]
    for e in inv.programs:
        size = f" | {format_size(e.size_bytes)}" if e.size_bytes else ""
        lines.append(
            f"  {e.display_name} | {e.publisher or '—'} | версия {e.display_version or '—'}{size}"
            f" | ключ {e.key} | {e.install_location or '—'} | удаление: {e.uninstall_string or '—'}"
        )
    lines += ["", "-- Запущенные процессы лаунчеров --"]
    lines += [f"  {p}" for p in inv.processes] or ["  (нет)"]
    lines += ["", "-- Ссылки-протоколы лаунчеров --"]
    lines += [f"  {scheme}: {cmd}" for scheme, cmd in sorted(inv.protocols.items())] or ["  (нет)"]
    lines += ["", "-- Папки (только связанные с играми) --"]
    for where, names in inv.folders.items():
        lines.append(f"  {where}: {', '.join(names) or '(пусто)'}")
    return sanitize("\n".join(lines) + "\n", ctx)


def sanitize(text: str, ctx: SystemContext) -> str:
    """Replace the Windows user folder (which contains the user name)."""
    profile = ctx.env.get("USERPROFILE")
    if not profile:
        return text
    variants = {profile, profile.replace("\\", "/")}
    for variant in sorted(variants, key=len, reverse=True):
        text = re.sub(re.escape(variant), "%USERPROFILE%", text, flags=re.IGNORECASE)
    return text


def default_report_name(result: ScanResult) -> str:
    computer = re.sub(r"[^\w-]+", "_", result.inventory.computer or "pc")
    return f"gupdater-otchet-{computer}-{result.finished_at:%Y%m%d-%H%M}.txt"
