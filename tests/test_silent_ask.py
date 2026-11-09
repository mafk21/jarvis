from pathlib import Path
from core import ambient_hotkey

ROOT = Path(__file__).resolve().parents[1]


def test_silent_ask_uses_requested_global_chord():
    assert ambient_hotkey.DEFAULT_CHORD == ("alt", "shift", "s")


def test_non_windows_fails_honestly_to_window_scope(monkeypatch):
    monkeypatch.setattr(ambient_hotkey.platform, "system", lambda: "Linux")
    hotkey = ambient_hotkey.SilentAskHotkey(lambda: None)
    assert hotkey.start() == "window"
    hotkey.stop()


def test_compact_dock_has_all_context_modes():
    source = (ROOT / "core" / "background_dock.py").read_text(encoding="utf-8")
    for mode in ("General", "Screen", "Crop", "Agent"):
        assert f'addItem("{mode}"' in source
    assert "on_crop_question" in source


def test_crop_question_carries_exact_region_to_vision():
    source = (ROOT / "ui.py").read_text(encoding="utf-8")
    assert "_pending_region_question" in source
    assert "Use screen_process with angle region" in source


def test_silent_ask_does_not_replace_apex():
    source = (ROOT / "ui.py").read_text(encoding="utf-8")
    assert "def open_silent_ask" in source
    assert "_ensure_bg_dock" in source
