"""Explicit lifecycle for measurable, verified skill outcomes.

The recorder is opt-in and is not wired into existing skills.  It turns a known
execution start and terminal observation into a strictly validated SkillOutcome.
Success can never be recorded without concrete verification text, and storage
failure leaves the session open so the caller can retry without inventing proof.
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable

from core.adaptation import AdaptationContext, OutcomeResult, SkillOutcome
from memory.adaptation_store import AdaptationSnapshot, AdaptationStore


class OutcomeLifecycleError(RuntimeError):
    """An invalid or repeated outcome transition was requested."""


@dataclass(frozen=True, slots=True)
class OutcomeSession:
    id: str
    skill: str
    task_type: str
    context: AdaptationContext
    strategy_record_id: str | None
    started_at: str
    started_monotonic: float
    store_revision: int
    user_feedback: str = ""
    correction: str = ""
    reversed: bool = False


class OutcomeRecorder:
    """Thread-safe start/feedback/terminal lifecycle backed by AdaptationStore."""

    def __init__(
        self,
        store: AdaptationStore,
        *,
        utc_now: Callable[[], str] | None = None,
        monotonic: Callable[[], float] | None = None,
    ):
        self.store = store
        self._utc_now = utc_now or (lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
        self._monotonic = monotonic or time.monotonic
        self._open: dict[str, OutcomeSession] = {}
        self._closed: set[str] = set()
        self._lock = threading.RLock()

    def start(
        self,
        *,
        skill: str,
        task_type: str,
        context: AdaptationContext,
        strategy_record_id: str | None = None,
        execution_id: str | None = None,
    ) -> OutcomeSession:
        """Start one measured execution without claiming any result."""
        if not isinstance(context, AdaptationContext):
            raise TypeError("context must be an AdaptationContext")
        stamp = self._utc_now()
        if execution_id:
            digest = hashlib.sha256(
                f"{skill}\0{task_type}\0{execution_id}".encode("utf-8")
            ).hexdigest()[:24]
            outcome_id = f"outcome-{digest}"
        else:
            outcome_id = f"outcome-{secrets.token_urlsafe(18)}"
        # Validate identifiers and timestamp through the final contract without
        # manufacturing a terminal outcome: lightweight checks happen here and
        # full validation happens before persistence in finish().
        if not str(skill or "").strip() or not str(task_type or "").strip():
            raise ValueError("skill and task_type are required")
        session = OutcomeSession(
            id=outcome_id,
            skill=str(skill),
            task_type=str(task_type),
            context=context,
            strategy_record_id=(str(strategy_record_id).strip() if strategy_record_id is not None else None),
            started_at=stamp,
            started_monotonic=self._monotonic(),
            store_revision=self.store.load().revision,
        )
        with self._lock:
            if outcome_id in self._open:
                return self._open[outcome_id]
            if outcome_id in self._closed or any(item.id == outcome_id for item in self.store.load().outcomes):
                raise OutcomeLifecycleError("execution outcome is already persisted")
            self._open[outcome_id] = session
        return session

    def feedback(
        self,
        outcome_id: str,
        *,
        user_feedback: str = "",
        correction: str = "",
        reversed: bool | None = None,
    ) -> OutcomeSession:
        """Attach explicit feedback without changing the execution result."""
        with self._lock:
            current = self._require_open(outcome_id)
            updated = replace(
                current,
                user_feedback=str(user_feedback or current.user_feedback),
                correction=str(correction or current.correction),
                reversed=current.reversed if reversed is None else bool(reversed),
            )
            self._open[outcome_id] = updated
            return updated

    def finish(
        self,
        outcome_id: str,
        *,
        result: OutcomeResult,
        verification: str,
        failure_reason: str = "",
    ) -> tuple[SkillOutcome, AdaptationSnapshot]:
        """Validate and persist exactly one terminal outcome.

        A succeeded result requires non-empty verification.  Failed/partial/
        uncertain results preserve their concrete reason rather than becoming a
        false success.  If persistence raises, the session remains open.
        """
        with self._lock:
            session = self._require_open(outcome_id)
            try:
                terminal = OutcomeResult(result)
            except (TypeError, ValueError) as exc:
                raise OutcomeLifecycleError("result must be a terminal OutcomeResult") from exc
            proof = str(verification or "").strip()
            reason = str(failure_reason or "").strip()
            if len(proof) < 12 or proof.casefold() in {"done", "completed", "success", "verified", "ok", "it worked"}:
                raise OutcomeLifecycleError("terminal outcomes require concrete verification evidence")
            if terminal in {OutcomeResult.FAILED, OutcomeResult.PARTIAL, OutcomeResult.UNCERTAIN} and not reason:
                raise OutcomeLifecycleError(f"{terminal.value} outcomes require a failure reason")
            elapsed = max(0.0, self._monotonic() - session.started_monotonic)
            latency_ms = min(604_800_000, round(elapsed * 1000))
            current_store = self.store.load()
            if current_store.revision > session.store_revision and not current_store.records and not current_store.outcomes:
                raise OutcomeLifecycleError("outcome session was invalidated by adaptation clearing")
            outcome = SkillOutcome(
                id=session.id,
                skill=session.skill,
                task_type=session.task_type,
                context=session.context,
                strategy_record_id=session.strategy_record_id,
                result=terminal,
                verification=proof,
                started_at=session.started_at,
                completed_at=self._utc_now(),
                latency_ms=latency_ms,
                user_feedback=session.user_feedback,
                correction=session.correction,
                reversed=session.reversed,
                failure_reason=reason,
            )
            snapshot = self.store.append_outcome(outcome)
            del self._open[outcome_id]
            self._closed.add(outcome_id)
            return outcome, snapshot

    def abandon(self, outcome_id: str) -> None:
        """Forget local tracking only; this makes no claim about task outcome."""
        with self._lock:
            self._require_open(outcome_id)
            del self._open[outcome_id]
            self._closed.add(outcome_id)

    def open_sessions(self) -> tuple[OutcomeSession, ...]:
        with self._lock:
            return tuple(self._open.values())

    def _require_open(self, outcome_id: str) -> OutcomeSession:
        clean = str(outcome_id or "").strip()
        if clean in self._closed:
            raise OutcomeLifecycleError("outcome is already closed")
        try:
            return self._open[clean]
        except KeyError as exc:
            raise OutcomeLifecycleError("unknown outcome session") from exc
