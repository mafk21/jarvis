"""Save explicit post-outcome feedback as an inactive adaptation candidate."""
from __future__ import annotations

from core.adaptation_feedback import attribute_explicit_feedback
from memory.adaptation_store import AdaptationStore


def adaptation_feedback(parameters=None, **_kwargs) -> str:
    from core.adaptation_privacy import explicitly_enabled, persistence_guard
    with persistence_guard():
        if not explicitly_enabled():
            return "Adaptive learning must be explicitly enabled and Incognito must be off."
        return _adaptation_feedback_guarded(parameters)


def _adaptation_feedback_guarded(parameters=None) -> str:
    p = parameters or {}
    outcome_id = str(p.get("outcome_id") or "").strip()
    text = str(p.get("user_text") or "").strip()
    store = AdaptationStore()
    snapshot = store.load()
    outcome = next((item for item in snapshot.outcomes if item.id == outcome_id), None)
    if outcome is None:
        return "No feedback saved: the exact originating outcome was not found."
    attributed = attribute_explicit_feedback(
        text, skill=outcome.skill, outcome_id=outcome.id, context=outcome.context,
        target=str(p.get("target") or "general"),
    )
    if attributed is None:
        return "No feedback saved: the statement was not an explicit correction or preference."
    existing = next((item for item in snapshot.records if item.id == attributed.record.id), None)
    if existing is not None and existing.status.value == "active":
        return f"Adaptation {existing.id} is already active; repeated feedback did not change it."
    result = store.put_record(attributed.record, expected_revision=snapshot.revision)
    warning = " Scope or permission wording requires confirmation." if attributed.requires_scope_confirmation else ""
    return (
        f"Saved inactive adaptation candidate {attributed.record.id} at revision {result.revision}."
        f"{warning} It will not affect behavior until the owner activates it."
    )


TOOL = {
    "name": "adaptation_feedback",
    "description": "Attribute an explicit user correction or preference to an exact recorded skill outcome. Saves only an inactive candidate; never infer from silence and never grant permission.",
    "parameters": {"type": "OBJECT", "properties": {
        "outcome_id": {"type": "STRING"}, "user_text": {"type": "STRING"},
        "target": {"type": "STRING", "description": "Behavior category such as length, format, sources, tone, naming, or retry-policy."},
    }, "required": ["outcome_id", "user_text", "target"]},
    "handler": adaptation_feedback,
}
