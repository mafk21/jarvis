import pytest

from core.adaptation import AdaptationContext, AdaptationKind, AdaptationScope, RiskLevel, StrategyStatus
from core.adaptation_feedback import attribute_explicit_feedback

NOW = "2026-10-21T12:00:00+00:00"
CTX = AdaptationContext(mode="work", project="JARVIS", device="desktop")


def attribute(text, **changes):
    values = dict(skill="daily-briefing", outcome_id="outcome-42", context=CTX, now=NOW)
    values.update(changes)
    return attribute_explicit_feedback(text, **values)


@pytest.mark.parametrize("text", [
    "Thanks.",
    "That is interesting.",
    "I had a bad morning.",
    "Why did the report take so long?",
    "I always read the security section first.",
    "Maybe shorter would work.",
    "",
])
def test_silence_sentiment_questions_and_implicit_patterns_are_not_learned(text):
    assert attribute(text) is None


def test_explicit_correction_is_attributed_to_exact_outcome_as_candidate():
    result = attribute("Next time, keep the briefing below 45 seconds.")
    assert result.record.kind is AdaptationKind.EXPLICIT_CORRECTION
    assert result.record.status is StrategyStatus.CANDIDATE
    assert result.record.skill == "daily-briefing"
    assert result.record.evidence_refs == ("outcome-42",)
    assert result.record.context == CTX
    assert result.outcome_id == "outcome-42"


def test_explicit_preference_is_not_mistaken_for_permission():
    result = attribute("I prefer concise bullet points.")
    assert result.record.kind is AdaptationKind.EXPLICIT_PREFERENCE
    assert result.record.scope is AdaptationScope.SKILL
    assert result.permission_language_detected is False


@pytest.mark.parametrize("text,scope", [
    ("Just this time, do not include news.", AdaptationScope.ONE_TIME),
    ("For this project, always keep the technical details.", AdaptationScope.PROJECT),
    ("In work mode, I prefer a short summary.", AdaptationScope.MODE),
])
def test_scope_is_narrowly_classified_when_explicit(text, scope):
    result = attribute(text)
    assert result.record.scope is scope
    assert result.requires_scope_confirmation is False


def test_ambiguous_global_or_missing_context_scope_requires_confirmation():
    global_result = attribute("Everywhere, I want you to keep answers short.")
    assert global_result.record.scope is AdaptationScope.GLOBAL
    assert global_result.requires_scope_confirmation is True

    missing_project = attribute(
        "For this project, do not include deployment steps.",
        context=AdaptationContext(mode="work"),
    )
    assert missing_project.record.scope is AdaptationScope.PROJECT
    assert missing_project.requires_scope_confirmation is True


def test_permission_language_is_flagged_but_never_authorizes_anything():
    result = attribute(
        "From now on, automatically send messages without asking.",
        skill="workspace-comms",
        risk=RiskLevel.HIGH,
    )
    assert result.permission_language_detected is True
    assert result.requires_scope_confirmation is True
    assert result.record.status is StrategyStatus.CANDIDATE
    assert not hasattr(result.record, "permission")
    assert "separate authorization" in result.reason


def test_attribution_id_is_stable_for_same_feedback_and_evidence():
    first = attribute("Do not include sports next time.")
    second = attribute("Do not include sports next time.")
    assert first.record.id == second.record.id
    changed_outcome = attribute(
        "Do not include sports next time.", outcome_id="outcome-43"
    )
    assert changed_outcome.record.id != first.record.id


def test_missing_execution_attribution_fails_closed():
    assert attribute_explicit_feedback(
        "Never do that again.", skill="daily-briefing", outcome_id="",
        context=CTX, now=NOW,
    ) is None
