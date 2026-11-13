"""Encrypted, versioned persistence for user-specific skill adaptation.

This store is intentionally not wired into skill execution yet.  It provides a
small auditable persistence boundary with strict schema validation, atomic
writes, a last-known-good backup, bounded growth, revision checks, and complete
user-controlled deletion.
"""
from __future__ import annotations

import json
import os
import stat
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core.adaptation import (
    SCHEMA_VERSION,
    AdaptationRecord,
    AdaptationValidationError,
    SkillOutcome,
)

MAX_RECORDS = 1000
MAX_OUTCOMES = 5000
_WRAPPER_VERSION = 1
_LOCK = threading.RLock()


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


ADAPTATION_PATH = _base_dir() / "memory" / "adaptation_store.json"


class AdaptationStoreError(RuntimeError):
    """Persistence failed without changing the last valid store."""


class RevisionConflict(AdaptationStoreError):
    """The caller attempted to overwrite a newer store revision."""


@dataclass(frozen=True, slots=True)
class AdaptationSnapshot:
    revision: int
    records: tuple[AdaptationRecord, ...]
    outcomes: tuple[SkillOutcome, ...]


def _empty() -> AdaptationSnapshot:
    return AdaptationSnapshot(revision=0, records=(), outcomes=())


def _payload(snapshot: AdaptationSnapshot) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": snapshot.revision,
        "records": [item.to_dict() for item in snapshot.records],
        "outcomes": [item.to_dict() for item in snapshot.outcomes],
    }


def _parse(raw: Any) -> AdaptationSnapshot:
    if not isinstance(raw, dict):
        raise AdaptationValidationError("adaptation store must be an object")
    allowed = {"schema_version", "revision", "records", "outcomes"}
    unknown = set(raw) - allowed
    if unknown:
        raise AdaptationValidationError(f"adaptation store contains unknown fields: {', '.join(sorted(unknown))}")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise AdaptationValidationError("unsupported adaptation store schema")
    revision = raw.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise AdaptationValidationError("adaptation store revision must be a non-negative integer")
    records, outcomes = raw.get("records"), raw.get("outcomes")
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise AdaptationValidationError("adaptation records are not a bounded list")
    if not isinstance(outcomes, list) or len(outcomes) > MAX_OUTCOMES:
        raise AdaptationValidationError("adaptation outcomes are not a bounded list")
    parsed_records = tuple(AdaptationRecord.from_dict(item) for item in records)
    parsed_outcomes = tuple(SkillOutcome.from_dict(item) for item in outcomes)
    record_ids = [item.id for item in parsed_records]
    outcome_ids = [item.id for item in parsed_outcomes]
    if len(set(record_ids)) != len(record_ids):
        raise AdaptationValidationError("adaptation record IDs must be unique")
    if len(set(outcome_ids)) != len(outcome_ids):
        raise AdaptationValidationError("adaptation outcome IDs must be unique")
    return AdaptationSnapshot(revision=revision, records=parsed_records, outcomes=parsed_outcomes)


class AdaptationStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or ADAPTATION_PATH)
        self.backup_path = self.path.with_suffix(self.path.suffix + ".bak")

    def load(self) -> AdaptationSnapshot:
        """Load primary, recover from backup, or fail closed to an empty store."""
        with _LOCK:
            if not self.path.exists() and not self.backup_path.exists():
                return _empty()
            try:
                return self._read(self.path)
            except Exception as primary_error:
                try:
                    backup = self._read(self.backup_path)
                except Exception as backup_error:
                    raise AdaptationStoreError(
                        f"adaptation store and backup are unreadable: {type(primary_error).__name__}; "
                        f"{type(backup_error).__name__}"
                    ) from backup_error
                # Restore only validated ciphertext generated from the parsed backup.
                self._write_file(self.path, backup)
                return backup

    def put_record(self, record: AdaptationRecord, *, expected_revision: int | None = None) -> AdaptationSnapshot:
        if not isinstance(record, AdaptationRecord):
            raise TypeError("record must be an AdaptationRecord")
        def change(current: AdaptationSnapshot) -> AdaptationSnapshot:
            rows = list(current.records)
            match = next((i for i, item in enumerate(rows) if item.id == record.id), None)
            if match is None:
                if len(rows) >= MAX_RECORDS:
                    raise AdaptationStoreError("adaptation record limit reached")
                rows.append(record)
            else:
                rows[match] = record
            return AdaptationSnapshot(current.revision + 1, tuple(rows), current.outcomes)
        return self._mutate(change, expected_revision)

    def replace_records(
        self,
        records: tuple[AdaptationRecord, ...],
        *,
        expected_revision: int,
    ) -> AdaptationSnapshot:
        """Atomically replace validated records for governance operations."""
        if not isinstance(records, tuple) or not all(isinstance(item, AdaptationRecord) for item in records):
            raise TypeError("records must be a tuple of AdaptationRecord values")
        if len(records) > MAX_RECORDS or len({item.id for item in records}) != len(records):
            raise AdaptationStoreError("records must be unique and within the store limit")
        return self._mutate(
            lambda current: AdaptationSnapshot(current.revision + 1, records, current.outcomes),
            expected_revision,
        )

    def append_outcome(self, outcome: SkillOutcome, *, expected_revision: int | None = None) -> AdaptationSnapshot:
        if not isinstance(outcome, SkillOutcome):
            raise TypeError("outcome must be a SkillOutcome")
        def change(current: AdaptationSnapshot) -> AdaptationSnapshot:
            if any(item.id == outcome.id for item in current.outcomes):
                raise AdaptationStoreError("adaptation outcome ID already exists")
            # Outcomes are an audit sequence. Retain the newest bounded window.
            rows = (*current.outcomes, outcome)[-MAX_OUTCOMES:]
            return AdaptationSnapshot(current.revision + 1, current.records, rows)
        return self._mutate(change, expected_revision)

    def remove_record(self, record_id: str, *, expected_revision: int | None = None) -> AdaptationSnapshot:
        clean_id = str(record_id or "").strip()
        if not clean_id:
            raise ValueError("record_id cannot be empty")
        def change(current: AdaptationSnapshot) -> AdaptationSnapshot:
            rows = tuple(item for item in current.records if item.id != clean_id)
            if len(rows) == len(current.records):
                raise KeyError(clean_id)
            # Keep outcomes as historical evidence, but sever their strategy link
            # when exporting/using them at a later integration stage.
            return AdaptationSnapshot(current.revision + 1, rows, current.outcomes)
        return self._mutate(change, expected_revision)

    def clear(self, *, expected_revision: int | None = None) -> AdaptationSnapshot:
        """Delete all learned records and outcomes while preserving revision order."""
        return self._mutate(
            lambda current: AdaptationSnapshot(current.revision + 1, (), ()),
            expected_revision,
        )

    def delete_files(self) -> None:
        """Completely remove the encrypted store and backup at the user's request."""
        with _LOCK:
            for target in (self.path, self.backup_path):
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass

    def _mutate(
        self,
        operation: Callable[[AdaptationSnapshot], AdaptationSnapshot],
        expected_revision: int | None,
    ) -> AdaptationSnapshot:
        with _LOCK:
            current = self.load()
            if expected_revision is not None and current.revision != expected_revision:
                raise RevisionConflict(
                    f"expected adaptation revision {expected_revision}, found {current.revision}"
                )
            candidate = operation(current)
            # Re-parse our own output before touching disk, enforcing every bound.
            validated = _parse(_payload(candidate))
            if self.path.exists():
                # Backup receives the previous valid state, enabling rollback from
                # a torn/tampered primary without accepting unvalidated bytes.
                self._write_file(self.backup_path, current)
            self._write_file(self.path, validated)
            return validated

    def _read(self, target: Path) -> AdaptationSnapshot:
        wrapper = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(wrapper, dict) or set(wrapper) != {"version", "encrypted_store"}:
            raise AdaptationValidationError("invalid encrypted adaptation wrapper")
        if wrapper["version"] != _WRAPPER_VERSION or not isinstance(wrapper["encrypted_store"], str):
            raise AdaptationValidationError("unsupported encrypted adaptation wrapper")
        from core.security_vault import decrypt_secret
        return _parse(json.loads(decrypt_secret(wrapper["encrypted_store"])))

    def _write_file(self, target: Path, snapshot: AdaptationSnapshot) -> None:
        from core.security_vault import encrypt_secret
        plaintext = json.dumps(_payload(snapshot), ensure_ascii=False, separators=(",", ":"))
        wrapper = json.dumps(
            {"version": _WRAPPER_VERSION, "encrypted_store": encrypt_secret(plaintext)},
            separators=(",", ":"),
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp")
        try:
            temporary.write_text(wrapper, encoding="utf-8")
            try:
                temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
            os.replace(temporary, target)
        except Exception:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise
