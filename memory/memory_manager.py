import json
import re
import shutil
from datetime import date, datetime
from threading import RLock
from pathlib import Path
import sys


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = get_base_dir()
MEMORY_PATH      = BASE_DIR / "memory" / "long_term.json"
_lock            = RLock()
MAX_VALUE_LENGTH = 380

# ── Why there are two very different numbers here ────────────────────────────
#
# There used to be one: MEMORY_MAX_CHARS = 2200, applied to the whole store. It
# was a *storage* limit, and it existed only because the entire memory was
# pasted into the system prompt on every connect — so growing the memory grew
# every single request. When it filled, _trim_to_limit() deleted the oldest
# entries and printed one line to a console nobody reads. A memory described as
# "deeply remembers projects, preferences and personal context" was in practice
# two pages long, and quietly forgot your sister's name after a few weeks.
#
# Storage and prompt budget are now separate concerns:
#
#   MEMORY_MAX_CHARS  — a runaway guard, not a feature limit. Nothing normal
#                       reaches it; a bug writing in a loop does.
#   PROMPT_CORE_CHARS — what actually rides in the system prompt every session.
#                       Smaller than the old whole-memory dump, so sessions
#                       start *faster* than before, not slower.
#
# Everything above the core stays on disk and is fetched on demand by the
# recall_memory tool — see search_memory() and format_memory_for_prompt().
MEMORY_MAX_CHARS  = 200_000
PROMPT_CORE_CHARS = 1800
PROMPT_INDEX_CHARS = 700
# Most entries any one category may contribute to the core block, so a person
# with forty stored preferences still gets their sister into the prompt.
PROMPT_MAX_PER_CATEGORY = 6

# ── Memory hygiene: TTL / forgetting ────────────────────────────────────────
# Per-category time-to-live in days, measured from each entry's "updated"
# date. Identity never expires — a name or city is a standing fact, not a
# passing impression. Wishes decay fastest: a "dream car" from three years
# ago is noise, not a preference.
_TTL_DAYS = {
    "identity":     None,   # never expires
    "relationships":730,    # 2 years — people change slowly
    "preferences":  365,    # 1 year
    "projects":     180,    # 6 months — active goals finish
    "notes":        180,    # 6 months
    "wishes":        90,    # 3 months — plans come and go
}


def _is_expired(entry: dict, category: str, now: date) -> bool:
    ttl = _TTL_DAYS.get(category)
    if ttl is None:
        return False
    updated = (entry or {}).get("updated", "")
    try:
        updated_date = date.fromisoformat(updated)
    except ValueError:
        return False                      # unparseable date → keep, don't destroy
    return (now - updated_date).days > ttl


def expire_memory(memory: dict, now: date | None = None) -> list[str]:
    """Remove entries whose per-category TTL has passed.

    Returns the list of removed "category/key" ids. Callers persist the
    cleaned store themselves (save_memory / load_memory do).
    """
    now = now or date.today()
    removed: list[str] = []
    for cat, ttl in _TTL_DAYS.items():
        if ttl is None:
            continue
        items = memory.get(cat)
        if not isinstance(items, dict):
            continue
        for key in list(items.keys()):
            if _is_expired(items[key], cat, now):
                del items[key]
                removed.append(f"{cat}/{key}")
    return removed


def dedup_memory(memory: dict) -> list[tuple]:
    """Merge cross-category duplicates of the same fact.

    Two entries with the same normalized value (case/whitespace-insensitive)
    in different categories are duplicates — e.g. preferences/color=blue and
    notes/fav_color=blue. The more recently updated copy wins; the other is
    removed. Returns (removed_cat, removed_key, kept_cat, kept_key) tuples.
    """
    seen: dict[str, tuple[str, str, str]] = {}  # norm -> (cat, key, updated)
    removed: list[tuple] = []
    cats = ("identity", "preferences", "projects", "relationships",
            "wishes", "notes")
    for cat in cats:
        items = memory.get(cat)
        if not isinstance(items, dict):
            continue
        for key in list(items.keys()):
            val = _entry_value(items[key])
            if not val:
                continue
            # Values alone are not duplicates: two different people can share
            # a name and one preference can legitimately equal a project note.
            # Merge only equivalent keys carrying the same value.
            norm = f"{_pretty(key).lower()}\0{val.strip().lower()}"
            updated = items[key].get("updated_at") or items[key].get("updated", "0000-00-00")
            if norm in seen:
                old_cat, old_key, old_updated = seen[norm]
                if updated >= old_updated:
                    # keep this (newer), remove the old one
                    old_entry = memory.get(old_cat, {}).get(old_key, {})
                    del memory[old_cat][old_key]
                    removed.append((old_cat, old_key, cat, key))
                    seen[norm] = (cat, key, updated)
                else:
                    del items[key]
                    removed.append((cat, key, old_cat, old_key))
            else:
                seen[norm] = (cat, key, updated)
    return removed


def hygiene_memory(memory: dict | None = None,
                   now: date | None = None) -> dict:
    """Run every hygiene pass: expire TTL, then dedup duplicates.

    Returns the cleaned store. Persist with save_memory() when you want the
    cleanup written to disk.
    """
    if memory is None:
        memory = load_memory()
    expire_memory(memory, now)
    dedup_memory(memory)
    return memory


def user_profile(memory: dict | None = None) -> dict:
    """Consolidated view of what JARVIS knows about this person.

    identity — standing facts (name, city, job …)
    about    — key relationships / preferences / projects, flattened
    """
    if memory is None:
        memory = load_memory()
    identity = memory.get("identity", {}) or {}
    profile: dict[str, str] = {}
    for field in _IDENTITY_FIELDS:
        if isinstance(identity.get(field), dict) and _memory_lifecycle(identity[field]) == "archived":
            continue
        if isinstance(identity.get(field), dict) and identity[field].get("status") == "conflicted":
            continue
        val = _entry_value(identity.get(field))
        if val:
            profile[field] = val
    about: dict[str, str] = {}
    for cat in ("relationships", "preferences", "projects"):
        for key, entry in (memory.get(cat, {}) or {}).items():
            if isinstance(entry, dict) and entry.get("status") == "conflicted":
                continue
            val = _entry_value(entry)
            if val:
                about[f"{cat}/{key}"] = val
    return {"identity": profile, "about": about}

def _empty_memory() -> dict:
    return {
        "identity":      {},
        "preferences":   {},
        "projects":      {},
        "relationships": {},
        "wishes":        {},
        "notes":         {},
    }

def load_memory() -> dict:
    if not MEMORY_PATH.exists():
        return _empty_memory()
    with _lock:
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            backup = MEMORY_PATH.with_suffix(MEMORY_PATH.suffix + ".bak")
            try:
                data = json.loads(backup.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("backup is not an object")
                print("[Memory] Restored the last valid memory snapshot after a load error.")
            except Exception:
                print(f"[Memory] ⚠️ Load error: {type(e).__name__}")
                return _empty_memory()
    if not isinstance(data, dict):
        return _empty_memory()
    base = _empty_memory()
    for key in base:
        if key not in data:
            data[key] = {}
    # Never delete personal facts merely because time passed. Stale context is
    # ranked lower at recall/prompt time; forgetting remains an explicit user
    # action. Only unambiguous duplicates are compacted here.
    removed_explicit: list[str] = []
    now = datetime.now().astimezone()
    for category, items in data.items():
        if not isinstance(items, dict):
            continue
        for item_key, entry in list(items.items()):
            expiry = entry.get("expires_at") if isinstance(entry, dict) else None
            if not expiry:
                continue
            try:
                deadline = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=now.tzinfo)
            except ValueError:
                continue
            if deadline <= now:
                del items[item_key]
                removed_explicit.append(f"{category}/{item_key}")
    removed_dups = dedup_memory(data)
    if removed_dups or removed_explicit:
        try:
            save_memory(data)
        except Exception:
            pass
        _notify_hygiene(removed_explicit, removed_dups)
    return data

def _all_entries(memory: dict) -> list[tuple]:
    entries = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            if isinstance(entry, dict) and "value" in entry:
                entries.append((cat, key, entry))
    return entries


# Set by main.py so a trim can reach the activity log. Deleting something a
# person told you and mentioning it only on stdout is how a memory loses trust.
_trim_notifier = None


def set_trim_notifier(fn) -> None:
    """Register a callable(str) that surfaces trims to the user."""
    global _trim_notifier
    _trim_notifier = fn


def _notify_hygiene(removed_expired: list[str], removed_dups: list[tuple]) -> None:
    if not (removed_expired or removed_dups):
        return
    parts = []
    if removed_expired:
        parts.append(f"forgot {len(removed_expired)} expired entries "
                     f"({', '.join(removed_expired[:3])}"
                     f"{'…' if len(removed_expired) > 3 else ''})")
    if removed_dups:
        parts.append(f"merged {len(removed_dups)} duplicate entries")
    msg = "SYS: Memory hygiene — " + "; ".join(parts)
    if _trim_notifier:
        try:
            _trim_notifier(msg)
        except Exception:
            pass
    print(f"[Memory] 🧹 {msg}")


def _trim_to_limit(memory: dict) -> dict:
    if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
        return memory
    entries = _all_entries(memory)
    entries.sort(key=lambda t: t[2].get("updated", "0000-00-00"))
    dropped = []
    for cat, key, _ in entries:
        if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
            break
        del memory[cat][key]
        dropped.append(f"{cat}/{key}")
        print(f"[Memory] 🗑️  Trimmed {cat}/{key}")
    if dropped and _trim_notifier:
        try:
            _trim_notifier(
                f"SYS: Memory full — forgot {len(dropped)} oldest entries "
                f"({', '.join(dropped[:3])}{'…' if len(dropped) > 3 else ''})"
            )
        except Exception:
            pass
    return memory

def _atomic_write(memory: dict) -> None:
    """Durably replace the memory store without exposing a partial JSON file."""
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = MEMORY_PATH.with_suffix(MEMORY_PATH.suffix + ".tmp")
    temp.write_text(json.dumps(memory, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        temp.chmod(0o600)
    except OSError:
        pass
    if MEMORY_PATH.exists():
        try:
            # One last-known-good rollback point for metadata migrations and edits.
            shutil.copy2(MEMORY_PATH, MEMORY_PATH.with_suffix(MEMORY_PATH.suffix + ".bak"))
        except OSError:
            pass
    temp.replace(MEMORY_PATH)


def save_memory(memory: dict) -> None:
    if not isinstance(memory, dict):
        return
    # Age affects relevance, never existence. Only explicit forget requests or
    # the runaway storage guard may remove a personal memory.
    memory = _trim_to_limit(memory)
    with _lock:
        _atomic_write(memory)


def _truncate_value(val: str) -> str:
    if isinstance(val, str) and len(val) > MAX_VALUE_LENGTH:
        return val[:MAX_VALUE_LENGTH].rstrip() + "…"
    return val


def _recursive_update(target: dict, updates: dict) -> bool:
    changed = False
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, dict) and "value" not in value:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
                changed = True
            if _recursive_update(target[key], value):
                changed = True
        else:
            now = datetime.now().astimezone()
            today = now.strftime("%Y-%m-%d")
            new_val  = _truncate_value(str(value["value"] if isinstance(value, dict) else value).strip())
            entry    = {
                "value": new_val, "updated": today, "updated_at": now.isoformat(timespec="seconds"),
                "provenance": [{"source": "conversation", "observed_at": now.isoformat(timespec="seconds")}],
                "status": "active",
            }
            if isinstance(value, dict):
                for meta in ("source", "confidence", "explicit", "expires_at", "sensitivity", "pinned"):
                    if meta in value:
                        entry[meta] = value[meta]
                entry["provenance"][0]["source"] = str(entry.get("source") or "conversation")[:80]
            existing = target.get(key, {})
            if isinstance(existing, dict):
                for meta in ("source", "confidence", "explicit", "expires_at", "sensitivity", "pinned"):
                    if meta not in entry and meta in existing:
                        entry[meta] = existing[meta]
            # Conflict resolution: same key, new value differs from stored.
            # Keep the previous value in _prev history (cap 5) so nothing is
            # silently overwritten; the latest value stays in "value".
            if (isinstance(existing, dict)
                    and existing.get("value") not in (None, new_val)):
                incoming_explicit = bool(entry.get("explicit"))
                existing_explicit = bool(existing.get("explicit"))
                if existing_explicit and not incoming_explicit:
                    contradictions = list(existing.get("contradictions") or [])[-4:]
                    contradictions.append({"value": new_val, "source": entry.get("source", "conversation"),
                                           "observed_at": entry["updated_at"]})
                    existing["contradictions"] = contradictions
                    target[key] = existing
                    changed = True
                    continue
                history = existing.get("_prev") or []
                history.append({"value": existing.get("value"),
                                "updated": existing.get("updated", today)})
                if len(history) > 5:
                    history = history[-5:]
                entry["_prev"] = history
                if not (incoming_explicit and not existing_explicit):
                    entry["status"] = "conflicted"
                    entry["confidence"] = min(float(entry.get("confidence", 0.75)), 0.5)
            if (not isinstance(existing, dict) or existing.get("value") != new_val
                    or existing.get("updated_at") != entry["updated_at"]):
                if isinstance(existing, dict) and existing.get("_prev") and "_prev" not in entry:
                    entry["_prev"] = existing["_prev"]
                target[key] = entry
                changed = True
    return changed


def update_memory(memory_update: dict) -> dict:
    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()
    # One read-modify-write transaction prevents simultaneous tool/session
    # updates from silently overwriting each other.
    with _lock:
        memory = load_memory()
        if _recursive_update(memory, memory_update):
            save_memory(memory)
            print(f"[Memory] 💾 Saved: {list(memory_update.keys())}")
        return memory

def _entry_value(entry) -> str:
    """Accept both the {'value': ..., 'updated': ...} shape and a bare string,
    because early versions of the store wrote plain strings."""
    if isinstance(entry, dict):
        return str(entry.get("value", "") or "").strip()
    return str(entry or "").strip()


def _pretty(key: str) -> str:
    return key.replace("_", " ").strip()


# Identity is always in the prompt; these categories compete for the remaining
# budget by recency.
_CATEGORY_LABELS = {
    "preferences":   "Preferences",
    "projects":      "Active projects / goals",
    "relationships": "People in their life",
    "wishes":        "Wishes / plans",
    "notes":         "Notes",
}

_IDENTITY_FIELDS = ["name", "age", "birthday", "city", "job",
                    "language", "school", "nationality"]


def format_memory_for_prompt(memory: dict | None) -> str:
    """Build the memory block that goes into the system prompt.

    This used to dump everything. It now sends three things:

      1. IDENTITY  - always, in full. It is small, and it is wrong for the
         assistant to have to look up your name.
      2. RECENT    - the most recently updated entries from every other
         category, up to PROMPT_CORE_CHARS. Recency is the cheapest useful
         relevance signal available without embeddings.
      3. AN INDEX  - the *keys* of everything else, values omitted.

    Point 3 is what makes recall work at all. A model cannot decide to look
    something up if it does not know the thing exists: with only points 1 and 2,
    "who is Ayse?" would get "I don't know" while ayse_sister sat on disk
    unread. The index costs a few hundred characters and turns recall from a
    gamble into a lookup.

    Net effect on latency: this block is SMALLER than the old full dump, so
    every session connects with fewer tokens. Occasionally the model spends one
    extra round trip on recall_memory - covered by the acknowledgment it
    already speaks before any slow step."""
    if not memory:
        return ""
    try:
        from memory.config_manager import get_personalization_enabled
        if not get_personalization_enabled():
            return ""
    except Exception:
        pass

    core_lines: list[str] = []

    # 1. Identity - always, in full
    identity = memory.get("identity", {}) or {}
    for field in _IDENTITY_FIELDS:
        if isinstance(identity.get(field), dict) and identity[field].get("status") == "conflicted":
            continue
        val = _entry_value(identity.get(field))
        if not val:
            continue
        if field == "language":
            # Labelled as an observation, not a setting. A bare "Language:
            # English" line written months ago reads like a standing order and
            # was one of the reasons a Turkish question came back in English.
            core_lines.append(
                f"Has spoken to you in: {val} (an observation about the past — "
                f"always answer in the language of their CURRENT message)")
        else:
            core_lines.append(f"{field.title()}: {val}")
    for key, entry in identity.items():
        if isinstance(entry, dict) and _memory_lifecycle(entry) == "archived":
            continue
        if key in _IDENTITY_FIELDS or (isinstance(entry, dict) and entry.get("status") == "conflicted"):
            continue
        val = _entry_value(entry)
        if val:
            core_lines.append(f"{_pretty(key).title()}: {val}")

    # 2. Everything else, most recently updated first
    rest: list[tuple[str, str, str, str]] = []   # (updated, cat, key, value)
    for cat in _CATEGORY_LABELS:
        for key, entry in (memory.get(cat, {}) or {}).items():
            if isinstance(entry, dict) and _memory_lifecycle(entry) == "archived":
                continue
            val = _entry_value(entry)
            if not val:
                continue
            updated = ((entry.get("updated_at") or entry.get("updated", "")) if isinstance(entry, dict) else "") or "0000-00-00"
            rest.append((updated, cat, key, val))
    rest.sort(key=lambda t: t[0], reverse=True)

    used    = sum(len(l) + 1 for l in core_lines)
    shown: dict[str, list[str]] = {}
    overflow: dict[str, list[str]] = {}

    # Recency decides order, but no single category may take the whole budget.
    # Without the cap, someone with forty stored preferences gets a prompt that
    # is forty preferences and not one person's name — the categories that
    # matter most in conversation are also the ones that change least often, so
    # pure recency systematically buries them.
    per_cat_used: dict[str, int] = {}
    for _updated, cat, key, val in rest:
        line = f"  - {_pretty(key).title()}: {val}"
        if (per_cat_used.get(cat, 0) < PROMPT_MAX_PER_CATEGORY
                and used + len(line) + 1 <= PROMPT_CORE_CHARS):
            shown.setdefault(cat, []).append(line)
            per_cat_used[cat] = per_cat_used.get(cat, 0) + 1
            used += len(line) + 1
        else:
            overflow.setdefault(cat, []).append(_pretty(key))

    # The index is a table of contents, so it is interleaved across categories
    # rather than continuing in recency order. Sorted by recency it would list
    # twenty-four preferences before the first relationship, and the one entry
    # the index exists for — the old fact the model has no other way to know
    # about — would fall off the end.
    indexed: list[str] = []
    if overflow:
        cats  = [c for c in _CATEGORY_LABELS if overflow.get(c)]
        cursor = {c: 0 for c in cats}
        while cats:
            for cat in list(cats):
                i = cursor[cat]
                if i >= len(overflow[cat]):
                    cats.remove(cat)
                    continue
                indexed.append(overflow[cat][i])
                cursor[cat] = i + 1

    for cat, label in _CATEGORY_LABELS.items():
        if shown.get(cat):
            core_lines.append("")
            core_lines.append(f"{label}:")
            core_lines.extend(shown[cat])

    if not core_lines and not indexed:
        return ""

    out = [
        "[WHAT YOU KNOW ABOUT THIS PERSON — use naturally, never recite like a list]",
        *core_lines,
    ]

    # 3. The index of what is on disk but not in this prompt
    if indexed:
        budget, names = PROMPT_INDEX_CHARS, []
        for n in indexed:
            if budget - len(n) - 2 < 0:
                break
            names.append(n)
            budget -= len(n) + 2
        if names:
            out.append("")
            out.append(
                "[ALSO REMEMBERED — values not shown here. Call recall_memory "
                "with a keyword to read any of these before saying you do not know]"
            )
            out.append(", ".join(names)
                       + (f" (+{len(indexed) - len(names)} more)"
                          if len(indexed) > len(names) else ""))

    return "\n".join(out) + "\n"


# ── Recall ────────────────────────────────────────────────────────────────────

def _score(query_words: list[str], cat: str, key: str, value: str) -> int:
    """Cheap lexical relevance. No embeddings, no network, no model call - this
    runs in well under a millisecond, which is the entire point: recall must
    cost one model round trip, never two."""
    hay_key = _pretty(key).lower()
    hay_val = value.lower()
    score   = 0
    for w in query_words:
        if not w:
            continue
        if w == hay_key:
            score += 10
        elif w in hay_key:
            score += 6
        if w in hay_val:
            score += 3
        if w in cat:
            score += 1
    return score


def search_memory(query: str, limit: int = 8) -> str:
    """Find stored facts matching `query`. Backs the recall_memory tool.

    An empty query is treated as "show me everything you know", capped - the
    model asks that when the user says "what do you remember about me?"."""
    memory = load_memory()
    stop = {"a", "an", "the", "i", "me", "my", "you", "do", "did", "what", "who", "is", "are", "about", "remember", "know"}
    raw_words = [w for w in re.split(r"[^\w]+", (query or "").casefold()) if len(w) > 1 and w not in stop]
    # Tiny language-agnostic-friendly normalization for common English plural
    # queries (projects -> project, hobbies -> hobby) without a heavy NLP model.
    words = list(dict.fromkeys(raw_words + [w[:-1] for w in raw_words if len(w) > 3 and w.endswith("s")]))

    rows: list[tuple[int, str, str, str]] = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            if isinstance(entry, dict) and _memory_lifecycle(entry) == "archived":
                continue
            val = _entry_value(entry)
            if not val:
                continue
            s = _score(words, cat, key, val) if words else 1
            if s > 0:
                rows.append((s, cat, key, val))
    # Session summaries are durable context too. They used to be skipped and
    # then physically deleted after one startup, making prior conversations
    # impossible to recall.
    for i, entry in enumerate(memory.get("sessions", []) if isinstance(memory.get("sessions"), list) else []):
        if not isinstance(entry, dict):
            continue
        val = str(entry.get("summary") or "").strip()
        if not val:
            continue
        key = str(entry.get("date") or entry.get("created_at") or f"session_{i + 1}")
        s = _score(words, "sessions", key, val) if words else 1
        if s > 0:
            rows.append((s, "sessions", key, val))

    if not rows:
        return (f"Nothing stored about '{query}'." if query
                else "I have not stored anything about this person yet.")

    rows.sort(key=lambda r: (-r[0], r[2]))
    lines = [f"{cat}/{_pretty(key)}: {val}" for _s, cat, key, val in rows[:max(1, limit)]]
    head  = (f"Stored facts matching '{query}':" if query
             else "Everything currently stored:")
    more  = (f"\n(+{len(rows) - len(lines)} more — search with a narrower keyword)"
             if len(rows) > len(lines) else "")
    return head + "\n" + "\n".join(lines) + more


def _memory_lifecycle(entry: dict) -> str:
    if not isinstance(entry, dict):
        return "active"
    explicit = str(entry.get("lifecycle") or "").lower()
    if explicit in {"active", "core", "recent", "archived"}:
        return explicit
    if entry.get("pinned"):
        return "core"
    updated = str(entry.get("updated_at") or entry.get("updated") or "")[:10]
    try:
        if (date.today() - date.fromisoformat(updated)).days <= 30:
            return "recent"
    except ValueError:
        pass
    return "active"


def set_memory_lifecycle(category: str, key: str, lifecycle: str) -> str:
    lifecycle = str(lifecycle or "").lower()
    if lifecycle not in {"active", "core", "recent", "archived"}:
        raise ValueError("lifecycle must be active, core, recent, or archived")
    memory = load_memory()
    entry = memory.get(category, {}).get(key)
    if not isinstance(entry, dict):
        raise KeyError("Memory not found")
    entry["lifecycle"] = lifecycle
    entry["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    if lifecycle == "core":
        entry["pinned"] = True
    elif entry.get("pinned"):
        entry["pinned"] = False
    with _lock:
        _atomic_write(memory)
    return lifecycle


def edit_memory(category: str, key: str, value: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError("Memory value cannot be empty")
    memory = load_memory()
    entry = memory.get(category, {}).get(key)
    if not isinstance(entry, dict):
        raise KeyError("Memory not found")
    entry["value"] = value[:MAX_VALUE_LENGTH]
    entry["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    entry["source"] = "user_edit"
    entry["confidence"] = 1.0
    with _lock:
        _atomic_write(memory)
    return entry["value"]


def all_entries_for_ui() -> list[dict]:
    """Flat list for the memory panel: what JARVIS knows, and when it learned it.
    Sorted newest first so the panel opens on what changed most recently."""
    memory = load_memory()
    rows = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            val = _entry_value(entry)
            if not val:
                continue
            rows.append({
                "category": cat,
                "key":      key,
                "value":    val,
                "updated":  (entry.get("updated", "") if isinstance(entry, dict) else ""),
                "source": (entry.get("source", "legacy") if isinstance(entry, dict) else "legacy"),
                "confidence": (entry.get("confidence") if isinstance(entry, dict) else None),
                "status": (entry.get("status", "active") if isinstance(entry, dict) else "legacy"),
                "sensitivity": (entry.get("sensitivity", "personal") if isinstance(entry, dict) else "personal"),
                "pinned": bool(entry.get("pinned", False)) if isinstance(entry, dict) else False,
                "lifecycle": _memory_lifecycle(entry),
                "expires_at": (entry.get("expires_at") if isinstance(entry, dict) else None),
            })
    rows.sort(key=lambda r: (r["updated"] or "0000-00-00"), reverse=True)
    return rows

_KEY_ALIASES = {
    "full_name": "name", "user_name": "name", "location": "city", "home_city": "city",
    "occupation": "job", "work": "job", "preferred_language": "language",
    "favourite_food": "favorite_food", "fav_food": "favorite_food",
    "favourite_color": "favorite_color", "fav_color": "favorite_color",
    "favourite_music": "favorite_music", "fav_music": "favorite_music",
}


def _clean_key(key: str) -> str:
    cleaned = re.sub(r"[^\w\- ]+", "", str(key or "").strip(), flags=re.UNICODE).strip().replace(" ", "_").lower() or "note"
    return _KEY_ALIASES.get(cleaned, cleaned)


def remember(key: str, value: str, category: str = "notes", *, manual: bool = False) -> str:
    if not manual:
        try:
            from memory.config_manager import get_adaptive_learning_enabled
            if not get_adaptive_learning_enabled():
                return "Adaptive learning is currently paused in HUD -> Brain -> Privacy."
        except Exception:
            pass
    valid = {"identity", "preferences", "projects", "relationships", "wishes", "notes"}
    if category not in valid:
        category = "notes"
    clean_key = _clean_key(key)
    clean_value = str(value or "").strip()
    if not clean_value:
        return "Nothing to remember: value is empty."
    update_memory({category: {clean_key: {
        "value": clean_value,
        "source": "explicit_user" if manual else "conversation",
        "confidence": 1.0 if manual else 0.75,
        "explicit": bool(manual),
    }}})
    return f"Remembered: {category}/{clean_key} = {clean_value}"


def clear_all_memories() -> str:
    """Wipe all stored memories in long_term.json on explicit user request."""
    empty = _empty_memory()
    with _lock:
        _atomic_write(empty)
    return "Cleared all stored personal memories."


def forget(key: str, category: str = "notes") -> str:
    memory = load_memory()
    clean_key = _clean_key(key)
    candidates = [category] + [c for c in _empty_memory() if c != category]
    for cat_name in candidates:
        cat = memory.get(cat_name, {})
        if not isinstance(cat, dict) or clean_key not in cat:
            continue
        del cat[clean_key]
        memory[cat_name] = cat
        save_memory(memory)
        return f"Forgotten: {cat_name}/{clean_key}"
    return f"Not found: {clean_key}"


forget_memory = forget


# ── Session memory ─────────────────────────────────────────────────────────────

_SESSION_MAX = 50  # durable conversation continuity; prompt uses only the newest


def save_session_summary(summary: str, language: str = "") -> None:
    """Append a 1-2 sentence session summary to long_term.json['sessions']."""
    summary = (summary or "").strip()
    if not summary:
        return
    now = datetime.now().astimezone()
    entry: dict = {
        "date": now.strftime("%Y-%m-%d"),
        "created_at": now.isoformat(timespec="seconds"),
        "summary": summary[:600],
        "briefed": False,
    }
    if language:
        entry["language"] = language
    with _lock:
        memory = load_memory()
        sessions = memory.get("sessions", [])
        if not isinstance(sessions, list):
            sessions = []
        sessions.append(entry)
        memory["sessions"] = sessions[-_SESSION_MAX:]
        _atomic_write(memory)
    print(f"[Memory] 📝 Session saved ({entry['date']}): {summary[:60]}…")


def pop_last_session() -> dict | None:
    """Return the newest unbriefed session and mark it briefed without erasing it."""
    with _lock:
        if not MEMORY_PATH.exists():
            return None
        try:
            memory = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            sessions = memory.get("sessions", [])
            if not isinstance(sessions, list) or not sessions:
                return None
            for entry in reversed(sessions):
                if not isinstance(entry, dict) or entry.get("briefed"):
                    continue
                entry["briefed"] = True
                _atomic_write(memory)
                return dict(entry)
            return None
        except Exception as e:
            print(f"[Memory] ⚠️ pop_last_session error: {e}")
            return None