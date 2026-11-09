"""
memory/timeline.py — Unified "Brain" & Forever Conversation Timeline (Phase 1).

Provides local-first, zero-cloud-lock-in persistence for:
  1. Forever Conversation Timeline (`timeline_messages` + compressed `timeline_epochs`)
     spanning Live Voice, Desktop Text, and Telegram/Omnichannel across restarts.
  2. Brain Knowledge Files (`brain_files` + `brain_chunks`) for drag-and-drop
     reference documents, notes, PDFs, Markdown, CSV, and code.
  3. Generated Outputs (`brain_outputs`) archiving every research report,
     briefing, digest, and artifact JARVIS creates (`show_content`).
  4. Unified sub-millisecond recall, 1-click deletion, and full JSON export/import.
"""

from __future__ import annotations

import base64
from datetime import datetime
import mimetypes
from pathlib import Path
import re
import sqlite3
import sys
import threading
import time
from typing import Any

from memory import config_manager as cfg
from memory import memory_manager as mm


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


DB_PATH = _base_dir() / "memory" / "brain.db"
KNOWLEDGE_DIR = _base_dir() / "memory" / "knowledge_files"

_db_lock = threading.Lock()
EPOCH_ROLLUP_THRESHOLD = 32
EPOCH_BATCH_SIZE = 24


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=15.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS timeline_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            speaker TEXT NOT NULL DEFAULT '',
            channel TEXT NOT NULL DEFAULT 'voice',
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            ts_epoch REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_timeline_ts ON timeline_messages(ts_epoch DESC);

        CREATE TABLE IF NOT EXISTS timeline_epochs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_msg_id INTEGER NOT NULL,
            end_msg_id INTEGER NOT NULL,
            summary TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS brain_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            stored_path TEXT NOT NULL DEFAULT '',
            mime_type TEXT NOT NULL DEFAULT 'text/plain',
            size_bytes INTEGER NOT NULL DEFAULT 0,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            preview TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS brain_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL REFERENCES brain_files(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_brain_chunks_file ON brain_chunks(file_id);

        CREATE TABLE IF NOT EXISTS brain_outputs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'output',
            content TEXT NOT NULL,
            pinned INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            ts_epoch REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_brain_outputs_ts ON brain_outputs(pinned DESC, ts_epoch DESC);
        """
    )


# ── 1. Forever Conversation Timeline ──────────────────────────────────────────

def append_turn(
    role: str,
    content: str,
    *,
    speaker: str = "",
    channel: str = "voice",
    force: bool = False,
) -> int | None:
    """Append a user or assistant turn to the Forever Timeline."""
    text = (content or "").strip()
    if not text:
        return None
    try:
        from core.session_privacy import enabled as incognito_enabled
        if incognito_enabled():
            return None
    except Exception:
        pass
    if not force and not cfg.get_timeline_persistence_enabled():
        return None

    norm_role = (role or "user").strip().lower()
    if norm_role not in ("user", "jarvis", "sys", "tool"):
        norm_role = "jarvis"
    spk = speaker.strip() or ("You" if norm_role == "user" else cfg.get_assistant_name())
    ch = (channel or "voice").strip().lower()
    now_ts = time.time()
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _db_lock:
        conn = _connect()
        try:
            # Guard against duplicate consecutive logging within 2.5 seconds
            last = conn.execute(
                "SELECT id, role, content, ts_epoch FROM timeline_messages ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if (
                last is not None
                and last["role"] == norm_role
                and last["content"] == text
                and (now_ts - float(last["ts_epoch"])) < 2.5
            ):
                return int(last["id"])

            cur = conn.execute(
                """
                INSERT INTO timeline_messages (role, speaker, channel, content, created_at, ts_epoch)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (norm_role, spk, ch, text[:8000], now_iso, now_ts),
            )
            msg_id = int(cur.lastrowid)
            _maybe_rollup_epochs(conn)
            conn.commit()
            return msg_id
        finally:
            conn.close()


def _maybe_rollup_epochs(conn: sqlite3.Connection) -> None:
    """Compress older stretches of conversation into searchable epoch digests."""
    last_ep = conn.execute(
        "SELECT COALESCE(MAX(end_msg_id), 0) AS max_end FROM timeline_epochs"
    ).fetchone()
    after_id = int(last_ep["max_end"]) if last_ep else 0
    rows = conn.execute(
        """
        SELECT id, role, speaker, channel, content, created_at
        FROM timeline_messages
        WHERE id > ? AND role IN ('user', 'jarvis')
        ORDER BY id ASC
        """,
        (after_id,),
    ).fetchall()
    if len(rows) < EPOCH_ROLLUP_THRESHOLD:
        return

    batch = rows[:EPOCH_BATCH_SIZE]
    start_id = int(batch[0]["id"])
    end_id = int(batch[-1]["id"])
    user_pts = [
        r["content"][:110].replace("\n", " ")
        for r in batch
        if r["role"] == "user"
    ][:6]
    asst_pts = [
        r["content"][:110].replace("\n", " ")
        for r in batch
        if r["role"] == "jarvis"
    ][:4]
    span = f"{batch[0]['created_at'][:16]} → {batch[-1]['created_at'][:16]}"
    summary = f"[{span}] User discussed: " + ("; ".join(user_pts) or "general tasks")
    if asst_pts:
        summary += " | Outcomes: " + "; ".join(asst_pts)

    conn.execute(
        """
        INSERT INTO timeline_epochs (start_msg_id, end_msg_id, summary, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (start_id, end_id, summary[:900], datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )


def get_recent_timeline(limit: int = 80, channel: str = "") -> list[dict[str, Any]]:
    """Return recent timeline turns in chronological order (oldest -> newest)."""
    lim = max(1, min(300, int(limit or 80)))
    with _db_lock:
        conn = _connect()
        try:
            if channel.strip():
                rows = conn.execute(
                    """
                    SELECT id, role, speaker, channel, content, created_at, ts_epoch
                    FROM timeline_messages
                    WHERE channel = ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (channel.strip().lower(), lim),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, role, speaker, channel, content, created_at, ts_epoch
                    FROM timeline_messages
                    ORDER BY id DESC LIMIT ?
                    """,
                    (lim,),
                ).fetchall()
            return [dict(r) for r in reversed(rows)]
        finally:
            conn.close()


def get_console_seed_lines(limit: int = 80) -> list[str]:
    """Format persisted Forever Timeline messages as CONSOLE log lines on boot."""
    rows = get_recent_timeline(limit=limit)
    out: list[str] = []
    for r in rows:
        role = r["role"]
        txt = r["content"]
        if role == "user":
            out.append(f"You: {txt}")
        elif role in ("sys", "tool"):
            out.append(txt if txt.upper().startswith(("SYS:", "TOOL:")) else f"SYS: {txt}")
        else:
            spk = r["speaker"] or cfg.get_assistant_name()
            out.append(f"{spk}: {txt}")
    return out


def search_timeline(query: str, limit: int = 20, channel: str = "") -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return list(reversed(get_recent_timeline(limit=limit, channel=channel)))
    terms = [t.lower() for t in re.findall(r"\w+", q) if len(t) >= 2]
    with _db_lock:
        conn = _connect()
        try:
            sql = "SELECT id, role, speaker, channel, content, created_at, ts_epoch FROM timeline_messages"
            params: list[Any] = []
            clauses: list[str] = []
            if channel.strip():
                clauses.append("channel = ?")
                params.append(channel.strip().lower())
            if terms:
                for t in terms[:5]:
                    clauses.append("LOWER(content) LIKE ?")
                    params.append(f"%{t}%")
            else:
                clauses.append("LOWER(content) LIKE ?")
                params.append(f"%{q.lower()}%")
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(max(1, min(100, int(limit or 20))))
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()


def list_epochs(limit: int = 12) -> list[dict[str, Any]]:
    with _db_lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT id, start_msg_id, end_msg_id, summary, created_at FROM timeline_epochs ORDER BY id DESC LIMIT ?",
                (max(1, min(50, limit)),),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def delete_timeline_message(msg_id: int) -> bool:
    with _db_lock:
        conn = _connect()
        try:
            cur = conn.execute("DELETE FROM timeline_messages WHERE id = ?", (int(msg_id),))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def clear_timeline() -> int:
    with _db_lock:
        conn = _connect()
        try:
            cur = conn.execute("DELETE FROM timeline_messages")
            conn.execute("DELETE FROM timeline_epochs")
            conn.commit()
            return int(cur.rowcount)
        finally:
            conn.close()


def format_timeline_for_prompt(recent_limit: int = 8) -> str:
    """Compact Forever Timeline continuity block injected at session start."""
    if not cfg.get_personalization_enabled():
        return ""
    epochs = list_epochs(limit=2)
    recent = [
        r for r in get_recent_timeline(limit=recent_limit * 2)
        if r["role"] in ("user", "jarvis")
    ][-recent_limit:]
    if not epochs and not recent:
        return ""

    lines = [
        "[FOREVER CONVERSATION TIMELINE — continuous across restarts, voice, text & Telegram]"
    ]
    if epochs:
        lines.append("Earlier conversation digest:")
        for ep in reversed(epochs):
            lines.append(f"  • {ep['summary'][:280]}")
    if recent:
        lines.append("Most recent turns:")
        for r in recent:
            who = "User" if r["role"] == "user" else (r["speaker"] or "JARVIS")
            lines.append(f"  [{r['channel']}] {who}: {r['content'][:220]}")
    return "\n".join(lines) + "\n"


# ── 2. Brain Knowledge Files (Upload / Paste / Semantic-Lexical Recall) ──────

def _sanitize_filename(name: str) -> str:
    raw = Path(name or "note.txt").name
    clean = re.sub(r"[^a-zA-Z0-9._\- ]+", "_", raw).strip()
    return clean or f"doc_{int(time.time())}.txt"


def _extract_text_from_bytes(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        for mod_name in ("pypdf", "PyPDF2"):
            try:
                import importlib
                import io
                mod = importlib.import_module(mod_name)
                reader = mod.PdfReader(io.BytesIO(data))
                pages = [p.extract_text() or "" for p in reader.pages[:60]]
                joined = "\n".join(pages).strip()
                if joined:
                    return joined
            except Exception:
                pass
        # Fallback: extract readable ASCII/UTF-8 runs from PDF bytes
        runs = re.findall(rb"[\x20-\x7E]{5,}", data)
        return " ".join(r.decode("latin-1", errors="ignore") for r in runs[:1500])
    return data.decode("utf-8", errors="replace")


def _chunk_text(text: str, chunk_chars: int = 750) -> list[str]:
    words = (text or "").split()
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for w in words:
        cur.append(w)
        cur_len += len(w) + 1
        if cur_len >= chunk_chars:
            chunks.append(" ".join(cur))
            cur = []
            cur_len = 0
    if cur:
        chunks.append(" ".join(cur))
    return chunks[:250]


def ingest_knowledge_file(
    filename: str,
    content: str | bytes,
    *,
    is_base64: bool = False,
) -> dict[str, Any]:
    """Save a document or note into the Brain and index its text chunks."""
    safe_name = _sanitize_filename(filename)
    if is_base64 and isinstance(content, str):
        b64 = content.split(",", 1)[1] if "," in content and content.startswith("data:") else content
        raw_bytes = base64.b64decode(b64)
    elif isinstance(content, bytes):
        raw_bytes = content
    else:
        raw_bytes = str(content or "").encode("utf-8")

    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = int(time.time() * 1000)
    dest = KNOWLEDGE_DIR / f"{stamp}_{safe_name}"
    dest.write_bytes(raw_bytes)

    extracted = _extract_text_from_bytes(safe_name, raw_bytes).strip()
    chunks = _chunk_text(extracted) if extracted else []
    mime = mimetypes.guess_type(safe_name)[0] or "text/plain"
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    preview = " ".join(extracted.split())[:260]

    with _db_lock:
        conn = _connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO brain_files (filename, stored_path, mime_type, size_bytes, chunk_count, preview, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (safe_name, str(dest), mime, len(raw_bytes), len(chunks), preview, now_iso),
            )
            fid = int(cur.lastrowid)
            if chunks:
                conn.executemany(
                    "INSERT INTO brain_chunks (file_id, chunk_index, text) VALUES (?, ?, ?)",
                    [(fid, idx, ch) for idx, ch in enumerate(chunks)],
                )
            conn.commit()
            return {
                "id": fid,
                "filename": safe_name,
                "mime_type": mime,
                "size_bytes": len(raw_bytes),
                "chunk_count": len(chunks),
                "preview": preview,
                "created_at": now_iso,
            }
        finally:
            conn.close()


def list_knowledge_files() -> list[dict[str, Any]]:
    with _db_lock:
        conn = _connect()
        try:
            rows = conn.execute(
                """
                SELECT id, filename, mime_type, size_bytes, chunk_count, preview, created_at
                FROM brain_files
                ORDER BY id DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def read_knowledge_file(file_id: int) -> dict[str, Any] | None:
    with _db_lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT id, filename, mime_type, size_bytes, chunk_count, preview, created_at FROM brain_files WHERE id = ?",
                (int(file_id),),
            ).fetchone()
            if not row:
                return None
            chunks = conn.execute(
                "SELECT text FROM brain_chunks WHERE file_id = ? ORDER BY chunk_index ASC",
                (int(file_id),),
            ).fetchall()
            d = dict(row)
            d["full_text"] = "\n\n".join(c["text"] for c in chunks)
            return d
        finally:
            conn.close()


def delete_knowledge_file(file_id: int) -> bool:
    with _db_lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT stored_path FROM brain_files WHERE id = ?", (int(file_id),)
            ).fetchone()
            if row and row["stored_path"]:
                try:
                    p = Path(row["stored_path"])
                    if p.exists():
                        p.unlink()
                except Exception:
                    pass
            cur = conn.execute("DELETE FROM brain_files WHERE id = ?", (int(file_id),))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def search_knowledge_chunks(query: str, limit: int = 5) -> list[dict[str, Any]]:
    q_clean = (query or "").strip().lower()
    terms = [t for t in re.findall(r"\w+", q_clean) if len(t) >= 2]
    if not terms and not q_clean:
        return []
    with _db_lock:
        conn = _connect()
        try:
            rows = conn.execute(
                """
                SELECT c.chunk_index, c.text, f.id AS file_id, f.filename
                FROM brain_chunks c
                JOIN brain_files f ON f.id = c.file_id
                """
            ).fetchall()
        finally:
            conn.close()

    scored: list[tuple[float, dict[str, Any]]] = []
    for r in rows:
        hay = r["text"].lower()
        fname = r["filename"].lower()
        score = 4.0 if (q_clean and q_clean in hay) else 0.0
        for t in terms:
            cnt = hay.count(t)
            if cnt:
                score += 1.2 + min(cnt, 5) * 0.25
            if t in fname:
                score += 2.0
        if score > 0:
            scored.append(
                (
                    score,
                    {
                        "file_id": r["file_id"],
                        "filename": r["filename"],
                        "chunk_index": r["chunk_index"],
                        "text": r["text"],
                    },
                )
            )
    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[: max(1, limit)]]


# ── 3. Generated Outputs Vault ───────────────────────────────────────────────

def record_output(title: str, content: str, category: str = "output") -> int | None:
    t = (title or "").strip()[:120]
    body = (content or "").strip()
    if not t or not body:
        return None
    now_ts = time.time()
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cat = (category or t.split("—")[0].split(":")[0] or "output").strip().lower()[:32]

    with _db_lock:
        conn = _connect()
        try:
            last = conn.execute(
                "SELECT id, title, content FROM brain_outputs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if last and last["title"] == t and last["content"] == body[:12000]:
                return int(last["id"])
            cur = conn.execute(
                """
                INSERT INTO brain_outputs (title, category, content, pinned, created_at, ts_epoch)
                VALUES (?, ?, ?, 0, ?, ?)
                """,
                (t, cat, body[:12000], now_iso, now_ts),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def list_outputs(query: str = "", limit: int = 40) -> list[dict[str, Any]]:
    q = (query or "").strip().lower()
    with _db_lock:
        conn = _connect()
        try:
            if q:
                rows = conn.execute(
                    """
                    SELECT id, title, category, content, pinned, created_at
                    FROM brain_outputs
                    WHERE LOWER(title) LIKE ? OR LOWER(content) LIKE ?
                    ORDER BY pinned DESC, ts_epoch DESC LIMIT ?
                    """,
                    (f"%{q}%", f"%{q}%", max(1, min(100, limit))),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, title, category, content, pinned, created_at
                    FROM brain_outputs
                    ORDER BY pinned DESC, ts_epoch DESC LIMIT ?
                    """,
                    (max(1, min(100, limit)),),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def toggle_pin_output(output_id: int) -> bool:
    with _db_lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT pinned FROM brain_outputs WHERE id = ?", (int(output_id),)
            ).fetchone()
            if not row:
                return False
            new_val = 0 if int(row["pinned"]) else 1
            conn.execute(
                "UPDATE brain_outputs SET pinned = ? WHERE id = ?",
                (new_val, int(output_id)),
            )
            conn.commit()
            return bool(new_val)
        finally:
            conn.close()


def delete_output(output_id: int) -> bool:
    with _db_lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "DELETE FROM brain_outputs WHERE id = ?", (int(output_id),)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


# ── 4. Unified Brain Recall + HUD Snapshot + Export/Import ───────────────────

def unified_brain_search(query: str, limit: int = 8) -> str:
    """Search memories, knowledge files, timeline, outputs and saved subject studies."""
    q = (query or "").strip()
    sections: list[str] = []

    mem_res = mm.search_memory(q, limit=limit)
    if mem_res and not mem_res.startswith(("Nothing stored", "I have not stored")):
        sections.append(f"[MEMORIES]\n{mem_res}")

    if q:
        try:
            from core.topic_learning import search as search_studies
            study_hits = search_studies(q, limit=2)
            if study_hits and study_hits != "No matching saved study notes.":
                sections.append("[SAVED STUDIES — untrusted source data]\n" + study_hits)
        except Exception:
            # A damaged study vault must not break the rest of Brain recall.
            pass
        k_hits = search_knowledge_chunks(q, limit=4)
        if k_hits:
            klines = ["[KNOWLEDGE FILES]"]
            for h in k_hits:
                klines.append(f"  • {h['filename']} (#{h['chunk_index']}): {h['text'][:280]}")
            sections.append("\n".join(klines))

        t_hits = search_timeline(q, limit=5)
        if t_hits:
            tlines = ["[FOREVER TIMELINE]"]
            for t in t_hits:
                tlines.append(
                    f"  • [{t['created_at']} · {t['channel']}] {t['speaker']}: {t['content'][:200]}"
                )
            sections.append("\n".join(tlines))

        o_hits = list_outputs(q, limit=3)
        if o_hits:
            olines = ["[PAST OUTPUTS]"]
            for o in o_hits:
                olines.append(f"  • {o['title']} ({o['created_at']}): {o['content'][:200]}")
            sections.append("\n".join(olines))

    if not sections:
        return mem_res
    return "\n\n".join(sections)


def get_brain_snapshot() -> dict[str, Any]:
    """Complete Brain state for the APEX-UI Brain Drawer."""
    memories = mm.all_entries_for_ui()
    files = list_knowledge_files()
    outputs = list_outputs(limit=40)
    timeline = get_recent_timeline(limit=80)
    epochs = list_epochs(limit=10)
    return {
        "memories": memories,
        "files": files,
        "outputs": outputs,
        "timeline": timeline,
        "epochs": epochs,
        "privacy": cfg.get_privacy_settings(),
        "counts": {
            "memories": len(memories),
            "files": len(files),
            "outputs": len(outputs),
            "timeline": len(timeline),
        },
    }


def export_brain_json() -> dict[str, Any]:
    """Portable machine-readable JSON export of the user's entire Brain."""
    return {
        "exported_at": datetime.now().isoformat(),
        "version": 1,
        "privacy": cfg.get_privacy_settings(),
        "long_term_memory": mm.load_memory(),
        "timeline": get_recent_timeline(limit=300),
        "epochs": list_epochs(limit=50),
        "knowledge_files": [
            read_knowledge_file(f["id"]) or f for f in list_knowledge_files()
        ],
        "outputs": list_outputs(limit=100),
    }


def import_brain_json(payload: dict[str, Any]) -> dict[str, int]:
    """Restore memories, notes/files, outputs, and timeline from an exported JSON object."""
    if not isinstance(payload, dict):
        raise ValueError("Invalid Brain export JSON")

    restored = {"memories": 0, "timeline": 0, "files": 0, "outputs": 0}
    ltm = payload.get("long_term_memory")
    if isinstance(ltm, dict):
        mm.update_memory(ltm)
        restored["memories"] = len(mm.all_entries_for_ui())

    for turn in payload.get("timeline") or []:
        if isinstance(turn, dict) and turn.get("content"):
            append_turn(
                str(turn.get("role") or "user"),
                str(turn["content"]),
                speaker=str(turn.get("speaker") or ""),
                channel=str(turn.get("channel") or "text"),
                force=True,
            )
            restored["timeline"] += 1

    for kf in payload.get("knowledge_files") or []:
        if isinstance(kf, dict) and kf.get("filename") and kf.get("full_text"):
            ingest_knowledge_file(str(kf["filename"]), str(kf["full_text"]))
            restored["files"] += 1

    for out in payload.get("outputs") or []:
        if isinstance(out, dict) and out.get("title") and out.get("content"):
            record_output(
                str(out["title"]),
                str(out["content"]),
                category=str(out.get("category") or "output"),
            )
            restored["outputs"] += 1

    return restored
