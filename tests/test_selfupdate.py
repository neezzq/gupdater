import hashlib
import io
import json
import shutil
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

from gupdater import selfupdate
from gupdater.selfupdate import Release, UpdateError

EXE_BYTES = b"MZ new GUpdater build" * 1000


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def release_json(version="0.9.0", with_asset=True, digest=True):
    asset = {
        "name": "GUpdater.exe",
        "size": len(EXE_BYTES),
        "browser_download_url": f"https://github.com/neezzq/gupdater/releases/download/v{version}/GUpdater.exe",
    }
    if digest:
        asset["digest"] = "sha256:" + hashlib.sha256(EXE_BYTES).hexdigest()
    return {
        "tag_name": f"v{version}",
        "html_url": f"https://github.com/neezzq/gupdater/releases/tag/v{version}",
        "body": "notes",
        "assets": [asset] if with_asset else [],
    }


def opener_for(payload):
    def opener(request, timeout):
        if isinstance(payload, Exception):
            raise payload
        if request.full_url.endswith("/releases/latest"):
            return FakeResponse(json.dumps(payload).encode())
        return FakeResponse(payload)
    return opener


@pytest.mark.parametrize(
    "candidate, current, newer",
    [("0.2.1", "0.2.0", True), ("v1.0.0", "0.9.9", True), ("0.10.0", "0.9.0", True),
     ("0.2.0", "0.2.0", False), ("0.1.9", "0.2.0", False), ("junk", "0.2.0", False)],
)
def test_version_comparison(candidate, current, newer):
    assert selfupdate.is_newer(candidate, current) is newer


def test_fetch_latest_reads_version_asset_and_checksum():
    release = selfupdate.fetch_latest(opener=opener_for(release_json("0.9.0")))
    assert release.version == "0.9.0"
    assert release.download_url.endswith("/v0.9.0/GUpdater.exe")
    assert release.size == len(EXE_BYTES)
    assert release.sha256 == hashlib.sha256(EXE_BYTES).hexdigest()


@pytest.mark.parametrize(
    "error, text",
    [
        (urllib.error.HTTPError("u", 404, "nf", {}, None), "нет ни одного выпуска"),
        (urllib.error.HTTPError("u", 403, "rl", {}, None), "ограничил"),
        (urllib.error.URLError("no network"), "Нет связи"),
    ],
)
def test_fetch_latest_errors_are_readable(error, text):
    with pytest.raises(UpdateError, match=text):
        selfupdate.fetch_latest(opener=opener_for(error))


def test_release_without_exe_is_rejected():
    with pytest.raises(UpdateError, match="нет файла"):
        selfupdate.fetch_latest(opener=opener_for(release_json(with_asset=False)))


def _release(**overrides):
    data = dict(version="0.9.0", download_url="https://x/GUpdater.exe", size=len(EXE_BYTES),
                sha256=hashlib.sha256(EXE_BYTES).hexdigest(), page_url="https://x")
    data.update(overrides)
    return Release(**data)


def test_download_checks_size_and_checksum(tmp_path):
    seen = []
    dest = selfupdate.download(_release(), tmp_path / "GUpdater.new.exe", progress=lambda d, t: seen.append(d),
                               opener=opener_for(EXE_BYTES))
    assert dest.read_bytes() == EXE_BYTES
    assert seen[-1] == len(EXE_BYTES)

    with pytest.raises(UpdateError, match="контрольная сумма"):
        selfupdate.download(_release(sha256="0" * 64), tmp_path / "bad.exe", opener=opener_for(EXE_BYTES))
    with pytest.raises(UpdateError, match="не полностью"):
        selfupdate.download(_release(size=10), tmp_path / "short.exe", opener=opener_for(EXE_BYTES))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["GUpdater.new.exe"]  # no half-downloaded leftovers


def test_download_can_be_cancelled(tmp_path):
    with pytest.raises(UpdateError, match="отменена"):
        selfupdate.download(_release(), tmp_path / "x.exe", cancelled=lambda: True, opener=opener_for(EXE_BYTES))
    assert not list(tmp_path.iterdir())


def test_install_swaps_files_and_cleanup_removes_old(tmp_path):
    exe = tmp_path / "GUpdater.exe"
    exe.write_bytes(b"old")
    (tmp_path / "GUpdater.exe.old").write_bytes(b"older leftover")
    new = tmp_path / "GUpdater.new.exe"
    new.write_bytes(b"new")

    old = selfupdate.install(new, exe)
    assert exe.read_bytes() == b"new"
    assert old.read_bytes() == b"old"
    assert not new.exists()

    selfupdate.cleanup_old_versions(exe, attempts=1)
    assert [p.name for p in tmp_path.iterdir()] == ["GUpdater.exe"]


def test_failed_install_keeps_the_old_program(tmp_path):
    exe = tmp_path / "GUpdater.exe"
    exe.write_bytes(b"old")
    with pytest.raises(UpdateError):
        selfupdate.install(tmp_path / "missing.exe", exe)
    assert exe.read_bytes() == b"old"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows renames running programs")
def test_running_program_can_be_replaced_on_windows(tmp_path):
    exe = tmp_path / "PING.EXE"
    shutil.copy(Path(r"C:\Windows\System32\PING.EXE"), exe)
    new = tmp_path / "new.exe"
    shutil.copy(exe, new)
    proc = subprocess.Popen([str(exe), "-n", "20", "127.0.0.1"], stdout=subprocess.DEVNULL)
    try:
        old = selfupdate.install(new, exe)
        assert exe.exists() and old.exists() and proc.poll() is None
    finally:
        proc.kill()
        proc.wait()
