"""Subtitle window.

A normal, always-on-top window: drag it anywhere, resize it from any edge or
corner, change the text size with - and +, close it with x. It is hidden from
screen sharing and recordings, so only you see it. Position, size and text
size are remembered between runs.
"""

import ctypes
import json
from collections import deque
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
                               QGridLayout, QHBoxLayout, QLabel, QScrollArea, QStackedWidget, QToolButton,
                               QVBoxLayout, QWidget)

WDA_EXCLUDEFROMCAPTURE = 0x11
SHADOW = 16         # transparent margin around the panel that holds the drop shadow
EDGE = 8            # px inside the panel edge that act as resize handles
RADIUS = 14
MIN_SIZE = (360, 130)
FONT_RANGE = (11, 40)

PANEL_BG = QColor(18, 20, 24, 115)  # 45% opaque
PANEL_BG_SOLID = QColor(18, 20, 24, 240)  # settings need a calm background to read
SETTINGS_MIN_HEIGHT = 440
PANEL_BORDER = QColor(255, 255, 255, 24)
ACCENT = {"them": "#6b7280", "me": "#4c8dff"}
TEXT_NEW, SUB_NEW = "#ffffff", "#9aa0a8"
TEXT_OLD, SUB_OLD = "#8c929b", "#5f656e"

BUTTON_STYLE = """
QToolButton { color: #9aa0a8; background: transparent; border: none; border-radius: 6px;
              font: 15px "Segoe UI"; }
QToolButton:hover { background: rgba(255, 255, 255, 0.08); color: #ffffff; }
QToolButton#close:hover { background: rgba(232, 17, 35, 0.9); }
"""

SCROLL_STYLE = """
QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }
QScrollBar::handle:vertical { background: rgba(255, 255, 255, 0.18); border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: rgba(255, 255, 255, 0.32); }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
"""

NEW_LINES_STYLE = """
QToolButton { color: #ffffff; background: #4c8dff; border: none; border-radius: 12px;
              padding: 3px 12px; font: 600 9pt "Segoe UI"; }
QToolButton:hover { background: #3b7af0; }
"""

MAX_KEPT_LINES = 500  # the whole meeting is in transcript.jsonl; the window keeps the recent part

_app = None


def _ensure_app() -> QApplication:
    global _app
    _app = QApplication.instance() or QApplication([])
    return _app


def _label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setAttribute(Qt.WA_TransparentForMouseEvents)
    # Soft dark glow so the text stays readable on light backgrounds behind the see-through panel.
    shadow = QGraphicsDropShadowEffect(label, blurRadius=8, xOffset=0, yOffset=1)
    shadow.setColor(QColor(0, 0, 0, 220))
    label.setGraphicsEffect(shadow)
    return label


class Line(QWidget):
    """One sentence: a colored bar for the speaker, the translation, the original under it."""

    def __init__(self, source: str, original: str, translation: str | None, font_size: int):
        super().__init__()
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        bar = QFrame()
        bar.setFixedWidth(3)
        bar.setStyleSheet(f"background: {ACCENT.get(source, ACCENT['them'])}; border-radius: 1px;")

        self.main = _label(translation or original)
        self.sub = _label(original) if translation else None
        column = QVBoxLayout()
        column.setSpacing(2)
        column.addWidget(self.main)
        if self.sub:
            column.addWidget(self.sub)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        row.addWidget(bar)
        row.addLayout(column, 1)
        self.recent = True
        self.set_font_size(font_size)

    def set_font_size(self, size: int):
        self.main.setFont(QFont("Segoe UI", size, QFont.DemiBold))
        if self.sub:
            self.sub.setFont(QFont("Segoe UI", max(9, round(size * 0.68))))
        self._apply_colors()

    def set_recent(self, recent: bool):
        self.recent = recent
        self._apply_colors()

    def _apply_colors(self):
        self.main.setStyleSheet(f"color: {TEXT_NEW if self.recent else TEXT_OLD};")
        if self.sub:
            self.sub.setStyleSheet(f"color: {SUB_NEW if self.recent else SUB_OLD};")


class Panel(QWidget):
    """The visible rounded card. Dragging it moves the window, its edges resize it."""

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.solid = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
        painter.fillPath(path, PANEL_BG_SOLID if self.solid else PANEL_BG)
        painter.setPen(PANEL_BORDER)
        painter.drawPath(path)

    def _edges(self, pos) -> Qt.Edge:
        edges = Qt.Edge(0)
        if pos.x() <= EDGE:
            edges |= Qt.LeftEdge
        if pos.x() >= self.width() - EDGE:
            edges |= Qt.RightEdge
        if pos.y() <= EDGE:
            edges |= Qt.TopEdge
        if pos.y() >= self.height() - EDGE:
            edges |= Qt.BottomEdge
        return edges

    def mouseMoveEvent(self, event):
        edges = self._edges(event.position().toPoint())
        horizontal = bool(edges & (Qt.LeftEdge | Qt.RightEdge))
        vertical = bool(edges & (Qt.TopEdge | Qt.BottomEdge))
        if horizontal and vertical:
            main_diagonal = edges in (Qt.LeftEdge | Qt.TopEdge, Qt.RightEdge | Qt.BottomEdge)
            self.setCursor(Qt.SizeFDiagCursor if main_diagonal else Qt.SizeBDiagCursor)
        elif horizontal:
            self.setCursor(Qt.SizeHorCursor)
        elif vertical:
            self.setCursor(Qt.SizeVerCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        handle = self.window().windowHandle()
        edges = self._edges(event.position().toPoint())
        if edges:
            handle.startSystemResize(edges)
        else:
            handle.startSystemMove()


class Overlay(QWidget):
    settings_requested = Signal()
    _pushed = Signal(str, str, object)
    _status = Signal(str)
    _stopped = Signal()

    def __init__(self, max_lines: int = MAX_KEPT_LINES, font_size: int = 17, state_path: str | Path | None = None):
        _ensure_app()
        super().__init__()
        self.font_size = font_size
        self.state_path = Path(state_path) if state_path else None
        self._lines: deque[Line] = deque()
        self._max_lines = max_lines
        self._settings = None           # the settings page while it is open
        self._geometry_before_settings = None

        self.setWindowTitle("meeting-live")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(MIN_SIZE[0] + 2 * SHADOW, MIN_SIZE[1] + 2 * SHADOW)

        self.panel = Panel()
        shadow = QGraphicsDropShadowEffect(blurRadius=30, xOffset=0, yOffset=4)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.panel.setGraphicsEffect(shadow)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW, SHADOW, SHADOW, SHADOW)
        outer.addWidget(self.panel)

        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(18, 10, 12, 16)
        layout.setSpacing(10)
        layout.addLayout(self._build_toolbar())
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_subtitles_page())
        layout.addWidget(self.stack, 1)
        self.lines_box = QVBoxLayout(self.lines_widget)
        self.lines_box.setContentsMargins(0, 0, 10, 0)
        self.lines_box.setSpacing(12)
        self.lines_box.addStretch(1)
        self.placeholder = _label("Listening…")
        self.placeholder.setStyleSheet(f"color: {SUB_OLD};")
        self.placeholder.setFont(QFont("Segoe UI", 12))
        self.lines_box.addWidget(self.placeholder)

        self._save_timer = QTimer(self, singleShot=True, interval=400)
        self._save_timer.timeout.connect(self._save_state)
        self._pushed.connect(self._add_line)
        self._status.connect(self.placeholder.setText)
        self._stopped.connect(self.close)
        self._restore_state()

    def _build_subtitles_page(self) -> QWidget:
        """Scrollable list of sentences, plus a "new lines" button when you have scrolled up."""
        self.lines_widget = QWidget()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(SCROLL_STYLE)
        self.scroll.setWidget(self.lines_widget)
        self._follow = True  # stay pinned to the newest line until the user scrolls up
        bar = self.scroll.verticalScrollBar()
        bar.valueChanged.connect(self._on_scrolled)
        bar.rangeChanged.connect(self._on_range_changed)

        self.new_lines = QToolButton(text="↓  New lines", cursor=Qt.PointingHandCursor)
        self.new_lines.setStyleSheet(NEW_LINES_STYLE)
        self.new_lines.clicked.connect(self._scroll_to_end)
        self.new_lines.hide()

        self.subtitles_page = QWidget()
        grid = QGridLayout(self.subtitles_page)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.addWidget(self.scroll, 0, 0)
        grid.addWidget(self.new_lines, 0, 0, Qt.AlignBottom | Qt.AlignHCenter)
        return self.subtitles_page

    def _on_scrolled(self, value: int):
        self._follow = value >= self.scroll.verticalScrollBar().maximum() - 4
        if self._follow:
            self.new_lines.hide()

    def _on_range_changed(self, minimum: int, maximum: int):
        if self._follow:
            self.scroll.verticalScrollBar().setValue(maximum)

    def _scroll_to_end(self):
        self._follow = True
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.new_lines.hide()

    def _build_toolbar(self) -> QHBoxLayout:
        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet("background: #34d399; border-radius: 4px;")
        dot.setAttribute(Qt.WA_TransparentForMouseEvents)
        title = QLabel("LIVE")
        title.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
        title.setStyleSheet("color: #9aa0a8; letter-spacing: 1px;")
        title.setAttribute(Qt.WA_TransparentForMouseEvents)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(dot)
        bar.addWidget(title)
        bar.addStretch(1)
        for text, tip, slot, name in (("⚙", "Settings", self.settings_requested.emit, ""),
                                      ("−", "Smaller text", lambda: self._change_font(-1), ""),
                                      ("+", "Larger text", lambda: self._change_font(1), ""),
                                      ("✕", "Close", self.close, "close")):
            button = QToolButton(text=text, toolTip=tip)
            button.setObjectName(name)
            button.setFixedSize(28, 24)
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(BUTTON_STYLE)
            button.clicked.connect(slot)
            bar.addWidget(button)
        return bar

    # Public API, safe to call from any thread

    def push(self, source: str, original: str, translation: str | None):
        self._pushed.emit(source, original, translation)

    def set_status(self, text: str):
        """Text shown while there are no sentences yet, e.g. "Loading speech model…"."""
        self._status.emit(text)

    def stop(self):
        self._stopped.emit()

    def run(self):
        """Show the window and run until it is closed."""
        self.show()
        _app.exec()

    # Settings page (call from the GUI thread)

    def show_settings(self, view: QWidget):
        if self._settings:
            return
        self._settings = view
        self.stack.addWidget(view)
        self.stack.setCurrentWidget(view)
        self.panel.solid = True
        self.panel.update()
        self._geometry_before_settings = self.geometry()
        if self.height() < SETTINGS_MIN_HEIGHT:
            self.resize(self.width(), SETTINGS_MIN_HEIGHT)

    def show_subtitles(self):
        if not self._settings:
            return
        self.stack.setCurrentWidget(self.subtitles_page)
        self.stack.removeWidget(self._settings)
        self._settings.deleteLater()
        self._settings = None
        self.panel.solid = False
        self.panel.update()
        if self._geometry_before_settings:
            self.setGeometry(self._geometry_before_settings)
            self._geometry_before_settings = None

    # Content

    def _add_line(self, source: str, original: str, translation):
        self.placeholder.hide()
        if self._lines:
            self._lines[-1].set_recent(False)
        if not self._follow:
            self.new_lines.show()
        line = Line(source, original, translation, self.font_size)
        self.lines_box.addWidget(line)
        self._lines.append(line)
        while len(self._lines) > self._max_lines:
            old = self._lines.popleft()
            self.lines_box.removeWidget(old)
            old.deleteLater()

        effect = QGraphicsOpacityEffect(line)
        line.setGraphicsEffect(effect)
        fade = QPropertyAnimation(effect, b"opacity", line)
        fade.setDuration(220)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)
        fade.finished.connect(lambda: line.setGraphicsEffect(None))
        fade.start()

    def _change_font(self, step: int):
        self.font_size = min(FONT_RANGE[1], max(FONT_RANGE[0], self.font_size + step))
        for line in self._lines:
            line.set_font_size(self.font_size)
        self._save_timer.start()

    # Window behavior

    def showEvent(self, event):
        super().showEvent(event)
        ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), WDA_EXCLUDEFROMCAPTURE)

    def moveEvent(self, event):
        super().moveEvent(event)
        self._save_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._save_timer.start()

    def closeEvent(self, event):
        self._save_state()
        super().closeEvent(event)

    def _restore_state(self):
        screen = QApplication.primaryScreen().availableGeometry()
        width = int(screen.width() * 0.55)
        height = 200
        x, y = screen.center().x() - width // 2, screen.bottom() - height - 24
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if QApplication.screenAt(QRectF(*state["geometry"]).center().toPoint()):
                x, y, width, height = state["geometry"]
            self.font_size = int(state["font_size"])
        except (AttributeError, OSError, ValueError, KeyError, TypeError):
            pass
        self.setGeometry(x, y, width, height)

    def _save_state(self):
        if self.state_path:
            # While settings are open the window may be temporarily taller; remember the real size.
            g = self._geometry_before_settings or self.geometry()
            state = {"geometry": [g.x(), g.y(), g.width(), g.height()], "font_size": self.font_size}
            self.state_path.write_text(json.dumps(state), encoding="utf-8")


if __name__ == "__main__":
    # Demo: adds sample lines a few seconds apart. Close it with x.
    samples = [
        ("them", "Thanks everyone for joining, let's get started.", "Katıldığınız için herkese teşekkürler, başlayalım."),
        ("them", "Orhun, can you give us a quick update on the landing pages?", "Orhun, landing page'ler hakkında kısa bir güncelleme verebilir misin?"),
        ("me", "Sure, we finished thirty-four of them this week.", "Tabii, bu hafta otuz dördünü bitirdik."),
        ("them", "Great. Let's aim to wrap up the rest by Friday.", "Harika. Kalanları cuma gününe kadar bitirmeyi hedefleyelim."),
    ]
    overlay = Overlay(state_path=Path(__file__).resolve().parent.parent / "overlay_state.json")
    for i, line in enumerate(samples):
        QTimer.singleShot(1200 + i * 3500, lambda line=line: overlay.push(*line))
    overlay.run()
