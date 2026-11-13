from pathlib import Path

import pytest

from actions import adaptation_inspect as inspect_action
from actions import adaptation_manage as manage_action
from core import security_vault as vault
from core.action_loader import discover_actions
from core.adaptation import AdaptationContext, AdaptationKind, AdaptationRecord, AdaptationScope, RiskLevel, StrategyStatus
from memory import adaptation_store as storage

NOW = "2026-10-21T12:00:00+00:00"


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "ADAPTATION_PATH", tmp_path / "adaptations.json")
    monkeypatch.setattr(vault, "VAULT_KEY_FILE", tmp_path / ".vault.key")
    return storage.AdaptationStore()


def candidate():
    return AdaptationRecord(id="a-1", skill="daily-briefing", kind=AdaptationKind.EXPLICIT_PREFERENCE,
        scope=AdaptationScope.SKILL, context=AdaptationContext(), statement="short", strategy="Keep it short",
        evidence_refs=("turn-1",), confidence=1, risk=RiskLevel.LOW, status=StrategyStatus.CANDIDATE,
        created_at=NOW, updated_at=NOW, target="length")


def test_actions_discover_with_mutation_confirmation_policy():
    registry = discover_actions(Path("actions"), logger=lambda _line: None)
    assert registry.has("adaptation_inspect")
    assert registry.has("adaptation_manage")
    record = registry._actions["adaptation_manage"]
    assert record.safety["confirmation"] == "required"


def test_inspect_and_revision_checked_manage(isolated):
    saved = isolated.put_record(candidate())
    listing = inspect_action.adaptation_inspect({"action": "list", "skill": "daily-briefing"})
    assert "a-1" in listing and f"revision {saved.revision}" in listing
    stale = manage_action.adaptation_manage({"action": "activate", "record_id": "a-1", "expected_revision": 0})
    assert "No adaptation change" in stale
    result = manage_action.adaptation_manage({"action": "activate", "record_id": "a-1", "expected_revision": saved.revision})
    assert "completed" in result
    assert isolated.load().records[0].status is StrategyStatus.ACTIVE


def test_read_only_plan_states_that_it_executes_nothing(isolated):
    isolated.put_record(candidate())
    text = inspect_action.adaptation_inspect({"action": "plan", "skill": "daily-briefing"})
    assert "does not grant permission or execute anything" in text
