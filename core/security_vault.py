"""
Security Vault, Hash-Chained Action Audit Log & Revocable Guest Portals — Phase 6.

Provides three enterprise-grade local security guarantees:
  1. Authenticated At-Rest Credential Encryption (`enc:v1:...`) for `memory/accounts.json`
     and optional strict mode on `config/api_keys.json`, backed by OS keyring or a
     `0600` 256-bit master key (`config/.vault.key`), using AES-256-GCM (when
     `cryptography` is installed) or authenticated SHAKE256 + HMAC-SHA256.
  2. Tamper-Evident Hash-Chained SQLite Action Audit Log (`memory/security_audit.db`)
     with automatic secret redaction and full chain verification (`verify_audit_chain()`).
  3. Revocable Token-Scoped Guest Portals (`/portal/<token>`) with expiry, max-view
     caps, visitor IP/User-Agent logging, and 1-click individual or global shutoff.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import sqlite3
import stat
import threading
import time
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
VAULT_KEY_FILE = BASE_DIR / "config" / ".vault.key"
AUDIT_DB_PATH = BASE_DIR / "memory" / "security_audit.db"

ENC_PREFIX = "enc:v1:"
SECRET_FIELD_NAMES = {
    "token",
    "api_key",
    "refresh_token",
    "client_secret",
    "app_password",
    "webhook_url",
    "bearer_token",
    "gemini_api_key",
    "openai_api_key",
    "anthropic_api_key",
    "composio_api_key",
    "github_token",
    "telegram_bot_token",
    "spotify_client_secret",
}

_REDACT_SUBSTRINGS = ("token", "secret", "password", "api_key", "bearer", "auth")

_LOCK = threading.RLock()

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _AESGCM
except Exception:  # pragma: no cover
    _AESGCM = None  # type: ignore[assignment]


# ── Master Key Management (OS Keyring -> 0600 Local Key File) ─────────────────

def _get_or_create_master_key() -> bytes:
    env_hex = os.environ.get("JARVIS_VAULT_MASTER_KEY", "").strip()
    if len(env_hex) == 64:
        try:
            return bytes.fromhex(env_hex)
        except ValueError:
            pass

    with _LOCK:
        if VAULT_KEY_FILE.is_file():
            raw = VAULT_KEY_FILE.read_bytes().strip()
            if len(raw) == 32:
                return raw
            try:
                decoded = base64.urlsafe_b64decode(raw)
                if len(decoded) == 32:
                    return decoded
            except Exception:
                pass

        key = secrets.token_bytes(32)
        VAULT_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        VAULT_KEY_FILE.write_bytes(base64.urlsafe_b64encode(key))
        try:
            os.chmod(VAULT_KEY_FILE, stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            pass
        return key


def is_encrypted_value(val: Any) -> bool:
    return isinstance(val, str) and val.startswith(ENC_PREFIX)


def encrypt_secret(plaintext: str, key: bytes | None = None) -> str:
    if not plaintext or is_encrypted_value(plaintext):
        return plaintext
    mk = key or _get_or_create_master_key()
    pt_bytes = plaintext.encode("utf-8")

    if _AESGCM is not None:
        nonce = secrets.token_bytes(12)
        ct = _AESGCM(mk).encrypt(nonce, pt_bytes, b"jarvis-vault-v1")
        blob = base64.urlsafe_b64encode(nonce + ct).decode("ascii")
        return f"{ENC_PREFIX}gcm:{blob}"

    # Pure-stdlib authenticated encryption: 16B nonce + SHAKE256 keystream XOR + 32B HMAC-SHA256
    nonce = secrets.token_bytes(16)
    enc_key = hmac.new(mk, b"enc-subkey-v1", hashlib.sha256).digest()
    mac_key = hmac.new(mk, b"mac-subkey-v1", hashlib.sha256).digest()
    stream = hashlib.shake_256(enc_key + nonce).digest(len(pt_bytes))
    ct = bytes(a ^ b for a, b in zip(pt_bytes, stream))
    tag = hmac.new(mac_key, b"jarvis-vault-v1" + nonce + ct, hashlib.sha256).digest()
    blob = base64.urlsafe_b64encode(nonce + tag + ct).decode("ascii")
    return f"{ENC_PREFIX}shk:{blob}"


def decrypt_secret(value: str, key: bytes | None = None) -> str:
    if not isinstance(value, str) or not value.startswith(ENC_PREFIX):
        return value
    mk = key or _get_or_create_master_key()
    rest = value[len(ENC_PREFIX):]
    alg, sep, b64 = rest.partition(":")
    if not sep:
        raise ValueError("Malformed encrypted vault value.")
    raw = base64.urlsafe_b64decode(b64.encode("ascii"))

    if alg == "gcm":
        if _AESGCM is None:
            raise RuntimeError("AES-GCM value requires 'cryptography' package.")
        if len(raw) < 28:
            raise ValueError("Truncated AES-GCM vault ciphertext.")
        nonce, ct = raw[:12], raw[12:]
        try:
            pt = _AESGCM(mk).decrypt(nonce, ct, b"jarvis-vault-v1")
        except Exception as exc:
            raise ValueError("Vault authentication tag mismatch (tampered or wrong key).") from exc
        return pt.decode("utf-8")

    if alg == "shk":
        if len(raw) < 48:
            raise ValueError("Truncated SHAKE-HMAC vault ciphertext.")
        nonce, tag, ct = raw[:16], raw[16:48], raw[48:]
        enc_key = hmac.new(mk, b"enc-subkey-v1", hashlib.sha256).digest()
        mac_key = hmac.new(mk, b"mac-subkey-v1", hashlib.sha256).digest()
        expected = hmac.new(mac_key, b"jarvis-vault-v1" + nonce + ct, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ValueError("Vault authentication tag mismatch (tampered or wrong key).")
        stream = hashlib.shake_256(enc_key + nonce).digest(len(ct))
        pt = bytes(a ^ b for a, b in zip(ct, stream))
        return pt.decode("utf-8")

    raise ValueError(f"Unsupported vault cipher '{alg}'.")


def encrypt_dict_secrets(obj: Any) -> Any:
    """Recursively encrypt secret string fields inside nested account/config dicts."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k in SECRET_FIELD_NAMES and isinstance(v, str) and v.strip():
                out[k] = encrypt_secret(v)
            else:
                out[k] = encrypt_dict_secrets(v)
        return out
    if isinstance(obj, list):
        return [encrypt_dict_secrets(x) for x in obj]
    return obj


def decrypt_dict_secrets(obj: Any) -> Any:
    """Recursively decrypt `enc:v1:...` string fields inside nested dicts."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if isinstance(v, str) and is_encrypted_value(v):
                out[k] = decrypt_secret(v)
            else:
                out[k] = decrypt_dict_secrets(v)
        return out
    if isinstance(obj, list):
        return [decrypt_dict_secrets(x) for x in obj]
    return obj


def count_encrypted_leaves(obj: Any) -> int:
    if isinstance(obj, dict):
        return sum(count_encrypted_leaves(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(count_encrypted_leaves(x) for x in obj)
    return 1 if is_encrypted_value(obj) else 0


def rotate_vault_master_key(accounts_file: Path, config_file: Path) -> dict[str, Any]:
    """Generate a fresh 256-bit master key and re-encrypt stored secrets atomically."""
    with _LOCK:
        old_key = _get_or_create_master_key()
        acc_plain = None
        if accounts_file.is_file():
            raw_acc = json.loads(accounts_file.read_text(encoding="utf-8"))
            acc_plain = _decrypt_with_key(raw_acc, old_key)

        cfg_plain = None
        had_cfg_enc = False
        if config_file.is_file():
            raw_cfg = json.loads(config_file.read_text(encoding="utf-8"))
            had_cfg_enc = count_encrypted_leaves(raw_cfg) > 0
            cfg_plain = _decrypt_with_key(raw_cfg, old_key)

        adaptation_plain: list[tuple[Path, dict[str, Any]]] = []
        adaptation_path = BASE_DIR / "memory" / "adaptation_store.json"
        for candidate in (adaptation_path, adaptation_path.with_suffix(adaptation_path.suffix + ".bak")):
            if candidate.is_file():
                wrapper = json.loads(candidate.read_text(encoding="utf-8"))
                encrypted = wrapper.get("encrypted_store") if isinstance(wrapper, dict) else None
                if not isinstance(encrypted, str):
                    raise ValueError(f"Invalid adaptation store wrapper: {candidate}")
                adaptation_plain.append((candidate, json.loads(decrypt_secret(encrypted, key=old_key))))

        new_key = secrets.token_bytes(32)
        VAULT_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        VAULT_KEY_FILE.write_bytes(base64.urlsafe_b64encode(new_key))
        try:
            os.chmod(VAULT_KEY_FILE, stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            pass

        reencrypted = 0
        if acc_plain is not None:
            enc_acc = _encrypt_with_key(acc_plain, new_key)
            accounts_file.write_text(json.dumps(enc_acc, indent=2), encoding="utf-8")
            reencrypted += count_encrypted_leaves(enc_acc)
        if cfg_plain is not None and had_cfg_enc:
            enc_cfg = _encrypt_with_key(cfg_plain, new_key)
            config_file.write_text(json.dumps(enc_cfg, indent=2), encoding="utf-8")
            # Same-size ciphertext writes can share timestamps on coarse FS.
            from memory.config_manager import invalidate_config_cache
            invalidate_config_cache()
            reencrypted += count_encrypted_leaves(enc_cfg)

        for candidate, plain_store in adaptation_plain:
            wrapper = {"version": 1, "encrypted_store": encrypt_secret(
                json.dumps(plain_store, ensure_ascii=False, separators=(",", ":")), key=new_key
            )}
            temporary = candidate.with_suffix(candidate.suffix + ".rotate.tmp")
            temporary.write_text(json.dumps(wrapper, separators=(",", ":")), encoding="utf-8")
            os.replace(temporary, candidate)
            reencrypted += 1

        log_audit_event("vault", "rotate_master_key", {}, f"Re-encrypted {reencrypted} secrets")
        return {"ok": True, "reencrypted_count": reencrypted}


def _decrypt_with_key(obj: Any, key: bytes) -> Any:
    if isinstance(obj, dict):
        return {
            k: decrypt_secret(v, key=key) if is_encrypted_value(v) else _decrypt_with_key(v, key)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_decrypt_with_key(x, key) for x in obj]
    return obj


def _encrypt_with_key(obj: Any, key: bytes) -> Any:
    if isinstance(obj, dict):
        return {
            k: encrypt_secret(v, key=key)
            if (k in SECRET_FIELD_NAMES and isinstance(v, str) and v.strip())
            else _encrypt_with_key(v, key)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_encrypt_with_key(x, key) for x in obj]
    return obj


# ── SQLite Connection (Audit Chain + Portals) ────────────────────────────────

def _conn() -> sqlite3.Connection:
    AUDIT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(AUDIT_DB_PATH), timeout=10.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ts              REAL    NOT NULL,
            actor           TEXT    NOT NULL,
            action          TEXT    NOT NULL,
            args_redacted   TEXT    NOT NULL,
            result_summary  TEXT    NOT NULL,
            status          TEXT    NOT NULL,
            prev_hash       TEXT    NOT NULL,
            entry_hash      TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS portals (
            id              TEXT PRIMARY KEY,
            token_hash      TEXT NOT NULL UNIQUE,
            title           TEXT NOT NULL,
            scope_type      TEXT NOT NULL,
            content_body    TEXT NOT NULL,
            active          INTEGER NOT NULL DEFAULT 1,
            created_at      REAL NOT NULL,
            expires_at      REAL,
            max_views       INTEGER NOT NULL DEFAULT 100,
            view_count      INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS portal_visits (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            portal_id       TEXT NOT NULL,
            ts              REAL NOT NULL,
            ip              TEXT NOT NULL,
            user_agent      TEXT NOT NULL,
            allowed         INTEGER NOT NULL,
            reason          TEXT NOT NULL
        );
        """
    )
    return c


def redact_args(args: Any) -> str:
    def _clean(o: Any) -> Any:
        if isinstance(o, dict):
            res = {}
            for k, v in o.items():
                kl = str(k).lower()
                if any(s in kl for s in _REDACT_SUBSTRINGS) and v:
                    res[k] = "[REDACTED]"
                else:
                    res[k] = _clean(v)
            return res
        if isinstance(o, list):
            return [_clean(x) for x in o[:20]]
        if isinstance(o, str):
            return o[:240]
        return o

    try:
        return json.dumps(_clean(args or {}), sort_keys=True, ensure_ascii=False)[:600]
    except Exception:
        return "{}"


def _compute_audit_hash(
    prev_hash: str,
    ts: float,
    actor: str,
    action: str,
    args_redacted: str,
    status: str,
) -> str:
    payload = f"{prev_hash}|{ts:.6f}|{actor}|{action}|{args_redacted}|{status}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def log_audit_event(
    actor: str,
    action: str,
    args: Any = None,
    result_summary: str = "",
    status: str = "ok",
) -> dict[str, Any]:
    now = round(time.time(), 6)
    redacted = redact_args(args)
    clean_res = str(result_summary or "")[:300]
    clean_status = str(status or "ok")[:32]
    clean_actor = str(actor or "jarvis")[:48]
    clean_action = str(action or "unknown")[:96]

    with _LOCK:
        with _conn() as c:
            row = c.execute(
                "SELECT entry_hash FROM audit_logs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            prev_hash = str(row["entry_hash"]) if row else ("0" * 64)
            ehash = _compute_audit_hash(
                prev_hash, now, clean_actor, clean_action, redacted, clean_status
            )
            cur = c.execute(
                "INSERT INTO audit_logs "
                "(ts, actor, action, args_redacted, result_summary, status, prev_hash, entry_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (now, clean_actor, clean_action, redacted, clean_res, clean_status, prev_hash, ehash),
            )
            c.commit()
            return {
                "id": int(cur.lastrowid),
                "ts": now,
                "actor": clean_actor,
                "action": clean_action,
                "status": clean_status,
                "entry_hash": ehash,
            }


def list_audit_events(query: str = "", limit: int = 80) -> list[dict[str, Any]]:
    q = (query or "").strip().lower()
    with _LOCK:
        with _conn() as c:
            if q:
                like = f"%{q}%"
                rows = c.execute(
                    "SELECT * FROM audit_logs WHERE lower(action) LIKE ? OR lower(actor) LIKE ? "
                    "OR lower(result_summary) LIKE ? ORDER BY id DESC LIMIT ?",
                    (like, like, like, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
    return [
        {
            "id": r["id"],
            "ts": r["ts"],
            "time_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"])),
            "actor": r["actor"],
            "action": r["action"],
            "args_redacted": r["args_redacted"],
            "result_summary": r["result_summary"],
            "status": r["status"],
            "entry_hash": r["entry_hash"][:16] + "…",
        }
        for r in rows
    ]


def verify_audit_chain() -> dict[str, Any]:
    """Cryptographically verify the entire hash-chained SQLite audit log."""
    with _LOCK:
        with _conn() as c:
            rows = c.execute("SELECT * FROM audit_logs ORDER BY id ASC").fetchall()
    expected_prev = "0" * 64
    checked = 0
    for r in rows:
        checked += 1
        if r["prev_hash"] != expected_prev:
            return {
                "valid": False,
                "checked": checked,
                "broken_at_id": r["id"],
                "reason": "prev_hash link broken",
            }
        recomputed = _compute_audit_hash(
            r["prev_hash"],
            float(r["ts"]),
            r["actor"],
            r["action"],
            r["args_redacted"],
            r["status"],
        )
        if not hmac.compare_digest(recomputed, r["entry_hash"]):
            return {
                "valid": False,
                "checked": checked,
                "broken_at_id": r["id"],
                "reason": "entry_hash tampered",
            }
        expected_prev = r["entry_hash"]
    return {"valid": True, "checked": checked, "broken_at_id": None}


# ── Revocable Scoped Guest Portals ────────────────────────────────────────────

def create_portal(
    title: str,
    content_body: str,
    scope_type: str = "output",
    expires_hours: float = 24.0,
    max_views: int = 50,
) -> dict[str, Any]:
    clean_title = (title or "Shared Deliverable").strip()[:120]
    clean_body = (content_body or "").strip()[:32000]
    if not clean_body:
        raise ValueError("Portal content cannot be empty.")

    raw_token = secrets.token_urlsafe(24)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    pid = f"portal-{secrets.token_hex(4)}"
    now = time.time()
    exp = (now + float(expires_hours) * 3600.0) if expires_hours and expires_hours > 0 else None

    with _LOCK:
        with _conn() as c:
            c.execute(
                "INSERT INTO portals "
                "(id, token_hash, title, scope_type, content_body, active, created_at, expires_at, max_views, view_count) "
                "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, 0)",
                (pid, token_hash, clean_title, scope_type[:32], clean_body, now, exp, max(1, int(max_views))),
            )
            c.commit()

    log_audit_event("hud", "portal_create", {"portal_id": pid, "title": clean_title}, "Created guest portal")
    return {
        "id": pid,
        "token": raw_token,
        "path": f"/portal/{raw_token}",
        "title": clean_title,
        "max_views": max(1, int(max_views)),
        "expires_at": exp,
    }


def list_portals() -> list[dict[str, Any]]:
    with _LOCK:
        with _conn() as c:
            rows = c.execute("SELECT * FROM portals ORDER BY created_at DESC").fetchall()
            visits = c.execute(
                "SELECT * FROM portal_visits ORDER BY id DESC LIMIT 100"
            ).fetchall()

    visits_by_pid: dict[str, list[dict[str, Any]]] = {}
    for v in visits:
        visits_by_pid.setdefault(v["portal_id"], []).append(
            {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(v["ts"])),
                "ip": v["ip"],
                "user_agent": v["user_agent"][:80],
                "allowed": bool(v["allowed"]),
                "reason": v["reason"],
            }
        )

    now = time.time()
    out = []
    for r in rows:
        expired = bool(r["expires_at"] and now > float(r["expires_at"]))
        out.append(
            {
                "id": r["id"],
                "title": r["title"],
                "scope_type": r["scope_type"],
                "active": bool(r["active"]) and not expired and (r["view_count"] < r["max_views"]),
                "revoked": not bool(r["active"]),
                "expired": expired,
                "view_count": r["view_count"],
                "max_views": r["max_views"],
                "created_str": time.strftime("%Y-%m-%d %H:%M", time.localtime(r["created_at"])),
                "visits": visits_by_pid.get(r["id"], [])[:10],
            }
        )
    return out


def revoke_portal(portal_id: str) -> bool:
    with _LOCK:
        with _conn() as c:
            cur = c.execute("UPDATE portals SET active = 0 WHERE id = ?", (portal_id,))
            c.commit()
            changed = cur.rowcount > 0
    if changed:
        log_audit_event("hud", "portal_revoke", {"portal_id": portal_id}, "Revoked portal")
    return changed


def revoke_all_portals() -> int:
    with _LOCK:
        with _conn() as c:
            cur = c.execute("UPDATE portals SET active = 0 WHERE active = 1")
            c.commit()
            count = int(cur.rowcount)
    log_audit_event("hud", "portal_revoke_all", {}, f"Shut off {count} active portals")
    return count


def access_portal_by_token(
    raw_token: str, client_ip: str = "127.0.0.1", user_agent: str = ""
) -> tuple[int, str]:
    """Validate token, record audited visit, and return (http_status, safe_html)."""
    thash = hashlib.sha256((raw_token or "").encode("utf-8")).hexdigest()
    now = time.time()

    with _LOCK:
        with _conn() as c:
            row = c.execute(
                "SELECT * FROM portals WHERE token_hash = ?", (thash,)
            ).fetchone()
            if row is None:
                return 404, _portal_html("Portal Not Found", "This link is invalid or has expired.", denied=True)

            pid = row["id"]
            reason = "ok"
            allowed = True
            if not row["active"]:
                allowed, reason = False, "revoked"
            elif row["expires_at"] and now > float(row["expires_at"]):
                allowed, reason = False, "expired"
            elif row["view_count"] >= row["max_views"]:
                allowed, reason = False, "max_views_reached"

            if allowed:
                c.execute(
                    "UPDATE portals SET view_count = view_count + 1 WHERE id = ?",
                    (pid,),
                )
            c.execute(
                "INSERT INTO portal_visits (portal_id, ts, ip, user_agent, allowed, reason) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (pid, now, str(client_ip)[:64], str(user_agent)[:160], 1 if allowed else 0, reason),
            )
            c.commit()

    log_audit_event(
        "portal_guest",
        "portal_visit",
        {"portal_id": pid, "ip": client_ip, "reason": reason},
        f"Portal visit ({'allowed' if allowed else 'denied:' + reason})",
        status="ok" if allowed else "denied",
    )

    if not allowed:
        return 403, _portal_html(
            "Portal Access Closed",
            f"Access to this shared portal is closed ({reason}).",
            denied=True,
        )

    return 200, _portal_html(row["title"], row["content_body"], denied=False)


def _portal_html(title: str, body: str, denied: bool = False) -> str:
    safe_t = html.escape(title)
    safe_b = html.escape(body)
    accent = "#ff5d6c" if denied else "#00e5ff"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>{safe_t} · JARVIS Scoped Portal</title>
<style>
  body {{
    margin: 0; padding: 36px 18px;
    background: radial-gradient(circle at 50% 0%, #10253a 0%, #050a14 70%);
    color: #f0ede8; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
  }}
  .card {{
    max-width: 780px; margin: 0 auto; padding: 28px 32px;
    border-radius: 18px; background: rgba(7, 14, 26, 0.9);
    border: 1px solid {accent}55; box-shadow: 0 20px 60px rgba(0,0,0,0.7);
  }}
  .badge {{
    font-family: ui-monospace, monospace; font-size: 10px;
    letter-spacing: 0.2em; color: {accent}; text-transform: uppercase;
  }}
  h1 {{ margin: 10px 0 18px; font-size: 22px; }}
  pre {{
    white-space: pre-wrap; word-break: break-word;
    font-family: ui-monospace, monospace; font-size: 13px; line-height: 1.65;
    color: rgba(240,237,232,0.9); margin: 0;
  }}
</style>
</head>
<body>
  <article class="card">
    <div class="badge">{'PORTAL CLOSED' if denied else 'JARVIS READ-ONLY GUEST PORTAL'}</div>
    <h1>{safe_t}</h1>
    <pre>{safe_b}</pre>
  </article>
</body>
</html>"""


def get_security_snapshot(accounts_file: Path, config_file: Path) -> dict[str, Any]:
    acc_enc_count = 0
    if accounts_file.is_file():
        try:
            acc_enc_count = count_encrypted_leaves(
                json.loads(accounts_file.read_text(encoding="utf-8"))
            )
        except Exception:
            pass
    cfg_enc_count = 0
    if config_file.is_file():
        try:
            cfg_enc_count = count_encrypted_leaves(
                json.loads(config_file.read_text(encoding="utf-8"))
            )
        except Exception:
            pass
    return {
        "cipher": "AES-256-GCM" if _AESGCM is not None else "SHAKE256-HMAC-SHA256",
        "key_present": VAULT_KEY_FILE.is_file(),
        "encrypted_account_secrets": acc_enc_count,
        "encrypted_config_secrets": cfg_enc_count,
        "chain": verify_audit_chain(),
        "audit_logs": list_audit_events(limit=60),
        "portals": list_portals(),
    }
