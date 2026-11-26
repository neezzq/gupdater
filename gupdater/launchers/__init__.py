"""All supported launchers, in the order they are shown and updated."""

from gupdater.launchers.base import Launcher
from gupdater.launchers.battlenet import BattleNet
from gupdater.launchers.ea import EA
from gupdater.launchers.epic import Epic
from gupdater.launchers.iccup import ICCup
from gupdater.launchers.lesta import Lesta
from gupdater.launchers.riot import Riot
from gupdater.launchers.steam import Steam
from gupdater.launchers.vkplay import VKPlay

ALL_LAUNCHERS: tuple[Launcher, ...] = (
    Steam(),
    Epic(),
    VKPlay(),
    BattleNet(),
    Riot(),
    EA(),
    Lesta(),
    ICCup(),
)

__all__ = ["ALL_LAUNCHERS", "Launcher"]
