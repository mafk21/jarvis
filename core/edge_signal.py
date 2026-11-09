"""Optional non-interactive screen-edge status signal for ambient JARVIS."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget


class EdgeSignal(QWidget):
    COLORS = {
        "LISTENING": QColor("#4fd2ff"),
        "THINKING": QColor("#d6a84b"),
        "PROCESSING": QColor("#d6a84b"),
        "SPEAKING": QColor("#f2d49b"),
        "VISION": QColor("#ff8a5b"),
        "ERROR": QColor("#ff5b79"),
    }

    def __init__(self):
        super().__init__(None)
        self._state = ""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_state(self, state: str, duration_ms: int | None = None) -> None:
        state = str(state or "").upper()
        if state not in self.COLORS:
            self.hide()
            return
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        self._state = state
        self.setGeometry(screen.geometry())
        self.show()
        self.raise_()
        self.update()
        self._hide_timer.stop()
        duration = duration_ms if duration_ms is not None else (1400 if state == "LISTENING" else 0)
        if duration > 0:
            self._hide_timer.start(duration)

    def paintEvent(self, _event) -> None:  # noqa: N802
        color = self.COLORS.get(self._state, QColor("#4fd2ff"))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for width, alpha in ((14, 25), (8, 50), (3, 210)):
            c = QColor(color); c.setAlpha(alpha)
            painter.setPen(QPen(c, width))
            inset = width // 2 + 1
            painter.drawRoundedRect(inset, inset, self.width()-2*inset, self.height()-2*inset, 10, 10)
        painter.end()
