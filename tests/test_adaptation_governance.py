from dataclasses import replace

import pytest

from core import security_vault as vault
from core.adaptation import AdaptationContext, AdaptationKind, AdaptationRecord, AdaptationScope, RiskLevel, StrategyStatus
from core.adaptation_governance import GovernanceError, activate, disable, inspect, remove, rollback
from memory.adaptation_store import AdaptationStore, RevisionConflict

NOW = "2026-10-21T12:00:00+00:00"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "VAULT_KEY_FILE", tmp_path / "config" / ".vault.key")
    return AdaptationStore(tmp_path / "adaptations.json")


def record(number, **changes):
    data = dict(id=f"a-{number}", skill="daily-briefing", kind=AdaptationKind.EXPLICIT_CORRECTION,
                scope=AdaptationScope.SKILL, context=AdaptationContext(), statement="shorter",
                strategy=f"strategy {number}", evidence_refs=(f"turn-{number}",), confidence=1,
                risk=RiskLevel.LOW, status=StrategyStatus.CANDIDATE, created_at=NOW,
                updated_at=NOW, target="length")
    data.update(changes)
    return AdaptationRecord(**data)


def test_explicit_activation_and_disable_are_revision_checked(store):
    saved = store.put_record(record(1))
    active = activate(store, "a-1", expected_revision=saved.revision)
    assert active.records[0].status is StrategyStatus.ACTIVE
    with pytest.raises(RevisionConflict):
        disable(store, "a-1", expected_revision=saved.revision)
    disabled = disable(store, "a-1", expected_revision=active.revision)
    assert disabled.records[0].status is StrategyStatus.DISABLED


def test_high_risk_and_observation_cannot_activate(store):
    first = store.put_record(record(1, risk=RiskLevel.HIGH))
    with pytest.raises(GovernanceError, match="high-risk"):
        activate(store, "a-1", expected_revision=first.revision)
    second = store.put_record(record(2, kind=AdaptationKind.OBSERVED_PATTERN))
    with pytest.raises(GovernanceError, match="evidence"):
        activate(store, "a-2", expected_revision=second.revision)


def test_rollback_atomically_restores_matching_ancestor(store):
    old = record(1, status=StrategyStatus.DISABLED)
    new = record(2, status=StrategyStatus.ACTIVE, previous_record_id="a-1")
    one = store.put_record(old)
    two = store.put_record(new, expected_revision=one.revision)
    result = rollback(store, "a-2", expected_revision=two.revision)
    states = {item.id: item.status for item in result.records}
    assert states == {"a-1": StrategyStatus.ACTIVE, "a-2": StrategyStatus.ROLLED_BACK}


def test_rollback_rejects_mismatched_ancestor(store):
    old = record(1, status=StrategyStatus.DISABLED, target="tone")
    new = record(2, status=StrategyStatus.ACTIVE, previous_record_id="a-1")
    store.put_record(old)
    saved = store.put_record(new)
    with pytest.raises(GovernanceError, match="does not match"):
        rollback(store, "a-2", expected_revision=saved.revision)


def test_referenced_history_cannot_be_removed_and_inspection_is_filtered(store):
    store.put_record(record(1, status=StrategyStatus.DISABLED))
    saved = store.put_record(record(2, previous_record_id="a-1"))
    with pytest.raises(GovernanceError, match="rollback history"):
        remove(store, "a-1", expected_revision=saved.revision)
    report = inspect(store, skill="daily-briefing")
    assert report["revision"] == saved.revision
    assert len(report["records"]) == 2
    assert inspect(store, skill="deep-research")["records"] == []
