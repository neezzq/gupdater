"""A made-up club PC, built in a temporary folder.

Used by the tests and by ``GUpdater.exe --demo`` to show what the window
looks like without real launchers. Nothing here touches the real system.
"""

from __future__ import annotations

import json
from pathlib import Path

from gupdater.core import vdf
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
        if location:
            Path(location).mkdir(parents=True, exist_ok=True)

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
    for library in (steam, library2):
        for manifest in (library / "steamapps").glob("appmanifest_*.acf"):
            installdir = vdf.load(manifest)["appstate"]["installdir"]
            (library / "steamapps" / "common" / installdir).mkdir(parents=True, exist_ok=True)
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
        if data.get("InstallLocation"):
            Path(data["InstallLocation"]).mkdir(parents=True, exist_ok=True)
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
        (c / "Riot Games" / folder).mkdir(parents=True, exist_ok=True)
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


# --- A demo PC whose launchers "download" on a fast-forward clock -----------

MB = 1024 * 1024
# launcher exe (lower case) -> (process name, [(from s, to s, read B/s, write B/s)], closes politely)
_DEMO_PROFILES = {
    "steam.exe": ("steam.exe", [(15, 140, 1 * MB, 12 * MB)], True),
    "epicgameslauncher.exe": ("epicgameslauncher.exe", [(0, 15, 3 * MB, 0)], True),
    "gamecenter.exe": ("gamecenter.exe", [(30, 200, MB // 2, 6 * MB)], True),
    "battle.net launcher.exe": ("battle.net.exe", [(20, 320, 1 * MB, 9 * MB)], True),
    "riotclientservices.exe": ("riotclientservices.exe", [(40, 160, MB // 2, 8 * MB)], True),
    "eadesktop.exe": ("eadesktop.exe", [(0, 10, 2 * MB, 0)], False),  # ignores a polite close
    "lgc.exe": ("lgc.exe", [], True),
    "iccup launcher.exe": ("iccup launcher.exe", [(5, 15, MB // 5, MB // 10)], True),
}
# What Steam's manifests look like once the demo updates are done.
_STEAM_UPDATED = {
    "570": ("Dota 2", "dota 2 beta", "18712345", 41_000_000_000),
    "578080": ("PUBG: BATTLEGROUNDS", "PUBG", "18500001", 40_000_000_000),
}


class _DemoProc:
    def __init__(self, pid: int, name: str, started: float, profile: list, graceful: bool) -> None:
        self.pid, self.name, self.started, self.profile, self.graceful = pid, name, started, list(profile), graceful

    def counters(self, t: float) -> tuple[int, int]:
        age = t - self.started
        read = written = 0.0
        for start, end, r, w in self.profile:
            span = max(0.0, min(age, end) - start)
            read += span * r
            written += span * w
        return int(read), int(written)


class DemoSystem:
    """Implements ``gupdater.autopilot.system.System`` for the demo PC."""

    def __init__(self, world: "DemoWorld", speed: float = 100.0) -> None:
        import threading

        self.world = world
        self.speed = speed
        self.t = 0.0
        self.wall0 = __import__("time").time()
        self._lock = threading.Lock()
        self._procs: dict[int, _DemoProc] = {}
        self._events: list[tuple[float, object]] = []
        self._next_pid = 1000
        for name in ("explorer.exe", "smartshell.client.exe"):
            self._add(name, [], True)

    # System protocol
    def now(self) -> float:
        return self.t

    def wall_time(self) -> float:
        return self.wall0 + self.t

    def sleep(self, seconds: float, stop) -> bool:
        if stop.wait(seconds / self.speed):
            return False
        with self._lock:
            self.t += seconds
            due = [e for e in self._events if e[0] <= self.t]
            self._events = [e for e in self._events if e[0] > self.t]
        for _, action in due:
            action()
        return True

    def start(self, command) -> None:
        exe = Path(command[0]).name.lower()
        args = list(command[1:])
        with self._lock:
            if exe == "steam.exe" and "-shutdown" in args:
                self._remove({"steam.exe"}, force=True)
                return
            validate = next((a for a in args if a.startswith("steam://validate/")), None)
            if exe == "steam.exe" and validate:
                appid = validate.rsplit("/", 1)[1]
                for proc in self._procs.values():
                    if proc.name == "steam.exe":
                        age = self.t - proc.started
                        proc.profile.append((age, age + 150, 20 * MB, 15 * MB))
                self._events.append((self.t + 150, lambda: self._steam_done(appid)))
                return
            if exe not in _DEMO_PROFILES:
                raise OSError(f"нет такой программы: {command[0]}")
            name, profile, graceful = _DEMO_PROFILES[exe]
            self._add(name, profile, graceful)
            if exe == "steam.exe":
                local = Path(self.world.base.env["LOCALAPPDATA"]) / "Steam" / "local.vdf"
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_text('"MachineUserConfigStore"\n{\n\t"ConnectCache"\n\t{\n\t\t"1a2b3c1"\t"demo-club-token"\n\t}\n}\n',
                                 encoding="utf-8")
            if exe == "steam.exe":
                self._events.append((self.t + 140, lambda: self._steam_done("578080")))

    def processes(self):
        from gupdater.autopilot.system import ProcInfo

        with self._lock:
            result = []
            for p in self._procs.values():
                read, written = p.counters(self.t)
                result.append(ProcInfo(p.pid, p.name, None, self.wall0 + p.started, read, written))
            return result

    def close(self, names, force: bool) -> None:
        with self._lock:
            self._remove({n.lower() for n in names}, force)

    def idle_seconds(self):
        return None

    # helpers
    def running_names(self) -> frozenset[str]:
        with self._lock:
            return frozenset(p.name for p in self._procs.values())

    def _add(self, name: str, profile: list, graceful: bool) -> None:
        self._next_pid += 1
        self._procs[self._next_pid] = _DemoProc(self._next_pid, name, self.t, profile, graceful)

    def _remove(self, names: set[str], force: bool) -> None:
        for pid, proc in list(self._procs.items()):
            if proc.name in names and (force or proc.graceful):
                del self._procs[pid]

    def _steam_done(self, appid: str) -> None:
        if appid not in _STEAM_UPDATED:
            return
        name, installdir, buildid, size = _STEAM_UPDATED[appid]
        for manifest in self.world.root.rglob(f"appmanifest_{appid}.acf"):
            manifest.write_text(_manifest(appid, name, installdir, 4, buildid, size), encoding="utf-8")


class DemoWorld:
    """The demo PC: files on disk plus simulated running programs."""

    def __init__(self, root: Path, speed: float = 100.0) -> None:
        self.root = root
        self.base = build_demo_context(root / "pc")
        self.system = DemoSystem(self, speed)

    def context(self) -> SystemContext:
        from dataclasses import replace

        return replace(self.base, running=self.system.running_names())
