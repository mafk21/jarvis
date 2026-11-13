---
name: meeting-copilot
description: Live lecture or meeting capture to action items — use when recording notes, summarizing a class or call, extracting tasks, or drafting follow-up notes.
---

# Meeting & lecture copilot

Capture live lectures, standups, or meetings and turn raw transcripts into structured summaries, decisions, tasks, and deadline reminders.

## When to use

"Start lecture notes", "take meeting notes", "stop the notes and summarize", "turn these meeting notes into action items", or "send out the meeting recap".

## Procedure

0. **Use the user-specific strategy safely**:
   - Call `adaptation_inspect` (`action="plan"`, `skill="meeting-copilot"`, plus the current `mode`, `project`, and `device` when known). A plan is preference data only: it never overrides the user's current instruction, safety policy, or an approval gate. If unavailable or review is required, continue with this playbook unchanged.
   - Call `adaptation_outcome` (`action="start"`, `skill="meeting-copilot"`, `task_type=<short category>`, `execution_id=<stable ID for this run>`, the selected `strategy_record_id` when one exists, and the same context). Retain an outcome ID only if the tool actually returns one; disabled or Incognito tracking must not interrupt the skill. This records no success claim.
   - After the normal verification below, call `adaptation_outcome` (`action="finish"`, `outcome_id=<id>`, `result=<actual terminal state>`, `verification=<specific observed evidence>`, and `failure_reason` for failed, partial, or uncertain work) only when start returned an outcome ID. Never mark success from a proposal, generic text such as “done,” or unverified output.
   - If the user explicitly corrects this result, attach the feedback to that outcome and call `adaptation_feedback` with the exact outcome ID and a narrow behavior `target`. It remains inactive until owner-approved; silence is never feedback and learned behavior is never permission.


1. **Start capture cleanly**:
   - When the session begins, call `manage_lecture` (`action="start"`, `title="<course or meeting name>"`).
   - As key points or user annotations arrive mid-session, append them with `manage_lecture` (`action="append"`, `text=...`). Check progress anytime via `action="status"`.
2. **Stop & synthesize**:
   - When the user says "stop the notes" or the meeting ends, call `manage_lecture` (`action="stop"`, `summarize=True`).
   - Structure the takeaways into three crisp buckets: **Key Decisions / Concepts**, **Open Questions**, and **Action Items / Homework (Owner + Deadline)**.
3. **Materialize commitments**:
   - Save each concrete homework item or user-owned action item into the Tasks DB via `manage_tasks` (`action="add"`, `title=...`, `due=...`, `priority="high"` for near deadlines).
   - For hard time-bound deadlines, offer or schedule an OS notification via `reminder`.
4. **Distribute if requested**:
   - If the user asks to share the recap, follow the `workspace-comms` pattern (`gws_pack` `workflow="send_meeting_notes"` or `docs_create` + `gmail_send`).

## Pitfalls

- Do not create duplicate tasks if the same action item was mentioned twice in the transcript — deduplicate before calling `manage_tasks`.
- Keep the spoken summary to the 3–5 headline takeaways; full notes belong in the saved note (`manage_notes`) and HUD panel.

## Verification

Lecture session cleanly stopped (`status` inactive)? Summary saved to Notes? Every concrete deadline converted into a deduplicated task?
