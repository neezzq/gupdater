"""Where the window gets its computer from: the real PC or the demo one."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from gupdater.autopilot.system import System
from gupdater.core.context import SystemContext
from gupdater.core.registry import WritableRegistry, system_registry


@dataclass
class Runtime:
    context_factory: Callable[[], SystemContext]
    system_factory: Callable[[], System]
    demo: bool = False
    registry_factory: Callable[[], WritableRegistry] = field(default=system_registry)
