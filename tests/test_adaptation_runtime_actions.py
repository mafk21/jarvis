import pytest

from actions import adaptation_feedback as feedback_action
from actions import adaptation_outcome as outcome_action
from core import adaptation_privacy
from core import security_vault as vault
from core.session_privacy import set_enabled
from memory import adaptation_store as storage, config_manager as cfg


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "ADAPTATION_PATH", tmp_path / "adaptations.json")
    monkeypatch.setattr(vault, "VAULT_KEY_FILE", tmp_path / ".vault.key")
    monkeypatch.setattr(adaptation_privacy, "explicitly_enabled", lambda: True)
    outcome_action._RECORDER = None
    set_enabled(False)
    yield storage.AdaptationStore()
    outcome_action._RECORDER = None
    set_enabled(False)


def test_runtime_outcome_then_explicit_feedback_creates_inactive_candidate(isolated):
    started = outcome_action.adaptation_outcome({
        "action": "start", "skill": "daily-briefing", "task_type": "morning",
        "mode": "work", "project": "JARVIS", "execution_id": "run-1",
    })
    outcome_id = started.split(": ", 1)[1].split(".", 1)[0]
    finished = outcome_action.adaptation_outcome({
        "action": "finish", "outcome_id": outcome_id, "result": "succeeded",
        "verification": "Briefing delivered and user reviewed it.",
    })
    assert "recorded" in finished
    saved = feedback_action.adaptation_feedback({
        "outcome_id": outcome_id,
        "user_text": "In work mode, next time keep the briefing shorter.",
        "target": "length",
    })
    assert "inactive adaptation candidate" in saved
    snapshot = isolated.load()
    assert len(snapshot.outcomes) == 1
    assert len(snapshot.records) == 1
    assert snapshot.records[0].target == "length"
    assert snapshot.records[0].status.value == "candidate"


def test_runtime_recording_respects_incognito_and_adaptive_toggle(isolated, monkeypatch):
    set_enabled(True)
    assert "Incognito" in outcome_action.adaptation_outcome({"action": "start"})
    set_enabled(False)
    monkeypatch.setattr(adaptation_privacy, "explicitly_enabled", lambda: False)
    assert "explicitly enabled" in outcome_action.adaptation_outcome({"action": "start"})
    assert isolated.load().outcomes == ()
