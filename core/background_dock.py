from __future__ import annotations

from collections import deque
import math
import time
from typing import Callable

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QKeyEvent,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

COLLAPSED_SIZE = 64
EXPANDED_W = 388
EXPANDED_H = 346
CORNER_MARGIN = 18


class _MiniOrbIndicator(QWidget):
    """Compact live audio-reactive orb painted inside the expanded header."""

    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._primary = QColor("#4fd2ff")
        self._secondary = QColor("#ffb347")
        self._state = "LISTENING"
        self._muted = False
        self._level = 0.0
        self._phase = 0.0

    def update_visual(
        self,
        primary: QColor,
        secondary: QColor,
        state: str,
        muted: bool,
        level: float,
        phase: float,
    ) -> None:
        self._primary = primary
        self._secondary = secondary
        self._state = state
        self._muted = muted
        self._level = level
        self._phase = phase
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx, cy = self.width() / 2.0, self.height() / 2.0

        st = (self._state or "").upper()
        if self._muted or st == "MUTED":
            col = QColor("#ff5b79")
        elif st == "SPEAKING":
            col = QColor(self._secondary)
        else:
            col = QColor(self._primary)

        pulse = 1.0 + min(0.32, self._level * 0.45) + 0.06 * math.sin(self._phase * 2.4)
        glow = QRadialGradient(QPointF(cx, cy), 13.0 * pulse)
        c_mid = QColor(col)
        c_mid.setAlpha(185)
        c_out = QColor(col)
        c_out.setAlpha(0)
        glow.setColorAt(0.0, QColor(255, 255, 255, 230))
        glow.setColorAt(0.38, c_mid)
        glow.setColorAt(1.0, c_out)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(cx, cy), 12.5 * pulse, 12.5 * pulse)

        ring_pen = QPen(col, 1.3)
        p.setPen(ring_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), 9.5, 9.5)
        p.end()


class BackgroundDockWidget(QWidget):
    """Always-on-top bottom-right desktop widget for JARVIS Background Mode.

    - Collapsed (`64x64`): Visible glowing orb button pinned to the bottom-right
      corner of the screen while JARVIS continues listening and speaking in the
      background.
    - Expanded (`388x346`): Smoothly extends upward/leftward from the bottom-right
      corner into a sleek rounded glass panel with live voice status, recent
      conversation turns, mic mute toggle, Full HUD restore, and instant typing.
    """

    def __init__(
        self,
        *,
        on_send_text: Callable[[str], None] | None = None,
        on_toggle_mute: Callable[[], None] | None = None,
        on_restore_full: Callable[[], None] | None = None,
        on_interrupt: Callable[[], None] | None = None,
        on_crop_question: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(None)
        self._on_send_text = on_send_text
        self._on_toggle_mute = on_toggle_mute
        self._on_restore_full = on_restore_full
        self._on_interrupt = on_interrupt
        self._on_crop_question = on_crop_question

        self.setWindowTitle("JARVIS Mini Dock")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._expanded = False
        self._hovered = False
        self._persona = "male"
        self._assistant_name = "JARVIS"
        self._raw_state = "LISTENING"
        self._muted = False
        self._audio_level = 0.0
        self._phase = 0.0
        self._messages: deque[tuple[str, str]] = deque(maxlen=24)

        # Custom anchor offset from bottom-right of availableGeometry if dragged
        self._anchor_right_offset = CORNER_MARGIN
        self._anchor_bottom_offset = CORNER_MARGIN
        self._drag_press_global: QPoint | None = None
        self._drag_start_offsets: tuple[int, int] = (CORNER_MARGIN, CORNER_MARGIN)
        self._dragged = False

        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setDuration(190)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._on_anim_finished)

        self._build_expanded_ui()

        self._tick = QTimer(self)
        self._tick.setInterval(33)  # ~30 FPS smooth pulse while visible
        self._tick.timeout.connect(self._on_tick)

        self.resize(COLLAPSED_SIZE, COLLAPSED_SIZE)
        self._panel.hide()

    # ── Theme helpers ─────────────────────────────────────────────────────────

    def _palette(self) -> tuple[QColor, QColor, str, str, str]:
        if self._persona == "female":
            return (
                QColor("#ff5db1"),  # primary rose-orchid
                QColor("#ffd06a"),  # secondary warm gold
                "#ff5db1",
                "#ffd06a",
                "rgba(16, 6, 20, 0.94)",
            )
        return (
            QColor("#4fd2ff"),  # primary electric cyan
            QColor("#ffb347"),  # secondary molten gold
            "#4fd2ff",
            "#ffb347",
            "rgba(4, 10, 18, 0.94)",
        )

    # ── UI Construction ───────────────────────────────────────────────────────

    def _build_expanded_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._panel = QFrame(self)
        self._panel.setObjectName("bgDockPanel")
        p_layout = QVBoxLayout(self._panel)
        p_layout.setContentsMargins(14, 12, 14, 12)
        p_layout.setSpacing(10)

        # Header Row
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setSpacing(8)

        self._mini_orb = _MiniOrbIndicator(self._panel)
        self._mini_orb.setToolTip("Tap to interrupt speech or wake")
        self._mini_orb.clicked.connect(self._handle_orb_click)
        hdr.addWidget(self._mini_orb)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(1)

        self._title_lbl = QLabel("JARVIS", self._panel)
        f_title = QFont("Segoe UI", 9)
        f_title.setBold(True)
        f_title.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.2)
        self._title_lbl.setFont(f_title)
        title_col.addWidget(self._title_lbl)

        self._status_lbl = QLabel("● LISTENING · VOICE ACTIVE", self._panel)
        f_sub = QFont("Consolas", 8)
        self._status_lbl.setFont(f_sub)
        title_col.addWidget(self._status_lbl)

        hdr.addLayout(title_col, 1)

        self._mute_btn = QPushButton("MIC", self._panel)
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.setToolTip("Mute / Unmute microphone")
        self._mute_btn.setFixedHeight(26)
        self._mute_btn.clicked.connect(self._handle_mute_click)
        hdr.addWidget(self._mute_btn)

        self._full_btn = QPushButton("FULL ⤢", self._panel)
        self._full_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._full_btn.setToolTip("Restore full 3D JARVIS HUD window")
        self._full_btn.setFixedHeight(26)
        self._full_btn.clicked.connect(self._handle_restore_click)
        hdr.addWidget(self._full_btn)

        self._collapse_btn = QPushButton("▾", self._panel)
        self._collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_btn.setToolTip("Collapse back to corner button")
        self._collapse_btn.setFixedSize(26, 26)
        self._collapse_btn.clicked.connect(self.collapse)
        hdr.addWidget(self._collapse_btn)

        p_layout.addLayout(hdr)

        # Scrollable Mini Feed
        self._scroll = QScrollArea(self._panel)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { width: 5px; background: transparent; }"
            "QScrollBar::handle:vertical { background: rgba(140,190,225,0.25); border-radius: 2px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
        )

        self._feed_host = QWidget()
        self._feed_host.setStyleSheet("background: transparent;")
        self._feed_layout = QVBoxLayout(self._feed_host)
        self._feed_layout.setContentsMargins(2, 2, 2, 2)
        self._feed_layout.setSpacing(6)
        self._feed_layout.addStretch(1)
        self._scroll.setWidget(self._feed_host)
        p_layout.addWidget(self._scroll, 1)

        # Input Row
        inp_row = QHBoxLayout()
        inp_row.setContentsMargins(0, 0, 0, 0)
        inp_row.setSpacing(7)

        self._mode = QComboBox(self._panel)
        self._mode.addItem("General", "general")
        self._mode.addItem("Screen", "screen")
        self._mode.addItem("Crop", "crop")
        self._mode.addItem("Agent", "agent")
        self._mode.setToolTip("Choose what context JARVIS may use")
        self._mode.setFixedHeight(36)
        inp_row.addWidget(self._mode)

        self._input = QLineEdit(self._panel)
        self._input.setPlaceholderText("Type to JARVIS… (mic & voice still active)")
        self._input.setFixedHeight(36)
        self._input.returnPressed.connect(self._handle_send)
        inp_row.addWidget(self._input, 1)

        self._send_btn = QPushButton("➤", self._panel)
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setToolTip("Send message")
        self._send_btn.setFixedSize(38, 36)
        self._send_btn.clicked.connect(self._handle_send)
        inp_row.addWidget(self._send_btn)

        p_layout.addLayout(inp_row)
        root_layout.addWidget(self._panel)

        self._apply_styles()
        self._rebuild_feed()

    def _apply_styles(self) -> None:
        _c1, _c2, pri_hex, sec_hex, bg_rgba = self._palette()
        self._panel.setStyleSheet(
            f"""
            QFrame#bgDockPanel {{
                background: {bg_rgba};
                border: 1px solid {pri_hex}55;
                border-radius: 20px;
            }}
            """
        )
        self._title_lbl.setStyleSheet(f"color: #f0ede8; background: transparent;")
        st = (self._raw_state or "LISTENING").upper()
        if self._muted or st == "MUTED":
            st_col = "#ff5b79"
            st_txt = "● MIC MUTED"
        elif st == "SPEAKING":
            st_col = sec_hex
            st_txt = "● SPEAKING · CLICK ORB TO INTERRUPT"
        elif st in ("THINKING", "PROCESSING"):
            st_col = sec_hex
            st_txt = "● THINKING…"
        else:
            st_col = "#34d399"
            st_txt = "● LISTENING · VOICE ACTIVE"
        self._status_lbl.setText(st_txt)
        self._status_lbl.setStyleSheet(f"color: {st_col}; background: transparent;")

        pill_btn = (
            "QPushButton {{"
            " background: rgba(255,255,255,0.05);"
            f" border: 1px solid {pri_hex}40;"
            " border-radius: 13px;"
            " padding: 0 9px;"
            " color: #e8eef5;"
            " font-family: Consolas, monospace;"
            " font-size: 9.5px;"
            " }}"
            f"QPushButton:hover {{ background: {pri_hex}28; border-color: {pri_hex}; }}"
        )
        if self._muted:
            self._mute_btn.setText("MUTED")
            self._mute_btn.setStyleSheet(
                "QPushButton { background: rgba(255,91,121,0.18); border: 1px solid #ff5b7988;"
                " border-radius: 13px; padding: 0 9px; color: #ff5b79;"
                " font-family: Consolas, monospace; font-size: 9.5px; }"
            )
        else:
            self._mute_btn.setText("MIC ON")
            self._mute_btn.setStyleSheet(pill_btn)

        self._full_btn.setStyleSheet(pill_btn)
        self._collapse_btn.setStyleSheet(pill_btn)

        self._input.setStyleSheet(
            f"""
            QLineEdit {{
                background: rgba(255, 255, 255, 0.055);
                border: 1px solid {pri_hex}44;
                border-radius: 18px;
                padding: 0 13px;
                color: #f4f6fa;
                font-size: 12px;
                selection-background-color: {pri_hex}66;
            }}
            QLineEdit:focus {{
                border: 1px solid {pri_hex};
                background: rgba(255, 255, 255, 0.08);
            }}
            """
        )
        self._mode.setStyleSheet(
            f"QComboBox {{ background: rgba(255,255,255,0.055); border: 1px solid {pri_hex}44; "
            "border-radius: 16px; padding: 0 8px; color: #f4f6fa; }}"
        )
        self._send_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: {pri_hex}2a;
                border: 1px solid {pri_hex}88;
                border-radius: 18px;
                color: {pri_hex};
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {pri_hex}48;
                color: #ffffff;
            }}
            """
        )

    def _rebuild_feed(self) -> None:
        while self._feed_layout.count() > 1:
            item = self._feed_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        _c1, _c2, pri_hex, sec_hex, _bg = self._palette()

        if not self._messages:
            hint = QLabel(
                f"{self._assistant_name} is running in the background — speak anytime or type below.",
                self._feed_host,
            )
            hint.setWordWrap(True)
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint.setStyleSheet(
                "color: rgba(220,232,245,0.48); font-size: 11px; padding: 26px 12px; background: transparent;"
            )
            self._feed_layout.insertWidget(0, hint)
            return

        shown = list(self._messages)[-8:]
        for idx, (role, line) in enumerate(shown):
            bub = QLabel(line, self._feed_host)
            bub.setWordWrap(True)
            bub.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            accent = pri_hex if role == "user" else sec_hex if role == "jarvis" else "#7f9bb3"
            bg = (
                f"{pri_hex}18"
                if role == "user"
                else f"{sec_hex}16"
                if role == "jarvis"
                else "rgba(255,255,255,0.04)"
            )
            bub.setStyleSheet(
                f"background: {bg}; border-left: 2px solid {accent};"
                " border-radius: 9px; padding: 6px 9px; color: rgba(242,244,248,0.92);"
                " font-size: 11.5px;"
            )
            self._feed_layout.insertWidget(idx, bub)

        QTimer.singleShot(
            15,
            lambda: self._scroll.verticalScrollBar().setValue(
                self._scroll.verticalScrollBar().maximum()
            ),
        )

    # ── Geometry & Show / Expand / Collapse ───────────────────────────────────

    def _available_screen_rect(self) -> QRect:
        scr = self.screen() or QApplication.primaryScreen()
        if scr is not None:
            return scr.availableGeometry()
        return QRect(0, 0, 1920, 1040)

    def _target_geometry(self, expanded: bool) -> QRect:
        avail = self._available_screen_rect()
        w = EXPANDED_W if expanded else COLLAPSED_SIZE
        h = EXPANDED_H if expanded else COLLAPSED_SIZE
        x = max(
            avail.left() + 8,
            min(avail.right() - w - 8, avail.right() - w - self._anchor_right_offset),
        )
        y = max(
            avail.top() + 8,
            min(avail.bottom() - h - 8, avail.bottom() - h - self._anchor_bottom_offset),
        )
        return QRect(x, y, w, h)

    def show_collapsed_in_corner(self) -> None:
        """Show the compact 64x64 orb button in the bottom-right corner without stealing focus."""
        self._anim.stop()
        self._expanded = False
        self._panel.hide()
        self.setGeometry(self._target_geometry(False))
        self.setToolTip(
            f"{self._assistant_name} running in background (voice active) — Click to expand & type"
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.show()
        self.raise_()
        if not self._tick.isActive():
            self._tick.start()

    def expand(self) -> None:
        if self._expanded:
            self.activateWindow()
            self._input.setFocus(Qt.FocusReason.MouseFocusReason)
            return
        self._anim.stop()
        self._expanded = True
        self.setToolTip("")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        start_rect = self.geometry()
        end_rect = self._target_geometry(True)
        self._panel.show()
        self._apply_styles()
        self._rebuild_feed()
        self._anim.setStartValue(start_rect)
        self._anim.setEndValue(end_rect)
        self._anim.start()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(
            60, lambda: self._input.setFocus(Qt.FocusReason.MouseFocusReason)
        )

    def collapse(self) -> None:
        if not self._expanded:
            return
        self._anim.stop()
        self._expanded = False
        self._panel.hide()
        start_rect = self.geometry()
        end_rect = self._target_geometry(False)
        self.setToolTip(
            f"{self._assistant_name} running in background (voice active) — Click to expand & type"
        )
        self._anim.setStartValue(start_rect)
        self._anim.setEndValue(end_rect)
        self._anim.start()

    def hide_dock(self) -> None:
        self._anim.stop()
        self._tick.stop()
        self._expanded = False
        self._panel.hide()
        self.hide()

    def _on_anim_finished(self) -> None:
        if self._expanded:
            self._panel.show()
            self.activateWindow()
            self._input.setFocus(Qt.FocusReason.MouseFocusReason)
        else:
            self._panel.hide()

    # ── Live State Updates (called on Qt GUI thread) ──────────────────────────

    def sync_metadata(
        self,
        *,
        persona: str,
        assistant_name: str,
        muted: bool,
        state: str | None = None,
    ) -> None:
        changed = (
            persona != self._persona
            or assistant_name != self._assistant_name
            or muted != self._muted
            or (state is not None and state != self._raw_state)
        )
        self._persona = "female" if str(persona).lower() == "female" else "male"
        self._assistant_name = (assistant_name or "JARVIS").strip() or "JARVIS"
        self._muted = bool(muted)
        if state is not None:
            self._raw_state = str(state)
        self._title_lbl.setText(self._assistant_name.upper())
        if changed:
            self._apply_styles()
            if self._expanded:
                self._rebuild_feed()
            self.update()

    def set_state(self, state: str) -> None:
        self._raw_state = str(state or "LISTENING")
        self._apply_styles()
        self.update()

    def set_audio_level(self, level: float) -> None:
        try:
            v = max(0.0, min(1.0, float(level)))
        except Exception:
            v = 0.0
        self._audio_level = self._audio_level * 0.45 + v * 0.55

    def append_log(self, raw_line: str) -> None:
        txt = (raw_line or "").strip()
        if not txt:
            return
        low = txt.lower()
        if low.startswith(("you:", "user:")):
            role = "user"
        elif low.startswith(("sys:", "net:", "err:", "tool:", "action:")):
            role = "sys"
        else:
            role = "jarvis"
        self._messages.append((role, txt))
        if self._expanded:
            self._rebuild_feed()

    # ── User Actions ──────────────────────────────────────────────────────────

    def _handle_send(self) -> None:
        msg = self._input.text().strip()
        if not msg:
            return
        self._input.clear()
        mode = str(self._mode.currentData() or "general")
        if mode == "crop" and callable(self._on_crop_question):
            self._on_crop_question(msg)
            self.collapse()
        elif callable(self._on_send_text):
            if mode == "general":
                msg = "Answer without inspecting the screen or camera: " + msg
            elif mode == "screen":
                msg = "Use screen_process on the current screen to answer: " + msg
            elif mode == "agent":
                msg = "Perform this as a computer task, preserving confirmation rules: " + msg
            self._on_send_text(msg)
        self._input.setFocus(Qt.FocusReason.OtherFocusReason)

    def _handle_mute_click(self) -> None:
        if callable(self._on_toggle_mute):
            self._on_toggle_mute()

    def _handle_restore_click(self) -> None:
        if callable(self._on_restore_full):
            self._on_restore_full()

    def _handle_orb_click(self) -> None:
        if callable(self._on_interrupt):
            self._on_interrupt()

    def _on_tick(self) -> None:
        self._phase = (self._phase + 0.09) % (math.pi * 200.0)
        self._audio_level *= 0.88
        c1, c2, *_ = self._palette()
        if self._expanded:
            self._mini_orb.update_visual(
                c1, c2, self._raw_state, self._muted, self._audio_level, self._phase
            )
        else:
            self.update()

    # ── Events & Custom Painting ──────────────────────────────────────────────

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self._expanded:
            self.collapse()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_press_global = event.globalPosition().toPoint()
            self._drag_start_offsets = (
                self._anchor_right_offset,
                self._anchor_bottom_offset,
            )
            self._dragged = False
            if not self._expanded:
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_press_global is not None and (
            event.buttons() & Qt.MouseButton.LeftButton
        ):
            cur = event.globalPosition().toPoint()
            delta = cur - self._drag_press_global
            if abs(delta.x()) + abs(delta.y()) >= 7:
                self._dragged = True
                avail = self._available_screen_rect()
                r0, b0 = self._drag_start_offsets
                self._anchor_right_offset = max(
                    8, min(avail.width() - self.width() - 8, r0 - delta.x())
                )
                self._anchor_bottom_offset = max(
                    8, min(avail.height() - self.height() - 8, b0 - delta.y())
                )
                self.setGeometry(self._target_geometry(self._expanded))
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            was_dragged = self._dragged
            self._drag_press_global = None
            self._dragged = False
            if not self._expanded and not was_dragged:
                self.expand()
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        if self._expanded:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w, h = float(self.width()), float(self.height())
        cx, cy = w * 0.5, h * 0.5
        c_pri, c_sec, _pri_hex, _sec_hex, _bg = self._palette()

        st = (self._raw_state or "LISTENING").upper()
        if self._muted or st == "MUTED":
            active_col = QColor("#ff5b79")
        elif st == "SPEAKING":
            active_col = QColor(c_sec)
        elif st in ("THINKING", "PROCESSING"):
            active_col = QColor(c_sec)
        else:
            active_col = QColor(c_pri)

        lvl = min(1.0, self._audio_level * 1.4)
        breath = 0.5 + 0.5 * math.sin(self._phase * 1.6)
        hover_boost = 1.08 if self._hovered else 1.0

        # 1. Soft outer ambient halo
        halo_r = (28.0 + lvl * 3.5 + breath * 1.5) * hover_boost
        halo = QRadialGradient(QPointF(cx, cy), halo_r)
        h_inner = QColor(active_col)
        h_inner.setAlpha(95 if self._hovered else 68)
        h_outer = QColor(active_col)
        h_outer.setAlpha(0)
        halo.setColorAt(0.0, h_inner)
        halo.setColorAt(1.0, h_outer)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(halo))
        p.drawEllipse(QPointF(cx, cy), halo_r, halo_r)

        # 2. Dark obsidian / velvet-plum glass base disc
        disc_r = 23.5 * hover_boost
        disc_grad = QLinearGradient(cx - disc_r, cy - disc_r, cx + disc_r, cy + disc_r)
        if self._persona == "female":
            disc_grad.setColorAt(0.0, QColor(24, 9, 30, 240))
            disc_grad.setColorAt(1.0, QColor(10, 4, 14, 245))
        else:
            disc_grad.setColorAt(0.0, QColor(7, 17, 30, 240))
            disc_grad.setColorAt(1.0, QColor(2, 7, 14, 245))

        border_col = QColor(active_col)
        border_col.setAlpha(210 if self._hovered else 155)
        p.setPen(QPen(border_col, 1.5))
        p.setBrush(QBrush(disc_grad))
        p.drawEllipse(QPointF(cx, cy), disc_r, disc_r)

        # 3. Rotating sci-fi orbital arc
        arc_rect = QRectF(cx - 18.5, cy - 18.5, 37.0, 37.0)
        arc_col = QColor(active_col)
        arc_col.setAlpha(190)
        arc_pen = QPen(arc_col, 1.6)
        arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(arc_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        deg = int((self._phase * 42.0) % 360.0) * 16
        p.drawArc(arc_rect, deg, 110 * 16)
        p.drawArc(arc_rect, (deg + 180 * 16) % (360 * 16), 75 * 16)

        # 4. Luminous audio-reactive inner plasma core
        core_r = 9.0 + lvl * 5.2 + breath * 1.3
        core_grad = QRadialGradient(QPointF(cx, cy), core_r * 1.35)
        core_grad.setColorAt(0.0, QColor(255, 255, 255, 245))
        c_mid = QColor(active_col)
        c_mid.setAlpha(220)
        c_fade = QColor(active_col)
        c_fade.setAlpha(0)
        core_grad.setColorAt(0.45, c_mid)
        core_grad.setColorAt(1.0, c_fade)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(core_grad))
        p.drawEllipse(QPointF(cx, cy), core_r * 1.35, core_r * 1.35)

        # 5. Subtle expand chevron glyph on hover
        if self._hovered:
            chev_pen = QPen(QColor(255, 255, 255, 210), 1.6)
            chev_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(chev_pen)
            path = QPainterPath()
            path.moveTo(cx - 4.0, cy + 1.5)
            path.lineTo(cx, cy - 2.5)
            path.lineTo(cx + 4.0, cy + 1.5)
            p.drawPath(path)

        p.end()
