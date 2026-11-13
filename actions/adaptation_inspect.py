"""Read-only owner visibility into skill-specific adaptation."""
from __future__ import annotations

from datetime import datetime, timezone

from core.adaptation import AdaptationContext
from core.adaptation_governance import inspect
from core.adaptation_strategy import propose_strategy
from memory.adaptation_store import AdaptationStore


def adaptation_inspect(parameters=None, **_kwargs) -> str:
    p = parameters or {}
    action = str(p.get("action") or "list").strip().lower()
    store = AdaptationStore()
    if action == "list":
        report = inspect(store, skill=str(p.get("skill") or "").strip() or None)
        if not report["records"]:
            return f"Adaptation revision {report['revision']}: no matching learned strategies."
        lines = [f"Adaptation revision {report['revision']} ({len(report['records'])} record(s)):" ]
        for item in report["records"][:100]:
            lines.append(
                f"{item['id']} | {item['skill']} | {item['target']} | {item['status']} | "
                f"{item['kind']} | {item['strategy']}"
            )
        return "\n".join(lines)
    if action == "plan":
        skill = str(p.get("skill") or "").strip()
        if not skill:
            return "A skill is required to inspect an adaptation plan."
        snapshot = store.load()
        context = AdaptationContext(
            mode=str(p.get("mode") or "default"),
            project=str(p.get("project") or ""),
            device=str(p.get("device") or ""),
        )
        plan = propose_strategy(snapshot.records, skill=skill, context=context,
                                now=datetime.now(timezone.utc))
        selected = ", ".join(f"{item.id}: {item.strategy}" for item in plan.selected) or "none"
        return (
            f"Proposed read-only plan for {skill}: {selected}. "
            f"Excluded {len(plan.excluded)} record(s). Review required: {plan.requires_review}. "
            "This plan does not grant permission or execute anything."
        )
    return "Use list or plan."


TOOL = {
    "name": "adaptation_inspect",
    "description": "Inspect what JARVIS has learned for a skill or preview a read-only context-specific strategy plan. Never executes the plan or changes permissions.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": ["list", "plan"]},
            "skill": {"type": "STRING"}, "mode": {"type": "STRING"},
            "project": {"type": "STRING"}, "device": {"type": "STRING"},
        },
        "required": ["action"],
    },
    "handler": adaptation_inspect,
}
