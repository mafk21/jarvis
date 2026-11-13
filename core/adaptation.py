"""Strict, side-effect-free contracts for user-specific skill adaptation.

This module deliberately performs no persistence and changes no runtime behavior.
It is the schema boundary for a staged adaptive-learning rollout.  In particular,
preferences and learned strategies can never represent authorization: permission
continues to be decided by the existing safety and confirmation systems.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

SCHEMA_VERSION = 1
MAX_SHORT_TEXT = 160
MAX_TEXT = 1200
MAX_REFS = 32
_SKILL = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class AdaptationValidationError(ValueError):
    """Raised when adaptation data fails the strict contract."""


class AdaptationKind(str, Enum):
    EXPLICIT_PREFERENCE = "explicit_preference"
    EXPLICIT_CORRECTION = "explicit_correction"
    OBSERVED_PATTERN = "observed_pattern"
    LEARNED_STRATEGY = "learned_strategy"


class AdaptationScope(str, Enum):
    ONE_TIME = "one_time"
    MODE = "mode"
    PROJECT = "project"
    SKILL = "skill"
    GLOBAL = "global"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class StrategyStatus(str, Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    DISABLED = "disabled"
    ROLLED_BACK = "rolled_back"


class OutcomeResult(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    UNCERTAIN = "uncertain"


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AdaptationValidationError(f"{label} must be an object")
    return value


def _strict(data: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise AdaptationValidationError(
            f"{label} contains unknown fields: {', '.join(sorted(map(str, unknown)))}"
        )


def _text(value: Any, label: str, maximum: int = MAX_TEXT, *, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise AdaptationValidationError(f"{label} must be text")
    clean = " ".join(value.split())
    if not clean and not empty:
        raise AdaptationValidationError(f"{label} cannot be empty")
    if len(clean) > maximum:
        raise AdaptationValidationError(f"{label} exceeds {maximum} characters")
    if any(ord(char) < 32 for char in clean):
        raise AdaptationValidationError(f"{label} contains control characters")
    return clean


def _skill(value: Any) -> str:
    clean = _text(value, "skill", 64).lower()
    if not _SKILL.fullmatch(clean):
        raise AdaptationValidationError("skill must be a lowercase skill identifier")
    return clean


def _timestamp(value: Any, label: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    clean = _text(value, label, 40)
    try:
        parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdaptationValidationError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise AdaptationValidationError(f"{label} must include a timezone")
    return clean


def _confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AdaptationValidationError("confidence must be a number")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise AdaptationValidationError("confidence must be finite and between 0 and 1")
    return result


def _enum(enum_type: type[Enum], value: Any, label: str):
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise AdaptationValidationError(f"unsupported {label}") from exc


def _refs(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > MAX_REFS:
        raise AdaptationValidationError(f"evidence_refs must be a list of at most {MAX_REFS} items")
    refs = tuple(_text(item, "evidence reference", MAX_SHORT_TEXT) for item in value)
    if len(set(refs)) != len(refs):
        raise AdaptationValidationError("evidence_refs cannot contain duplicates")
    return refs


@dataclass(frozen=True, slots=True)
class AdaptationContext:
    """Where an adaptation applies; blank fields mean no narrower qualifier."""

    mode: str = "default"
    project: str = ""
    device: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", _text(self.mode, "mode", 80))
        object.__setattr__(self, "project", _text(self.project, "project", 160, empty=True))
        object.__setattr__(self, "device", _text(self.device, "device", 160, empty=True))

    @classmethod
    def from_dict(cls, raw: Any) -> "AdaptationContext":
        data = _mapping(raw, "adaptation context")
        _strict(data, {"mode", "project", "device"}, "adaptation context")
        return cls(mode=data.get("mode", "default"), project=data.get("project", ""), device=data.get("device", ""))


@dataclass(frozen=True, slots=True)
class AdaptationRecord:
    """Evidence-backed preference, correction, observation, or strategy.

    This contract intentionally has no permission/authorization field.  A record
    may alter strategy selection but cannot approve an action or bypass a gate.
    """

    id: str
    skill: str
    kind: AdaptationKind
    scope: AdaptationScope
    context: AdaptationContext
    statement: str
    strategy: str
    evidence_refs: tuple[str, ...]
    confidence: float
    risk: RiskLevel
    status: StrategyStatus
    created_at: str
    updated_at: str
    validated_at: str | None = None
    previous_record_id: str | None = None
    target: str = "general"

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _text(self.id, "adaptation id", 80))
        object.__setattr__(self, "skill", _skill(self.skill))
        object.__setattr__(self, "kind", _enum(AdaptationKind, self.kind, "adaptation kind"))
        object.__setattr__(self, "scope", _enum(AdaptationScope, self.scope, "adaptation scope"))
        if not isinstance(self.context, AdaptationContext):
            raise AdaptationValidationError("context must be an AdaptationContext")
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        object.__setattr__(self, "strategy", _text(self.strategy, "strategy"))
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs))
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        object.__setattr__(self, "risk", _enum(RiskLevel, self.risk, "risk level"))
        object.__setattr__(self, "status", _enum(StrategyStatus, self.status, "strategy status"))
        object.__setattr__(self, "created_at", _timestamp(self.created_at, "created_at"))
        object.__setattr__(self, "updated_at", _timestamp(self.updated_at, "updated_at"))
        object.__setattr__(self, "validated_at", _timestamp(self.validated_at, "validated_at", optional=True))
        if self.previous_record_id is not None:
            object.__setattr__(self, "previous_record_id", _text(self.previous_record_id, "previous_record_id", 80))
        object.__setattr__(self, "target", _text(self.target, "target", 80))
        if self.kind in {AdaptationKind.OBSERVED_PATTERN, AdaptationKind.LEARNED_STRATEGY} and not self.evidence_refs:
            raise AdaptationValidationError("inferred adaptations require evidence")
        if self.risk is RiskLevel.HIGH and self.kind in {AdaptationKind.OBSERVED_PATTERN, AdaptationKind.LEARNED_STRATEGY}:
            raise AdaptationValidationError("high-risk behavior cannot be activated from inference")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("kind", "scope", "risk", "status"):
            data[key] = getattr(self, key).value
        return data

    @classmethod
    def from_dict(cls, raw: Any) -> "AdaptationRecord":
        data = _mapping(raw, "adaptation record")
        fields = {
            "id", "skill", "kind", "scope", "context", "statement", "strategy",
            "evidence_refs", "confidence", "risk", "status", "created_at", "updated_at",
            "validated_at", "previous_record_id", "target",
        }
        _strict(data, fields, "adaptation record")
        required = fields - {"validated_at", "previous_record_id", "target"}
        missing = required - set(data)
        if missing:
            raise AdaptationValidationError(f"adaptation record is missing fields: {', '.join(sorted(missing))}")
        return cls(
            id=data["id"], skill=data["skill"], kind=data["kind"], scope=data["scope"],
            context=AdaptationContext.from_dict(data["context"]), statement=data["statement"],
            strategy=data["strategy"], evidence_refs=tuple(data["evidence_refs"]),
            confidence=data["confidence"], risk=data["risk"], status=data["status"],
            created_at=data["created_at"], updated_at=data["updated_at"],
            validated_at=data.get("validated_at"), previous_record_id=data.get("previous_record_id"),
            target=data.get("target", "general"),
        )


@dataclass(frozen=True, slots=True)
class SkillOutcome:
    """Minimal measurable result emitted by a skill execution."""

    id: str
    skill: str
    task_type: str
    context: AdaptationContext
    strategy_record_id: str | None
    result: OutcomeResult
    verification: str
    started_at: str
    completed_at: str
    latency_ms: int
    user_feedback: str = ""
    correction: str = ""
    reversed: bool = False
    failure_reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _text(self.id, "outcome id", 80))
        object.__setattr__(self, "skill", _skill(self.skill))
        object.__setattr__(self, "task_type", _text(self.task_type, "task_type", 120))
        if not isinstance(self.context, AdaptationContext):
            raise AdaptationValidationError("context must be an AdaptationContext")
        if self.strategy_record_id is not None:
            object.__setattr__(self, "strategy_record_id", _text(self.strategy_record_id, "strategy_record_id", 80))
        object.__setattr__(self, "result", _enum(OutcomeResult, self.result, "outcome result"))
        object.__setattr__(self, "verification", _text(self.verification, "verification"))
        object.__setattr__(self, "started_at", _timestamp(self.started_at, "started_at"))
        object.__setattr__(self, "completed_at", _timestamp(self.completed_at, "completed_at"))
        if isinstance(self.latency_ms, bool) or not isinstance(self.latency_ms, int) or not 0 <= self.latency_ms <= 604_800_000:
            raise AdaptationValidationError("latency_ms must be a non-negative bounded integer")
        for name in ("user_feedback", "correction", "failure_reason"):
            object.__setattr__(self, name, _text(getattr(self, name), name, empty=True))
        if not isinstance(self.reversed, bool):
            raise AdaptationValidationError("reversed must be true or false")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["result"] = self.result.value
        return data

    @classmethod
    def from_dict(cls, raw: Any) -> "SkillOutcome":
        data = _mapping(raw, "skill outcome")
        fields = {
            "id", "skill", "task_type", "context", "strategy_record_id", "result",
            "verification", "started_at", "completed_at", "latency_ms", "user_feedback",
            "correction", "reversed", "failure_reason",
        }
        _strict(data, fields, "skill outcome")
        required = fields - {"strategy_record_id", "user_feedback", "correction", "reversed", "failure_reason"}
        missing = required - set(data)
        if missing:
            raise AdaptationValidationError(f"skill outcome is missing fields: {', '.join(sorted(missing))}")
        return cls(
            id=data["id"], skill=data["skill"], task_type=data["task_type"],
            context=AdaptationContext.from_dict(data["context"]),
            strategy_record_id=data.get("strategy_record_id"), result=data["result"],
            verification=data["verification"], started_at=data["started_at"],
            completed_at=data["completed_at"], latency_ms=data["latency_ms"],
            user_feedback=data.get("user_feedback", ""), correction=data.get("correction", ""),
            reversed=data.get("reversed", False), failure_reason=data.get("failure_reason", ""),
        )
