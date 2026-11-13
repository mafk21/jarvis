"""Opt-in execution measurement used by adaptive skill playbooks."""
from __future__ import annotations

import threading

from core.adaptation import AdaptationContext, OutcomeResult
from core.adaptation_outcomes import OutcomeRecorder
from memory.adaptation_store import AdaptationStore

_LOCK = threading.Lock()
_RECORDER: OutcomeRecorder | None = None


def _enabled() -> tuple[bool, str]:
    from core.session_privacy import enabled as incognito
    from memory.config_manager import get_adaptive_learning_enabled
    if incognito():
        return False, "Incognito is active, so adaptive outcome recording is paused."
    if not get_adaptive_learning_enabled():
        return False, "Adaptive learning is disabled in Privacy settings."
    return True, ""


def _recorder() -> OutcomeRecorder:
    global _RECORDER
    with _LOCK:
        if _RECORDER is None:
            _RECORDER = OutcomeRecorder(AdaptationStore())
        return _RECORDER


def adaptation_outcome(parameters=None, **_kwargs) -> str:
    ok, message = _enabled()
    if not ok:
        return message
    p = parameters or {}
    action = str(p.get("action") or "").strip().lower()
    recorder = _recorder()
    try:
        if action == "start":
            session = recorder.start(
                skill=str(p.get("skill") or ""), task_type=str(p.get("task_type") or "task"),
                context=AdaptationContext(mode=str(p.get("mode") or "default"),
                                          project=str(p.get("project") or ""),
                                          device=str(p.get("device") or "")),
                strategy_record_id=str(p.get("strategy_record_id") or "").strip() or None,
                execution_id=str(p.get("execution_id") or "").strip() or None,
            )
            return f"Adaptive outcome started: {session.id}. This is not a success claim."
        outcome_id = str(p.get("outcome_id") or "")
        if action == "feedback":
            recorder.feedback(outcome_id, user_feedback=str(p.get("user_feedback") or ""),
                              correction=str(p.get("correction") or ""),
                              reversed=p.get("reversed") if "reversed" in p else None)
            return f"Explicit feedback attached to {outcome_id}."
        if action == "finish":
            outcome, _snapshot = recorder.finish(
                outcome_id, result=OutcomeResult(str(p.get("result") or "")),
                verification=str(p.get("verification") or ""),
                failure_reason=str(p.get("failure_reason") or ""),
            )
            return f"Adaptive outcome recorded: {outcome.id} = {outcome.result.value}."
        if action == "abandon":
            recorder.abandon(outcome_id)
            return "Local outcome tracking abandoned; no result was recorded."
        return "Use start, feedback, finish, or abandon."
    except (TypeError, ValueError, RuntimeError) as exc:
        return f"Adaptive outcome was not changed: {exc}"


TOOL = {
    "name": "adaptation_outcome",
    "description": "Measure an adaptive skill run. Start before the skill, then finish only with concrete verification; use feedback for explicit corrections. This never changes action permission.",
    "parameters": {"type": "OBJECT", "properties": {
        "action": {"type": "STRING", "enum": ["start", "feedback", "finish", "abandon"]},
        "skill": {"type": "STRING"}, "task_type": {"type": "STRING"},
        "mode": {"type": "STRING"}, "project": {"type": "STRING"}, "device": {"type": "STRING"},
        "strategy_record_id": {"type": "STRING"}, "execution_id": {"type": "STRING"},
        "outcome_id": {"type": "STRING"},
        "result": {"type": "STRING", "enum": ["succeeded", "failed", "partial", "cancelled", "uncertain"]},
        "verification": {"type": "STRING"}, "failure_reason": {"type": "STRING"},
        "user_feedback": {"type": "STRING"}, "correction": {"type": "STRING"},
        "reversed": {"type": "BOOLEAN"},
    }, "required": ["action"]},
    "handler": adaptation_outcome,
}
