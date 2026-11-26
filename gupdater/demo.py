"""A made-up club PC, built in a temporary folder.

Used by the tests and by ``GUpdater.exe --demo`` to show what the window
looks like without real launchers. Nothing here touches the real system.
"""

from __future__ import annotations

import json
from pathlib import Path

from gupdater.core.context import SystemContext
from gupdater.core.registry import DictRegistry

UNINSTALL = r"HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"

# Values that must never show up in a report.
SECRET_STEAM_ACCOUNT = "player_one_login"
SECRET_TOKEN = "SECRET-LOGIN-TOKEN-12345"


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _vdf_str(value: object) -> str:
    return str(value).replace("\\", "\\\\")


def _manifest(appid: str, name: str, installdir: str, flags: int, buildid: str, size: int, **extra: str) -> str:
    fields = {
        "appid": appid,
        "name": name,
        "StateFlags": flags,
        "installdir": installdir,
        "SizeOnDisk": size,
        "buildid": buildid,
        **extra,
    }
    body = "\n".join(f'\t"{k}"\t\t"{_vdf_str(v)}"' for k, v in fields.items())
    return f'"AppState"\n{{\n{body}\n}}\n'


def build_demo_context(root: Path) -> SystemContext:
    c, d = root / "C", root / "D"
    program_data = c / "ProgramData"
    pf, pf86 = c / "Program Files", c / "Program Files (x86)"
    profile = c / "Users" / "Admin"
    local, roaming = profile / "AppData" / "Local", profile / "AppData" / "Roaming"
    for folder in (program_data, pf, pf86, local, roaming, d):
        folder.mkdir(parents=True, exist_ok=True)

    reg = DictRegistry()

    def program(key: str, name: str, publisher: str = "", location: Path | str = "", version: str = "",
                uninstall: str = "", size_kb: int | None = None) -> None:
        values = {
            "DisplayName": name,
            "Publisher": publisher,
            "InstallLocation": str(location),
            "DisplayVersion": version,
            "UninstallString": uninstall,
        }
        if size_kb:
            values["EstimatedSize"] = size_kb
        reg.set(f"{UNINSTALL}\\{key}", values)

    # --- Steam: two libraries, one game waiting for an update, one updating
    steam = pf86 / "Steam"
    library2 = d / "SteamLibrary"
    _write(steam / "steam.exe")
    _write(
        steam / "steamapps" / "libraryfolders.vdf",
        '"libraryfolders"\n{\n'
        f'\t"0"\n\t{{\n\t\t"path"\t\t"{_vdf_str(steam)}"\n\t\t"apps"\n\t\t{{\n\t\t\t"730"\t\t"1"\n\t\t}}\n\t}}\n'
        f'\t"1"\n\t{{\n\t\t"path"\t\t"{_vdf_str(library2)}"\n\t}}\n}}\n',
    )
    _write(steam / "steamapps" / "appmanifest_730.acf",
           _manifest("730", "Counter-Strike 2", "Counter-Strike Global Offensive", 4, "18731234", 38_000_000_000))
    _write(steam / "steamapps" / "appmanifest_228980.acf",
           _manifest("228980", "Steamworks Common Redistributables", "Steamworks Shared", 4, "1", 1_000_000))
    _write(library2 / "steamapps" / "appmanifest_570.acf",
           _manifest("570", "Dota 2", "dota 2 beta", 6, "18690011", 41_000_000_000, TargetBuildID="18712345"))
    _write(library2 / "steamapps" / "appmanifest_578080.acf",
           _manifest("578080", "PUBG: BATTLEGROUNDS", "PUBG", 4 | 2 | 1024 | (1 << 20), "18500000", 40_000_000_000,
                     BytesToDownload="2000000000", BytesDownloaded="500000000"))
    _write(library2 / "steamapps" / "appmanifest_1172470.acf",
           _manifest("1172470", "Apex Legends", "Apex Legends", 4, "18622222", 75_000_000_000))
    _write(
        steam / "config" / "loginusers.vdf",
        '"users"\n{\n'
        f'\t"76561190000000001"\n\t{{\n\t\t"AccountName"\t\t"{SECRET_STEAM_ACCOUNT}"\n'
        '\t\t"PersonaName"\t\t"Игрок"\n\t\t"RememberPassword"\t\t"1"\n\t}\n'
        '\t"76561190000000002"\n\t{\n\t\t"AccountName"\t\t"guest_two"\n\t\t"RememberPassword"\t\t"0"\n\t}\n}\n',
    )
    reg.set(r"HKCU\Software\Valve\Steam", {"SteamPath": str(steam), "AutoLoginUser": SECRET_STEAM_ACCOUNT})
    program("Steam App 1172470", "Apex Legends", "Electronic Arts", library2 / "steamapps" / "common" / "Apex Legends",
            uninstall=f'"{steam / "steam.exe"}" steam://uninstall/1172470')

    # --- Epic Games: two games and a DLC that must not be listed separately
    _write(pf86 / "Epic Games" / "Launcher" / "Portal" / "Binaries" / "Win64" / "EpicGamesLauncher.exe")
    manifests = program_data / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    for item_id, data in {
        "A1": {"DisplayName": "Fortnite", "AppName": "Fortnite", "AppCategories": ["public", "games", "applications"],
               "InstallLocation": str(d / "Epic Games" / "Fortnite"),
               "AppVersionString": "++Fortnite+Release-33.10-CL-38000000-Windows", "InstallSize": 32_000_000_000},
        "B2": {"DisplayName": "Rocket League", "AppName": "Sugar", "AppCategories": ["public", "games"],
               "InstallLocation": str(d / "Epic Games" / "rocketleague"), "AppVersionString": "2.51",
               "InstallSize": 25_000_000_000},
        "C3": {"DisplayName": "Rocket League — Season Pass", "AppName": "SugarDLC", "MainGameAppName": "Sugar",
               "AppCategories": ["addons"]},
    }.items():
        _write(manifests / f"{item_id}.item", json.dumps(data, ensure_ascii=False, indent=2))
    _write(local / "EpicGamesLauncher" / "Saved" / "Config" / "Windows" / "GameUserSettings.ini",
           f"[RememberMe]\nEnable=True\nData={SECRET_TOKEN}\n")

    # --- VK Play
    vk = local / "GameCenter"
    _write(vk / "GameCenter.exe")
    program("VK Play", "VK Play", "VK", vk, "4.1700")
    program("Warface_ru", "Warface", "MY.GAMES", d / "Games" / "Warface", "1.0",
            uninstall=f'"{vk / "GameCenter.exe"}" -uninstall 0.1177', size_kb=30_000_000)

    # --- Battle.net
    bnet = pf86 / "Battle.net"
    _write(bnet / "Battle.net Launcher.exe")
    _write(program_data / "Battle.net" / "Agent" / "product.db")
    uninstaller = program_data / "Battle.net" / "Agent" / "Blizzard Uninstaller.exe"
    program("Battle.net", "Battle.net", "Blizzard Entertainment", bnet, "2.40")
    program("Overwatch", "Overwatch", "Blizzard Entertainment", d / "Overwatch", "2.14",
            f'"{uninstaller}" --lang=ruRU --uid=prometheus --displayname="Overwatch"', 50_000_000)
    program("Diablo IV", "Diablo IV", "Blizzard Entertainment", d / "Diablo IV", "2.1",
            f'"{uninstaller}" --lang=ruRU --uid=fenris --displayname="Diablo IV"', 90_000_000)

    # --- Riot
    riot_client = c / "Riot Games" / "Riot Client" / "RiotClientServices.exe"
    _write(riot_client)
    riot_data = program_data / "Riot Games"
    _write(riot_data / "RiotClientInstalls.json", json.dumps({"rc_default": str(riot_client)}))
    for product, folder, shortcut in (("valorant.live", "VALORANT/live", "VALORANT.lnk"),
                                      ("league_of_legends.live", "League of Legends", "League of Legends.lnk"),
                                      ("riot_client", "Riot Client", "")):
        _write(riot_data / "Metadata" / product / f"{product}.product_settings.yaml",
               f'product_install_full_path: "{c / "Riot Games" / folder}"\nshortcut_name: "{shortcut}"\n')
    program("Riot Game valorant.live", "VALORANT", "Riot Games, Inc", c / "Riot Games" / "VALORANT" / "live")
    _write(local / "Riot Games" / "Riot Client" / "Data" / "RiotGamesPrivateSettings.yaml", f"token: {SECRET_TOKEN}\n")

    # --- EA app
    _write(pf / "Electronic Arts" / "EA Desktop" / "EA Desktop" / "EADesktop.exe")
    program("{EA-APP}", "EA app", "Electronic Arts", pf / "Electronic Arts" / "EA Desktop", "13.300")
    program("{BF2042}", "Battlefield 2042", "Electronic Arts", d / "EA Games" / "Battlefield 2042", "1.0.88",
            f'"{d / "EA Games" / "Battlefield 2042" / "__Installer" / "Cleanup.exe"}" uninstall_game', 100_000_000)

    # --- Lesta Game Center
    lgc = program_data / "Lesta" / "GameCenter"
    _write(lgc / "lgc.exe")
    (lgc / "apps" / "tanks").mkdir(parents=True)
    tanks = d / "Games" / "Tanki"
    _write(tanks / "game_info.xml", "<protocol><game><version_name>1.31.0.1</version_name></game></protocol>")
    program("Lesta Game Center", "Lesta Game Center", "Lesta Games", lgc)
    program("MT.RU.PRODUCTION", "Мир танков", "Lesta Games", tanks, "1.31", size_kb=70_000_000)

    # --- iCCup
    _write(d / "iCCup" / "iCCup Launcher.exe")
    _write(d / "iCCup" / "Warcraft III" / "war3.exe")

    # --- SmartShell and launcher protocols
    program("SmartShell Client", "SmartShell Client", "SmartShell", pf / "SmartShell", "4.2")
    for scheme, exe in (("steam", steam / "steam.exe"), ("battlenet", bnet / "Battle.net Launcher.exe")):
        reg.set(f"HKCR\\{scheme}", {"URL Protocol": ""})
        reg.set(f"HKCR\\{scheme}\\shell\\open\\command", {"": f'"{exe}" "%1"'})

    return SystemContext(
        registry=reg,
        env={
            "PROGRAMDATA": str(program_data),
            "PROGRAMFILES": str(pf),
            "PROGRAMFILES(X86)": str(pf86),
            "LOCALAPPDATA": str(local),
            "APPDATA": str(roaming),
            "USERPROFILE": str(profile),
        },
        drives=[str(c), str(d)],
        running=frozenset({"steam.exe", "epicgameslauncher.exe", "smartshell.client.exe", "explorer.exe"}),
        is_windows=True,
        computer_name="CLUB-PC-07",
        os_name="Windows 11 (демо)",
    )
