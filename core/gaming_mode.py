"""Automatic, user-owned Gaming Mode detection.

Gaming Mode pauses unsolicited proactive work while keeping direct wake, typed,
and voice requests available. Detection is local and stores no activity history.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PATH = BASE / "config" / "gaming_mode.json"
_DEFAULT_GAMES = ("minecraft", "terraria", "eldenring", "elden ring")
_LOCK = threading.RLock()
_ACTIVE = False
_ACTIVE_APP = ""


def get_policy() -> dict:
    try:
        raw = json.loads(PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or int(raw.get("version", 1)) > 1:
            raise ValueError
    except FileNotFoundError:
        raw = {}
    except (OSError, ValueError, TypeError):
        return {"enabled": False, "games": [], "corrupt": True}
    games = raw.get("games", list(_DEFAULT_GAMES))
    if not isinstance(games, list):
        games = []
    return {"enabled": bool(raw.get("enabled", False)), "games": [str(x).strip()[:100] for x in games if str(x).strip()][:100]}


def save_policy(enabled: bool, games: list[str]) -> dict:
    data = {"version": 1, "enabled": bool(enabled), "games": [str(x).strip()[:100] for x in games if str(x).strip()][:100]}
    PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(temp, PATH)
    return get_policy()


def _process_names() -> list[str]:
    try:
        import psutil  # type: ignore
        return [str(p.info.get("name") or "") for p in psutil.process_iter(["name"])]
    except Exception:
        pass
    if os.name == "posix":
        try:
            names = []
            for process_dir in Path("/proc").iterdir():
                comm = process_dir / "comm"
                if process_dir.name.isdigit() and comm.exists():
                    try:
                        names.append(comm.read_text(encoding="utf-8").strip())
                    except OSError:
                        pass
            return names
        except OSError:
            pass
    return []


def refresh(processes: list[str] | None = None) -> dict:
    global _ACTIVE, _ACTIVE_APP
    policy = get_policy()
    active, matched = False, ""
    if policy["enabled"]:
        names = processes if processes is not None else _process_names()
        for name in names:
            low = str(name).casefold()
            match = next((g for g in policy["games"] if g.casefold() in low), "")
            if match:
                active, matched = True, str(name)[:150]
                break
    with _LOCK:
        _ACTIVE, _ACTIVE_APP = active, matched
    return status()


def status() -> dict:
    with _LOCK:
        return {"active": _ACTIVE, "application": _ACTIVE_APP, "policy": get_policy()}


def active() -> bool:
    with _LOCK:
        return _ACTIVE


class GamingModeMonitor:
    def __init__(self, on_change=None, interval: float = 5.0):
        self.on_change = on_change
        self.interval = max(2.0, float(interval))
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="gaming-mode", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        previous = None
        while not self._stop.is_set():
            current = refresh()
            state = bool(current["active"])
            if state != previous and callable(self.on_change):
                try:
                    self.on_change(current)
                except Exception:
                    pass
            previous = state
            self._stop.wait(self.interval)
