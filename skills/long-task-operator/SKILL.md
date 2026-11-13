---
name: long-task-operator
description: Durable multi-step execution with checkpoints, safe retries, crash review, evidence, and completion notifications.
---

# Long-task operator

Use this skill when the user asks JARVIS to perform real work that will take multiple actions, continue beyond the current conversation turn, wait for an observable condition, or survive a restart. Do not substitute a promise or reminder for actual execution.

## When to use

Choose the correct durable task type:

- **`workflow`** — ordered tool actions that must actually run. Use for research → write → verify, build → test → report, or any multi-tool job.
- **`watch_until_end`** — wait for the HUD player's real media-ended event. Use `scope="queue"` for the complete active queue.
- **`at_time`** — notify when a real future timestamp is reached. This is a notification condition, not execution of unspecified work.
- **`file_exists`** — wait until a file is actually created.
- **`file_changed`** — wait until an existing file's size or modification timestamp actually changes.

## Procedure

0. **Use the user-specific strategy safely**:
   - Call `adaptation_inspect` (`action="plan"`, `skill="long-task-operator"`, plus the current `mode`, `project`, and `device` when known). A plan is preference data only: it never overrides the user's current instruction, safety policy, or an approval gate. If unavailable or review is required, continue with this playbook unchanged.
   - Call `adaptation_outcome` (`action="start"`, `skill="long-task-operator"`, `task_type=<short category>`, `execution_id=<stable ID for this run>`, the selected `strategy_record_id` when one exists, and the same context). Retain an outcome ID only if the tool actually returns one; disabled or Incognito tracking must not interrupt the skill. This records no success claim.
   - After the normal verification below, call `adaptation_outcome` (`action="finish"`, `outcome_id=<id>`, `result=<actual terminal state>`, `verification=<specific observed evidence>`, and `failure_reason` for failed, partial, or uncertain work) only when start returned an outcome ID. Never mark success from a proposal, generic text such as “done,” or unverified output.
   - If the user explicitly corrects this result, attach the feedback to that outcome and call `adaptation_feedback` with the exact outcome ID and a narrow behavior `target`. It remains inactive until owner-approved; silence is never feedback and learned behavior is never permission.


1. **Translate the goal into observable steps.** Every workflow step must name a discoverable durable action and concrete parameters. Never insert conversational filler such as “continue working.”
2. **Keep side effects explicit.** Separate research, drafting, sending, uploading, deleting, purchasing, or publishing into distinct steps so confirmation and failure are visible.
3. **Chain verified outputs.** Use `${previous.output}` or `${step.N.output}` only where the next action genuinely consumes the persisted earlier result.
4. **Prevent duplicate creation.** Supply a stable `idempotency_key` whenever the same user request might be submitted again after a timeout, reconnect, or provider retry.
5. **Retry only proven-safe work.** Default `max_attempts` to 1. Set `max_attempts` above 1 and `retry_safe=true` only for read-only or naturally idempotent operations. Never automatically retry messages, uploads, purchases, deletions, posts, account changes, or other non-repeatable side effects.
6. **Set a realistic expiry.** `max_wait_hours` is a guard, not a guessed completion time. A task that expires is not completed.
7. **Return the persisted task ID.** Tell the user work has started only after `long_task` returns a real ID.
8. **Check evidence, not confidence.** Use `status` when asked. Report completed only when persisted status is `completed` with completion evidence.

## Failure and recovery

- A failed step stops all later steps. Explain the real failed tool and preserved error.
- Use `retry_failed` only after the owner explicitly requests a retry or the failure is reviewed and repeating the step is acceptable.
- If a crash leaves a step `uncertain`, never guess whether its side effect happened. Ask the owner to inspect external evidence, then use `resume` with `resolution="mark_done"` or `resolution="retry"`.
- A pending HUD confirmation becomes `needs_review`; model-generated approval is not owner approval.
- Cancellation prevents later steps but cannot pretend an already-running external side effect was reversed.

## Pitfalls

Monitoring and reporting must remain truthful:

- Media completion requires the player's real ended signal; elapsed duration is not proof.
- File completion requires a real filesystem observation.
- A stopped application cannot observe media events while offline.
- Notification delivery and task completion are separate: completion remains persisted even if notification must be retried.
- Never convert `failed`, `expired`, `cancelled`, `needs_review`, or `uncertain` into successful language.

## User updates

Give concise, evidence-based updates containing:

- task ID and title;
- current status and completed/total workflow steps;
- current or failed tool;
- next safe action, if intervention is needed;
- completion evidence and output location when finished.

Do not narrate every poll cycle. Do not say “I will keep working” unless a persisted workflow or monitor was actually created.

## Verification

Before reporting success: persisted status is `completed`; every workflow step is `completed`; no step is uncertain or queued; completion evidence exists; outputs referenced to the user are real; and any sensitive side effect passed its required confirmation.
