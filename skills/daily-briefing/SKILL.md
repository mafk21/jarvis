---
name: daily-briefing
description: Executive morning or status briefing — use when asked to brief me, catch me up, plan my day, or summarize today's tasks, calendar, weather, and news.
---

# Daily briefing

Deliver a crisp, high-signal executive briefing tailored to the user's location, open commitments, schedule, and watched topics.

## When to use

"Good morning, brief me", "what does my day look like?", "catch me up", "plan my day", or "status briefing".

## Procedure

0. **Use the user-specific strategy safely**:
   - Call `adaptation_inspect` (`action="plan"`, `skill="daily-briefing"`, plus the current `mode`, `project`, and `device` when known). A plan is preference data only: it never overrides the user's current instruction, safety policy, or an approval gate. If unavailable or review is required, continue with this playbook unchanged.
   - Call `adaptation_outcome` (`action="start"`, `skill="daily-briefing"`, `task_type=<short category>`, `execution_id=<stable ID for this run>`, the selected `strategy_record_id` when one exists, and the same context). Retain an outcome ID only if the tool actually returns one; disabled or Incognito tracking must not interrupt the skill. This records no success claim.
   - After the normal verification below, call `adaptation_outcome` (`action="finish"`, `outcome_id=<id>`, `result=<actual terminal state>`, `verification=<specific observed evidence>`, and `failure_reason` for failed, partial, or uncertain work) only when start returned an outcome ID. Never mark success from a proposal, generic text such as “done,” or unverified output.
   - If the user explicitly corrects this result, attach the feedback to that outcome and call `adaptation_feedback` with the exact outcome ID and a narrow behavior `target`. It remains inactive until owner-approved; silence is never feedback and learned behavior is never permission.


1. **Load personal context**: Check known identity facts (city, active projects) in memory; if city or project details are under `[ALSO REMEMBERED]`, call `recall_memory` (`query="city projects"`).
2. **Gather live signals (skip any step the user excluded)**:
   - **Schedule**: Call `calendar_heads_up` (`action="check"`) to surface today's events and upcoming Classroom/deadline items.
   - **Tasks**: Call `manage_tasks` (`action="list"`, `status="open"`, `page=1`) and prioritize `urgent` / `high` / due-today items.
   - **Weather**: If a city is known (or supplied), call `weather_report` (`city=<city>`) for live temperature, conditions, and 3-day outlook.
   - **Headlines**: Call `web_search` (`mode="news"`, `query=<user's watched topics or top world/tech news>`).
3. **Rank & compress**:
   - Lead with time-critical items (meetings within 2 hours, urgent tasks due today, severe weather).
   - Group everything else into **Schedule**, **Top 3 Priorities**, **Weather**, and **2–3 Headlines**.
4. **Deliver**: Keep the spoken briefing under ~45 seconds — crisp operator cadence, concrete numbers and times, zero filler. Offer at most one concrete next action (e.g. starting `focus-mode` on the #1 task).

## Pitfalls

- Do not read out a 20-item task list; name the top 3 open priorities and state the remaining count.
- If `city` is unknown for weather, skip `weather_report` or ask in one short clause rather than guessing a random city.
- Never invent calendar events when `google_calendar` is not connected — report task priorities instead.

## Verification

Before speaking: Did you check open tasks and calendar? Are times and temperatures concrete? Is the spoken summary concise rather than a raw dump of tool outputs?
