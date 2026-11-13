from concurrent.futures import ThreadPoolExecutor

import pytest

from core import security_vault as vault
from core.adaptation import AdaptationContext, OutcomeResult
from core.adaptation_outcomes import OutcomeLifecycleError, OutcomeRecorder
from memory.adaptation_store import AdaptationStore

NOW = "2026-10-21T12:00:00+00:00"
CTX = AdaptationContext(mode="work", project="JARVIS")


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "VAULT_KEY_FILE", tmp_path / "config" / ".vault.key")
    return AdaptationStore(tmp_path / "memory" / "adaptations.json")


def test_verified_success_records_start_completion_and_latency(store):
    ticks = iter((10.0, 10.812))
    recorder = OutcomeRecorder(store, utc_now=lambda: NOW, monotonic=lambda: next(ticks))
    session = recorder.start(
        skill="daily-briefing", task_type="morning", context=CTX,
        strategy_record_id="adapt-1", execution_id="run-1",
    )
    outcome, snapshot = recorder.finish(
        session.id, result=OutcomeResult.SUCCEEDED,
        verification="Briefing delivered and acknowledged.",
    )
    assert outcome.started_at == outcome.completed_at == NOW
    assert outcome.latency_ms == 812
    assert outcome.strategy_record_id == "adapt-1"
    assert snapshot.outcomes == (outcome,)
    assert recorder.open_sessions() == ()


def test_success_without_verification_is_rejected_and_remains_open(store):
    recorder = OutcomeRecorder(store, utc_now=lambda: NOW)
    session = recorder.start(skill="deep-research", task_type="report", context=CTX)
    with pytest.raises(OutcomeLifecycleError, match="verification"):
        recorder.finish(session.id, result=OutcomeResult.SUCCEEDED, verification="")
    assert recorder.open_sessions() == (session,)
    assert store.load().outcomes == ()


@pytest.mark.parametrize("result", [OutcomeResult.FAILED, OutcomeResult.PARTIAL, OutcomeResult.UNCERTAIN])
def test_non_success_requires_concrete_failure_reason(store, result):
    recorder = OutcomeRecorder(store, utc_now=lambda: NOW)
    session = recorder.start(skill="deep-research", task_type="report", context=CTX)
    with pytest.raises(OutcomeLifecycleError, match="failure reason"):
        recorder.finish(session.id, result=result, verification="Provider response checked")
    outcome, _ = recorder.finish(
        session.id, result=result, verification="Provider response checked",
        failure_reason="Provider timed out",
    )
    assert outcome.result is result
    assert outcome.failure_reason == "Provider timed out"


def test_feedback_correction_and_reversal_attach_before_terminal_result(store):
    recorder = OutcomeRecorder(store, utc_now=lambda: NOW)
    session = recorder.start(skill="safe-file-organizer", task_type="downloads", context=CTX)
    updated = recorder.feedback(
        session.id,
        user_feedback="Archives should be separate.",
        correction="Use an Archives folder.",
        reversed=True,
    )
    assert updated.reversed is True
    outcome, _ = recorder.finish(
        session.id, result=OutcomeResult.CANCELLED,
        verification="User cancelled and undo completed.",
    )
    assert outcome.correction == "Use an Archives folder."
    assert outcome.reversed is True


def test_closed_or_unknown_sessions_cannot_be_changed_twice(store):
    recorder = OutcomeRecorder(store, utc_now=lambda: NOW)
    session = recorder.start(skill="focus-mode", task_type="session", context=CTX)
    recorder.finish(session.id, result=OutcomeResult.CANCELLED, verification="Timer cancelled")
    with pytest.raises(OutcomeLifecycleError, match="already closed"):
        recorder.finish(session.id, result=OutcomeResult.CANCELLED, verification="Again")
    with pytest.raises(OutcomeLifecycleError, match="unknown"):
        recorder.feedback("missing", user_feedback="No")


def test_storage_failure_does_not_close_or_lose_session(store, monkeypatch):
    recorder = OutcomeRecorder(store, utc_now=lambda: NOW)
    session = recorder.start(skill="meeting-copilot", task_type="summary", context=CTX)
    original = store.append_outcome
    monkeypatch.setattr(store, "append_outcome", lambda _outcome: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        recorder.finish(session.id, result=OutcomeResult.SUCCEEDED, verification="Summary verified")
    assert recorder.open_sessions()[0].id == session.id
    monkeypatch.setattr(store, "append_outcome", original)
    outcome, _ = recorder.finish(
        session.id, result=OutcomeResult.SUCCEEDED, verification="Summary verified"
    )
    assert outcome.id == session.id


def test_execution_id_prevents_duplicate_tracking(store):
    recorder = OutcomeRecorder(store, utc_now=lambda: NOW)
    recorder.start(
        skill="code-ship", task_type="test", context=CTX, execution_id="same-run"
    )
    with pytest.raises(OutcomeLifecycleError, match="already being tracked"):
        recorder.start(
            skill="code-ship", task_type="test", context=CTX, execution_id="same-run"
        )


def test_abandon_makes_no_persisted_outcome_claim(store):
    recorder = OutcomeRecorder(store, utc_now=lambda: NOW)
    session = recorder.start(skill="gui-autopilot", task_type="click", context=CTX)
    recorder.abandon(session.id)
    assert store.load().outcomes == ()
    with pytest.raises(OutcomeLifecycleError, match="already closed"):
        recorder.feedback(session.id, user_feedback="late")


def test_concurrent_distinct_sessions_are_all_recorded(store):
    recorder = OutcomeRecorder(store, utc_now=lambda: NOW)
    sessions = [
        recorder.start(
            skill="daily-briefing", task_type="item", context=CTX,
            execution_id=f"run-{number}",
        )
        for number in range(20)
    ]

    def finish(session):
        return recorder.finish(
            session.id, result=OutcomeResult.SUCCEEDED, verification="Verified"
        )[0].id

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = set(pool.map(finish, sessions))
    assert len(ids) == 20
    assert len(store.load().outcomes) == 20
