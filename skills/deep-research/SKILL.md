---
name: deep-research
description: Multi-wave cited research synthesis — use when comparing options, investigating a topic in depth, weighing trade-offs, or verifying claims across sources.
---

# Deep research

Turn an open-ended or high-stakes question into a concise, cited, bottom-line-first report. Single-query lookups are not deep research — verify decisive claims across independent sources.

## When to use

Comparisons ("X vs Y", "best laptop under…"), architecture/library evaluations, market or technical investigations, purchase advice, or whenever the user says "research", "dig into", or "find out everything about".

## Procedure

0. **Use the user-specific strategy safely**:
   - Call `adaptation_inspect` (`action="plan"`, `skill="deep-research"`, plus the current `mode`, `project`, and `device` when known). A plan is preference data only: it never overrides the user's current instruction, safety policy, or an approval gate. If unavailable or review is required, continue with this playbook unchanged.
   - Call `adaptation_outcome` (`action="start"`, `skill="deep-research"`, `task_type=<short category>`, and the same context). Retain its outcome ID. This records no success claim.
   - After the normal verification below, call `adaptation_outcome` (`action="finish"`, `outcome_id=<id>`, `result=<actual terminal state>`, `verification=<concrete evidence>`, and `failure_reason` for failed, partial, or uncertain work). Never mark success from a proposal or unverified output.
   - If the user explicitly corrects this result, attach the feedback to that outcome and call `adaptation_feedback` with the exact outcome ID and a narrow behavior `target`. It remains inactive until owner-approved; silence is never feedback and learned behavior is never permission.


1. **Scope (at most one question)**: If a missing constraint (budget, platform, deadline) would flip the recommendation, ask ONE compact question. Otherwise state your assumption in one clause and proceed.
2. **Check local context first**: If the topic relates to the user's projects or notes, run `recall_memory` or `rag_docs` (`action="search"`) so the report builds on their actual stack and constraints.
3. **Run multi-wave synthesis**:
   - Call `deep_research` (`query`, `depth="standard"` or `"deep"`) to run parallel grounded sub-queries and gather initial cited waves.
   - Follow up on thin or contested numbers (pricing, benchmarks, release dates) with targeted `web_search` calls (`mode="compare"`, `"price"`, `"news"`, or `"research"`). Cap total searches at ~8.
4. **Cross-verify decisive facts**: Every number, price, or version the recommendation turns on must be backed by a named source; if two credible sources disagree, report the discrepancy explicitly (see `references/source-rubric.md` via `skill_read` when evaluating conflicting evidence).
5. **Synthesize for dual delivery**:
   - `deep_research` and `web_search` automatically mirror detailed results to the HUD Content Panel (do NOT call `show_content` as a tool — it is handled by the HUD).
   - **Spoken reply**: Lead with a 1–2 sentence bottom-line recommendation, followed by only the 2–3 decisive trade-offs and any key unverified gap. Never read URLs or walls of bullet points aloud.
6. **Persist if requested**: If the user wants to keep the report, save it via `manage_notes` (`action="add"`) or `rag_docs` (`action="generate"`).

## Pitfalls

- Do not narrate intermediate search waves aloud — acknowledge once at the start, then deliver one finished synthesis.
- Never fabricate citations, dates, or prices. Label unverified claims plainly.
- Do not call `show_content` directly; HUD mirroring is automatic on `deep_research` and `web_search`.

## Verification

Before speaking: 3+ distinct sources consulted? Clear first-sentence recommendation? Every decisive number traceable to a source? Disagreements or unverifiable items called out?
