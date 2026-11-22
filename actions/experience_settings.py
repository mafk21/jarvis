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
    if action == "set_background_surface":
        from memory.config_manager import save_background_surface

        surface = save_background_surface(str(params.get("surface") or ""))
        label = "top notch" if surface == "notch" else "bottom-right mini dock"
        return f"Background Mode will use the {label} from the next time it is opened."
    if action == "set_startup_view":
        from memory.config_manager import save_startup_view_preference

        view = save_startup_view_preference(str(params.get("view") or ""))
        label = "compact notch" if view == "notch" else "full interface"
        return f"JARVIS will start in the {label} on future launches."
    raise ValueError("action must be set_incognito, set_presentation, set_background_surface, or set_startup_view")


TOOL = {
    "name": "experience_settings",
    "description": (
        "Change presentation, Incognito, or the Background Mode surface only when the user explicitly asks. "
        "Use set_presentation for phrases such as 'switch to Sentinel', 'keep it clean', "
        "or 'you can swear around me'. Use set_incognito for explicit private-session requests. "
        "Use set_background_surface with surface=notch for a PixelNotch-style top-centre notch, "
        "or surface=corner for the established bottom-right mini dock. Use set_startup_view "
        "with view=notch or view=interface when the user asks how JARVIS should open on every launch. "
        "Never infer these preferences from casual language."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "set_presentation | set_incognito | set_background_surface | set_startup_view"},
            "personality": {"type": "STRING", "description": "command | inventor | sentinel | companion"},
            "language": {"type": "STRING", "description": "clean | casual | adult"},
            "enabled": {"type": "BOOLEAN", "description": "Incognito state for set_incognito"},
            "surface": {"type": "STRING", "description": "notch | corner"},
            "view": {"type": "STRING", "description": "notch | interface"},
        },
        "required": ["action"],
    },
    "run": run,
}
