"""Conservative attribution of explicit user feedback to a completed skill run.

This module is intentionally pure: it does not write memory, activate a strategy,
or change execution.  Callers must supply the exact originating skill and outcome
ID, so a correction is never guessed from unrelated conversation.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

from core.adaptation import (
    AdaptationContext,
    AdaptationKind,
    AdaptationRecord,
    AdaptationScope,
    RiskLevel,
    StrategyStatus,
)

MAX_FEEDBACK_LENGTH: Final = 1200
_EXPLICIT_CORRECTION = re.compile(
    r"(?:^|\b)(?:don't|do not|stop|never|instead|next time|that was wrong|not what i (?:asked|wanted)|"
    r"i said|you should have|you shouldn't|please don't|from now on)\b",
    re.IGNORECASE,
)
_EXPLICIT_PREFERENCE = re.compile(
    r"(?:^|\b)(?:i prefer|i want you to|my preference is|from now on|"
    r"always (?:keep|use|make|give|show|tell|ask|format|write|summarize|organize))\b",
    re.IGNORECASE,
)
_ONE_TIME = re.compile(r"\b(?:just this time|only this time|for this one|this time only)\b", re.IGNORECASE)
_PROJECT = re.compile(r"\b(?:for|in|on) (?:this|the) project\b", re.IGNORECASE)
_MODE = re.compile(r"\b(?:in|for|during|when in) (?:work|personal|focus|study|meeting|private) mode\b", re.IGNORECASE)
_GLOBAL = re.compile(r"\b(?:everywhere|for everything|in all skills|globally)\b", re.IGNORECASE)
_PERMISSION_LANGUAGE = re.compile(
    r"\b(?:without (?:asking|confirmation)|bypass|skip (?:approval|confirmation)|always approve|"
    r"permission to|authorize|automatically send|automatically delete)\b",
    re.IGNORECASE,
)
_UNSAFE_INSTRUCTION = re.compile(
    r"\b(?:ignore|override|bypass|disable)\b.{0,40}\b(?:instruction|policy|safety|system|confirmation)|"
    r"\b(?:reveal|send|delete|execute|run)\b.{0,30}\b(?:secret|password|token|api key)\b",
    re.IGNORECASE,
)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class FeedbackAttribution:
    record: AdaptationRecord
    outcome_id: str
    requires_scope_confirmation: bool
    permission_language_detected: bool
    reason: str


def _clean(value: str, maximum: int) -> str:
    clean = " ".join(_CONTROL.sub(" ", str(value or "")).split())
    return clean[:maximum]


def _scope(text: str, context: AdaptationContext) -> tuple[AdaptationScope, bool]:
    if _ONE_TIME.search(text):
        return AdaptationScope.ONE_TIME, False
    if _PROJECT.search(text):
        # A project-scoped correction is ambiguous if no project was attached to
        # the originating execution; it must not silently become skill-wide.
        return AdaptationScope.PROJECT, not bool(context.project)
    if _MODE.search(text):
        return AdaptationScope.MODE, context.mode == "default"
    if _GLOBAL.search(text):
        return AdaptationScope.GLOBAL, True
    # Conservative default: affect only this skill, never every skill.
    return AdaptationScope.SKILL, False


def attribute_explicit_feedback(
    user_text: str,
    *,
    skill: str,
    outcome_id: str,
    context: AdaptationContext,
    risk: RiskLevel = RiskLevel.LOW,
    target: str = "general",
    now: str | None = None,
) -> FeedbackAttribution | None:
    """Create an inactive candidate only for unmistakably explicit feedback.

    Silence, praise, questions, and generic negative sentiment return ``None``.
    Permission-like wording is recorded only as a safety signal; it never creates
    authorization and always requires confirmation before any later promotion.
    """
    text = _clean(user_text, MAX_FEEDBACK_LENGTH)
    evidence = _clean(outcome_id, 160)
    if not text or not evidence or not isinstance(context, AdaptationContext):
        return None
    correction = bool(_EXPLICIT_CORRECTION.search(text))
    preference = bool(_EXPLICIT_PREFERENCE.search(text))
    if not correction and not preference:
        return None
    kind = AdaptationKind.EXPLICIT_CORRECTION if correction else AdaptationKind.EXPLICIT_PREFERENCE
    scope, scope_confirmation = _scope(text, context)
    permission_detected = bool(_PERMISSION_LANGUAGE.search(text))
    if _UNSAFE_INSTRUCTION.search(text):
        return None
    if scope is AdaptationScope.GLOBAL:
        context = AdaptationContext()
    timestamp = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    digest = hashlib.sha256(
        f"{skill}\0{target}\0{evidence}\0{text.casefold()}".encode("utf-8")
    ).hexdigest()[:20]
    record = AdaptationRecord(
        id=f"feedback-{digest}",
        skill=skill,
        kind=kind,
        scope=scope,
        context=context,
        statement=text,
        # Preserve the explicit instruction without inventing a broader policy.
        strategy=text,
        evidence_refs=(evidence,),
        confidence=1.0,
        risk=risk,
        status=StrategyStatus.CANDIDATE,
        created_at=timestamp,
        updated_at=timestamp,
        target=target,
        permission_related=permission_detected,
    )
    reason = "explicit correction" if correction else "explicit preference"
    if permission_detected:
        reason += "; permission language requires separate authorization"
    return FeedbackAttribution(
        record=record,
        outcome_id=evidence,
        requires_scope_confirmation=scope_confirmation or permission_detected,
        permission_language_detected=permission_detected,
        reason=reason,
    )
