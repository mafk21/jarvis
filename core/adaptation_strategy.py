"""Read-only, conservative selection of user-specific skill strategies.

The engine never executes a strategy, writes memory, or changes permissions.  It
only proposes a bounded plan from already-active records and explains every
exclusion. Ambiguous ties fail closed for that target instead of guessing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from core.adaptation import (
    AdaptationContext,
    AdaptationKind,
    AdaptationRecord,
    AdaptationScope,
    RiskLevel,
    StrategyStatus,
)

_INFERRED_MAX_AGE_DAYS = 90
_EXPLICIT_MAX_AGE_DAYS = 730
_MIN_INFERRED_CONFIDENCE = 0.70
_MIN_EXPLICIT_CONFIDENCE = 0.50
_KIND_RANK = {
    AdaptationKind.EXPLICIT_CORRECTION: 4,
    AdaptationKind.EXPLICIT_PREFERENCE: 3,
    AdaptationKind.LEARNED_STRATEGY: 2,
    AdaptationKind.OBSERVED_PATTERN: 1,
}
_SCOPE_RANK = {
    AdaptationScope.PROJECT: 4,
    AdaptationScope.MODE: 3,
    AdaptationScope.SKILL: 2,
    AdaptationScope.GLOBAL: 1,
    AdaptationScope.ONE_TIME: 0,
}


@dataclass(frozen=True, slots=True)
class StrategyExclusion:
    record_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class StrategyPlan:
    skill: str
    context: AdaptationContext
    selected: tuple[AdaptationRecord, ...]
    excluded: tuple[StrategyExclusion, ...]
    requires_review: bool

    @property
    def strategies(self) -> tuple[str, ...]:
        return tuple(item.strategy for item in self.selected)


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _context_matches(record: AdaptationRecord, current: AdaptationContext) -> bool:
    saved = record.context
    if record.scope is AdaptationScope.GLOBAL:
        return True
    if saved.device and saved.device.casefold() != current.device.casefold():
        return False
    if record.scope is AdaptationScope.PROJECT:
        return bool(saved.project and current.project and saved.project.casefold() == current.project.casefold())
    if record.scope is AdaptationScope.MODE:
        return saved.mode.casefold() == current.mode.casefold()
    # Skill/global records must not carry hidden narrower qualifiers. A non-default
    # mode or project on such a record is treated as context, not ignored.
    if saved.project and saved.project.casefold() != current.project.casefold():
        return False
    if saved.mode != "default" and saved.mode.casefold() != current.mode.casefold():
        return False
    return True


def propose_strategy(
    records: Iterable[AdaptationRecord],
    *,
    skill: str,
    context: AdaptationContext,
    now: datetime | None = None,
) -> StrategyPlan:
    """Select at most one unambiguous active strategy for each target."""
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        raise ValueError("strategy evaluation time must include a timezone")
    candidates: list[AdaptationRecord] = []
    excluded: list[StrategyExclusion] = []
    all_records = tuple(records)
    for record in all_records:
        reason = ""
        if record.scope is not AdaptationScope.GLOBAL and record.skill != skill:
            reason = "different skill"
        elif record.status is not StrategyStatus.ACTIVE:
            reason = "not active"
        elif any(item.status is StrategyStatus.ACTIVE and item.previous_record_id == record.id
                 and (item.scope is AdaptationScope.GLOBAL or item.skill == skill)
                 and _context_matches(item, context) for item in all_records):
            reason = "superseded by a newer active record"
        elif record.scope is AdaptationScope.ONE_TIME:
            reason = "one-time strategies require an exact execution binding"
        elif record.risk is RiskLevel.HIGH or record.permission_related:
            reason = "high-risk or permission-related strategies require runtime authorization"
        elif record.kind is AdaptationKind.OBSERVED_PATTERN:
            reason = "observations are evidence, not executable strategies"
        elif not _context_matches(record, context):
            reason = "context mismatch"
        else:
            inferred = record.kind is AdaptationKind.LEARNED_STRATEGY
            minimum = _MIN_INFERRED_CONFIDENCE if inferred else _MIN_EXPLICIT_CONFIDENCE
            max_age = _INFERRED_MAX_AGE_DAYS if inferred else _EXPLICIT_MAX_AGE_DAYS
            age_days = (current_time - _time(record.updated_at)).total_seconds() / 86400
            if record.confidence < minimum:
                reason = "confidence below threshold"
            elif age_days < -1:
                reason = "record timestamp is in the future"
            elif age_days > max_age:
                reason = "record is stale"
            elif inferred and record.validated_at is None:
                reason = "learned strategy has not been validated"
        if reason:
            excluded.append(StrategyExclusion(record.id, reason))
        else:
            candidates.append(record)

    selected: list[AdaptationRecord] = []
    review = False
    by_target: dict[str, list[AdaptationRecord]] = {}
    for record in candidates:
        by_target.setdefault(record.target.casefold(), []).append(record)
    for group in by_target.values():
        ranked = sorted(
            group,
            key=lambda item: (
                _KIND_RANK[item.kind],
                _SCOPE_RANK[item.scope],
                item.confidence,
                _time(item.updated_at),
            ),
            reverse=True,
        )
        winner = ranked[0]
        if len(ranked) > 1:
            first_key = (_KIND_RANK[winner.kind], _SCOPE_RANK[winner.scope], winner.confidence, _time(winner.updated_at))
            tied = [item for item in ranked if
                    (_KIND_RANK[item.kind], _SCOPE_RANK[item.scope], item.confidence, _time(item.updated_at)) == first_key]
            if len({item.strategy.casefold() for item in tied}) > 1:
                review = True
                excluded.extend(StrategyExclusion(item.id, "ambiguous equal-priority conflict") for item in ranked)
                continue
            excluded.extend(StrategyExclusion(item.id, f"lower precedence than {winner.id}") for item in ranked[1:])
        selected.append(winner)
    selected.sort(key=lambda item: item.target.casefold())
    return StrategyPlan(
        skill=skill,
        context=context,
        selected=tuple(selected),
        excluded=tuple(excluded),
        requires_review=review,
    )
