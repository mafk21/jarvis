"""Process-local Incognito state.

Incognito intentionally resets to off on every launch. While active, new chat
history and memories are not persisted, memory recall/context is unavailable,
screen/camera capture is denied, and unsolicited proactive behavior is paused.
Existing data is never silently deleted.
"""
from __future__ import annotations

import threading

_LOCK = threading.RLock()
_ENABLED = False


def enabled() -> bool:
    with _LOCK:
        return _ENABLED


def set_enabled(value: bool) -> bool:
    global _ENABLED
    from core.adaptation_privacy import persistence_guard
    with persistence_guard(), _LOCK:
        _ENABLED = bool(value)
        return _ENABLED


def status() -> dict:
    active = enabled()
    return {
        "enabled": active,
        "temporary": True,
        "pauses": ["new memories", "saved chat", "memory recall", "screen and camera capture", "proactive help"],
    }


def deny_message(capability: str) -> str:
    return f"Incognito is active, so {capability} is paused. Turn Incognito off and try again."
