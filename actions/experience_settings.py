"""Explicit user controls for personality, language, and private sessions."""
from __future__ import annotations


def run(params: dict, context: dict | None = None) -> str:
    context = context or {}
    action = str(params.get("action") or "").strip().lower()
    player = context.get("player")
    if action == "set_incognito":
        from core.session_privacy import set_enabled
        active = set_enabled(bool(params.get("enabled", False)))
        callback = getattr(player, "on_incognito_change", None)
        if callable(callback):
            callback(active)
        return f"Incognito is {'on' if active else 'off'}; a fresh voice session is starting."
    if action == "set_presentation":
        from core.experience import load_profile, save_profile
        current = load_profile()
        profile = save_profile(
            personality=str(params.get("personality") or current.personality),
            language=str(params.get("language") or current.language),
        )
        # Presentation also requires a fresh model prompt. The same callback's
        # safe fresh-session behavior is appropriate; privacy state is unchanged.
        reconnect = getattr(player, "on_experience_change", None)
        if callable(reconnect):
            reconnect()
        return f"Presentation set to {profile.personality}, language {profile.language}."
    raise ValueError("action must be set_incognito or set_presentation")


TOOL = {
    "name": "experience_settings",
    "description": (
        "Change presentation or Incognito only when the user explicitly asks. "
        "Use set_presentation for phrases such as 'switch to Sentinel', 'keep it clean', "
        "or 'you can swear around me'. Use set_incognito for explicit private-session requests. "
        "Never infer these preferences from casual language."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "set_presentation | set_incognito"},
            "personality": {"type": "STRING", "description": "command | inventor | sentinel | companion"},
            "language": {"type": "STRING", "description": "clean | casual | adult"},
            "enabled": {"type": "BOOLEAN", "description": "Incognito state for set_incognito"},
        },
        "required": ["action"],
    },
    "run": run,
}
