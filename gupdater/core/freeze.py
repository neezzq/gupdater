"""Disk-freezing programs: everything on a protected disk is rolled back on reboot."""

from __future__ import annotations

from gupdater.core.context import SystemContext

# Name in the Windows programs list (lower case) -> name to show.
_PROGRAMS = {
    "shadow defender": "Shadow Defender",
    "deep freeze": "Deep Freeze",
    "reboot restore": "Reboot Restore Rx",
    "toolwiz time freeze": "Toolwiz Time Freeze",
    "returnil": "Returnil",
    "shadowuser": "ShadowUser",
    "wondershare time freeze": "Time Freeze",
}
_PROCESSES = {
    "defenderdaemon.exe": "Shadow Defender",
    "dfserv.exe": "Deep Freeze",
    "frzstate2k.exe": "Deep Freeze",
    "toolwiztimefreeze.exe": "Toolwiz Time Freeze",
}


def disk_freeze(ctx: SystemContext) -> list[str]:
    found: dict[str, None] = {}
    for entry in ctx.uninstall_entries:
        name = entry.display_name.lower()
        for needle, label in _PROGRAMS.items():
            if needle in name:
                found[label] = None
    for process, label in _PROCESSES.items():
        if process in ctx.running:
            found[label] = None
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        if ctx.env_path(var, "Shadow Defender") and ctx.env_path(var, "Shadow Defender").is_dir():
            found["Shadow Defender"] = None
    return list(found)


def freeze_advice(names: list[str]) -> str:
    joined = ", ".join(names)
    return (
        f"На этом ПК стоит {joined}: после перезагрузки защищённый диск откатывается. "
        "Поэтому мастер «Запомнить вход» и расписание настраивайте при выключенной защите "
        f"(или сохраните изменения в {names[0]}), а GUpdater.exe держите на незащищённом диске с играми. "
        "Тогда игры обновятся, даже если после перезагрузки все аккаунты вышли."
    )
