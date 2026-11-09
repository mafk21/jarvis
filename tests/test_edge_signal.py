from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_edge_signal_is_visual_only_and_input_transparent():
    source = (ROOT / "core" / "edge_signal.py").read_text(encoding="utf-8")
    assert "WindowTransparentForInput" in source
    assert "WA_ShowWithoutActivating" in source


def test_edge_signal_distinguishes_ambient_states():
    source = (ROOT / "core" / "edge_signal.py").read_text(encoding="utf-8")
    for state in ("LISTENING", "THINKING", "SPEAKING", "VISION", "ERROR"):
        assert f'"{state}"' in source


def test_ui_forwards_state_without_replacing_hud():
    source = (ROOT / "ui.py").read_text(encoding="utf-8")
    assert "self._edge_signal.show_state" in source
    assert "self._apex_bridge.push_state(state)" in source
