"""Settings page shown inside the subtitle window.

Each audio channel can be turned on or off, pointed at a device and given a
language. Emits `saved` with the new Config, or `cancelled`.
"""

from copy import deepcopy

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from app.config import Channel, Config, system_language

LANGUAGES = [
    ("en", "English"), ("tr", "Türkçe"), ("de", "Deutsch"), ("fr", "Français"), ("es", "Español"),
    ("it", "Italiano"), ("pt", "Português"), ("nl", "Nederlands"), ("pl", "Polski"), ("ru", "Русский"),
    ("uk", "Українська"), ("ar", "العربية"), ("hi", "हिन्दी"), ("zh", "中文"), ("ja", "日本語"), ("ko", "한국어"),
]

STYLE = """
QWidget { color: #e6e8eb; font: 10pt "Segoe UI"; }
QLabel#title { font: 600 12pt "Segoe UI"; }
QLabel#hint { color: #8a9099; font: 9pt "Segoe UI"; }
QComboBox { background: rgba(255, 255, 255, 0.07); border: 1px solid rgba(255, 255, 255, 0.10);
            border-radius: 8px; padding: 6px 10px; }
QComboBox:hover { border-color: rgba(255, 255, 255, 0.24); }
QComboBox:disabled { color: #5f656e; border-color: rgba(255, 255, 255, 0.05); }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: #1b1e23; color: #e6e8eb; border: 1px solid rgba(255, 255, 255, 0.12);
                              selection-background-color: #2b5fb8; outline: none; padding: 4px; }
QCheckBox { font: 600 10.5pt "Segoe UI"; spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid rgba(255, 255, 255, 0.35); }
QCheckBox::indicator:checked { background: #4c8dff; border-color: #4c8dff; }
QPushButton { border: none; border-radius: 8px; padding: 7px 18px; background: rgba(255, 255, 255, 0.08); }
QPushButton:hover { background: rgba(255, 255, 255, 0.14); }
QPushButton#primary { background: #4c8dff; color: #ffffff; font-weight: 600; }
QPushButton#primary:hover { background: #3b7af0; }
"""


def _combo(items: list[tuple[str, str]], current: str) -> QComboBox:
    """items are (value, label) pairs."""
    combo = QComboBox()
    combo.setCursor(Qt.PointingHandCursor)
    for value, label in items:
        combo.addItem(label, value)
    index = combo.findData(current)
    combo.setCurrentIndex(max(index, 0))
    return combo


class ChannelRow:
    def __init__(self, grid: QGridLayout, row: int, title: str, hint: str, channel: Channel, devices: list[str]):
        self.enabled = QCheckBox(title)
        self.enabled.setChecked(channel.enabled)
        self.enabled.setCursor(Qt.PointingHandCursor)
        hint_label = QLabel(hint, objectName="hint")

        device_items = [("default", "Default device")] + [(name, name) for name in devices]
        if channel.device not in ("default", *devices):
            device_items.append((channel.device, f"{channel.device} (not connected)"))
        self.device = _combo(device_items, channel.device)
        self.language = _combo([("auto", "Detect language")] + LANGUAGES, channel.language)

        grid.addWidget(self.enabled, row, 0, 1, 2)
        grid.addWidget(hint_label, row + 1, 0, 1, 2)
        grid.addWidget(self.device, row + 2, 0)
        grid.addWidget(self.language, row + 2, 1)
        self.enabled.toggled.connect(self._sync)
        self._sync(channel.enabled)

    def _sync(self, on: bool):
        self.device.setEnabled(on)
        self.language.setEnabled(on)

    def value(self) -> Channel:
        return Channel(self.enabled.isChecked(), self.device.currentData(), self.language.currentData())


class SettingsView(QWidget):
    saved = Signal(object)
    cancelled = Signal()

    def __init__(self, config: Config, devices: dict[str, list[str]]):
        super().__init__()
        self.config = config
        self.setStyleSheet(STYLE)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        self.meeting = ChannelRow(grid, 0, "Meeting audio", "What comes out of your speakers: the other side",
                                  config.meeting_audio, devices.get("them", []))
        grid.setRowMinimumHeight(3, 14)
        self.mic = ChannelRow(grid, 4, "My microphone", "Your own voice, in the language you speak",
                              config.microphone, devices.get("me", []))
        grid.setRowMinimumHeight(7, 14)

        grid.addWidget(QLabel("Subtitles in", objectName="hint"), 8, 0, 1, 2)
        windows = system_language()
        self.subtitles = _combo([("auto", f"Windows language ({windows})")] + LANGUAGES, config.subtitle_language)
        grid.addWidget(self.subtitles, 9, 0)

        cancel = QPushButton("Cancel", cursor=Qt.PointingHandCursor)
        save = QPushButton("Save", objectName="primary", cursor=Qt.PointingHandCursor)
        cancel.clicked.connect(self.cancelled.emit)
        save.clicked.connect(self._save)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(QLabel("Settings", objectName="title"))
        layout.addLayout(grid)
        layout.addStretch(1)
        layout.addLayout(buttons)

    def _save(self):
        config = deepcopy(self.config)
        config.meeting_audio = self.meeting.value()
        config.microphone = self.mic.value()
        config.subtitle_language = self.subtitles.currentData()
        self.saved.emit(config)
