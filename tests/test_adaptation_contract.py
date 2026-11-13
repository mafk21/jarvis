from dataclasses import fields

import pytest

from core.adaptation import (
    AdaptationContext,
    AdaptationKind,
    AdaptationRecord,
    AdaptationScope,
    AdaptationValidationError,
    OutcomeResult,
    RiskLevel,
    SkillOutcome,
    StrategyStatus,
)

NOW = "2026-10-21T12:00:00+00:00"


def record(**changes):
    values = dict(
        id="adapt-1",
        skill="daily-briefing",
        kind=AdaptationKind.EXPLICIT_CORRECTION,
        scope=AdaptationScope.MODE,
        context=AdaptationContext(mode="work", project="JARVIS"),
        statement="The briefing was too long.",
        strategy="Keep work briefings below 45 seconds.",
        evidence_refs=("turn-42",),
        confidence=1.0,
        risk=RiskLevel.LOW,
        status=StrategyStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )
    values.update(changes)
    return AdaptationRecord(**values)


def test_record_round_trip_is_strict_and_contextual():
    original = record(previous_record_id="adapt-0", validated_at=NOW)
    restored = AdaptationRecord.from_dict(original.to_dict())
    assert restored == original
    assert restored.context.mode == "work"
    with pytest.raises(AdaptationValidationError, match="unknown fields"):
        AdaptationRecord.from_dict({**original.to_dict(), "permission": "send_without_confirmation"})


def test_contract_has_no_authorization_or_permission_field():
    names = {item.name for item in fields(AdaptationRecord)}
    assert "permission" not in names
    assert "authorization" not in names
    assert "approved" not in names


def test_inference_requires_evidence_and_cannot_enable_high_risk_behavior():
    with pytest.raises(AdaptationValidationError, match="require evidence"):
        record(kind=AdaptationKind.OBSERVED_PATTERN, evidence_refs=())
    with pytest.raises(AdaptationValidationError, match="high-risk"):
        record(kind=AdaptationKind.LEARNED_STRATEGY, risk=RiskLevel.HIGH)
    explicit = record(kind=AdaptationKind.EXPLICIT_PREFERENCE, risk=RiskLevel.HIGH)
    assert explicit.risk is RiskLevel.HIGH  # still data, never authorization


def test_record_rejects_invalid_confidence_identity_and_time():
    with pytest.raises(AdaptationValidationError):
        record(confidence=float("nan"))
    with pytest.raises(AdaptationValidationError):
        record(skill="Daily Briefing")
    with pytest.raises(AdaptationValidationError):
        record(created_at="2026-10-21T12:00:00")


def test_outcome_round_trip_captures_verification_feedback_and_reversal():
    original = SkillOutcome(
        id="outcome-1",
        skill="safe-file-organizer",
        task_type="organize-downloads",
        context=AdaptationContext(mode="personal", device="desktop"),
        strategy_record_id="adapt-7",
        result=OutcomeResult.SUCCEEDED,
        verification="All intended files moved; no unintended files moved.",
        started_at=NOW,
        completed_at="2026-10-21T12:00:01+00:00",
        latency_ms=812,
        user_feedback="Keep archives separate next time.",
        correction="Use an Archives folder.",
        reversed=True,
    )
    assert SkillOutcome.from_dict(original.to_dict()) == original


def test_outcome_rejects_unverified_or_unbounded_results():
    with pytest.raises(AdaptationValidationError):
        SkillOutcome(
            id="outcome-1", skill="deep-research", task_type="report",
            context=AdaptationContext(), strategy_record_id=None,
            result=OutcomeResult.UNCERTAIN, verification="", started_at=NOW,
            completed_at=NOW, latency_ms=1,
        )
    with pytest.raises(AdaptationValidationError):
        SkillOutcome(
            id="outcome-1", skill="deep-research", task_type="report",
            context=AdaptationContext(), strategy_record_id=None,
            result=OutcomeResult.FAILED, verification="Provider failed", started_at=NOW,
            completed_at=NOW, latency_ms=-1,
        )
