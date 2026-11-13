"""End-to-end longitudinal acceptance test for the shared adaptation layer."""
from datetime import datetime, timezone

from core import adaptation_governance as governance
from core import security_vault as vault
from core.adaptation import AdaptationContext, OutcomeResult, StrategyStatus
from core.adaptation_feedback import attribute_explicit_feedback
from core.adaptation_governance import activate, disable
from core.adaptation_outcomes import OutcomeRecorder
from core.adaptation_strategy import propose_strategy
from memory.adaptation_store import AdaptationStore

NOW = "2026-10-21T12:00:00+00:00"


def test_correction_persists_applies_only_in_context_and_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "VAULT_KEY_FILE", tmp_path / ".vault.key")
    monkeypatch.setattr(governance, "_now", lambda: NOW)
    path = tmp_path / "adaptations.json"
    store = AdaptationStore(path)
    context = AdaptationContext(mode="work", project="JARVIS", device="desktop")

    recorder = OutcomeRecorder(store, utc_now=lambda: NOW)
    session = recorder.start(
        skill="daily-briefing", task_type="morning", context=context,
        execution_id="baseline-run",
    )
    baseline, first = recorder.finish(
        session.id, result=OutcomeResult.SUCCEEDED,
        verification="Briefing delivered; user then corrected its length.",
    )
    feedback = attribute_explicit_feedback(
        "In work mode, next time keep the briefing below 45 seconds.",
        skill="daily-briefing", outcome_id=baseline.id, context=context,
        target="length", now=NOW,
    )
    assert feedback is not None
    candidate = store.put_record(feedback.record, expected_revision=first.revision)
    assert candidate.records[0].status is StrategyStatus.CANDIDATE

    promoted = activate(store, feedback.record.id, expected_revision=candidate.revision)
    restarted = AdaptationStore(path)  # prove a new process-facing instance can reload it
    loaded = restarted.load()
    assert loaded.revision == promoted.revision

    evaluated_at = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    matching = propose_strategy(loaded.records, skill="daily-briefing", context=context, now=evaluated_at)
    assert matching.strategies == (feedback.record.strategy,)
    personal = propose_strategy(
        loaded.records, skill="daily-briefing",
        context=AdaptationContext(mode="personal", project="JARVIS", device="desktop"),
        now=evaluated_at,
    )
    assert personal.selected == ()

    disabled = disable(restarted, feedback.record.id, expected_revision=loaded.revision)
    after_disable = propose_strategy(
        disabled.records, skill="daily-briefing", context=context, now=evaluated_at
    )
    assert after_disable.selected == ()
    restarted.delete_files()
    assert restarted.load().records == ()
