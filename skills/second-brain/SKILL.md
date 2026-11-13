---
name: second-brain
description: Personal knowledge vault and screen-memory recall — use when searching past notes, local docs, or what was on screen earlier, or synthesizing grounded docs.
---

# Second brain & screen recall

Search across all three local memory layers — personal facts, saved notes/vault documents, and historical screen captures — before answering questions about the user's past work or generating grounded documents.

## When to use

"What was that link/error I saw on screen earlier?", "search my notes/Obsidian vault for…", "what did we decide about project X?", "index my docs folder", or "write a spec based on my notes".

## Procedure

0. **Use the user-specific strategy safely**:
   - Call `adaptation_inspect` (`action="plan"`, `skill="second-brain"`, plus the current `mode`, `project`, and `device` when known). A plan is preference data only: it never overrides the user's current instruction, safety policy, or an approval gate. If unavailable or review is required, continue with this playbook unchanged.
   - Call `adaptation_outcome` (`action="start"`, `skill="second-brain"`, `task_type=<short category>`, `execution_id=<stable ID for this run>`, the selected `strategy_record_id` when one exists, and the same context). Retain an outcome ID only if the tool actually returns one; disabled or Incognito tracking must not interrupt the skill. This records no success claim.
   - After the normal verification below, call `adaptation_outcome` (`action="finish"`, `outcome_id=<id>`, `result=<actual terminal state>`, `verification=<specific observed evidence>`, and `failure_reason` for failed, partial, or uncertain work) only when start returned an outcome ID. Never mark success from a proposal, generic text such as “done,” or unverified output.
   - If the user explicitly corrects this result, attach the feedback to that outcome and call `adaptation_feedback` with the exact outcome ID and a narrow behavior `target`. It remains inactive until owner-approved; silence is never feedback and learned behavior is never permission.


1. **Pick the right recall layer (run 2+ when uncertain where it lives)**:
   - **Previously studied subjects**: `topic_learning` (`action="search"`, `query="..."`), then `read` for cited notes and review status. For requests to learn a new subject, use the `topic-learning` skill rather than only saving a short personal fact.
   - **Unified Brain & Forever Timeline (`brain_control` / `recall_memory`)**: Call `recall_memory` (`query="..."`) or `brain_control` (`action="search" | "timeline" | "outputs" | "ingest_file"`) to search personal memories, uploaded Brain knowledge files, months of spoken/typed/Telegram Forever Timeline turns, and past generated reports in one shot.
   - **What appeared visually on screen (OCR + window titles)**: Call `screen_memory_search` (`query="..."`) for error messages, URLs, slides, code snippets, or chats the user viewed earlier.
   - **Saved notes**: Call `manage_notes` (`action="search"`, `query="..."`).
   - **Local folders / Obsidian vaults**: Call `rag_docs` (`action="search"`, `query="..."`). If no RAG index exists yet or the user specifies a folder, run `rag_docs` (`action="index"`, `path="<folder>"`) first, then `action="search"`.
   - **Single known file**: Call `file_processor` (`file_path="..."`) directly.
2. **Synthesize with provenance**:
   - Name where each fact came from (e.g. *"from Note #14"*, *"from `docs/architecture.md`"*, or *"from your VS Code window at 14:20"*).
   - When asked to produce a polished artifact, call `rag_docs` (`action="generate"`, `prompt=...`, `out=...`) or `manage_notes` (`action="add"`).
3. **Store durable facts**: If the user shares a new enduring project decision or preference, persist it silently via `save_memory`.

## Pitfalls

- Never tell the user "I don't have access to what you were looking at earlier" without checking `screen_memory_search` first.
- Never conflate retrieved local notes with guesses — if a detail is missing from all memory layers, state that plainly.

## Verification

Did you check the matching memory layer (`recall_memory`, `screen_memory_search`, `manage_notes`, `rag_docs`)? Is every retrieved claim attributed to its local source?
