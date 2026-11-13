"""Dedicated destructive confirmation boundary for erasing adaptation history."""
from memory.adaptation_store import AdaptationStore


def adaptation_clear(parameters=None, **_kwargs) -> str:
    p = parameters or {}
    try:
        revision = int(p.get("expected_revision"))
    except (TypeError, ValueError):
        return "Nothing erased: inspect adaptations and provide the exact current revision."
    try:
        result = AdaptationStore().clear(expected_revision=revision)
        return f"All adaptation records and outcomes were erased at revision {result.revision}."
    except RuntimeError as exc:
        return f"Nothing erased: {exc}"


TOOL = {
    "name": "adaptation_clear",
    "description": "DESTRUCTIVE: permanently erase all adaptation records and outcome history after showing this exact action to the owner.",
    "parameters": {"type": "OBJECT", "properties": {
        "expected_revision": {"type": "INTEGER"},
    }, "required": ["expected_revision"]},
    "handler": adaptation_clear,
    "safety": {"risk": "high", "permission": "memory_governance", "confirmation": "required",
               "reversible": False, "verification": "observed"},
}
