"""Confirmed owner controls for adaptation lifecycle and deletion."""
from __future__ import annotations

from core.adaptation_governance import activate, disable, remove, rollback
from memory.adaptation_store import AdaptationStore


def adaptation_manage(parameters=None, **_kwargs) -> str:
    p = parameters or {}
    action = str(p.get("action") or "").strip().lower()
    store = AdaptationStore()
    try:
        revision = int(p.get("expected_revision"))
    except (TypeError, ValueError):
        return "No change made: expected_revision must match the current inspected revision."
    record_id = str(p.get("record_id") or "").strip()
    try:
        if action == "activate":
            result = activate(store, record_id, expected_revision=revision)
        elif action == "disable":
            result = disable(store, record_id, expected_revision=revision)
        elif action == "rollback":
            result = rollback(store, record_id, expected_revision=revision)
        elif action == "remove":
            result = remove(store, record_id, expected_revision=revision)
        else:
            return "No change made: use activate, disable, rollback, or remove. Use adaptation_clear for complete erasure."
        return f"Adaptation {action} completed at revision {result.revision}."
    except (ValueError, KeyError, RuntimeError) as exc:
        return f"No adaptation change was made: {exc}"


TOOL = {
    "name": "adaptation_manage",
    "description": "Owner-confirmed control to activate, disable, roll back, or remove learned skill behavior. Inspect first and pass its exact revision. Never changes action permissions.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": ["activate", "disable", "rollback", "remove"]},
            "record_id": {"type": "STRING"},
            "expected_revision": {"type": "INTEGER"},
        },
        "required": ["action", "expected_revision"],
    },
    "handler": adaptation_manage,
    "safety": {
        "risk": "medium",
        "permission": "memory_governance",
        "confirmation": "required",
        "reversible": False,
        "verification": "observed",
    },
}
