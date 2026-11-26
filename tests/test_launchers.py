from pathlib import Path

from gupdater.core.context import SystemContext
from gupdater.core.models import GameStatus
from gupdater.core.registry import NullRegistry
from gupdater.launchers.steam import steam_status
from gupdater.report import run_scan


def names(scan):
    return [g.name for g in scan.games]


def test_every_launcher_is_found_in_demo(demo_scans):
    assert list(demo_scans) == ["steam", "epic", "vkplay", "battlenet", "riot", "ea", "lesta", "iccup"]
    for scan in demo_scans.values():
        assert scan.installed, scan.name
        assert scan.error is None, scan.error
        assert scan.games, scan.name


def test_steam_games_libraries_and_statuses(demo_scans):
    steam = demo_scans["steam"]
    status = {g.name: g.status for g in steam.games}
    assert status == {
        "Apex Legends": GameStatus.OK,
        "Counter-Strike 2": GameStatus.OK,
        "Dota 2": GameStatus.UPDATE_REQUIRED,
        "PUBG: BATTLEGROUNDS": GameStatus.UPDATING,
    }  # Steamworks Common Redistributables is a tool, not a game
    assert steam.updates_needed == 1
    assert steam.running
    cs2 = next(g for g in steam.games if g.game_id == "730")
    assert cs2.version == "18731234" and cs2.size_bytes == 38_000_000_000
    assert cs2.install_path.endswith("Counter-Strike Global Offensive")


def test_steam_status_rules():
    assert steam_status(4, "1", "0", 0, 0)[0] is GameStatus.OK
    assert steam_status(6, "1", "0", 0, 0)[0] is GameStatus.UPDATE_REQUIRED
    assert steam_status(4, "1", "2", 0, 0)[0] is GameStatus.UPDATE_REQUIRED
    assert steam_status(4, "1", "0", 10, 5)[0] is GameStatus.UPDATE_REQUIRED
    assert steam_status(4 | 2 | 512, "1", "0", 0, 0) == (GameStatus.UPDATE_REQUIRED, "Steam: обновление на паузе")
    assert steam_status(4 | 1024, "1", "0", 0, 0)[0] is GameStatus.UPDATING
    assert steam_status(4 | 32, "1", "0", 0, 0)[0] is GameStatus.BROKEN
    assert steam_status(0, "", "", 0, 0)[0] is GameStatus.UNKNOWN


def test_epic_skips_dlc_and_reads_versions(demo_scans):
    epic = demo_scans["epic"]
    assert names(epic) == ["Fortnite", "Rocket League"]
    assert epic.games[1].game_id == "Sugar" and epic.games[1].version == "2.51"
    assert "Сохранённый вход Epic: есть" in epic.notes


def test_battlenet_uses_uninstaller_uid(demo_scans):
    games = {g.name: g.game_id for g in demo_scans["battlenet"].games}
    assert games == {"Diablo IV": "fenris", "Overwatch": "prometheus"}


def test_riot_combines_metadata_and_programs_list(demo_scans):
    riot = demo_scans["riot"]
    assert names(riot) == ["League of Legends", "VALORANT"]
    assert all(g.game_id != "riot_client" for g in riot.games)
    assert riot.exe_path.endswith("RiotClientServices.exe")


def test_ea_ignores_games_owned_by_steam(demo_scans):
    assert names(demo_scans["ea"]) == ["Battlefield 2042"]


def test_vkplay_lesta_iccup(demo_scans):
    assert names(demo_scans["vkplay"]) == ["Warface"]
    lesta = demo_scans["lesta"]
    assert names(lesta) == ["Мир танков"]
    assert lesta.games[0].version == "1.31.0.1"  # from game_info.xml, not the programs list
    assert names(demo_scans["iccup"]) == ["Warcraft III (iCCup)"]
    assert demo_scans["iccup"].exe_path.endswith("iCCup Launcher.exe")


def test_empty_pc_finds_nothing_and_does_not_fail(tmp_path):
    ctx = SystemContext(registry=NullRegistry(), env={"PROGRAMDATA": str(tmp_path)}, drives=[str(tmp_path)])
    for scan in run_scan(ctx).scans:
        assert not scan.installed and not scan.games and scan.error is None, scan.name


def test_broken_detector_is_reported_not_raised(tmp_path, monkeypatch):
    from gupdater.launchers.epic import Epic

    def boom(self, ctx, result):
        raise RuntimeError("boom")

    monkeypatch.setattr(Epic, "_scan", boom)
    ctx = SystemContext(registry=NullRegistry(), env={}, drives=[])
    scans = {s.launcher_id: s for s in run_scan(ctx).scans}
    assert scans["epic"].error == "RuntimeError: boom"


def test_other_game_centers_are_not_vk_play(tmp_path):
    from gupdater.core.registry import DictRegistry
    from gupdater.demo import UNINSTALL

    reg = DictRegistry({
        rf"{UNINSTALL}\WGC": {"DisplayName": "Wargaming.net Game Center", "Publisher": "Wargaming.net"},
        rf"{UNINSTALL}\LGC": {"DisplayName": "Lesta Game Center", "Publisher": "Lesta Games"},
    })
    ctx = SystemContext(registry=reg, env={}, drives=[])
    scans = {s.launcher_id: s for s in run_scan(ctx).scans}
    assert not scans["vkplay"].installed
    assert scans["lesta"].installed
