"""Fail-closed screen/camera policy and local metadata-only access history."""
from __future__ import annotations

import json
import os
import platform
import threading
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
POLICY_PATH = BASE / "config" / "vision_policy.json"
AUDIT_PATH = BASE / "memory" / "access_history.jsonl"
_LOCK = threading.RLock()
_MAX_AUDIT_BYTES = 512_000
_DEFAULT_BLOCKED = (
    "1password", "bitwarden", "keepass", "lastpass", "dashlane",
    "password", "credential", "authenticator", "wallet", "seed phrase",
)


def _read_policy() -> dict:
    try:
        raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or int(raw.get("version", 1)) > 1:
            raise ValueError("unsupported policy")
        return raw
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError):
        return {"deny_all": True}


def get_policy() -> dict:
    raw = _read_policy()
    custom = raw.get("blocked_apps", [])
    if not isinstance(custom, list):
        custom = []
    return {
        "deny_all": bool(raw.get("deny_all", False)),
        "block_sensitive_defaults": bool(raw.get("block_sensitive_defaults", True)),
        "blocked_apps": [str(x).strip()[:120] for x in custom if str(x).strip()][:100],
    }


def save_policy(*, deny_all: bool, block_sensitive_defaults: bool, blocked_apps: list[str]) -> dict:
    policy = {
        "version": 1,
        "deny_all": bool(deny_all),
        "block_sensitive_defaults": bool(block_sensitive_defaults),
        "blocked_apps": [str(x).strip()[:120] for x in (blocked_apps or []) if str(x).strip()][:100],
    }
    POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = POLICY_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(policy, indent=2), encoding="utf-8")
    os.replace(temp, POLICY_PATH)
    return get_policy()


def active_application() -> str:
    """Best-effort executable/title identity; empty means unknown."""
    if platform.system() != "Windows":
        return ""
    try:
        import ctypes
        from ctypes import wintypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        executable = ""
        if handle:
            try:
                size = wintypes.DWORD(1024)
                buf = ctypes.create_unicode_buffer(size.value)
                if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    executable = Path(buf.value).name
            finally:
                kernel32.CloseHandle(handle)
        length = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
        return " | ".join(x for x in (executable, title) if x)[:300]
    except Exception:
        return ""


def _audit(capability: str, allowed: bool, application: str, reason: str, cloud: bool) -> None:
    row = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "capability": capability,
        "allowed": bool(allowed),
        "application": application[:300],
        "reason": reason[:200],
        "cloud_possible": bool(cloud and allowed),
        "content_stored": False,
    }
    with _LOCK:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        if AUDIT_PATH.exists() and AUDIT_PATH.stat().st_size > _MAX_AUDIT_BYTES:
            AUDIT_PATH.replace(AUDIT_PATH.with_suffix(".jsonl.1"))
        with AUDIT_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def authorize(capability: str, *, cloud_possible: bool = True) -> tuple[bool, str]:
    from core.session_privacy import enabled as incognito_enabled
    app = active_application()
    if incognito_enabled():
        reason = "Incognito is active"
        _audit(capability, False, app, reason, cloud_possible)
        return False, reason
    policy = get_policy()
    if policy["deny_all"]:
        reason = "Screen and camera access is disabled"
        _audit(capability, False, app, reason, cloud_possible)
        return False, reason
    haystack = app.casefold()
    patterns = list(policy["blocked_apps"])
    if policy["block_sensitive_defaults"]:
        patterns += list(_DEFAULT_BLOCKED)
    match = next((p for p in patterns if p.casefold() in haystack), "") if haystack else ""
    if match:
        reason = f"The active application matches protected rule '{match}'"
        _audit(capability, False, app, reason, cloud_possible)
        return False, reason
    _audit(capability, True, app, "User-requested access", cloud_possible)
    return True, "allowed"


def history(limit: int = 100) -> list[dict]:
    try:
        lines = AUDIT_PATH.read_text(encoding="utf-8").splitlines()[-max(1, min(500, int(limit))):]
        rows = []
        for line in reversed(lines):
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    rows.append(item)
            except ValueError:
                continue
        return rows
    except OSError:
        return []


def clear_history() -> None:
    with _LOCK:
        try:
            AUDIT_PATH.unlink()
        except FileNotFoundError:
            pass
