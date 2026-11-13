from datetime import datetime, timezone

import pytest

from core.adaptation import (
    AdaptationContext, AdaptationKind, AdaptationRecord, AdaptationScope,
    RiskLevel, StrategyStatus,
)
from core.adaptation_strategy import propose_strategy

NOW_TEXT = "2026-10-21T12:00:00+00:00"
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
CTX = AdaptationContext(mode="work", project="JARVIS", device="desktop")


def rec(number, **changes):
    values = dict(
        id=f"adapt-{number}", skill="daily-briefing",
        kind=AdaptationKind.EXPLICIT_PREFERENCE, scope=AdaptationScope.SKILL,
        context=AdaptationContext(), statement=f"Preference {number}",
        strategy=f"Strategy {number}", evidence_refs=(f"turn-{number}",),
        confidence=1.0, risk=RiskLevel.LOW, status=StrategyStatus.ACTIVE,
        created_at=NOW_TEXT, updated_at=NOW_TEXT, target="length",
    )
    values.update(changes)
    return AdaptationRecord(**values)


def reasons(plan):
    return {item.record_id: item.reason for item in plan.excluded}


def test_explicit_correction_outranks_preference_and_validated_inference():
    plan = propose_strategy([
        rec(1, kind=AdaptationKind.LEARNED_STRATEGY, validated_at=NOW_TEXT),
        rec(2, kind=AdaptationKind.EXPLICIT_PREFERENCE),
        rec(3, kind=AdaptationKind.EXPLICIT_CORRECTION),
    ], skill="daily-briefing", context=CTX, now=NOW)
    assert [item.id for item in plan.selected] == ["adapt-3"]
    assert "lower precedence" in reasons(plan)["adapt-1"]
    assert plan.requires_review is False


def test_different_targets_can_coexist_without_false_conflict():
    plan = propose_strategy([
        rec(1, target="length"),
        rec(2, target="sources", strategy="Prefer primary sources"),
    ], skill="daily-briefing", context=CTX, now=NOW)
    assert {item.id for item in plan.selected} == {"adapt-1", "adapt-2"}


def test_context_scopes_match_narrowly():
    project = rec(1, scope=AdaptationScope.PROJECT, context=AdaptationContext(project="JARVIS"))
    mode = rec(2, scope=AdaptationScope.MODE, context=AdaptationContext(mode="work"), target="format")
    wrong_device = rec(3, context=AdaptationContext(device="laptop"), target="sources")
    plan = propose_strategy([project, mode, wrong_device], skill="daily-briefing", context=CTX, now=NOW)
    assert {item.id for item in plan.selected} == {"adapt-1", "adapt-2"}
    assert reasons(plan)["adapt-3"] == "context mismatch"


def test_candidates_observations_other_skills_and_one_time_do_not_execute():
    plan = propose_strategy([
        rec(1, status=StrategyStatus.CANDIDATE),
        rec(2, kind=AdaptationKind.OBSERVED_PATTERN, target="format"),
        rec(3, skill="deep-research", target="sources"),
        rec(4, scope=AdaptationScope.ONE_TIME, target="tone"),
    ], skill="daily-briefing", context=CTX, now=NOW)
    assert plan.selected == ()
    found = reasons(plan)
    assert found["adapt-1"] == "not active"
    assert "observations" in found["adapt-2"]
    assert found["adapt-3"] == "different skill"
    assert "exact execution" in found["adapt-4"]


def test_high_risk_never_enters_read_only_plan_even_when_explicit():
    plan = propose_strategy(
        [rec(1, risk=RiskLevel.HIGH)], skill="daily-briefing", context=CTX, now=NOW
    )
    assert plan.selected == ()
    assert "authorization" in reasons(plan)["adapt-1"]


def test_inference_requires_confidence_validation_and_freshness():
    plan = propose_strategy([
        rec(1, kind=AdaptationKind.LEARNED_STRATEGY, confidence=.69, validated_at=NOW_TEXT),
        rec(2, kind=AdaptationKind.LEARNED_STRATEGY, confidence=.9, validated_at=None, target="format"),
        rec(3, kind=AdaptationKind.LEARNED_STRATEGY, confidence=.9, validated_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00", target="sources"),
    ], skill="daily-briefing", context=CTX, now=NOW)
    found = reasons(plan)
    assert found["adapt-1"] == "confidence below threshold"
    assert "not been validated" in found["adapt-2"]
    assert found["adapt-3"] == "record is stale"


def test_active_descendant_suppresses_previous_strategy():
    previous = rec(1, strategy="Long briefing")
    replacement = rec(2, previous_record_id="adapt-1", strategy="Short briefing")
    plan = propose_strategy([previous, replacement], skill="daily-briefing", context=CTX, now=NOW)
    assert [item.id for item in plan.selected] == ["adapt-2"]
    assert "superseded" in reasons(plan)["adapt-1"]


def test_equal_priority_conflict_fails_closed_for_target():
    first = rec(1, strategy="Use bullets")
    second = rec(2, strategy="Use paragraphs")
    plan = propose_strategy([first, second], skill="daily-briefing", context=CTX, now=NOW)
    assert plan.selected == ()
    assert plan.requires_review is True
    assert set(reasons(plan)) == {"adapt-1", "adapt-2"}


def test_naive_evaluation_time_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        propose_strategy([], skill="daily-briefing", context=CTX, now=datetime(2026, 1, 1))
