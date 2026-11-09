from core import gaming_mode
from core import proactive_permissions as pp


def isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(gaming_mode, "PATH", tmp_path / "gaming.json")
    monkeypatch.setattr(gaming_mode, "_ACTIVE", False)
    monkeypatch.setattr(gaming_mode, "_ACTIVE_APP", "")


def teardown_function():
    gaming_mode._ACTIVE = False
    gaming_mode._ACTIVE_APP = ""


def test_game_list_is_user_owned_and_detected(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    gaming_mode.save_policy(True, ["MyGame.exe"])
    state = gaming_mode.refresh(["explorer.exe", "MYGAME.EXE"])
    assert state["active"] is True
    assert state["application"] == "MYGAME.EXE"


def test_gaming_mode_pauses_proactive_but_not_direct_requests(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    gaming_mode.save_policy(True, ["game"])
    gaming_mode.refresh(["game.exe"])
    assert pp.allowed(pp.ProactivePolicy(enabled=True)) is False
    # Gaming state is deliberately not consulted by screen authorization or tools;
    # direct wake, Silent Ask, and approved actions remain available.


def test_disabled_gaming_mode_never_activates(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    gaming_mode.save_policy(False, ["game"])
    assert gaming_mode.refresh(["game.exe"])["active"] is False


def test_corrupt_gaming_policy_fails_disabled(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    gaming_mode.PATH.write_text("{broken", encoding="utf-8")
    policy = gaming_mode.get_policy()
    assert policy["enabled"] is False and policy["corrupt"] is True
