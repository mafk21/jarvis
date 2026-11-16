# OS — Complete Upgrade Roadmap — All Missing Skills, In Order

**Branch:** `arena/2cd19056-os` | **Base:** JARVIS foundations
**Principle:** No mix-ups — each phase is isolated, backward-compatible, with its own commit.

---

## Overview — 7 Phases, Dependency-Ordered

```
Phase 1: Voice Foundations        ┐ lowest risk, core loop
Phase 2: Offline & Multi-Provider ┤ providers
Phase 3: Productivity Core        ┤ data layer
Phase 4: Accounts & Remote        ┤ connectivity
Phase 5: Desktop Depth            ┤ OS control
Phase 6: Content & Creativity     ┤ generation
Phase 7: Ecosystem (MCP)          ┘ extensibility
```

Each phase → isolated commit + manual test before next.

---

### Phase 1 — Voice Foundations [START NOW]
**Why first:** touches `main.py` audio loop, foundation for everything else.
- **1.1 Voice Barge-in** — re-enable `EchoGuard` during `jarvis_speaking` in `_listen_audio` callback, count `required_blocks` consecutive positives, then `interrupt()`. Configurable via `config/api_keys.json: barge_in_enabled` (default off until room calibrated, user opt-in via UI).
- **1.2 Grace Window** — after Jarvis finishes, keep `_awake` alive + bypass wake-word for `grace_seconds` (8s default). Follow-ups don't need "Hey Jarvis".
- **1.3 Pause vs Stop** — distinguish `Pause` (mute listening, keep reply/task) vs `Stop` (clear queues, cancel tasks, end turn). Notch/UI button + voice phrases.
- **1.4 Region Capture** — `screen_process` new `angle="region"` + drag selector (`mss` bounding box + Qt rubberband). Trigger via `jarvis --region` keybind or voice "look at this chart".

### Phase 2 — Offline & Multi-Provider
- **2.1 Offline Local Mode** — `main.py` falls back to `core/llm_client.py` (Ollama/LM Studio) when Live unreachable, with local STT/TTS pipeline.
- **2.2 Provider Abstraction** — `core/gemini.py` ladder → `core/provider.py` universal ladder (Anthropic/OpenAI/xAI/DeepSeek/Groq/Together/Ollama) from OpenLive idea.
- **2.3 Local Voice Loop** — WebGPU/CPU VAD/STT/TTS local pipeline, Flow/Dictate hotkeys (Ctrl×2, dictation into focused textbox). No per-minute fees.

### Phase 3 — Productivity Core
- **3.1 Tasks DB** — `memory/productivity.db` SQLite, voice: "add task...", due dates, list/search/complete/reopen/archive/pagination (20/page).
- **3.2 Notes DB** — searchable notes (title+content), archive/restore, isolated from auto-memory.
- **3.3 Lecture Notes** — continuous mic capture → live transcribe → summary/key points/homework on "stop the notes".
- **3.4 Routines** — "when I say study mode, close Discord, open notes, 50m timer" → single trigger. Stored in `memory/routines.json`.
- **3.5 Checkpoints** — encrypted local checkpoints reopen folders/apps/pages with review step.

### Phase 4 — Accounts & Remote
- **4.1 Account Center** — Composio-style: Gmail, Calendar, Classroom, Drive, GitHub, Trello, Slack, Notion, Discord OAuth, per-account Ask/Full/ReadOnly/Paused.
- **4.2 Calendar Heads-ups** — 10m before events, 1d+2h before Classroom due, via `system_monitor` style loop.
- **4.3 Telegram Remote** — BotFather → pairing code → message tasks from anywhere (`/stop` cancels). Alongside LAN dashboard.
- **4.4 Internet Relay Option** — hosted proxy alternative (user opt-in) for non-technical remote.

### Phase 5 — Desktop Depth
- **5.1 Accessibility Tree** — AT-SPI (Linux) / UI Automation (Windows) press buttons by name in Discord/VS Code/Electron.
- **5.2 Shell + Background Agent** — bash/PowerShell execution + long jobs (many-step sites/forms) run in background while chatting.
- **5.3 Smart Home** — `smart_home/` with Tuya/MQTT plugins (tinytuya, paho-mqtt already in requirements).
- **5.4 Diagnostics Health Window** — what works/how to fix, microphone/speaker/key/connectivity checks.
- **5.5 Music & Selection** — Spotify `next/prev/what's playing`, `summarize selection`, `translate this`.

### Phase 6 — Content & Creativity
- **6.1 Web Studio** — local dev server + Chrome preview + SEO auditor + 9 theme presets.
- **6.2 GitHub Automation** — repo/PR/commit via `github_token`.
- **6.3 Goal-Driven Browser** — risk-based permission policy (low/medium/high), safe messaging review.
- **6.4 RAG & Document Generation** — Obsidian vault sync, file_processor → RAG index, generate docs.
- **6.5 Image Generation** — "make a picture..." via Gemini imagen or local SD.
- **6.6 Career Helpers** — LinkedIn agent, sysadmin diagnostic hub, voice KB.

### Phase 7 — Ecosystem
- **7.1 MCP Adapter** — any MCP server by URL or local command → auto tools, keeping `.py` plugin system.
- **7.2 Plugin Marketplace** — one-click install, versioned, isolated.
- **7.3 Hosted Auth Alternative** — email OTP + daily quota, no user API key paste (opt-in).

---

## Progress

| Phase | Status | Commit |
|-------|--------|--------|
| 1     | ✅ DONE | Phase 1 — barge-in + grace + pause/stop + region |
| 2     | ✅ DONE | Phase 2 — provider abstraction + offline fallback + local STT/TTS scaffold |
| 3     | ✅ DONE | Phase 3 — tasks/notes/lecture/routines/checkpoints (productivity.db) |
| 4     | ✅ DONE | Phase 4 — accounts/remote/telegram/relay/calendar heads-ups |
| 5     | ✅ DONE | Phase 5 — accessibility/shell BG agent/smart home/diagnostics/music |
| 6     | ✅ DONE | Phase 6 — web studio/github/browser/RAG/image/career |
| 7     | ✅ DONE | Phase 7 — MCP adapter/marketplace/hosted auth |

## Notes
- No skill removed; all additive.
- Each phase preserves backward compat with existing `config/api_keys.json`.
- Manual test checklist per phase before merge.
