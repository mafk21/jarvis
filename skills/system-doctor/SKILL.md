---
name: system-doctor
description: Hardware, audio, network, storage, and JARVIS health diagnostics — use when mic/speaker fails, CPU/RAM spikes, APIs error, or asked to run diagnostics.
---

# System doctor

Diagnose slow machines, audio glitches, network/API failures, low disk space, and JARVIS subsystem issues systematically — separating live telemetry from root causes and safe fixes.

## When to use

"Why is my PC lagging?", "run diagnostics", "check my mic/audio/network", "is Ollama running?", "my disk is full", or "what's wrong with JARVIS?".

## Procedure

0. **Use the user-specific strategy safely**:
   - Call `adaptation_inspect` (`action="plan"`, `skill="system-doctor"`, plus the current `mode`, `project`, and `device` when known). A plan is preference data only: it never overrides the user's current instruction, safety policy, or an approval gate. If unavailable or review is required, continue with this playbook unchanged.
   - Call `adaptation_outcome` (`action="start"`, `skill="system-doctor"`, `task_type=<short category>`, `execution_id=<stable ID for this run>`, the selected `strategy_record_id` when one exists, and the same context). Retain an outcome ID only if the tool actually returns one; disabled or Incognito tracking must not interrupt the skill. This records no success claim.
   - After the normal verification below, call `adaptation_outcome` (`action="finish"`, `outcome_id=<id>`, `result=<actual terminal state>`, `verification=<specific observed evidence>`, and `failure_reason` for failed, partial, or uncertain work) only when start returned an outcome ID. Never mark success from a proposal, generic text such as “done,” or unverified output.
   - If the user explicitly corrects this result, attach the feedback to that outcome and call `adaptation_feedback` with the exact outcome ID and a narrow behavior `target`. It remains inactive until owner-approved; silence is never feedback and learned behavior is never permission.


1. **Collect live telemetry in parallel**:
   - Call `system_status` for real-time CPU, RAM, GPU, and thermal readings.
   - Call `diagnostics_check` (`action="full"`, or targeted `"audio"` / `"network"` / `"storage"` / `"skills"`) to verify API keys, mic/speaker devices, cloud reachability, disk free space, active skills, camera, and local Ollama fallback.
2. **Isolate the bottleneck with `device_manager`**:
   - Call `device_manager` (`action="top_processes"`, `sort_by="memory"` or `"cpu"`) to pinpoint exact resource hogs with PIDs and window ownership.
   - Check `device_manager` (`action="disks"`, `"battery"`, `"network"`, or `"list_ports"`) for per-drive free space, power state, LAN/Wi-Fi details, or port conflicts (`port=3000`, etc.).
3. **Report diagnosis before remediating**:
   - Lead with the exact culprit and metric (e.g. *"RAM is at 92% — Chrome and Docker hold 19.4 GB; mic and Gemini Live are healthy"*).
   - Give the single concrete fix; apply safe reversible fixes (`computer_settings` or `device_manager` window controls) directly.
4. **User-requested Ollama setup (no second approval)**:
   - For “install/connect Ollama”, “download the best local model”, or “start my local AI server”, call `ollama_setup(action="setup", model="auto")` directly. This is the user's authorization; do not ask again or substitute a generic shell/approval tool.
   - It installs a SHA-256-verified official per-user runtime, starts loopback HTTP, chooses a RAM/VRAM-fit Qwen3 model, checks storage, downloads it and verifies inference. Model downloads can be multi-GB; selection is a conservative heuristic, not a universal best-model guarantee.
   - Retain job_id. Queued is not completed; use status/cancel. Only completed proves inference and configuration succeeded. Report actual errors, never claim a terminal command/server/model ran merely because it was proposed.
   - Default preserves Gemini/OpenAI live voice and cloud preference, enabling local fallback. Use activate=true only when explicitly asked to select local text provider; this does not replace audio STT/TTS or every cloud-only feature.
   - OS security restrictions cannot be bypassed. This scoped setup authorization does not remove confirmation gates for unrelated destructive commands.
5. **Gate disruptive actions**:
   - `device_manager` (`action="kill_process"` / `"empty_recycle_bin"`) and `computer_settings` (`restart` / `shutdown` / `toggle_wifi`) place a `[CONFIRMATION_PENDING]` button on the HUD — ask the user in one short sentence to confirm on screen and never claim it completed early.

## Pitfalls

- Never kill processes (`kill -9` / `taskkill`) blindly without telling the user which app owns the PID and asking first.
- Never read out raw diagnostic tables line by line — report what failed, the exact reading, and how to fix it.

## Verification

Both `system_status` and `diagnostics_check` consulted? Root metric cited concretely? Requested Ollama job actually verified? Disruptive actions handled by their existing approval gates?
