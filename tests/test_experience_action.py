from actions import experience_settings
from core import experience, session_privacy


class Player:
    def __init__(self):
        self.incognito = []
        self.experience_changes = 0

    def on_incognito_change(self, active):
        self.incognito.append(active)

    def on_experience_change(self):
        self.experience_changes += 1


def teardown_function():
    session_privacy.set_enabled(False)


def test_spoken_incognito_control_starts_fresh_session():
    player = Player()
    result = experience_settings.run(
        {"action": "set_incognito", "enabled": True}, {"player": player}
    )
    assert session_privacy.enabled() is True
    assert player.incognito == [True]
    assert "fresh voice session" in result


def test_spoken_presentation_control_is_validated(monkeypatch):
    saved = []
    monkeypatch.setattr(experience, "load_api_keys", lambda: {})
    monkeypatch.setattr(experience, "_patch_config", lambda **fields: saved.append(fields))
    player = Player()
    result = experience_settings.run(
        {"action": "set_presentation", "personality": "sentinel", "language": "casual"},
        {"player": player},
    )
    assert saved[-1]["experience_personality"] == "sentinel"
    assert player.experience_changes == 1
    assert "sentinel" in result
