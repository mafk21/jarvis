"""Durable least-privilege policy for unsolicited proactive behavior."""
from __future__ import annotations
import json, os, threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "config" / "proactive_permissions.json"
USAGE_PATH = Path(__file__).resolve().parent.parent / "config" / "proactive_usage.json"
_LOCK = threading.Lock()

@dataclass(frozen=True)
class ProactivePolicy:
    # Unsolicited monitoring must be explicitly enabled by the owner.
    enabled: bool = False
    use_memory: bool = False
    use_monitors: bool = False
    use_recent_conversation: bool = True
    quiet_start: int = 23
    quiet_end: int = 7
    daily_limit: int = 6
    allowed_topics: tuple[str, ...] = ()
    blocked_topics: tuple[str, ...] = ()
    minimum_urgency: str = "normal"


def load() -> ProactivePolicy:
    try:
        raw = json.loads(PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or int(raw.get("version", 1)) > 1:
            return ProactivePolicy(enabled=False)
        allowed = {k: raw[k] for k in asdict(ProactivePolicy()) if k in raw}
        return ProactivePolicy(**allowed)
    except FileNotFoundError:
        return ProactivePolicy()
    except (OSError, ValueError, TypeError):
        return ProactivePolicy(enabled=False)


def save(policy: ProactivePolicy) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = PATH.with_suffix(".tmp")
    temp.write_text(json.dumps({"version": 1, **asdict(policy)}, indent=2), encoding="utf-8")
    os.replace(temp, PATH)


def allowed(policy: ProactivePolicy | None = None, now: datetime | None = None, urgency: str = "normal") -> bool:
    p = policy or load(); current = now or datetime.now()
    try:
        from core.session_privacy import enabled as incognito_enabled
        if incognito_enabled():
            return False
        from core.gaming_mode import active as gaming_active
        if gaming_active():
            return False
    except Exception:
        pass
    if not p.enabled or p.daily_limit <= 0: return False
    levels = {"low": 0, "normal": 1, "high": 2, "critical": 3}
    if levels.get(str(urgency).lower(), 1) < levels.get(p.minimum_urgency, 1): return False
    try:
        usage = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
        count = int(usage.get("count", 0)) if usage.get("date") == current.date().isoformat() else 0
    except (OSError, ValueError, TypeError):
        count = 0
    if count >= p.daily_limit: return False
    hour = current.hour
    if p.quiet_start > p.quiet_end:
        return not (hour >= p.quiet_start or hour < p.quiet_end)
    return not (p.quiet_start <= hour < p.quiet_end)


def record(now: datetime | None = None) -> None:
    current = now or datetime.now(); day = current.date().isoformat()
    with _LOCK:
        try: usage = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError): usage = {}
        count = int(usage.get("count", 0)) + 1 if usage.get("date") == day else 1
        events = list(usage.get("events", [])) if isinstance(usage.get("events"), list) else []
        events.append({"at": current.astimezone().isoformat(timespec="seconds"), "event": "suggestion delivered"})
        events = events[-100:]
        USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = USAGE_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps({"date": day, "count": count, "events": events}), encoding="utf-8")
        os.replace(temp, USAGE_PATH)


def history() -> list[dict]:
    try:
        raw = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
        events = raw.get("events", [])
        return list(reversed(events[-100:])) if isinstance(events, list) else []
    except (OSError, ValueError, TypeError):
        return []


def clear_history() -> None:
    try:
        USAGE_PATH.unlink()
    except FileNotFoundError:
        pass


def filter_context(memory: dict, monitors: list[str] | None, recent: list[str] | None,
                   policy: ProactivePolicy | None = None):
    p = policy or load()
    scoped_monitors = monitors if p.use_monitors else None
    if scoped_monitors:
        blocked = {topic.casefold() for topic in p.blocked_topics}
        allowed_topics = {topic.casefold() for topic in p.allowed_topics}
        scoped_monitors = [topic for topic in scoped_monitors if topic.casefold() not in blocked and
                           (not allowed_topics or topic.casefold() in allowed_topics)]
    return (memory if p.use_memory else {}, scoped_monitors,
            recent if p.use_recent_conversation else None)
