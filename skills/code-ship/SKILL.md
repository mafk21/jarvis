---
name: code-ship
description: End-to-end bugfix, feature build, test run, and Git/PR shipping — use when fixing code, adding features, running test suites, or preparing pull requests.
---

# Code ship

Diagnose, implement, test, and ship software changes cleanly without regressions or blind edits.

## When to use

Bug reports, stack traces, feature requests in a codebase, refactoring tasks, running tests/linters, reviewing diffs, committing changes, or opening GitHub pull requests.

## Procedure

0. **Use the user-specific strategy safely**:
   - Call `adaptation_inspect` (`action="plan"`, `skill="code-ship"`, plus the current `mode`, `project`, and `device` when known). A plan is preference data only: it never overrides the user's current instruction, safety policy, or an approval gate. If unavailable or review is required, continue with this playbook unchanged.
   - Call `adaptation_outcome` (`action="start"`, `skill="code-ship"`, `task_type=<short category>`, and the same context). Retain its outcome ID. This records no success claim.
   - After the normal verification below, call `adaptation_outcome` (`action="finish"`, `outcome_id=<id>`, `result=<actual terminal state>`, `verification=<concrete evidence>`, and `failure_reason` for failed, partial, or uncertain work). Never mark success from a proposal or unverified output.
   - If the user explicitly corrects this result, attach the feedback to that outcome and call `adaptation_feedback` with the exact outcome ID and a narrow behavior `target`. It remains inactive until owner-approved; silence is never feedback and learned behavior is never permission.


1. **Decompose if large**: If the request spans 5+ distinct steps or multiple subsystems, spawn a tracked plan via `subagent` (`action="spawn"`, `goal=...`) so steps and verification stay isolated.
2. **Inspect before editing**:
   - Check repository state with `github_automation` (`action="git_status"`, `cwd=...`) or `shell_agent` (`action="run"`, `command="git status -sb"`).
   - Read target files and existing tests first (`file_processor` or `code_helper`) — never patch code you have not read.
3. **Implement minimal, surgical changes**:
   - Follow the codebase's existing style, imports, error handling, and naming conventions.
   - Use `dev_agent`, `code_helper`, or `file_controller` for edits; avoid unrelated formatting churn.
4. **Verify with real execution**:
   - Run targeted unit tests and syntax/type checks via `shell_agent` (`action="run"`, e.g. `pytest`, `npm test`, `cargo test`, `py_compile`).
   - For long builds or watchers, use `shell_agent` (`action="run_background"`) and poll with `action="log"`.
5. **Audit the diff & ship (only push/PR when asked)**:
   - Inspect `github_automation` (`action="git_diff"`) and run through `references/pr-checklist.md` (`skill_read`) before committing or calling `github_automation` (`action="create_pr"`).

## Pitfalls

- Never claim tests pass without actually running them via `shell_agent` and checking the exit output.
- Never commit secrets (`.env`, `api_keys.json`, tokens), build artifacts (`__pycache__`, `node_modules`, `dist`), or untracked scratch files.
- Never force-push or run destructive git resets (`git reset --hard`) unless the user explicitly instructs you to.

## Verification

Tests executed and passing? `git status` clean of stray artifacts? Diff minimal and matching the user's exact request?
