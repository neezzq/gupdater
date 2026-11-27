"""A launcher "card": icon, name, a short subtitle, a state on the right, buttons."""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from gupdater.ui.style import MUTED

ICON_SIZE = 32


def games_text(count: int) -> str:
    if count == 0:
        return "игр нет"
    tail = count % 100
    if 11 <= tail <= 14:
        word = "игр"
    elif count % 10 == 1:
        word = "игра"
    elif 2 <= count % 10 <= 4:
        word = "игры"
    else:
        word = "игр"
    return f"{count} {word}"


class LauncherRow(QFrame):
    toggled = Signal(str, bool)

    def __init__(self, launcher_id: str, name: str, icon: QIcon, *, checkable: bool = False, checked: bool = True,
                 buttons: Iterable[QPushButton] = ()) -> None:
        super().__init__()
        self.launcher_id = launcher_id
        self.setObjectName("Row")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 6, 12, 6)
        layout.setSpacing(12)

        self.check: QCheckBox | None = None
        if checkable:
            self.check = QCheckBox()
            self.check.setChecked(checked)
            self.check.setToolTip("Обновлять этот лаунчер")
            self.check.toggled.connect(lambda on: self.toggled.emit(launcher_id, on))
            layout.addWidget(self.check)

        self.icon = QLabel()
        self.icon.setFixedSize(ICON_SIZE, ICON_SIZE)
        self.set_icon(icon)
        layout.addWidget(self.icon)

        text = QVBoxLayout()
        text.setSpacing(1)
        self.name = QLabel(name)
        font = QFont(self.name.font())
        font.setPointSizeF(font.pointSizeF() + 1.5)
        font.setWeight(QFont.Weight.Bold)
        self.name.setFont(font)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("Muted")
        text.addWidget(self.name)
        text.addWidget(self.subtitle)
        layout.addLayout(text)
        layout.addStretch(1)

        self.state = QLabel()
        self.state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        state_font = QFont(self.state.font())
        state_font.setWeight(QFont.Weight.DemiBold)
        self.state.setFont(state_font)
        layout.addWidget(self.state)
        for button in buttons:
            layout.addWidget(button)

    def set_icon(self, icon: QIcon) -> None:
        self.icon.setPixmap(icon.pixmap(QSize(ICON_SIZE, ICON_SIZE), self.devicePixelRatioF()))

    def set_subtitle(self, text: str) -> None:
        self.subtitle.setText(text)

    def set_state(self, text: str, color: str = MUTED, tooltip: str = "") -> None:
        self.state.setText(text)
        self.state.setStyleSheet(f"color: {QColor(color).name()};")
        self.state.setToolTip(tooltip or text)

    @property
    def enabled(self) -> bool:
        return self.check.isChecked() if self.check else True
