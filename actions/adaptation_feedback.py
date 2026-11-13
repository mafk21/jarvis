"""Save explicit post-outcome feedback as an inactive adaptation candidate."""
from __future__ import annotations

from core.adaptation_feedback import attribute_explicit_feedback
from memory.adaptation_store import AdaptationStore


def adaptation_feedback(parameters=None, **_kwargs) -> str:
    from core.session_privacy import enabled as incognito
    from memory.config_manager import get_adaptive_learning_enabled
    if incognito():
        return "Incognito is active, so adaptive feedback storage is paused."
    if not get_adaptive_learning_enabled():
        return "Adaptive learning is disabled in Privacy settings."
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
