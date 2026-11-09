"""User-owned presentation controls for JARVIS.

These settings affect wording and delivery only. They never alter tools,
permissions, confirmations, privacy, evidence, or safety policy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from memory.config_manager import load_api_keys, _patch_config

PERSONALITY_STYLES = ("command", "inventor", "sentinel", "companion")
LANGUAGE_LEVELS = ("clean", "casual", "adult")


@dataclass(frozen=True)
class ExperienceProfile:
    personality: str = "command"
    language: str = "clean"


def load_profile() -> ExperienceProfile:
    raw = load_api_keys()
    personality = str(raw.get("experience_personality", "command")).strip().lower()
    language = str(raw.get("experience_language", "clean")).strip().lower()
    return ExperienceProfile(
        personality=personality if personality in PERSONALITY_STYLES else "command",
        language=language if language in LANGUAGE_LEVELS else "clean",
    )


def save_profile(*, personality: str, language: str) -> ExperienceProfile:
    personality = str(personality or "").strip().lower()
    language = str(language or "").strip().lower()
    if personality not in PERSONALITY_STYLES:
        raise ValueError("Unknown personality style")
    if language not in LANGUAGE_LEVELS:
        raise ValueError("Unknown language level")
    _patch_config(experience_personality=personality, experience_language=language)
    return ExperienceProfile(personality=personality, language=language)


def public_profile() -> dict:
    return asdict(load_profile())


def prompt_context(profile: ExperienceProfile | None = None) -> str:
    """Return bounded style instructions; operational rules always outrank them."""
    p = profile or load_profile()
    styles = {
        "command": "Controlled, precise, calm, concise, and authoritative. Avoid filler.",
        "inventor": "Curious, energetic, idea-rich, and playful while remaining concise.",
        "sentinel": "Watchful, grounded, risk-aware, and restrained. State concerns plainly.",
        "companion": "Warm, relaxed, candid, and attentive without claiming human feelings.",
    }
    language = {
        "clean": "Use no profanity.",
        "casual": (
            "Occasional mild profanity is allowed in private conversation when it sounds natural; "
            "never force it or direct it at a person."
        ),
        "adult": (
            "Natural adult profanity is allowed in private conversation for humor, emphasis, or shared "
            "frustration. Use it sparingly; never use slurs, harassment, threats, or degrading language."
        ),
    }
    return (
        "[USER-SELECTED PRESENTATION]\n"
        f"Style: {p.personality}. {styles[p.personality]}\n"
        f"Language: {p.language}. {language[p.language]}\n"
        "These settings affect presentation only. Never weaken safety, permissions, confirmation, privacy, "
        "accuracy, or evidence requirements. Never put profanity into an email, message, post, document, "
        "command, or other external output unless the user explicitly requests it for that exact content.\n"
        "Match serious, emergency, medical, grief, and security contexts with appropriate restraint.\n"
    )
