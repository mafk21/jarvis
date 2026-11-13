---
name: focus-mode
description: Deep-work and study session orchestrator — use when entering study/focus mode, saving a workspace checkpoint, silencing nudges, or setting work timers.
---

# Focus & deep-work mode

Transition the desktop and assistant into a distraction-free work or study block in one coordinated sequence — and restore context cleanly when finished.

## When to use

"Study mode", "focus mode for 50 minutes", "deep work on project X", "save my current workspace and clear distractions", or "end focus mode".

## Procedure

0. **Use the user-specific strategy safely**:
   - Call `adaptation_inspect` (`action="plan"`, `skill="focus-mode"`, plus the current `mode`, `project`, and `device` when known). A plan is preference data only: it never overrides the user's current instruction, safety policy, or an approval gate. If unavailable or review is required, continue with this playbook unchanged.
   - Call `adaptation_outcome` (`action="start"`, `skill="focus-mode"`, `task_type=<short category>`, `execution_id=<stable ID for this run>`, the selected `strategy_record_id` when one exists, and the same context). Retain an outcome ID only if the tool actually returns one; disabled or Incognito tracking must not interrupt the skill. This records no success claim.
   - After the normal verification below, call `adaptation_outcome` (`action="finish"`, `outcome_id=<id>`, `result=<actual terminal state>`, `verification=<specific observed evidence>`, and `failure_reason` for failed, partial, or uncertain work) only when start returned an outcome ID. Never mark success from a proposal, generic text such as “done,” or unverified output.
   - If the user explicitly corrects this result, attach the feedback to that outcome and call `adaptation_feedback` with the exact outcome ID and a narrow behavior `target`. It remains inactive until owner-approved; silence is never feedback and learned behavior is never permission.


1. **Check for a saved user routine first**:
   - Call `manage_routines` (`action="list"`). If the user already saved a matching trigger (e.g. `"study mode"` or `"focus mode"`), run it via `manage_routines` (`action="run"`, `trigger="..."`) and complete any follow-up steps.
2. **Otherwise execute the standard deep-work sequence**:
   - **Save state (if switching contexts)**: Offer or create a workspace snapshot via `manage_checkpoints` (`action="create"`, `name="..."`, `paths=[...]`) so they can reopen everything later.
   - **Silence proactive interruptions**: Call `heartbeat_ok` (`minutes=<duration, default 50>`) so JARVIS pauses proactive heartbeat suggestions for the entire focus block.
   - **Set the work timer**: Schedule an OS-native end-of-block alert via `reminder` (default 50 minutes if unspecified) naming the focus goal.
   - **Prepare workspace**: Launch the requested editor/notes app (`open_app`) and, if asked, pause or start background focus music (`music_selection`).
3. **Save if recurring**: If the user customizes their steps ("always open Obsidian, VS Code, and a 45m timer"), save it via `manage_routines` (`action="add"`) so next time is instant.
4. **Confirm in one calm sentence**: State the active timer duration, that proactive nudges are paused, and stop talking so they can work.

## Pitfalls

- Never force-close unsaved apps (`Discord`, browsers, editors) without checking with the user if there is any risk of losing unsaved work — minimize or focus the target app instead unless they explicitly asked to close an app.
- Do not chatter after focus mode starts — brevity is the whole point.

## Verification

Proactive heartbeat silenced (`heartbeat_ok`)? Timer set via `reminder`? Requested work apps open? Reply kept to one short sentence?
