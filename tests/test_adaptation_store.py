import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from core import security_vault as vault
from core.adaptation import (
    AdaptationContext,
    AdaptationKind,
    AdaptationRecord,
    AdaptationScope,
    OutcomeResult,
    RiskLevel,
    SkillOutcome,
    StrategyStatus,
)
from memory import adaptation_store as storage

NOW = "2026-10-21T12:00:00+00:00"


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "VAULT_KEY_FILE", tmp_path / "config" / ".vault.key")
    return storage.AdaptationStore(tmp_path / "memory" / "adaptations.json")


def make_record(number=1):
    return AdaptationRecord(
        id=f"adapt-{number}", skill="daily-briefing",
        kind=AdaptationKind.EXPLICIT_CORRECTION, scope=AdaptationScope.MODE,
        context=AdaptationContext(mode="work"), statement=f"Correction {number}",
        strategy=f"Strategy {number}", evidence_refs=(f"turn-{number}",), confidence=1,
        risk=RiskLevel.LOW, status=StrategyStatus.ACTIVE,
        created_at=NOW, updated_at=NOW,
    )


def make_outcome(number=1):
    return SkillOutcome(
        id=f"outcome-{number}", skill="daily-briefing", task_type="morning",
        context=AdaptationContext(mode="work"), strategy_record_id="adapt-1",
        result=OutcomeResult.SUCCEEDED, verification="Delivered and acknowledged",
        started_at=NOW, completed_at=NOW, latency_ms=number,
    )


def test_encrypted_round_trip_and_owner_only_file(store):
    snapshot = store.put_record(make_record())
    raw = store.path.read_text(encoding="utf-8")
    assert "Correction 1" not in raw
    assert "Strategy 1" not in raw
    assert "enc:v1:" in raw
    assert store.load() == snapshot
    assert store.path.stat().st_mode & 0o077 == 0


def test_revision_check_prevents_lost_updates(store):
    first = store.put_record(make_record(), expected_revision=0)
    assert first.revision == 1
    with pytest.raises(storage.RevisionConflict):
        store.put_record(make_record(2), expected_revision=0)
    assert [item.id for item in store.load().records] == ["adapt-1"]


def test_outcomes_are_append_only_and_duplicate_ids_fail(store):
    store.put_record(make_record())
    result = store.append_outcome(make_outcome())
    assert result.outcomes[0].strategy_record_id == "adapt-1"
    with pytest.raises(storage.AdaptationStoreError, match="already exists"):
        store.append_outcome(make_outcome())


def test_corrupt_primary_recovers_previous_valid_snapshot(store):
    first = store.put_record(make_record())
    store.put_record(make_record(2))  # creates backup of first
    store.path.write_text("tampered", encoding="utf-8")
    recovered = store.load()
    assert recovered.revision == 2
    assert {item.id for item in recovered.records} == {"adapt-1", "adapt-2"}
    assert store.load() == recovered


def test_both_corrupt_fail_closed_without_silently_erasing_evidence(store):
    store.put_record(make_record())
    store.put_record(make_record(2))
    store.path.write_text("bad primary", encoding="utf-8")
    store.backup_path.write_text("bad backup", encoding="utf-8")
    with pytest.raises(storage.AdaptationStoreError, match="unreadable"):
        store.load()
    assert store.path.read_text(encoding="utf-8") == "bad primary"


def test_remove_clear_and_complete_file_deletion(store):
    store.put_record(make_record())
    store.append_outcome(make_outcome())
    removed = store.remove_record("adapt-1")
    assert removed.records == ()
    assert len(removed.outcomes) == 1
    cleared = store.clear()
    assert cleared.records == cleared.outcomes == ()
    store.delete_files()
    assert not store.path.exists()
    assert not store.backup_path.exists()
    assert store.load().revision == 0


def test_store_rejects_unknown_plaintext_fields(store):
    # Exercise strict parsing independently of encryption; migrations must be explicit.
    raw = {"schema_version": 1, "revision": 0, "records": [], "outcomes": [], "permission": True}
    with pytest.raises(Exception, match="unknown fields"):
        storage._parse(raw)


def test_concurrent_writes_do_not_drop_records(store):
    def add(number):
        store.put_record(make_record(number))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(add, range(1, 33)))
    snapshot = store.load()
    assert snapshot.revision == 32
    assert {item.id for item in snapshot.records} == {f"adapt-{number}" for number in range(1, 33)}


def test_capacity_failure_preserves_existing_store(store, monkeypatch):
    monkeypatch.setattr(storage, "MAX_RECORDS", 1)
    before = store.put_record(make_record())
    with pytest.raises(storage.AdaptationStoreError, match="limit"):
        store.put_record(make_record(2))
    assert store.load() == before


def test_ciphertext_wrapper_has_no_extra_metadata(store):
    store.put_record(make_record())
    wrapper = json.loads(store.path.read_text(encoding="utf-8"))
    assert set(wrapper) == {"version", "encrypted_store"}
