"""Shared synchronization boundary for adaptive persistence privacy toggles."""
from __future__ import annotations
from contextlib import contextmanager
import threading

_LOCK = threading.RLock()

@contextmanager
def persistence_guard():
    with _LOCK:
        yield


def explicitly_enabled() -> bool:
    try:
        from core.session_privacy import enabled
        from memory.config_manager import load_api_keys
        return not enabled() and load_api_keys().get("adaptive_learning_enabled") is True
    except Exception:
        return False
