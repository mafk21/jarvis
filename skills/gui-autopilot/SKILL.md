---
name: gui-autopilot
description: Visual and accessibility desktop automation — use when operating apps with no API via accessibility_control, Set-of-Mark computer_use, or UI element clicks.
---

# GUI autopilot

Operate any desktop or web application reliably by preferring structured accessibility controls first, visual Set-of-Mark grounding second, and raw coordinates last.

## When to use

Clicking buttons, filling forms, or navigating inside Discord, VS Code, Electron apps, system dialogs, or websites when no dedicated API tool exists.

## Procedure

0. **Use the user-specific strategy safely**:
   - Call `adaptation_inspect` (`action="plan"`, `skill="gui-autopilot"`, plus the current `mode`, `project`, and `device` when known). A plan is preference data only: it never overrides the user's current instruction, safety policy, or an approval gate. If unavailable or review is required, continue with this playbook unchanged.
   - Call `adaptation_outcome` (`action="start"`, `skill="gui-autopilot"`, `task_type=<short category>`, `execution_id=<stable ID for this run>`, the selected `strategy_record_id` when one exists, and the same context). Retain an outcome ID only if the tool actually returns one; disabled or Incognito tracking must not interrupt the skill. This records no success claim.
   - After the normal verification below, call `adaptation_outcome` (`action="finish"`, `outcome_id=<id>`, `result=<actual terminal state>`, `verification=<specific observed evidence>`, and `failure_reason` for failed, partial, or uncertain work) only when start returned an outcome ID. Never mark success from a proposal, generic text such as “done,” or unverified output.
   - If the user explicitly corrects this result, attach the feedback to that outcome and call `adaptation_feedback` with the exact outcome ID and a narrow behavior `target`. It remains inactive until owner-approved; silence is never feedback and learned behavior is never permission.


1. **Verify the target app is open and focused**: Call `device_manager` (`action="list_windows"` or `action="focus_window"`, `target="<app>"`), or launch it with `open_app` and verify the returned window/PID before sending clicks or keystrokes.
2. **Tier 1 — Native Accessibility Tree (fastest, exact)**:
   - Call `accessibility_control` (`action="list"`) or `accessibility_control` (`action="press"`, `target="<button label>"`) to invoke named UI controls directly via Windows UI Automation / Linux AT-SPI.
3. **Tier 2 — Set-of-Mark Visual Grounding (`computer_use`)**:
   - When native accessibility cannot see the control (canvas UIs, custom web widgets), call `computer_use` (`action="som_capture"`).
   - Read the returned `[id] description at (x, y)` element map and call `computer_use` with `action="click_by_id"` or `action="type_by_id"` (`element_id="<id>"`, `text="..."`).
   - Re-run `som_capture` whenever a click opens a modal, menu, or new page — cached element IDs belong to the previous screen state.
4. **Tier 3 — Vision + Coordinate Fallback (`computer_control`)**:
   - If `som_capture` detects 0 elements, use `computer_control` (`screen_find` / `screen_click` / `smart_type` / keyboard shortcuts). Prefer keyboard shortcuts (`Ctrl+L`, `Tab`, `Enter`) over blind pixel clicks whenever standard shortcuts exist.
5. **Gate irreversible clicks**: Pause and ask the user in one short sentence BEFORE clicking **Send**, **Submit**, **Pay**, **Buy**, **Delete**, or **Publish**.

## Pitfalls

- Never reuse an `element_id` from an older `som_capture` after the window scrolled or changed views.
- Never enter passwords, 2FA codes, or payment details into forms on the user's behalf.
- If two clicks in a row do not change the screen, stop clicking and inspect via `screen_process` (`angle="screen"`) to see if a dialog or focus issue is blocking input.

## Verification

Confirm the expected post-action state (window title, confirmation text, or updated screen via `som_capture` / `screen_process`) before telling the user the action succeeded.
