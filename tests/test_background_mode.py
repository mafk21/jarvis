from __future__ import annotations

import os
from pathlib import Path
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fastapi.testclient import TestClient
import pytest

from core.apex_bridge import ApexHudBridge

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_native_background_dock_bottom_right_expand_type_and_collapse():
    QtWidgets = pytest.importorskip("PyQt6.QtWidgets", exc_type=ImportError)
    from core.background_dock import (
        COLLAPSED_SIZE,
        CORNER_MARGIN,
        EXPANDED_H,
        EXPANDED_W,
        BackgroundDockWidget,
    )

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv[:1])

    sent_messages: list[str] = []
    mute_toggles: list[int] = []
    restored: list[int] = []
    interrupted: list[int] = []

    dock = BackgroundDockWidget(
        on_send_text=lambda msg: sent_messages.append(msg),
        on_toggle_mute=lambda: mute_toggles.append(1),
        on_restore_full=lambda: restored.append(1),
        on_interrupt=lambda: interrupted.append(1),
    )
    try:
        dock.show_collapsed_in_corner()
        avail = dock._available_screen_rect()
        geom = dock.geometry()

        # 1. Collapsed button is 64x64 pinned to bottom-right of available screen
        assert not dock._expanded
        assert geom.width() == COLLAPSED_SIZE
        assert geom.height() == COLLAPSED_SIZE
        assert abs((avail.right() - geom.width() - CORNER_MARGIN) - geom.x()) <= 12
        assert abs((avail.bottom() - geom.height() - CORNER_MARGIN) - geom.y()) <= 12

        # 2. Clicking/expanding opens the sleek typing drawer anchored bottom-right
        dock.expand()
        target_exp = dock._target_geometry(True)
        assert dock._expanded
        assert target_exp.width() == EXPANDED_W
        assert target_exp.height() == EXPANDED_H
        assert dock._panel.isVisible()

        # 3. Typing and submitting sends command while mic/voice stays unmuted
        assert dock._muted is False
        dock._input.setText("what is on my schedule today?")
        dock._handle_send()
        assert sent_messages == ["what is on my schedule today?"]
        assert dock._input.text() == ""

        # 4. Live speaking / audio level / Female theme updates work seamlessly
        dock.append_log("You: what is on my schedule today?")
        dock.append_log("JARVIS: You have a design review at 3 PM.")
        dock.set_state("SPEAKING")
        dock.set_audio_level(0.82)
        dock.sync_metadata(
            persona="female",
            assistant_name="FRIDAY",
            muted=False,
            state="SPEAKING",
        )
        assert dock._persona == "female"
        assert dock._assistant_name == "FRIDAY"
        assert "SPEAKING" in dock._status_lbl.text()

        # 5. Controls: interrupt, mute toggle, collapse, and restore full HUD
        dock._handle_orb_click()
        assert len(interrupted) == 1
        dock._handle_mute_click()
        assert len(mute_toggles) == 1

        dock.collapse()
        assert not dock._expanded

        dock._handle_restore_click()
        assert len(restored) == 1

        # 6. Optional PixelNotch-style surface is centred at the top, remains
        # always on top, and restores the full HUD instead of opening the drawer.
        dock.set_surface_mode("notch")
        dock.show_collapsed_in_corner()
        notch_geom = dock.geometry()
        assert notch_geom.width() == 224
        assert notch_geom.height() == 42
        assert abs(notch_geom.center().x() - dock._available_screen_rect().center().x()) <= 2
        assert notch_geom.top() == dock._available_screen_rect().top()
        assert not dock._expanded
        before = len(restored)
        dock._handle_restore_click()
        assert len(restored) == before + 1
    finally:
        dock.hide_dock()
        dock.close()


def test_desktop_ui_and_dock_wiring_preserve_live_voice():
    ui_src = (REPO_ROOT / "ui.py").read_text(encoding="utf-8")
    dock_src = (REPO_ROOT / "core" / "background_dock.py").read_text(encoding="utf-8")

    assert "def enter_background_mode(self)" in ui_src
    assert "def exit_background_mode(self)" in ui_src
    assert "def send_text_from_dock(self, text: str)" in ui_src
    assert "BackgroundDockWidget" in ui_src
    assert "WindowStaysOnTopHint" in dock_src
    assert "FramelessWindowHint" in dock_src
    assert "show_collapsed_in_corner" in dock_src
    assert "set_surface_mode" in dock_src
    assert "get_background_surface" in ui_src


def test_background_surface_preference_is_validated(monkeypatch):
    from memory import config_manager

    monkeypatch.setattr(config_manager, "load_api_keys", lambda: {"background_surface": "notch"})
    assert config_manager.get_background_surface() == "notch"
    monkeypatch.setattr(config_manager, "load_api_keys", lambda: {"background_surface": "unexpected"})
    assert config_manager.get_background_surface() == "corner"

    saved = {}
    monkeypatch.setattr(config_manager, "_patch_config", lambda **values: saved.update(values))
    assert config_manager.save_background_surface("pixelnotch") == "notch"
    assert saved == {"background_surface": "notch"}
    with pytest.raises(ValueError):
        config_manager.save_background_surface("floating-chaos")


def test_bridge_background_mode_keeps_voice_alive_on_window_close(monkeypatch):
    quit_calls: list[int] = []
    from memory import config_manager

    selected_surface = {"value": "corner"}
    monkeypatch.setattr(
        config_manager,
        "save_background_surface",
        lambda value: selected_surface.update(value=value) or value,
    )
    entered: list[int] = []
    exited: list[int] = []
    spoken_texts: list[str] = []

    class DummyUI:
        muted = False

        def enter_background_mode(self):
            entered.append(1)

        def exit_background_mode(self):
            exited.append(1)

        def on_text_command(self, txt: str):
            spoken_texts.append(txt)

    ui = DummyUI()
    bridge = ApexHudBridge(
        ui,
        on_all_windows_closed=lambda: quit_calls.append(1),
        auto_close_on_disconnect=True,
    )
    app = bridge._build_app()

    with TestClient(app) as client:
        # User can explicitly select the persistent background surface.
        r_surface = client.post(
            "/api/hud/action",
            json={"action": "set_background_surface", "surface": "notch"},
        )
        assert r_surface.status_code == 200
        assert r_surface.json()["background_surface"] == "notch"
        assert selected_surface["value"] == "notch"

        # Enter background mode
        r = client.post("/api/hud/action", json={"action": "enter_background_mode"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["background_mode"] is True
        assert bridge._background_mode is True
        assert len(entered) == 1

        # Simulate main HUD window closing while background mode is active:
        # auto-close MUST NOT terminate JARVIS!
        bridge._had_ws_client = True
        bridge._schedule_auto_close()
        assert quit_calls == []

        # JARVIS still hears & responds to typed/spoken turns while backgrounded
        r_txt = client.post(
            "/api/hud/action",
            json={"action": "text_command", "text": "keep working in background"},
        )
        assert r_txt.status_code == 200
        deadline = time.time() + 1.0
        while not spoken_texts and time.time() < deadline:
            time.sleep(0.02)
        assert spoken_texts == ["keep working in background"]
        assert ui.muted is False

        snap = client.get("/api/hud/bootstrap").json()
        assert snap["background_mode"] is True
        assert snap["muted"] is False

        # Exit background mode restores full HUD
        r_exit = client.post("/api/hud/action", json={"action": "exit_background_mode"})
        assert r_exit.status_code == 200
        assert r_exit.json()["background_mode"] is False
        assert bridge._background_mode is False
        assert len(exited) == 1


def test_web_hud_has_background_button_and_bottom_right_expandable_dock():
    overlays = (
        REPO_ROOT / "apex_ui" / "components" / "JarvisHudOverlays.tsx"
    ).read_text(encoding="utf-8")
    dock = (
        REPO_ROOT / "apex_ui" / "components" / "BackgroundCornerDock.tsx"
    ).read_text(encoding="utf-8")

    assert 'data-testid="enter-bg-mode-btn"' in overlays
    assert "enterBackgroundMode" in overlays
    assert "<BackgroundCornerDock />" in overlays

    assert 'data-testid="bg-corner-dock-collapsed"' in dock
    assert 'data-testid="bg-corner-dock-expanded"' in dock
    assert "right: 20" in dock
    assert "bottom: 20" in dock
    assert "sendText(trimmed)" in dock
    assert "exitBackgroundMode()" in dock
