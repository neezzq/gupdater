"""Updating GUpdater itself from the project's GitHub Releases.

The new GUpdater.exe is downloaded next to the running one and checked
against the size and SHA-256 that GitHub reports. Windows does not let a
running program be overwritten, but it does let it be renamed, so the old
file becomes ``GUpdater.exe.old``, the new one takes its name, the new one is
started and the old one quits. The ``.old`` file is removed on the next start.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from gupdater import __version__
from gupdater.autopilot.system import start_detached

REPO = "neezzq/gupdater"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
ASSET_NAME = "GUpdater.exe"
_HEADERS = {"User-Agent": f"GUpdater/{__version__}", "Accept": "application/vnd.github+json"}


class UpdateError(Exception):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    download_url: str
    size: int
    sha256: str | None
    page_url: str
    notes: str = ""


def parse_version(text: str) -> tuple[int, ...]:
    parts = []
    for piece in text.strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit()) if piece[:1].isdigit() else ""
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) or (0,)


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


def fetch_latest(opener: Callable = urllib.request.urlopen, timeout: float = 15) -> Release:
    request = urllib.request.Request(LATEST_API, headers=_HEADERS)
    try:
        with opener(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("На GitHub пока нет ни одного выпуска программы") from exc
        if exc.code in (403, 429):
            raise UpdateError("GitHub временно ограничил число проверок, попробуйте через час") from exc
        raise UpdateError(f"GitHub ответил ошибкой {exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpdateError(f"Нет связи с GitHub: {getattr(exc, 'reason', exc)}") from exc

    asset = next((a for a in data.get("assets") or [] if a.get("name") == ASSET_NAME), None)
    if asset is None:
        raise UpdateError(f"В последнем выпуске нет файла {ASSET_NAME}")
    digest = asset.get("digest") or ""
    return Release(
        version=str(data.get("tag_name", "")).lstrip("vV"),
        download_url=asset["browser_download_url"],
        size=int(asset.get("size") or 0),
        sha256=digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else None,
        page_url=data.get("html_url") or RELEASES_PAGE,
        notes=data.get("body") or "",
    )


def download(
    release: Release,
    dest: Path,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    opener: Callable = urllib.request.urlopen,
) -> Path:
    part = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    done = 0
    try:
        request = urllib.request.Request(release.download_url, headers={"User-Agent": _HEADERS["User-Agent"]})
        with opener(request, timeout=60) as response, open(part, "wb") as out:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                if cancelled and cancelled():
                    raise UpdateError("Загрузка отменена")
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, release.size)
        if release.size and done != release.size:
            raise UpdateError("Файл скачался не полностью, попробуйте ещё раз")
        if release.sha256 and digest.hexdigest() != release.sha256:
            raise UpdateError("Скачанный файл повреждён (не совпала контрольная сумма)")
        os.replace(part, dest)
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, OSError) as exc:
        part.unlink(missing_ok=True)
        raise UpdateError(f"Не удалось скачать обновление: {getattr(exc, 'reason', exc)}") from exc
    return dest


def running_exe() -> Path | None:
    """GUpdater.exe itself, or None when running from source code."""
    return Path(sys.executable) if getattr(sys, "frozen", False) else None


def download_path(exe: Path) -> Path:
    return exe.with_name(exe.stem + ".new" + exe.suffix)


def install(new_file: Path, exe: Path) -> Path:
    """Put ``new_file`` in place of ``exe`` (which may be running); returns the old file."""
    old = exe.with_name(exe.name + ".old")
    if old.exists():
        try:
            old.unlink()
        except OSError:
            old = exe.with_name(f"{exe.name}.{int(time.time())}.old")
    try:
        exe.rename(old)
    except OSError as exc:
        raise UpdateError(
            f"Нет прав на запись в папку {exe.parent}. Запустите GUpdater от имени администратора "
            "или переложите его в другую папку."
        ) from exc
    try:
        new_file.rename(exe)
    except OSError as exc:
        old.rename(exe)
        raise UpdateError(f"Не удалось заменить программу: {exc}") from exc
    return old


def restart(exe: Path, args: list[str]) -> None:
    start_detached([str(exe), *args])


def cleanup_old_versions(exe: Path | None = None, attempts: int = 10) -> None:
    """Remove ``GUpdater.exe*.old`` left by an update (the old process may still be exiting)."""
    exe = exe or running_exe()
    if exe is None:
        return
    for attempt in range(attempts):
        leftovers = [p for p in exe.parent.glob(exe.name + "*.old")]
        for path in leftovers:
            try:
                path.unlink()
            except OSError:
                pass
        if not any(p.exists() for p in leftovers):
            return
        time.sleep(0.5)
