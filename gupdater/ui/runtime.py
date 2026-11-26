"""Where the window gets its computer from: the real PC or the demo one."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from gupdater.autopilot.system import System
from gupdater.core.context import SystemContext


@dataclass
class Runtime:
    context_factory: Callable[[], SystemContext]
    system_factory: Callable[[], System]
    demo: bool = False
