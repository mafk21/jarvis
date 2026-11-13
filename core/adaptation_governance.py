"""Explicit governance for adaptation lifecycle changes.

No operation here is automatic. Callers must name an exact record and use the
current store revision, making every activation, disable, rollback, and deletion
an auditable owner-directed mutation.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from core.adaptation import AdaptationKind, AdaptationRecord, RiskLevel, StrategyStatus
from memory.adaptation_store import AdaptationSnapshot, AdaptationStore


class GovernanceError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _index(snapshot: AdaptationSnapshot, record_id: str) -> int:
    for index, item in enumerate(snapshot.records):
        if item.id == record_id:
            return index
    raise GovernanceError(f"adaptation record not found: {record_id}")


def activate(store: AdaptationStore, record_id: str, *, expected_revision: int) -> AdaptationSnapshot:
    snapshot = store.load()
    if snapshot.revision != expected_revision:
        from memory.adaptation_store import RevisionConflict
        raise RevisionConflict(f"expected adaptation revision {expected_revision}, found {snapshot.revision}")
    index = _index(snapshot, record_id)
    item = snapshot.records[index]
    if item.status is not StrategyStatus.CANDIDATE:
        raise GovernanceError("only candidate adaptations can be activated")
    if item.risk is RiskLevel.HIGH or item.permission_related:
        raise GovernanceError("high-risk or permission-related adaptations cannot be activated as strategy")
    if item.kind is AdaptationKind.OBSERVED_PATTERN:
        raise GovernanceError("observed patterns are evidence and cannot be activated")
    rows = list(snapshot.records)
    previous = next((row for row in rows if row.status is StrategyStatus.ACTIVE
                     and row.skill == item.skill and row.target == item.target
                     and row.context == item.context), None)
    stamp = _now()
    if previous is not None:
        previous_index = rows.index(previous)
        rows[previous_index] = replace(previous, status=StrategyStatus.DISABLED, updated_at=stamp)
    rows[index] = replace(item, status=StrategyStatus.ACTIVE, validated_at=stamp, updated_at=stamp,
                          previous_record_id=previous.id if previous else item.previous_record_id)
    return store.replace_records(tuple(rows), expected_revision=expected_revision)


def disable(store: AdaptationStore, record_id: str, *, expected_revision: int) -> AdaptationSnapshot:
    snapshot = store.load()
    index = _index(snapshot, record_id)
    item = snapshot.records[index]
    if item.status not in {StrategyStatus.ACTIVE, StrategyStatus.CANDIDATE}:
        raise GovernanceError("adaptation is already inactive")
    rows = list(snapshot.records)
    rows[index] = replace(item, status=StrategyStatus.DISABLED, updated_at=_now())
    return store.replace_records(tuple(rows), expected_revision=expected_revision)


def rollback(store: AdaptationStore, record_id: str, *, expected_revision: int) -> AdaptationSnapshot:
    snapshot = store.load()
    index = _index(snapshot, record_id)
    current = snapshot.records[index]
    if current.status is not StrategyStatus.ACTIVE or not current.previous_record_id:
        raise GovernanceError("active adaptation has no rollback ancestor")
    previous_index = _index(snapshot, current.previous_record_id)
    previous = snapshot.records[previous_index]
    if previous.skill != current.skill or previous.target != current.target:
        raise GovernanceError("rollback ancestor does not match skill and target")
    stamp = _now()
    rows = list(snapshot.records)
    rows[index] = replace(current, status=StrategyStatus.ROLLED_BACK, updated_at=stamp)
    rows[previous_index] = replace(previous, status=StrategyStatus.ACTIVE, validated_at=stamp, updated_at=stamp)
    return store.replace_records(tuple(rows), expected_revision=expected_revision)


def remove(store: AdaptationStore, record_id: str, *, expected_revision: int) -> AdaptationSnapshot:
    snapshot = store.load()
    _index(snapshot, record_id)
    descendants = [item.id for item in snapshot.records if item.previous_record_id == record_id]
    if descendants:
        raise GovernanceError("cannot remove a record that is referenced by rollback history")
    return store.remove_record(record_id, expected_revision=expected_revision)


def inspect(store: AdaptationStore, *, skill: str | None = None) -> dict:
    snapshot = store.load()
    records = [item for item in snapshot.records if not skill or item.skill == skill]
    return {
        "revision": snapshot.revision,
        "records": [item.to_dict() for item in records],
        "outcome_count": len(snapshot.outcomes),
    }
