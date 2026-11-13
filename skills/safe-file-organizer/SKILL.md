---
name: safe-file-organizer
description: Dry-run folder triage and undo-safe cleanup — use when organizing Downloads or Desktop, batch-renaming files, sorting folders, or undoing file moves.
---

# Safe file organizer

Clean up messy directories (`Downloads`, `Desktop`, `Documents`, project folders), batch-rename files, isolate exact duplicates, and extract/process archives with exact path targeting, zero empty ghost folders, zero silent deletions, and full `undo` rollback safety.

## When to use

"Clean up my Downloads", "organize my files in Downloads", "organize my Desktop by type/date", "rename all screenshots in this folder", "find or quarantine duplicates in Downloads", "move all PDFs into Invoices", "remove empty folders on Desktop", or "undo those file changes".

## Procedure

0. **Use the user-specific strategy safely**:
   - Call `adaptation_inspect` (`action="plan"`, `skill="safe-file-organizer"`, plus the current `mode`, `project`, and `device` when known). A plan is preference data only: it never overrides the user's current instruction, safety policy, or an approval gate. If unavailable or review is required, continue with this playbook unchanged.
   - Call `adaptation_outcome` (`action="start"`, `skill="safe-file-organizer"`, `task_type=<short category>`, `execution_id=<stable ID for this run>`, the selected `strategy_record_id` when one exists, and the same context). Retain an outcome ID only if the tool actually returns one; disabled or Incognito tracking must not interrupt the skill. This records no success claim.
   - After the normal verification below, call `adaptation_outcome` (`action="finish"`, `outcome_id=<id>`, `result=<actual terminal state>`, `verification=<specific observed evidence>`, and `failure_reason` for failed, partial, or uncertain work) only when start returned an outcome ID. Never mark success from a proposal, generic text such as “done,” or unverified output.
   - If the user explicitly corrects this result, attach the feedback to that outcome and call `adaptation_feedback` with the exact outcome ID and a narrow behavior `target`. It remains inactive until owner-approved; silence is never feedback and learned behavior is never permission.


1. **Always pass the user's exact target folder (`path`)**:
   - Never omit `path`! Pass `path="downloads"` for Downloads, `path="desktop"` for Desktop, `path="documents"` for Documents, or the exact folder path requested (Windows OneDrive Known Folders are resolved automatically). If the user says "organize my files" without naming a folder, ask whether they mean `Downloads` or `Desktop`.
2. **Use first-class atomic `file_controller` operations (with `dry_run=True` preview when >5 files)**:
   - **Sort a whole folder**: `file_controller(action="organize", path="<target>", mode="by_type", dry_run=True|False)` (`mode="by_date"` for `YYYY-MM/`). Creates `Images/`, `Documents/`, `Installers/`, `Archives/`, `Videos/`, `Audio/`, `Code/`, `Design_3D/` **only** when matching files exist, handles filename collisions safely, and registers one atomic `undo`.
   - **Filter / bulk move**: `file_controller(action="move", path="<target>", extension=".pdf", destination="Invoices")` (or `pattern="Screenshot*"`, or `files=[...]`) — moves all matching files in a single undoable step.
   - **Batch rename**: `file_controller(action="batch_rename", path="<target>", pattern="Screenshot*", prefix="Trip", include_date=True, dry_run=True|False)` (or `replace_from` / `replace_to`) — renames all matching files atomically with one `undo`.
   - **Duplicate triage**: `file_controller(action="duplicates", path="<target>")` to scan by size + SHA-256 hash, and `file_controller(action="quarantine_duplicates", path="<target>")` to isolate exact copies into `_To_Review/Duplicates/` without deleting anything.
   - **Clean empty folders / checkpoints / archives**: `file_controller(action="clean_empty_folders", path="<target>")`, `manage_checkpoints(action="create", ...)` before major restructures, and `file_processor(file_path="downloads/foo.zip", action="extract")` for archives.
3. **Verify & remind of rollback**:
   - Report the exact folder path modified and final counts per category/action.
   - If the user dislikes the layout or says "put it back", call `undo` immediately.

## Pitfalls

- Never call `desktop_control` to organize `Downloads` or other folders — always use `file_controller`.
- Never permanently delete user files during organization or duplicate triage; quarantine into `_To_Review/Duplicates/` unless the user explicitly asks to `delete` named files (Recycle Bin / Trash).
- Never overwrite existing files silently, and never touch `.git/`, system folders, shortcuts (`.lnk`/`.url`), or active incomplete downloads (`~$*`, `*.part`, `*.crdownload`).

## Verification

Exact requested folder (`Downloads` vs `Desktop`) targeted? Zero empty folders created? Every moved, renamed, or quarantined batch reversible in one step via `undo`?
