import platform as _platform
import subprocess as _subprocess

# ── Default background subprocesses to CREATE_NO_WINDOW on Windows ───────────
# Hidden helper calls (git, ffprobe, powershell WMI queries, etc.) should not
# flash console windows, EXCEPT when JARVIS explicitly launches a visible user
# app or interactive console (visible_window=True or CREATE_NEW_CONSOLE).
if _platform.system() == "Windows":
    _OrigPopen = _subprocess.Popen
    _subprocess._OrigPopen = _OrigPopen  # type: ignore[attr-defined]
    _CREATE_NEW_CONSOLE = getattr(_subprocess, "CREATE_NEW_CONSOLE", 0x00000010)

    class _Popen(_OrigPopen):
        def __init__(self, args, **kw):
            visible = bool(kw.pop("visible_window", False))
            flags = int(kw.get("creationflags", 0) or 0)
            if not visible and not (flags & _CREATE_NEW_CONSOLE):
                kw["creationflags"] = flags | _subprocess.CREATE_NO_WINDOW
                kw.pop("startupinfo", None)   # drop any stale/shared STARTUPINFO
            super().__init__(args, **kw)

    _subprocess.Popen = _Popen


# ── Console must survive non-UTF-8 code pages ────────────────────────────────
# Every status line in this file carries an emoji, and on a legacy Windows
# console the active code page is the system one — cp1254 in Turkey, cp1251 in
# Russia, cp932 in Japan. Printing an emoji there raises UnicodeEncodeError, and
# because most of these prints sit inside the receive loop it takes the session
# down on startup. Reconfiguring to UTF-8 with a replacement fallback costs
# nothing and makes the app launch the same way in every locale.
import sys as _sys

for _stream in ("stdout", "stderr"):
    try:
        _s = getattr(_sys, _stream, None)
        if _s is not None and hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass          # pythonw / redirected pipes / anything exotic — never fatal

# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import os
import re
import threading
import time
import json
import sys
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path

import sounddevice as sd
import numpy as np
from google import genai
from google.genai import types
from ui import JarvisUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
    save_session_summary, pop_last_session,
    search_memory, set_trim_notifier, remember,
)

# The file-backed tools (open_app, web_search, browser_control, …) are no longer
# imported or declared here — they self-describe via a TOOL dict in their own
# actions/*.py file and are auto-discovered by core.action_loader at startup.
# Only tools that are tied to live-session state stay inline in this file
# (screen_process, close_camera, save_memory, manage_monitor, shutdown_jarvis,
# system_status).
from actions.screen_processor  import _capture_camera, _capture_screen
from actions.system_monitor    import SystemMonitor, get_system_status
from actions.proactive         import ProactiveEngine
from actions.background_monitor import (
    add_monitor, remove_monitor, list_monitors, check_all as monitor_check_all,
)
from core.heartbeat            import HeartbeatEngine, HeartbeatLevel
from core.screen_memory        import (get_screen_memory, screen_memory_search,
                                       CAPTURE_INTERVAL_SEC)
from core.multi_channel        import (get_gateway, start_webhook, stop_webhook,
                                       multi_channel)
from core.subagents            import get_subagent_manager, subagent
from core.gws_pack             import gws_pack
from core.session_recycle      import (
    SessionRecycler, parse_go_away_seconds,
    CHECK_INTERVAL_SEC as RECYCLE_CHECK_SEC,
)
from core.connection_diagnostics import (
    user_message as _connection_user_message,
    write_failure as _write_connection_failure,
)
from core.live_errors import (
    flatten_error_text as _flatten_error_text,
    is_realtime_send_stall as _is_realtime_send_stall,
    leaf_errors as _leaf_errors,
)
from actions.web_search        import _news as _fetch_news_sync
from memory.config_manager     import (
    get_brief_enabled, get_media_resolution, get_persona, get_proactive_audio_enabled,
    get_push_to_talk_enabled, get_thinking_enabled, get_turn_tuning, get_voice,
    get_wake_word_enabled, save_wake_word_enabled,    get_input_device, get_output_device,
    get_barge_in_enabled, get_grace_period, save_barge_in_enabled, save_grace_period,
)
from core                     import gemini as _gemini
from core.plugin_loader        import discover_plugins
from core                      import undo as undo_stack
from core                      import confirm as confirm_gate
from core                      import update_manager
from core                      import audio_devices
from core.action_loader        import discover_actions, sanitize_tool_parameters
from core.echo                 import EchoGuard, is_voiced_speech, speech_band_level
from core.viseme               import VisemeStream
from core.wake_word            import (
    WakeWordDetector, is_ready as wake_is_ready, install_and_download as wake_install,
)
from core.loop_safety          import (
    out_put_drop_oldest, throttled_loop_exception_handler,
)
from core.skill_loader         import discover_skills

# How long the assistant stays awake with no user speech before it auto-sleeps
# again (wake-word mode only).
WAKE_SLEEP_TIMEOUT = 120.0   # seconds (2 minutes)

def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
# The conversation's model. A NAME, not a decision: the ladder lives in
# core/gemini.py and this is only whichever rung is currently in use, kept here
# as a module attribute because plugins read it (chat_takeover asks main for it
# so that upgrading the assistant upgrades the plugin too).
#
# It is reassigned on every connect, so a model that runs out of quota is
# stepped over and the assistant keeps talking instead of failing to start.
# gemini-3.1-flash-live-preview SHUTS DOWN 2026-11-17 (Google deprecation);
# gemini-3.8-live is its GA replacement. Ladder lives in core/gemini.py.
LIVE_MODEL          = "models/gemini-3.8-live"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000 
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

# RMS below which 16-bit PCM is treated as room silence; above _LEVEL_FULL it
# reads as a full-height waveform. Tuned so ordinary speech lands mid-range and
# the bars still move for a quiet talker — language- and device-independent.
_LEVEL_FLOOR = 60.0
_LEVEL_FULL  = 2600.0


def _pcm_level(samples) -> float:
    """Map a block of int16 PCM samples to a 0.0–1.0 loudness level for the HUD
    waveform. Returns 0.0 on empty/invalid input so it can never raise."""
    try:
        x = np.asarray(samples, dtype=np.float32)
        if x.size == 0:
            return 0.0
        rms = float(np.sqrt(np.mean(x * x)))
    except Exception:
        return 0.0
    if rms <= _LEVEL_FLOOR:
        return 0.0
    return min(1.0, (rms - _LEVEL_FLOOR) / (_LEVEL_FULL - _LEVEL_FLOOR))


# ── Viseme extraction ─────────────────────────────────────────────────────────
# The avatar's mouth used to be driven by one RMS value per ~200 ms write batch,
# which is five updates a second averaged over a fifth of a second — it could
# only ever flap. These read the *shape* of each 20 ms slice straight from the
# spectrum of the audio being played, so no transcript, no forced alignment and
# no language assumption: it works the same for Turkish and English.
#
# Two numbers come out. Openness tracks the first formant — F1 climbs as the jaw
# drops, so /a/ reads open and /i/ or /u/ read closed. Width tracks the second —
# F2 is high for spread vowels (/i/, /e/) and low for rounded ones (/u/, /o/).
# Extra time beyond the device's reported output latency before the microphone
# is trusted again: covers room decay and the speaker's own settling.
_TAIL_MARGIN = 0.25

_VIS_WIN = 1024        # ~43 ms analysis window at 24 kHz: enough for formants
_VIS_HOP = 480         # 20 ms between frames, i.e. 50 shapes a second

# Delay from handing the first bytes of a reply to an already-running output
# stream to hearing them: one callback period, plus whatever the DAC adds.
_FIRST_SOUND = CHUNK_SIZE / RECEIVE_SAMPLE_RATE      # ~43 ms
# How far past the device's own buffer the mouth's timeline may drift before it
# is re-anchored. The buffer is the hard limit on how much audio can be queued
# ahead, so anything beyond it plus a margin for clock error is impossible.
_CURSOR_SLACK = 0.15

# Erring early is the safe direction. A viewer tolerates a mouth that moves
# slightly before the sound far better than one that moves after it — the
# broadcast limits are about 45 ms of lag against 125 ms of lead — so where
# this is uncertain it is biased to lead.


def _pcm_visemes(samples, sr: int = 24000):
    """Slice a PCM block into (level, openness, width) frames, one per 20 ms.

    Returns [] on anything unexpected — the mouth falls back to loudness-only
    articulation rather than the caller having to handle an error.
    """
    try:
        x = np.asarray(samples, dtype=np.float32)
        if x.size < _VIS_WIN:
            return []
        win = np.hanning(_VIS_WIN).astype(np.float32)
        freqs = np.fft.rfftfreq(_VIS_WIN, 1.0 / sr)
        b_f1_lo = (freqs >= 150) & (freqs < 450)     # F1 of close vowels
        b_f1_hi = (freqs >= 450) & (freqs < 1100)    # F1 of open vowels
        b_f2_bk = (freqs >= 600) & (freqs < 1300)    # F2 of rounded vowels
        b_f2_fr = (freqs >= 1700) & (freqs < 3200)   # F2 of spread vowels
        b_hiss = (freqs >= 3800) & (freqs < 8000)    # fricatives

        # One frame per hop across the *whole* block. Stepping only while a full
        # window fits stopped 1024 - 480 samples short of the end, so a 200 ms
        # batch yielded 160 ms of schedule: the mouth ran out of frames before
        # the audio ran out of sound, and each batch no longer lined up with the
        # end of the one before it. Losing 20 % of every batch is most of why
        # the mouth did not track the words.
        out = []
        for start in range(0, x.size, _VIS_HOP):
            # The level gates closures, so it is measured over exactly this
            # 20 ms and never looks ahead. The spectrum needs a longer window
            # to resolve formants and may be short-filled at the very end.
            level = _pcm_level(x[start:start + _VIS_HOP])
            seg = x[start:start + _VIS_WIN]
            if seg.size < _VIS_WIN:
                seg = np.concatenate([seg, np.zeros(_VIS_WIN - seg.size,
                                                    dtype=np.float32)])
            if level <= 0.0:
                out.append((0.0, 0.0, 0.0))
                continue
            mag = np.abs(np.fft.rfft((seg - seg.mean()) * win))
            f1l, f1h = float(mag[b_f1_lo].sum()), float(mag[b_f1_hi].sum())
            f2b, f2f = float(mag[b_f2_bk].sum()), float(mag[b_f2_fr].sum())
            hiss = float(mag[b_hiss].sum())

            openness = f1h / (f1l + f1h + 1e-6)
            width = (f2f - f2b) / (f2f + f2b + 1e-6)
            # A wide-open jaw physically cannot purse, so openness damps width.
            # /a/ has a low enough F2 to read as "rounded" on the bands alone;
            # letting openness suppress the width term is what keeps an open
            # vowel from pursing.
            width *= (1.0 - openness) ** 0.8
            # Fricatives are formed with a nearly closed mouth.
            h = hiss / (f1l + f1h + f2b + f2f + hiss + 1e-6)
            openness *= 1.0 - 0.65 * min(1.0, h * 2.5)
            out.append((level,
                        float(min(1.0, max(0.0, openness))),
                        float(min(1.0, max(-1.0, width)))))
        return out
    except Exception:
        return []


def _describe_tools(declarations) -> str:
    """One line per capability, straight from the live tool declarations.

    Derived rather than written down: the action and plugin registries are
    discovered at startup, so whatever the user has installed is what the model
    is told it can do. Adding a plugin extends this by itself, and removing one
    stops the model from claiming an ability it no longer has.
    """
    lines = []
    for d in declarations or ():
        try:
            name = d.get("name") if isinstance(d, dict) else getattr(d, "name", None)
            desc = (d.get("description") if isinstance(d, dict)
                    else getattr(d, "description", "")) or ""
        except Exception:
            continue
        if not name:
            continue
        desc = " ".join(str(desc).split())
        lines.append(f"- {name}: {desc[:150]}" if desc else f"- {name}")
    return "\n".join(lines)


def _describe_limits(has_vision: bool, has_mic: bool) -> str:
    """The other half of self-knowledge: what is out of reach, and why.

    Derived from how the program is actually built, not from a list of refusals.
    A model that knows its boundaries stops improvising around them, and stating
    them as architecture rather than as rules keeps the answer honest in any
    language.
    """
    out = [
        "- Anything not listed above is outside your reach. Say so in one clause "
        "and offer the nearest thing you can actually do — never mime an action "
        "you cannot take, and never report a result you did not get.",
        "- You act on this machine only. You cannot reach the user's other "
        "devices, accounts or hardware except through the tools listed above.",
        "- You remember what is in the memory block and what has been said this "
        "session. Anything else you were told before is gone unless it was saved.",
    ]
    if has_vision:
        out.append(
            "- Your sight is not continuous. You see nothing until you call a "
            "vision tool, and then only that single frame at that moment — you "
            "cannot watch, monitor or notice something changing on screen.")
    else:
        out.append("- You have no sight at all in this build.")
    if has_mic:
        out.append(
            "- You hear nothing while the microphone is muted, and you cannot "
            "unmute it yourself.")
    return "\n".join(out)


def _render_prompt(template: str, values: dict) -> str:
    """Fill {tokens} in the prompt template.

    A plain replace rather than str.format: the file is meant to be edited by
    hand, and a stray brace in someone's own wording must never take the app
    down at startup.
    """
    out = template or ""
    for key, val in values.items():
        out = out.replace("{" + key + "}", str(val))
    return out


def _get_api_key() -> str:
    try:
        from memory.config_manager import get_api_key
        key = get_api_key()
        if key:
            return key
    except Exception:
        pass
    try:
        with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = str(json.load(f).get("gemini_api_key") or "")
        if raw.startswith("enc:v1:"):
            from core.security_vault import decrypt_secret
            return decrypt_secret(raw)
        return raw
    except Exception:
        return ""


def _get_openai_key() -> str:
    try:
        from memory.config_manager import get_openai_key
        key = get_openai_key()
        if key:
            return key
    except Exception:
        pass
    try:
        with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = str(json.load(f).get("openai_api_key") or "")
        if raw.startswith("enc:v1:"):
            from core.security_vault import decrypt_secret
            return decrypt_secret(raw)
        return raw
    except Exception:
        return ""


def _resolve_live_engine(skip_engine: str = "") -> str:
    try:
        from memory.config_manager import resolve_cloud_engine
        return resolve_cloud_engine(skip_engine=skip_engine)
    except Exception:
        gk = _get_api_key()
        ok = _get_openai_key()
        if ok and not gk:
            return "openai"
        return "gemini"


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )


def _load_soul_context() -> str:
    """Return canonical Soul context when enabled, otherwise preserve legacy behavior."""
    try:
        from core.soul.service import build_runtime_context
        return build_runtime_context()
    except Exception:
        return ""


_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

# Transcript chunks shorter than this may legitimately repeat ("evet, evet"),
# so only longer ones are treated as duplicates.
_REPEAT_MIN = 12


def _is_repeat_chunk(txt: str, buf: list) -> bool:
    """True if this transcript chunk has already been seen this turn.

    Guards against the API re-sending the tail of a response across the several
    turn_completes a tool-using turn produces.
    """
    if len(txt) < _REPEAT_MIN:
        return bool(buf) and txt == buf[-1]
    joined = " ".join(buf)
    return txt in joined

def _clean_transcript(text: str) -> str:
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()


def _inject_inbound(jarvis, channel_id: str, sender: str, text: str) -> None:
    """Inject an inbound multi-channel message into JARVIS's Live session.

    Called from the webhook server thread — uses run_coroutine_threadsafe to
    schedule on the main event loop.
    """
    session = jarvis.session
    if not session:
        print(f"[MultiChannel] Dropped inbound (no session): {channel_id}/{sender}")
        return

    prefixed = f"[{channel_id}] {sender}: {text}"

    async def _deliver():
        try:
            await session.send_client_content(
                turns={"role": "user", "parts": [{"text": prefixed}]},
                turn_complete=True,
            )
            jarvis.ui.write_log(f"[{channel_id}] {sender}: {text[:60]}")
        except Exception as e:
            print(f"[MultiChannel] Inject error: {e}")

    try:
        loop = jarvis._loop
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(_deliver(), loop)
    except Exception as e:
        print(f"[MultiChannel] Inject schedule error: {e}")

TOOL_DECLARATIONS = [
    # ── Inline tools ─────────────────────────────────────────────────────────
    # These stay here (rather than in an actions/*.py TOOL dict) because their
    # handling is woven into live-session state — vision capture/injection,
    # camera stream, memory writes, the monitor engine, and shutdown. All other
    # tools live in their own action file and are auto-discovered by
    # core.action_loader (see JarvisLive.__init__).
    {
        "name": "skill_read",
        "description": (
            "Reads a SKILL.md skill's instructions, or one file bundled with it. "
            "Your prompt's [SKILLS] block lists every installed skill by name and "
            "description. When a task matches a skill's description, call this "
            "BEFORE starting and follow its instructions — skills carry the "
            "step-by-step procedures for recurring tasks. "
            "Call with just 'name' to load the instructions. "
            "Add 'path' (relative, e.g. 'references/details.md') to open a file "
            "the instructions point at. This tool only reads; bundled scripts are "
            "run through your shell tool."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "name": {
                    "type": "STRING",
                    "description": "Skill name exactly as listed in [SKILLS] (folder name)",
                },
                "path": {
                    "type": "STRING",
                    "description": "Optional file inside the skill folder, e.g. 'references/x.md'",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "skill_manage",
        "description": (
            "Propose, approve, roll back, inspect reliability, or list SKILL.md skills. "
            "CREATE when a task needed 5+ tool calls or careful sequencing and will "
            "plausibly happen again: ask the user in ONE short line first, unless "
            "they already told you to save it ('remember how you…'). "
            "UPDATE when a skill you followed was wrong, stale or incomplete — "
            "supply the full corrected body; fixing a skill you found lacking is "
            "your job, not a complaint to report. "
            "LIST to show what is installed. "
            "name = lowercase-with-hyphens folder name; description = what it does "
            "AND when to use it (the trigger); body = markdown with Instructions, "
            "Pitfalls and Verification sections. One-offs never become skills."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "create | update | approve | rollback | reliability | list",
                },
                "name": {
                    "type": "STRING",
                    "description": "Skill (folder) name, lowercase-with-hyphens",
                },
                "description": {
                    "type": "STRING",
                    "description": "create/update: trigger line — what it does and when to use it",
                },
                "body": {
                    "type": "STRING",
                    "description": "create/update: full SKILL.md body (Instructions, Pitfalls, Verification)",
                },
                "backup": {
                    "type": "STRING",
                    "description": "rollback: exact backup path returned by a prior approval",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "system_status",
        "description": (
            "Returns real-time system metrics: CPU usage, RAM, GPU load, CPU temperature, "
            "uptime, and process count. Use when the user asks about computer performance, "
            "temperature, memory, or resource usage."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures the screen or webcam image and lets you analyze it. "
            "MUST be called when user asks what is on screen, what you see, "
            "look at camera, analyze my screen, etc. "
            "You have NO visual ability without this tool. "
            "After the image is captured it is sent directly to you — describe what you see and answer the user's question. "
            "When using camera: the live view stays open until user says close it or calls close_camera."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' for display, 'camera' for webcam, 'region' for a cropped bounding box. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"},
                "region": {"type": "OBJECT", "description": "Optional bounding box {x,y,w,h} in screen pixels for region capture.", "properties": {"x": {"type": "NUMBER"}, "y": {"type": "NUMBER"}, "w": {"type": "NUMBER"}, "h": {"type": "NUMBER"}}},
                "x": {"type": "NUMBER", "description": "Region left (alt to region object)"},
                "y": {"type": "NUMBER", "description": "Region top"},
                "w": {"type": "NUMBER", "description": "Region width"},
                "h": {"type": "NUMBER", "description": "Region height"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "close_camera",
        "description": (
            "Closes the live camera view shown on screen. "
            "Call when the user says (in ANY language): close camera, stop camera, "
            "turn off camera, that's creepy, etc."
        ),
        "parameters": {"type": "OBJECT", "properties": {}, "required": []}
    },
    {
        "name": "manage_monitor",
        "description": (
            "Add, remove, or list background monitoring topics. "
            "JARVIS checks these topics once a day and alerts the user when there is a new development. "
            "Use 'add' when the user says 'monitor X', 'track X', 'follow X'. "
            "Use 'remove' when the user says 'stop monitoring X'. "
            "Use 'list' when the user asks what is being monitored. "
            "Do NOT add crypto, financial, or trading topics."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type":        "STRING",
                    "description": "add | remove | list",
                },
                "topic": {
                    "type":        "STRING",
                    "description": "Topic to monitor or stop monitoring (e.g. 'space exploration', 'AI news')",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "heartbeat_ok",
        "description": (
            "The user is happy with the current proactive / heartbeat state. "
            "Call this when the user says 'heartbeat ok', 'stop suggesting', "
            "'quiet for a while', or otherwise asks JARVIS to pause proactive "
            "suggestions. Suggestions stay paused for 30 minutes unless the "
            "user asks again; urgent act-level items can still break through. "
            "This does NOT disable system alerts or background monitoring."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "minutes": {
                    "type": "INTEGER",
                    "description": "How many minutes to pause suggestions (default 30)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "screen_memory_search",
        "description": (
            "Search JARVIS's screen memory — full-text search over OCR text and "
            "accessibility trees captured from your screen. Use when the user asks "
            "about something they saw earlier ('what was that article I was reading', "
            "'find the error message from before', 'what was on my screen at 3pm'). "
            "Leave query empty for the most recent captures."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "Text to search for in screen captures",
                },
                "limit": {
                    "type": "INTEGER",
                    "description": "Maximum results to return (default 10)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "set_language",
        "description": (
            "Set or switch the conversation language. Gemini 3.8 Live natively "
            "supports mid-turn switching across 97 languages — the model detects "
            "the user's language and responds in it automatically. Call this to "
            "explicitly set a language preference (stored in memory for future "
            "sessions) or when the user asks to switch languages. Pass a language "
            "name or code (e.g. 'Turkish', 'tr', 'Spanish', 'es', 'Arabic', 'ar') "
            "or 'auto' for automatic detection."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "language": {
                    "type": "STRING",
                    "description": "Language name, code, or 'auto' for auto-detect",
                },
            },
            "required": ["language"],
        },
    },
    {
        "name": "multi_channel",
        "description": (
            "Multi-channel messaging gateway — send/receive across WhatsApp, "
            "Telegram, Discord, Slack, iMessage and desktop apps. "
            "Actions: 'send' (send via a channel), 'channels' (list registered "
            "channels), 'webhook' (get inbound webhook URL), 'broadcast' (send "
            "to all enabled channels). "
            "Channel IDs: 'desktop' (opens WhatsApp/Telegram desktop app), "
            "'telegram' (Telegram bot). Configure channel webhooks to receive "
            "inbound messages."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "send | channels | webhook | broadcast",
                },
                "channel": {
                    "type": "STRING",
                    "description": "Channel ID (desktop, telegram, ...)",
                },
                "text": {
                    "type": "STRING",
                    "description": "Message text to send",
                },
                "recipient": {
                    "type": "STRING",
                    "description": "Recipient (phone, chat_id, username, ...)",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "subagent",
        "description": (
            "Delegate complex multi-step tasks to a subagent. Use subagent when "
            "a task needs 5+ sequential steps, careful planning, or independent "
            "verification. Actions: 'spawn' (create a subagent with a goal and "
            "optional tool whitelist), 'list' (show all subagents), 'status' "
            "(check a subagent's progress), 'result' (get a completed "
            "subagent's output), 'cancel' (stop a subagent), 'remove' "
            "(delete a finished subagent). The parent (JARVIS) executes all "
            "tools — the subagent provides structure, goal tracking, and "
            "result isolation."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "spawn | list | status | result | cancel | remove",
                },
                "agent_id": {
                    "type": "STRING",
                    "description": "Subagent ID (from spawn) — required for status/result/cancel/remove",
                },
                "goal": {
                    "type": "STRING",
                    "description": "spawn: the goal/task for the subagent",
                },
                "tools": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "spawn: optional whitelist of tool names the subagent may use",
                },
                "max_steps": {
                    "type": "INTEGER",
                    "description": "spawn: maximum steps before auto-complete (default 10)",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "gws_pack",
        "description": (
            "Google Workspace automation via computer_use (Set-of-Mark visual "
            "grounding). Automates Gmail, Google Docs, Google Drive, Google "
            "Calendar through their web UIs — no API keys, no OAuth. Actions: "
            "'gmail_send' (to, subject, body), 'gmail_search' (query), "
            "'docs_create' (title), 'docs_write' (content), 'drive_upload' "
            "(file_path), 'calendar_add' (title, when, description), "
            "'gws_open' (app: gmail|docs|drive|calendar), 'workflow' (name: "
            "send_meeting_notes|save_research_to_drive|schedule_meeting). "
            "Each action captures the screen, detects clickable elements by ID, "
            "and interacts with them. Falls back to human-readable SOPs when "
            "visual grounding is unavailable."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "gmail_send | gmail_search | docs_create | docs_write | drive_upload | calendar_add | gws_open | workflow",
                },
                "to": {
                    "type": "STRING",
                    "description": "gmail_send: recipient email address",
                },
                "subject": {
                    "type": "STRING",
                    "description": "gmail_send: email subject",
                },
                "body": {
                    "type": "STRING",
                    "description": "gmail_send: email body / docs_write: content",
                },
                "query": {
                    "type": "STRING",
                    "description": "gmail_search: Gmail search query",
                },
                "title": {
                    "type": "STRING",
                    "description": "docs_create: document title / calendar_add: event title",
                },
                "content": {
                    "type": "STRING",
                    "description": "docs_write: text to write into the document",
                },
                "file_path": {
                    "type": "STRING",
                    "description": "drive_upload: path to file to upload",
                },
                "when": {
                    "type": "STRING",
                    "description": "calendar_add: event time (e.g. 'tomorrow 3pm')",
                },
                "description": {
                    "type": "STRING",
                    "description": "calendar_add: event description",
                },
                "app": {
                    "type": "STRING",
                    "description": "gws_open: gmail | docs | drive | calendar",
                },
                "name": {
                    "type": "STRING",
                    "description": "workflow: send_meeting_notes | save_research_to_drive | schedule_meeting",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "shutdown_jarvis",
        "description": (
            "Shuts down the assistant completely. "
            "Call this when the user expresses intent to end the conversation, "
            "close the assistant, say goodbye, or stop Jarvis. "
            "The user can say this in ANY language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this when the user explicitly asks you to remember a personal fact. "
            "When adaptive learning is enabled, it may also save stable facts such as name, city, "
            "preferences, relationships, or active projects, but never guesses, transient moods, "
            "weather, reminders, searches, or one-time commands. Preserve names and values in the "
            "user's own language; do not translate them. Do not announce background saves."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity — name, age, birthday, city, job, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies | "
                        "projects — active projects, goals, things being built | "
                        "relationships — friends, family, partner, colleagues | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise factual value, preserving the user's language and spelling"},
                "explicit": {"type": "BOOLEAN", "description": "True only when the user directly asked JARVIS to remember/save this fact"},
            },
            "required": ["category", "key", "value", "explicit"]
        }
    },
    {
        "name": "recall_memory",
        "description": (
            "Look up a fact you have stored about the user but which is NOT in "
            "the memory block of your system prompt. "
            "The prompt lists the keys it did not have room for under "
            "'[ALSO REMEMBERED]' — if the user asks about anything named there, "
            "call this FIRST. "
            "Also call it before saying you do not know something personal, and "
            "when the user asks what you remember about them (leave query empty "
            "for everything). "
            "This is a local file search: it is instant and costs nothing."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": (
                        "Keyword to search for — a name, a topic, a category "
                        "(e.g. 'ayse', 'coffee', 'projects'). "
                        "Leave empty to list everything stored."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "undo",
        "description": (
            "Reverse the last change YOU made to this computer — a file you "
            "moved, renamed, created or wrote, or a setting you changed such as "
            "volume, brightness, dark mode or WiFi. "
            "Call this whenever the user says undo, revert, take it back, put it "
            "back, cancel that, or tells you that you did the wrong thing, in ANY "
            "language. "
            "Use action='list' when they ask what can be undone. "
            "This only covers your own actions — it is not the Ctrl+Z of whatever "
            "application is on screen (that is computer_settings with action 'undo')."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "undo (default) — reverse the last change | list — show what can be undone",
                },
            },
            "required": [],
        },
    },
]

class _ReconnectSignal(Exception):
    """Raised inside the session TaskGroup to force a clean, voluntary reconnect
    (e.g. the user picked a new voice — the voice is fixed at connect time, so
    the session must be rebuilt).

    Carries `keep_context`: True for an ordinary rebuild, where the stored
    resumption handle is replayed and the conversation continues; False when the
    new session must genuinely start clean (see the voice-change note in
    _on_voice_change)."""

    def __init__(self, keep_context: bool = True):
        super().__init__()
        self.keep_context = keep_context


def _is_reconnect_signal(exc: BaseException) -> bool:
    """True if `exc` is a _ReconnectSignal, or a(n) (Base)ExceptionGroup that
    wraps one — TaskGroup bundles child exceptions into a group."""
    if isinstance(exc, _ReconnectSignal):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return any(_is_reconnect_signal(sub) for sub in exc.exceptions)
    return False


def _keep_context_of(exc: BaseException) -> bool:
    """Read `keep_context` off a reconnect signal, unwrapping the group the
    TaskGroup put it in. Defaults to True: an unexpected shape must not silently
    wipe the conversation."""
    if isinstance(exc, _ReconnectSignal):
        return getattr(exc, "keep_context", True)
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            if _is_reconnect_signal(sub):
                return _keep_context_of(sub)
    return True


class JarvisLive:
    def __init__(self, ui: JarvisUI):
        self.ui             = ui
        self._asst_name     = "JARVIS"       # updated each session from config
        self.session              = None
        self.audio_in_queue       = None
        self.out_queue            = None
        self._loop                     = None
        self._is_speaking         = False
        self._speaking_lock       = threading.Lock()
        self._phone_active        = False   # True while phone mic is streaming; pauses PC mic
        self._pending_vision       = None    # (img_bytes, mime_type, question, angle) to inject after tool response
        self._vision_cam_active    = False   # True if camera was opened for vision → auto-close after response
        self._vision_close_pending = False   # True after vision injected; next turn_complete closes camera
        self._vision_last_time     = 0.0     # monotonic time of last screen_process call (cooldown guard)
        self._vision_busy          = False   # True while a vision capture/inject cycle is in flight
        self._interrupted          = False   # True while draining audio after user interrupt
        self._interrupted_at       = 0.0     # monotonic timestamp when _interrupted was armed
        self._last_interrupted_rx  = 0.0     # monotonic timestamp of last discarded old chunk
        self._abort_playback       = threading.Event()  # Queue-drain signal on interrupt (never aborts PortAudio stream)
        # Transcript-driven mouth shapes for the avatar. Fed from the receive
        # loop as words arrive, drained by the playback loop against the audio.
        self._visemes              = VisemeStream()
        self._last_out_logged      = ""      # de-dupes a re-sent transcript tail
        # Push-to-talk
        self._ptt_enabled          = False
        self._ptt_held             = False
        self._ptt                  = None    # core.hotkey.PushToTalk
        self._out_level            = 0.0     # level of the audio being played right now
        self._echo                 = EchoGuard()
        # `stream.write()` returns when the buffer accepts the audio, not when the
        # speaker has finished with it, so sound is still in the room after the
        # speaking flag drops. Streaming the microphone during that gap is how an
        # assistant ends up answering itself. Measured from the device rather than
        # guessed; see _play_audio.
        self._out_latency          = 0.20    # seconds, replaced with the real value
        self._tail_until           = 0.0     # monotonic time the echo tail expires
        # Wall-clock time at which the audio written next will begin to sound.
        # The mouth is scheduled against this, never against "now": batches are
        # handed to the device far faster than they play, so "now" ran the lips
        # ahead of the words and cut every schedule short. 0 = nothing playing.
        self._play_cursor          = 0.0
        self.ui.on_push_to_talk   = self.set_push_to_talk
        self.ui.ptt_hold          = self._on_ptt
        self.ui.on_text_command   = self._on_text_command
        self.ui.on_remote_clicked = self._make_remote_key
        self.ui.on_interrupt      = self.interrupt
        self.ui.on_voice_change   = self._on_voice_change     # voice picker → rebuild session
        self.ui.on_audio_device_change = self._on_audio_device_change
        self.ui.on_integrations_change = self._on_integrations_change
        self.ui.on_incognito_change = self._on_incognito_change
        self.ui.on_experience_change = lambda: self.request_reconnect(
            keep_context=False, reason="presentation style"
        )
        self.ui.retry_live_connection = self.request_connection_retry
        from core.ambient_hotkey import SilentAskHotkey
        self._silent_ask_hotkey = SilentAskHotkey(self.ui.open_silent_ask)
        self._silent_ask_scope = self._silent_ask_hotkey.start()
        self._retry_connection_requested = threading.Event()
        self._reconnect_event: asyncio.Event | None = None
        self._reconnect_keep = True   # False → next rebuild drops the resumption handle

        # ── Session resumption ─────────────────────────────────────────
        # The server issues a resumption handle every few seconds and reissues
        # it as the conversation moves on. Before this, session_resumption was
        # switched ON in the config and the update was never read, so the handle
        # was thrown away and EVERY reconnect — a dropped packet, a voice change,
        # switching microphone — started an empty session. "Unlimited sessions"
        # leaked through exactly this hole.
        #
        # Deliberately in RAM only, never written to disk. Persisting it would
        # make a fresh launch continue yesterday's conversation, which sounds
        # appealing but breaks the session-summary flow: _save_session_summary
        # runs at shutdown and the morning briefing pops it the next day. A
        # conversation that never ends never produces a summary, and the
        # "yesterday we talked about…" line silently disappears.
        self._resume_handle: str | None = None
        self._turn_done_event: asyncio.Event | None = None
        self._dashboard     = None
        self._briefing_sent    = False          # morning briefing fires once per process
        self._sys_monitor      = SystemMonitor()  # persistent cooldown state
        self._proactive        = ProactiveEngine()
        from core.gaming_mode import GamingModeMonitor
        self._gaming_monitor = GamingModeMonitor(
            lambda state: self.ui.write_log(
                "SYS: Gaming Mode active — proactive interruptions paused; direct JARVIS requests remain available."
                if state.get("active") else "SYS: Gaming Mode ended — normal proactive policy restored."
            )
        )
        self._gaming_monitor.start()
        self._heartbeat        = HeartbeatEngine()   # Phase 4: observe/suggest/act + HEARTBEAT_OK + never-nag-twice
        self._screen_memory    = get_screen_memory()   # Phase 7: screen memory (event-driven capture + FTS5 search)
        self._session_recycler = SessionRecycler()     # Phase 13: proactive 15-min WebSocket recycle
        self._reconnect_silent = False                 # True → silent background recycle (no HUD log spam)
        self._proactive_recycle_pending = False        # True across a background recycle handoff
        self._last_user_speech = time.monotonic()  # updated on every user utterance
        self._session_log: list[str] = []          # conversation turns for end-of-session summary

        # Learning loop (Phase 9): census of tool calls in the current window
        # (restarts after 10 min idle) and a once-per-process hint flag — the
        # model is nudged at most ONE time, matching the never-nag-twice rule.
        self._skill_window_tools = 0
        self._skill_window_start  = 0.0
        self._skill_hinted        = False

        self._enhanced_live = True  # proactive audio; auto-disabled if the server rejects it
        self._tuned_live    = True  # turn-taking / media / thinking knobs; same fallback
        self._strip_tool_behavior = False  # strip behavior field if a fallback Live model rejects it
        self._realtime_send_stalls = 0  # consecutive transport stalls before a successful audio send

        _base_dir = Path(__file__).resolve().parent
        _inline_names = {t["name"] for t in TOOL_DECLARATIONS}

        # File-backed tools: every actions/*.py with a TOOL dict, discovered the
        # same way plugins are. Reserved names = the inline tools above, so an
        # action can never shadow one.
        self._action_registry = discover_actions(
            actions_dir=_base_dir / "actions",
            reserved_names=_inline_names,
            logger=lambda msg: print(f"[Actions] {msg}"),
        )

        # Plugins must not collide with either an inline tool or a discovered action.
        _core_names = _inline_names | self._action_registry.names()
        self._plugin_registry = discover_plugins(
            plugins_dir=_base_dir / "plugins",
            core_tool_names=_core_names,
            # Console gets the full boot transcript; the activity log gets only
            # what the user has to know about. Every plugin loading correctly is
            # the expected case and does not belong in their conversation.
            logger=lambda msg: print(f"[Plugins] {msg}"),
            notify=lambda msg: self.ui.write_log(f"SYS: {msg}"),
        )
        self.ui.get_plugins = self._plugin_registry.list_for_ui
        self.ui.get_plugin_settings = self._plugin_registry.settings_schemas  # ⚙ settings tab
        self.ui.request_say = self.plugin_say   # plugins: mid-task speech channel

        # Skills — the open SKILL.md standard (agentskills.io). Metadata enters
        # the prompt through {skills}; bodies load on demand via skill_read.
        # Same never-raise contract as actions/plugins: a broken folder is
        # logged and skipped.
        self._skill_registry = discover_skills(
            skills_dir=_base_dir / "skills",
            logger=lambda msg: print(f"[Skills] {msg}"),
        )

        # Ensure recurring Automations run even in Classic PyQt6 mode (no ApexHudBridge)
        self._classic_auto_scheduler = None
        if getattr(self.ui, "_apex_bridge", None) is None:
            try:
                from core.automations import AutomationScheduler
                self._classic_auto_scheduler = AutomationScheduler(on_log=self.ui.write_log)
                self._classic_auto_scheduler.start()
            except Exception:
                pass

        # Durable condition monitors run in both Classic and APEX modes. The
        # manager itself also emits a native desktop notification; this callback
        # keeps the active conversation/activity log in sync.
        self._long_task_manager = None
        try:
            from core.long_tasks import get_long_task_manager
            self._long_task_manager = get_long_task_manager()
            def _execute_durable_step(tool, params, execution_context=None):
                execution_context = execution_context or {}
                context = {
                    "player": self.ui, "speak": self.speak,
                    "response": None, "session_memory": None,
                    "execution_id": execution_context.get("execution_id"),
                    "cancellation_event": execution_context.get("cancellation_event"),
                }
                if self._action_registry.has(tool):
                    return self._action_registry.run(tool, params, context)
                if self._plugin_registry.has(tool):
                    return self._plugin_registry.run(
                        tool, params, player=self.ui, session_memory=None
                    )
                raise ValueError(
                    f"Tool '{tool}' is not a durable action/plugin. "
                    "Live-session-only tools cannot run after the session disappears."
                )
            self._long_task_manager.set_executor(_execute_durable_step)
            # Affect accepts only evidence-backed application events. The long
            # task manager calls this adapter only for persisted completions;
            # the adapter independently verifies status, ID, and evidence.
            from core.soul.service import record_long_task_completion
            self._long_task_manager.add_notifier(record_long_task_completion)
            if getattr(self.ui, "_apex_bridge", None) is None:
                self._long_task_manager.add_notifier(
                    lambda task: self.ui.write_log(
                        f"SYS: LONG TASK COMPLETE — {task.get('notify_message') or task.get('title')}"
                    )
                )
            self._long_task_manager.start()
        except Exception:
            pass

        # ── Wake word ────────────────────────────────────────────────────────
        # _awake gates the mic (see _listen_audio) and the background speakers.
        # It is True whenever wake word is OFF, so default behaviour is unchanged.
        self._wake_enabled     = get_wake_word_enabled()
        self._awake            = not self._wake_enabled
        self._wake_detector: WakeWordDetector | None = None
        self._wake_sleep_timeout = WAKE_SLEEP_TIMEOUT
        # ── Phase 1: Voice Foundations ───────────────────────────────────
        self._barge_enabled     = get_barge_in_enabled()
        self._grace_until      = 0.0        # monotonic deadline for follow-up without wake word
        self._grace_period      = float(get_grace_period())
        self._paused           = False      # Pause = deaf but reply/task continues
        self._barge_blocks     = 0          # consecutive barge-in positive blocks
        self._barge_score      = 0.0        # leaky syllable-bridging confidence accumulator (triggers >= 2.0)
        self._barge_consonant_hold = 0      # tolerates brief intra-word consonants (/s/, /t/, /k/)
        self._barge_preroll: list[bytes] = []  # candidate voiced blocks held until barge-in confirms
        self._mic_ring: deque[bytes] = deque(maxlen=4)  # 256 ms rolling pre-roll (keeps initial /st/, /w/)
        self._ambient_floor    = 0.0        # adaptive true room floor in 200-3500 Hz (capped at 0.04)
        self._barge_notified   = False      # log once per barge session
        self._barge_open_until = 0.0       # window after barge where PTT is bypassed & quiet voice boosted
        # UI hooks for Phase 1 controls
        self.ui.on_barge_toggle  = self._ui_barge_toggle
        self.ui.on_grace_change  = self._ui_grace_change
        self.ui.on_pause_toggle  = self._ui_pause_toggle
        self.ui.on_stop_all      = self._ui_stop_all
        self.ui.get_barge_state  = lambda: self._barge_enabled
        self.ui.get_grace_period = lambda: self._grace_period
        self.ui.get_pause_state  = lambda: self._paused
        self.ui.get_grace_remaining = lambda: max(0.0, self._grace_until - __import__('time').monotonic()) if self._grace_until else 0.0
        self.ui._on_region_capture = self._ui_region_capture
        # ── Phase 2: Offline & multi-provider ──────────────────────────────
        self._offline_mode = False
        self._offline_q: object = None  # asyncio.Queue when offline
        try:
            from memory.config_manager import get_provider as _gp
            self._provider_name = _gp()
        except Exception:
            self._provider_name = "auto"

        # Restore the saved push-to-talk preference. Doing it here rather than
        # in __init__ means the hotkey thread only exists once there is a
        # session to talk to.
        if get_push_to_talk_enabled():
            try:
                self.set_push_to_talk(True)
            except Exception as e:
                print(f"[JARVIS] ⚠ Push-to-talk unavailable: {e}")
        # UI control surface for the Wake Word settings section.
        self.ui.wake_is_ready    = wake_is_ready          # () -> bool
        self.ui.wake_get_state   = self._wake_state       # () -> dict
        self.ui.on_wake_toggle   = self._ui_wake_toggle   # (enable: bool) -> str
        self.ui.on_wake_manual   = self._ui_wake_manual   # () -> toggle awake/asleep
        self.ui.on_wake_install  = self._ui_wake_install  # () -> (ok, msg)

    # ── Wake word: state machine ─────────────────────────────────────────────

    def _wake_state(self) -> dict:
        # A loaded, running detector is definitively ready; otherwise fall back
        # to the cheap on-disk model-file check (no Model construction).
        ready = bool(self._wake_detector and self._wake_detector.ready) or wake_is_ready()
        return {"enabled": self._wake_enabled, "awake": self._awake, "ready": ready}

    def _ensure_wake_detector(self) -> bool:
        """Load the detector once (model loads on first start). Idempotent."""
        if self._wake_detector is None:
            self._wake_detector = WakeWordDetector(
                on_detect=self._on_wake_detected,
                logger=lambda m: print(f"[Wake] {m}"),
                notify=lambda m: self.ui.write_log(f"SYS: {m}"),
            )
        if not self._wake_detector.ready:
            return self._wake_detector.start()
        return True

    def _on_wake_detected(self) -> None:
        """Called from the detector thread when 'Hey Jarvis' is heard."""
        self.wake(reason="wake word")

    def wake(self, reason: str = "wake word") -> None:
        # Grace window also wakes — follow-up doesn't need "Hey Jarvis"
        if self._awake:
            return
        self._awake = True
        self._paused = False
        self._grace_until = 0.0
        self._last_user_speech = time.monotonic()   # start the auto-sleep clock now
        if not self.ui.muted:
            self.ui.set_state("LISTENING")
        self.ui.write_log(f"SYS: Awake — {reason}.")

    def sleep(self, reason: str = "timeout") -> None:
        if not self._awake:
            return
        self._awake = False
        self._paused = False
        self._grace_until = 0.0
        self.set_speaking(False)
        self.ui.set_state("SLEEPING")
        self.ui.write_log(f"SYS: Sleeping — {reason}. Say 'Hey Jarvis' to wake me.")

    # ── Phase 1: Pause vs Stop, Barge-in, Grace ──────────────────────────
    def _ui_barge_toggle(self, enable=None) -> str:
        if enable is None:
            self._barge_enabled = not self._barge_enabled
        else:
            self._barge_enabled = bool(enable)
        try:
            save_barge_in_enabled(self._barge_enabled)
        except Exception:
            pass
        self.ui.write_log(f"SYS: Barge-in {'on' if self._barge_enabled else 'off'}.")
        return self._barge_enabled

    def _ui_grace_change(self, seconds: int) -> None:
        try:
            seconds = int(seconds)
        except Exception:
            return
        self._grace_period = float(max(0, min(30, seconds)))
        try:
            save_grace_period(int(self._grace_period))
        except Exception:
            pass
        if hasattr(self.ui, '_grace_spin'):
            try:
                if int(self.ui._grace_spin.value()) != int(self._grace_period):
                    self.ui._grace_spin.setValue(int(self._grace_period))
            except Exception:
                pass

    def _ui_pause_toggle(self) -> str:
        """Pause = deaf but keep replying/working. Resume = listen again."""
        if not self._awake:
            self.wake(reason="pause toggle")
            return "listening"
        self._paused = not self._paused
        if self._paused:
            self.ui.set_state("PAUSED")
            self.ui.write_log("SYS: Paused — listening off, tasks continue. Tap again to resume.")
            return "paused"
        else:
            self.ui.set_state("LISTENING" if not self._is_speaking else "SPEAKING")
            self.ui.write_log("SYS: Resumed — listening.")
            return "listening"

    def _ui_stop_all(self) -> None:
        """Stop = hard stop: drain audio, clear queues, end turn."""
        self._paused = False
        self._grace_until = 0.0
        self.interrupt()
        # also clear pending vision / grace
        self._pending_vision = None
        self._vision_busy = False
        self.ui.write_log("SYS: Stopped — all tasks and audio cleared.")
        try:
            self.ui.set_state("LISTENING" if self._awake else "SLEEPING")
        except Exception:
            pass

    def _ui_region_capture(self, x: int, y: int, w: int, h: int) -> None:
        """Called from UI thread when user drags a region. Injects a vision turn."""
        try:
            import asyncio as _aio
            from actions.screen_processor import _capture_region as _cr
            img_b, mime_t = _cr(int(x), int(y), int(w), int(h))
            self._pending_vision = (img_b, mime_t, f"What do you see in this region ({x},{y} {w}x{h})?", "region")
            # show preview
            try:
                self.ui._cam_preview.show_frame(img_b)
                from PyQt6.QtCore import QSizeF as _QS
                cw = self.ui.centralWidget()
                pw = 244
                ph = self.ui._cam_preview.height()
                self.ui._cam_preview.setGeometry(cw.width() - 420 - pw - 12, cw.height() - ph - 28, pw, ph)
                self.ui._cam_preview.show(); self.ui._cam_preview.raise_()
            except Exception:
                pass
            # send as a turn if session exists
            async def _send():
                if getattr(self, 'session', None):
                    try:
                        await self.session.send_client_content(
                            turns={"role": "user", "parts": [{"inline_data": {"data": img_b, "mime_type": mime_t}}, {"text": self._pending_vision[2]}]},
                            turn_complete=True,
                        )
                    except Exception as e:
                        print(f"[Region] send failed: {e}")
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(_send())
            except Exception:
                pass
        except Exception as e:
            print(f"[Region] capture failed: {e}")


    async def _run_offline_mode(self, reason: str = "network error") -> None:
        """Local-LLM fallback when Live is unreachable. Text I/O; voice if STT/TTS installed."""
        self._offline_mode = True
        self._offline_q: asyncio.Queue = asyncio.Queue()
        try:
            from memory.config_manager import get_offline_fallback_enabled
            if not get_offline_fallback_enabled():
                self._offline_mode = False
                return
        except Exception:
            pass
        try:
            self.ui.set_offline(True, reason[:120])
            self.ui.set_state("LISTENING")
        except Exception:
            pass
        print(f"[JARVIS] OFFLINE MODE — {reason} — type to chat via local LLM")
        system_prompt = ""
        try:
            from pathlib import Path as _P
            for cand in [Path("core/prompt.txt"), Path(__file__).parent / "core" / "prompt.txt"]:
                if cand.exists():
                    system_prompt = cand.read_text(encoding="utf-8")[:4000]
                    break
        except Exception:
            pass
        soul_ctx = _load_soul_context()
        try:
            from core.soul.service import reconcile_legacy_prompt
            system_prompt = reconcile_legacy_prompt(system_prompt, soul_ctx)
        except Exception as exc:
            print(f"[Soul] Legacy prompt reconciliation failed safely: {type(exc).__name__}: {exc}")
        if soul_ctx:
            system_prompt = soul_ctx + "\n\n" + system_prompt
        history: list[dict] = []
        if system_prompt:
            history.append({"role": "system", "content": system_prompt})
        try:
            from core.llm_client import ensure_ollama_running
            ensure_ollama_running(timeout=8)
        except Exception:
            pass
        consecutive_fails = 0
        while getattr(self, '_offline_mode', False):
            try:
                text = await asyncio.wait_for(self._offline_q.get(), timeout=18.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            text = (text or "").strip()
            if not text:
                continue
            history.append({"role": "user", "content": text})
            self.ui.set_state("THINKING")
            reply = ""
            try:
                try:
                    from core.provider import text as _pt
                    reply = _pt([text], tier="smart", config={"system_instruction": system_prompt}, timeout_ms=20000, default="")
                except Exception:
                    reply = ""
                if not reply:
                    from core.llm_client import call_llm
                    raw = call_llm(history, timeout=60)
                    reply = (raw.get("content") or "").strip()
                if reply:
                    history.append({"role": "assistant", "content": reply})
                    self.ui.write_log(f"JARVIS (offline): {reply}")
                    self.ui.set_state("SPEAKING")
                    try:
                        from memory.config_manager import get_local_tts_enabled
                        if get_local_tts_enabled():
                            from core.local_voice import speak_text
                            import threading as _th
                            _th.Thread(target=lambda: speak_text(reply), daemon=True).start()
                    except Exception:
                        pass
                    await asyncio.sleep(0.2)
                    self.ui.set_state("LISTENING")
                    consecutive_fails = 0
                else:
                    self.ui.write_log("SYS: (offline) No reply — local model may be down. Try: ollama serve && ollama pull llama3.2")
                    consecutive_fails += 1
            except Exception as e:
                self.ui.write_log(f"SYS: Offline error — {e}")
                consecutive_fails += 1
            if len(history) > 12:
                history = history[:1] + history[-10:]
            if consecutive_fails >= 3:
                self.ui.write_log("SYS: Offline model failing — waiting 15s…")
                await asyncio.sleep(15)
                consecutive_fails = 0

    def request_connection_retry(self) -> None:
        """Interrupt offline/backoff waiting so the owner can retry immediately."""
        self._retry_connection_requested.set()
        self._conn_backoff = 0
        if getattr(self, "_offline_mode", False):
            self._offline_mode = False
            loop = getattr(self, "_loop", None)
            queue = getattr(self, "_offline_q", None)
            if loop is not None and queue is not None:
                try:
                    loop.call_soon_threadsafe(queue.put_nowait, "")
                except RuntimeError:
                    pass
        try:
            self.ui.write_log("NET: Retrying the live AI connection now…")
            self.ui.set_offline(False)
        except Exception:
            pass

    async def _wait_before_reconnect(self, delay: float) -> None:
        remaining = max(0.0, float(delay))
        while remaining > 0 and not self._retry_connection_requested.is_set():
            step = min(0.25, remaining)
            await asyncio.sleep(step)
            remaining -= step
        self._retry_connection_requested.clear()

    def _exit_offline_mode(self):
        if getattr(self, '_offline_mode', False):
            self._offline_mode = False
            try:
                self.ui.set_offline(False)
            except Exception:
                pass
            print("[JARVIS] Exiting offline mode — reconnecting to Live")

    async def _run_sleep_watch(self) -> None:
        """Auto-sleep after the configured silence window (wake-word mode only)."""
        while True:
            await asyncio.sleep(5)
            if not self._wake_enabled or not self._awake:
                continue
            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking:
                continue
            if (time.monotonic() - self._last_user_speech) > self._wake_sleep_timeout:
                self.sleep(reason="no speech for 2 minutes")

    # ── Wake word: UI callbacks (called from the Qt thread) ──────────────────

    def _ui_wake_toggle(self, enable: bool) -> str:
        """Enable/disable wake word from the settings UI. Returns a status token:
        'enabled' | 'disabled' | 'need_download'."""
        if enable:
            if not wake_is_ready():
                return "need_download"
            self._wake_enabled = True
            save_wake_word_enabled(True)
            self._ensure_wake_detector()
            self.sleep(reason="wake word enabled")
            return "enabled"
        else:
            self._wake_enabled = False
            save_wake_word_enabled(False)
            self.wake(reason="wake word disabled")
            return "disabled"

    def _ui_wake_manual(self) -> None:
        """Manual sleep/wake button in the UI."""
        if not self._wake_enabled:
            return
        if self._awake:
            self.sleep(reason="you tapped sleep")
        else:
            self.wake(reason="you tapped wake")

    def _ui_wake_install(self) -> tuple[bool, str]:
        """Download openwakeword + the model (runs in a UI worker thread)."""
        # Triggered by the user pressing the button, so its progress is exactly
        # what they are waiting to see.
        return wake_install(logger=lambda m: print(f"[Wake] {m}"),
                            notify=lambda m: self.ui.write_log(f"SYS: {m}"))

    def plugin_say(self, instruction: str) -> None:
        """
        Thread-safe speech channel for plugins: lets a plugin ask JARVIS to
        say something short WHILE its run() is still executing (plugins block
        their executor thread, so they can't speak through the tool response
        until they finish). The instruction is injected into the Live session
        exactly like a proactive check-in; Gemini phrases it naturally in the
        user's language. Silently a no-op when no session is connected.
        """
        loop = getattr(self, "_loop", None)
        if not loop or not self.session:
            return

        async def _say():
            try:
                await self.session.send_client_content(
                    turns={"role": "user", "parts": [{"text": instruction}]},
                    turn_complete=True,
                )
            except Exception as e:
                print(f"[PluginSay] {e}")

        try:
            asyncio.run_coroutine_threadsafe(_say(), loop)
        except Exception as e:
            print(f"[PluginSay] {e}")

    def request_reconnect(
        self,
        keep_context: bool = True,
        reason: str = "",
        silent: bool = False,
    ):
        """Thread-safe: ask the run loop to tear down and rebuild the Live
        session. Called from the Qt thread or background loop tasks. No-op
        until the async loop and reconnect event exist.

        `keep_context=False` drops the resumption handle so the new session
        starts empty — only for changes the server cannot apply to a resumed
        session. `silent=True` suppresses HUD chat log chatter for routine
        proactive 15-min WebSocket recycles."""
        loop = getattr(self, "_loop", None)
        ev   = self._reconnect_event
        self._reconnect_keep   = keep_context
        self._reconnect_reason = reason
        self._reconnect_silent = silent
        if loop and ev is not None:
            loop.call_soon_threadsafe(ev.set)
        elif ev is not None:
            ev.set()

    def _on_voice_change(self, *_args):
        """Voice picker applied.

        The voice is baked into the session at connect time, so a rebuild is
        required. It is rebuilt WITHOUT the resumption handle on purpose:
        resuming restores the server's own session state, and the safe reading
        is that it restores the voice with it — which would make the picker
        appear to do nothing. Losing context here is acceptable because changing
        voice is a deliberate, rare act; losing it on a dropped packet was not."""
        self.request_reconnect(keep_context=False, reason="new voice")

    def _on_audio_device_change(self, *_args):
        """Microphone or speaker changed. Both streams are opened inside the
        session TaskGroup, so they can only be re-opened by rebuilding it —
        but the conversation is kept, which is the whole reason resumption
        landed before this feature did."""
        self.request_reconnect(keep_context=True, reason="audio device")

    def _on_integrations_change(self, *_args):
        """Connected accounts updated mid-session — refresh system prompt silently."""
        self.request_reconnect(keep_context=True, reason="integrations", silent=True)

    def _on_incognito_change(self, enabled: bool):
        """Apply privacy immediately and discard server-side conversation context.

        Blocking capture/persistence is immediate. A fresh Live session ensures
        context loaded before Incognito was enabled is no longer available.
        Disabling also starts fresh so private-session content cannot cross back.
        """
        self.interrupt()
        self._session_log = []
        self.request_reconnect(
            keep_context=False,
            reason="Incognito on" if enabled else "Incognito off",
        )

    async def _watch_reconnect(self):
        """Session-scoped task: when a voluntary reconnect is requested, raise a
        signal that unwinds the TaskGroup so the run loop rebuilds the session."""
        assert self._reconnect_event is not None
        await self._reconnect_event.wait()
        self._reconnect_event.clear()
        keep   = self._reconnect_keep
        reason = getattr(self, "_reconnect_reason", "") or "settings"
        silent = getattr(self, "_reconnect_silent", False)
        self._reconnect_silent = False
        if not silent:
            self.ui.write_log(
                f"SYS: Applying {reason} — reconnecting"
                + ("..." if keep else " (starting a fresh conversation)...")
            )
        raise _ReconnectSignal(keep_context=keep)

    def _make_remote_key(self):
        """Called from Qt main thread when user presses Remote Control."""
        if self._dashboard is None:
            try:
                from dashboard.server import DashboardServer
                self._dashboard = DashboardServer()
                self._dashboard.set_connect_callback(self._on_phone_connected)
                loop = self._loop
                if not loop or not loop.is_running():
                    raise RuntimeError("JARVIS event loop is not running")
                asyncio.run_coroutine_threadsafe(self._dashboard.serve(), loop)
                asyncio.run_coroutine_threadsafe(self._process_dashboard_commands(), loop)
                self.ui.write_log("SYS: Private LAN dashboard started by explicit request.")
            except Exception as exc:
                self._dashboard = None
                self.ui.write_log(
                    "SYS: Dashboard unavailable. "
                    "Run: pip install fastapi \"uvicorn[standard]\" cryptography "
                    f"({exc})"
                )
                return None
        key    = self._dashboard.new_key()
        url    = self._dashboard.get_url()
        manual = self._dashboard.get_manual_url()
        return url, key, f"{url}/auto-login?key={key}", manual

    def _try_lecture_append(self, text: str):
        try:
            import memory.productivity as _prod
            st=_prod.lecture_status()
            if st.get('active'):
                _prod.lecture_append(text)
        except Exception:
            pass

    def _answer_text_fallback(self, text: str) -> None:
        """Guaranteed reply path when Live WebSocket is still reconnecting or
        unavailable: answers via core.gemini / core.provider REST ladder so a
        typed command never hangs or goes unanswered."""
        reply = ""
        soul_ctx = _load_soul_context()
        sys_hint = (
            soul_ctx + "\n\n[CHANNEL]\nAnswer this typed desktop message directly and concisely."
            if soul_ctx else
            f"You are {self._asst_name}, a sharp, concise AI operating companion. "
            "Answer the user's message directly and helpfully."
        )
        try:
            reply = (
                _gemini.text(
                    text,
                    _gemini.FAST,
                    config={"system_instruction": sys_hint},
                    timeout_ms=20_000,
                )
                or ""
            ).strip()
        except Exception as e1:
            print(f"[TextFallback] Gemini/OpenAI REST fallback failed: {e1}")
        if not reply:
            try:
                from core.provider import text as _prov_text
                reply = (
                    _prov_text(
                        text,
                        config={"system_instruction": sys_hint},
                        timeout_ms=20_000,
                    )
                    or ""
                ).strip()
            except Exception as e2:
                print(f"[TextFallback] Provider fallback failed: {e2}")
        if reply:
            self.ui.write_log(f"{self._asst_name}: {reply}")
            self._session_log.append(f"{self._asst_name}: {reply}")
            try:
                from memory.timeline import append_turn
                append_turn("jarvis", reply, speaker=self._asst_name, channel="text")
            except Exception:
                pass
        else:
            self.ui.write_log(
                "SYS: Live connection is reconnecting — please check your network or API key in Settings."
            )
        if not self.ui.muted and not self._paused:
            self.ui.set_state("LISTENING")

    def _apply_experience_command(self, text: str) -> bool:
        """Apply explicit privacy/personality requests without sending them to a model."""
        normalized = " ".join((text or "").casefold().strip().rstrip(".!?").split())
        incognito_on = {"turn on incognito", "enable incognito", "go incognito", "private session"}
        incognito_off = {"turn off incognito", "disable incognito", "leave incognito", "end private session"}
        if normalized in incognito_on | incognito_off:
            from core.session_privacy import set_enabled
            active = normalized in incognito_on
            set_enabled(active)
            self.ui.write_log(f"SYS: Incognito {'on' if active else 'off'}.")
            self._on_incognito_change(active)
            return True

        from core.experience import load_profile, save_profile
        profile = load_profile()
        personality_aliases = {
            "switch to command": "command", "use command": "command",
            "switch to inventor": "inventor", "use inventor": "inventor",
            "switch to sentinel": "sentinel", "use sentinel": "sentinel",
            "switch to companion": "companion", "use companion": "companion",
            "be less energetic": "command",
        }
        language_aliases = {
            "keep it clean": "clean", "don't swear": "clean", "do not swear": "clean",
            "you can swear around me": "adult", "adult language on": "adult",
            "keep profanity casual": "casual", "casual language": "casual",
        }
        personality = personality_aliases.get(normalized)
        language = language_aliases.get(normalized)
        if personality or language:
            saved = save_profile(
                personality=personality or profile.personality,
                language=language or profile.language,
            )
            self.ui.write_log(
                f"SYS: Presentation set to {saved.personality.title()} · {saved.language.title()}."
            )
            self.request_reconnect(keep_context=False, reason="presentation style")
            return True
        return False

    def _on_text_command(self, text: str):
        text = (text or "").strip()
        if not text:
            return
        if self._apply_experience_command(text):
            return
        # Explicitly typing to JARVIS wakes it if wake-word sleep was active
        if self._wake_enabled and not self._awake:
            self.wake(reason="typed command")
        self._last_user_speech = time.monotonic()
        self._session_log.append(f"User: {text}")
        try:
            from memory.timeline import append_turn
            append_turn("user", text, speaker="You", channel="text")
        except Exception:
            pass
        try:
            from core.companions import detect_and_record_correction
            detect_and_record_correction(text)
        except Exception:
            pass
        self._try_lecture_append(text)

        # Offline mode: queue for local LLM
        if getattr(self, '_offline_mode', False):
            try:
                if self._loop and hasattr(self, '_offline_q') and self._offline_q is not None:
                    asyncio.run_coroutine_threadsafe(self._offline_q.put(text), self._loop)
                    return
            except Exception:
                pass

        # Wait briefly (up to 6s) if the Live WebSocket is mid-connect / recycling
        if not self._loop or not self.session:
            for _ in range(30):
                if self._loop and self.session:
                    break
                time.sleep(0.2)

        if self._loop and self.session:
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    self.session.send_client_content(
                        turns={"role": "user", "parts": [{"text": text}]},
                        turn_complete=True
                    ),
                    self._loop
                )
                fut.result(timeout=8.0)
                return
            except Exception as exc:
                print(f"[JARVIS] Live text send failed ({exc}) — using direct fallback")

        # Live session unreachable: answer immediately via REST/Provider fallback
        self._answer_text_fallback(text)

    def _tail_active(self) -> bool:
        """True while the speakers may still be finishing our last sentence."""
        return time.monotonic() < self._tail_until

    def _in_grace(self) -> bool:
        """Follow-up window after Jarvis stops where wake word is not needed."""
        return self._wake_enabled and not self._awake and time.monotonic() < self._grace_until

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            was_speaking = self._is_speaking
            self._is_speaking = value
        if value:
            self._tail_until = 0.0
            # IMPORTANT: _play_audio calls set_speaking(True) on every ~60 ms
            # output batch. Only reset barge-in accumulators on the rising edge
            # (False -> True), NEVER mid-sentence, or ongoing user speech gets
            # wiped every 60 ms and can never reach the barge-in threshold!
            if not was_speaking:
                self._barge_blocks = 0
                self._barge_score = 0.0
                self._barge_consonant_hold = 0
                self._barge_preroll.clear()
                self._mic_ring.clear()
        else:
            # Hold the guard open across the device's own output latency plus a
            # margin for the room. The microphone is NOT muted during it — the
            # guard still lets a genuine reply through, so answering instantly
            # still works. Only our own echo is dropped.
            self._tail_until = time.monotonic() + self._out_latency + _TAIL_MARGIN
            # Grace window: stay reachable for follow-ups without "Hey Jarvis"
            if self._wake_enabled and self._grace_period > 0:
                self._grace_until = time.monotonic() + self._grace_period
        if not value:
            # The echo history is deliberately NOT cleared here: the tail above
            # still needs it to recognise our own voice. It is dropped when the
            # tail expires. What the guard learned about the room always stays.
            self._out_level = 0.0
        if value:
            if not was_speaking:
                self.ui.set_state("SPEAKING")
        elif self._paused:
            self.ui.set_state("PAUSED")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def set_push_to_talk(self, enabled: bool) -> str:
        """Turn hold-to-talk on or off. Returns the scope actually achieved."""
        from core.hotkey import PushToTalk

        self._ptt_enabled = bool(enabled)
        self._ptt_held = False
        if not enabled:
            if self._ptt is not None:
                self._ptt.stop()
                self._ptt = None
            return "off"

        if self._ptt is None:
            self._ptt = PushToTalk(self._on_ptt)
        scope = self._ptt.start()
        # A window-scoped chord is a real limitation, not a detail — say it once
        # in the log so nobody wonders why it does nothing while another app is
        # focused. Reporting it must never be able to undo the thing it reports.
        try:
            self.ui.write_log(
                f"SYS: Push-to-talk on — hold {self._ptt.label}"
                + ("." if scope == "global"
                   else " (works while this window is focused)."))
        except Exception:
            pass
        return scope

    def _on_ptt(self, held: bool) -> None:
        """Chord pressed or released — may arrive on the hotkey thread."""
        self._ptt_held = held
        if held:
            # Holding the key is also a way to wake it, so push-to-talk works
            # without having to say the wake word first.
            if self._wake_enabled and not self._awake:
                self._awake = True
                self._last_user_speech = time.monotonic()
        try:
            self.ui.set_state("LISTENING" if held else "SLEEPING")
        except Exception:
            pass

    def interrupt(self) -> None:
        """Stop JARVIS mid-speech: drain queued audio and open the mic immediately.

        Crucially, Gemini Live streams audio faster than real-time and often
        sends `turn_complete` seconds before local speaker playback finishes.
        If `_turn_done_event` is ALREADY set, the server has zero remaining
        chunks for the old turn — setting `_interrupted = True` in that state
        would silently discard Gemini's NEXT reply to the user's interruption!
        """
        server_already_done = bool(
            self._turn_done_event and self._turn_done_event.is_set()
        )
        now_mono = time.monotonic()
        if server_already_done:
            self._interrupted = False
            self._interrupted_at = 0.0
        else:
            self._interrupted = True
            self._interrupted_at = now_mono
            self._last_interrupted_rx = now_mono
        self._abort_playback.set()
        q = self.audio_in_queue
        if q:
            drained = 0
            while True:
                try:
                    q.get_nowait()
                    drained += 1
                except Exception:
                    break
            if drained:
                print(f"[JARVIS] ✋ Interrupted — {drained} audio chunks discarded")
        self.set_speaking(False)
        # Barge-in must be instant — kill the tail that set_speaking just armed.
        self._tail_until = 0.0
        self._barge_blocks = 0
        self._barge_score = 0.0
        self._barge_consonant_hold = 0
        self._barge_preroll.clear()
        # Keep mic hot & un-gated for the follow-up phrase after interrupt
        self._barge_open_until = max(
            getattr(self, "_barge_open_until", 0.0), now_mono + 2.5
        )
        # The words we were about to mouth are never going to be spoken now.
        self._visemes.reset()
        self._play_cursor = 0.0     # next batch starts a fresh timeline
        # Cancel active OpenAI Realtime / REST generation immediately on barge-in
        _sess_obj = getattr(self, "session", None)
        _loop_obj = getattr(self, "_loop", None)
        _cancel_fn = getattr(_sess_obj, "cancel_response", None) if _sess_obj else None
        if callable(_cancel_fn) and _loop_obj:
            try:
                asyncio.run_coroutine_threadsafe(_cancel_fn(), _loop_obj)
            except Exception:
                pass
        if self._turn_done_event:
            self._turn_done_event.clear()
        self.ui.write_log("SYS: Interrupted — listening...")

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"role": "user", "parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        # Load customization from config
        try:
            from memory.config_manager import load_api_keys
            _cfg = load_api_keys()
            self._asst_name = (_cfg.get("assistant_name") or "JARVIS").strip()
            selfuser_name = (_cfg.get("user_name") or "").strip()
            _user_name = selfuser_name
        except Exception:
            self._asst_name = "JARVIS"
            _user_name = ""

        try:
            from core.session_privacy import enabled as _incognito_enabled
            _private_session = _incognito_enabled()
        except Exception:
            _private_session = False
        memory     = {} if _private_session else load_memory()
        mem_str    = "" if _private_session else format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        # Identity injection — overrides any hardcoded name in prompt.txt
        # Address form is a property of the language being spoken, so it is
        # stated as a principle rather than a two-language lookup — the model
        # already knows the respectful register of whatever language it is in.
        _addr = (f"ADDRESS: Always call the user '{_user_name}'."
                 if _user_name
                 else 'ADDRESS: Address the user with the ordinary respectful form '
                      'for a superior in the language you are currently speaking — '
                      '"sir" in English, its everyday equivalent in any other '
                      'language. Never an archaic or aristocratic form, and never '
                      'the form from a different language than the one you are '
                      'speaking in this sentence.')
        _persona = get_persona()
        _persona_line = (
            "EDITION: Female interface & vocal persona — composed, articulate, steady female operator presence."
            if _persona == "female"
            else "EDITION: Male interface & vocal persona — calm, authoritative, steady male operator presence."
        )
        identity_ctx = (
            f"[IDENTITY]\n"
            f"Your name is {self._asst_name}. "
            f"Always refer to yourself as {self._asst_name}.\n"
            f"{_persona_line}\n"
            f"{_addr}\n\n"
        )

        # Everything the model is told about *itself* is derived here, not
        # written into prompt.txt: the name comes from config, the platform from
        # the host, the capability list from the registries that were just
        # discovered. Rename the assistant, add a plugin or move to another OS
        # and this follows without anyone editing a prompt.
        _raw_decls = (TOOL_DECLARATIONS
                      + self._action_registry.get_tool_declarations()
                      + self._plugin_registry.get_tool_declarations())
        _all_decls = [
            ({
                **d,
                "parameters": sanitize_tool_parameters(
                    d.get("parameters") or {"type": "OBJECT", "properties": {}},
                    is_root=True,
                ),
            } if isinstance(d, dict) else d)
            for d in _raw_decls
        ]
        _names = {(d.get("name") if isinstance(d, dict) else getattr(d, "name", ""))
                  for d in _all_decls}
        sys_prompt = _render_prompt(sys_prompt, {
            "assistant_name": self._asst_name,
            "platform": f"{_platform.system()} {_platform.release()}".strip(),
            "capabilities": _describe_tools(_all_decls),
            # Level 1 of progressive disclosure: one line per skill (name +
            # trigger description). Bodies load later through skill_read.
            "skills": self._skill_registry.get_listing(),
            "limits": _describe_limits(
                has_vision="screen_process" in _names,
                has_mic=True,
            ),
        })

        soul_ctx = _load_soul_context()
        # Soul and both legacy identity sources are mutually exclusive. Keep
        # operational/tool rules while selecting exactly one personality owner.
        try:
            from core.soul.service import reconcile_legacy_prompt
            sys_prompt = reconcile_legacy_prompt(sys_prompt, soul_ctx)
        except Exception as exc:
            print(f"[Soul] Legacy prompt reconciliation failed safely: {type(exc).__name__}: {exc}")
        parts = [time_ctx, soul_ctx if soul_ctx else identity_ctx]
        if _private_session:
            parts.append(
                "[INCOGNITO SESSION]\nDo not save or recall personal memory, saved chat, screen, or camera context. "
                "Do not offer proactive help. Existing stored data is outside this session.\n"
            )
        # Presentation is user-owned and deliberately separate from edition,
        # capability, and safety. Invalid/missing settings fail to the clean,
        # concise Command profile.
        try:
            from core.experience import prompt_context as _experience_prompt
            parts.append(_experience_prompt())
        except Exception:
            pass
        # Shared by Gemini Live and the OpenAI adapters: retain discoverability after restarts.
        try:
            from core.topic_learning import prompt_index
            study_index = prompt_index()
            if study_index:
                parts.append(study_index)
        except Exception:
            pass
        try:
            from memory.accounts import format_connected_for_prompt
            parts.append(format_connected_for_prompt())
        except Exception:
            pass
        if mem_str:
            parts.append(mem_str)
        try:
            from memory.taste_manager import format_for_prompt
            taste_context = format_for_prompt()
            if taste_context:
                parts.append(taste_context)
        except Exception:
            pass
        try:
            from memory.timeline import format_timeline_for_prompt
            tl_str = format_timeline_for_prompt(recent_limit=8)
            if tl_str:
                parts.append(tl_str)
        except Exception:
            pass
        # Soul imports the behavior interview and learned rules, but custom
        # skills and active specialist scope must remain available in both paths.
        try:
            from core.companions import format_behavior_and_companion_for_prompt
            beh_str = format_behavior_and_companion_for_prompt(
                include_personalization=not bool(soul_ctx)
            )
            if beh_str:
                parts.append(beh_str)
        except Exception:
            pass
        parts.append(sys_prompt)

        # gemini-3.8-live defaults tool calls to ASYNC (NON_BLOCKING); this
        # app's flow executes the tool and answers with its result, which is
        # the legacy blocking contract. Pin it there per Google's migration
        # guide — only on 3.8, older models reject the field on v1beta.
        if self._strip_tool_behavior or ("gemini-3.8" not in LIVE_MODEL and not self._enhanced_live):
            _all_decls = [
                ({k: v for k, v in d.items() if k != "behavior"}
                 if isinstance(d, dict) else d)
                for d in _all_decls
            ]
        elif "gemini-3.8" in LIVE_MODEL:
            _all_decls = [
                ({**d, "behavior": d.get("behavior") or "BLOCKING"}
                 if isinstance(d, dict) else d)
                for d in _all_decls
            ]

        _raw_voice = get_voice()
        _GEMINI_VOICES = {"Charon", "Fenrir", "Puck", "Orus", "Aoede", "Kore", "Leda", "Zephyr"}
        _gemini_voice = _raw_voice if _raw_voice in _GEMINI_VOICES else (
            "Aoede" if get_persona() == "female" else "Charon"
        )

        cfg = dict(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": _all_decls}],
            # Asks the server to issue session-resumption handles. Enabled but
            # NOT yet used: no handle is captured from the resumption update and
            # none is passed back here, so a reconnect starts a fresh session
            # rather than continuing the old one. Left on because the handles
            # cost nothing and are the prerequisite for doing it properly.
            # Hand back the handle captured from the last session_resumption
            # update. `handle=None` is exactly the old behaviour (ask for
            # handles, start fresh), so the first connect of a run is unchanged.
            session_resumption=types.SessionResumptionConfig(
                handle=self._resume_handle
            ),
            # Sliding-window compression: session never dies from a full context
            # window — JARVIS can stay in one conversation for hours
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow(),
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=_gemini_voice
                    )
                )
            ),
        )
        _is38 = "gemini-3.8" in LIVE_MODEL
        if self._enhanced_live:
            # Proactive audio: JARVIS stays silent when speech isn't addressed
            # to it (background chatter, talking to someone else in the room).
            # On gemini-3.8-live proactive audio is ALWAYS ON server-side and
            # the proactivity field is rejected — so it is sent only to the
            # older models where it is still an opt-in.
            # (Affective dialog was dropped: gemini-3.1-flash-live does not
            #  support it, and it never reliably detected tone in practice.
            #  To restore it on a 2.5 native-audio model, add back:
            #  cfg["enable_affective_dialog"] = True )
            if get_proactive_audio_enabled() and not _is38:
                cfg["proactivity"] = types.ProactivityConfig(proactive_audio=True)

        if self._tuned_live:
            cfg.update(self._tuning_config())

        return types.LiveConnectConfig(**cfg)

    def _tuning_config(self) -> dict:
        """The optional knobs, kept apart so one bad field can be dropped wholesale.

        Every one of these is a preview-API field. If a future model release
        stops accepting any of them the connection fails at setup, so the run
        loop turns `_tuned_live` off and reconnects on the plain config rather
        than leaving the user with an assistant that will not start.
        """
        out: dict = {}

        # How long the server waits through a pause before deciding your turn is
        # over. This — not the size of the prompt — is what most of the delay
        # before a reply actually is, and the default has to suit everybody, so
        # it is necessarily cautious.
        turn = get_turn_tuning()
        if turn.get("enabled", True):
            detect = types.AutomaticActivityDetection(
                silence_duration_ms=turn["silence_ms"],
                prefix_padding_ms=turn["prefix_ms"],
            )
            if turn["end_sensitivity"] == "high":
                detect.end_of_speech_sensitivity = types.EndSensitivity.END_SENSITIVITY_HIGH
            elif turn["end_sensitivity"] == "low":
                detect.end_of_speech_sensitivity = types.EndSensitivity.END_SENSITIVITY_LOW
            if turn["start_sensitivity"] == "high":
                detect.start_of_speech_sensitivity = types.StartSensitivity.START_SENSITIVITY_HIGH
            elif turn["start_sensitivity"] == "low":
                detect.start_of_speech_sensitivity = types.StartSensitivity.START_SENSITIVITY_LOW
            out["realtime_input_config"] = types.RealtimeInputConfig(
                automatic_activity_detection=detect)

        # Screenshots and camera frames are tokenised at this resolution and then
        # stay in the session's context. 'medium' keeps on-screen text legible
        # for a fraction of a full-resolution frame.
        res = get_media_resolution()
        if res != "default":
            out["media_resolution"] = {
                "low":    types.MediaResolution.MEDIA_RESOLUTION_LOW,
                "medium": types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
                "high":   types.MediaResolution.MEDIA_RESOLUTION_HIGH,
            }[res]

        # Thinking is left at the server default deliberately. Forcing the budget
        # to zero was measured on gemini-3.1-flash-live over interleaved trials
        # and did not make the first word arrive sooner — this model does not
        # appear to deliberate on the Live path, so pinning the field only adds a
        # way for a future release to behave differently. Set "thinking_enabled"
        # in config/api_keys.json to true to let it reason instead.
        if get_thinking_enabled() and "gemini-3.8" not in LIVE_MODEL:
            # gemini-3.8-live REJECTS thinking_config/level — omit it there
            # (3.8 does interleaved reasoning without the field).
            out["thinking_config"] = types.ThinkingConfig(thinking_budget=-1)

        return out

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        print(f"[JARVIS] 🔧 {name}  {args}")
        self.ui.set_state("THINKING")
        _notify_tool = getattr(self.ui, "notify_tool_call", None)
        if callable(_notify_tool):
            _notify_tool(name)
        _task_id = f"fc-{getattr(fc, 'id', None) or int(time.time() * 1000)}-{name}"
        _notify_start = getattr(self.ui, "notify_tool_start", None)
        if callable(_notify_start):
            _arg_preview = ", ".join(
                f"{k}={str(v)[:28]}" for k, v in list(args.items())[:2]
            )
            _notify_start(_task_id, name, _arg_preview)

        # Learning-loop census: window restarts after 10 quiet minutes so the
        # hint measures one burst of work, not a whole day of chatting.
        _now = time.monotonic()
        if _now - self._skill_window_start > 600.0:
            self._skill_window_tools = 0
        self._skill_window_start = _now
        self._skill_window_tools += 1

        # Enforce scoped tool permissions when a Specialist Companion is active
        try:
            from core.companions import is_tool_allowed_for_active_companion
            _allowed_ok, _deny_msg = is_tool_allowed_for_active_companion(name)
            if not _allowed_ok:
                _nf = getattr(self.ui, "notify_tool_finish", None)
                if callable(_nf):
                    _nf(_task_id, _deny_msg, "failed")
                if not self.ui.muted:
                    self.ui.set_state("LISTENING")
                return types.FunctionResponse(
                    id=fc.id, name=name, response={"result": _deny_msg}
                )
        except Exception:
            pass

        if name in {"save_memory", "recall_memory", "screen_process"}:
            try:
                from core.session_privacy import deny_message, enabled as incognito_enabled
                if incognito_enabled():
                    capability = {
                        "save_memory": "new memories",
                        "recall_memory": "memory recall",
                        "screen_process": "screen and camera capture",
                    }[name]
                    result = deny_message(capability)
                    _nf = getattr(self.ui, "notify_tool_finish", None)
                    if callable(_nf):
                        _nf(_task_id, result, "failed")
                    if not self.ui.muted:
                        self.ui.set_state("LISTENING")
                    return types.FunctionResponse(id=fc.id, name=name, response={"result": result})
            except Exception:
                pass

        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            explicit = bool(args.get("explicit", False))
            if key and value:
                result = remember(key, value, category, manual=explicit)
                print(f"[Memory] 💾 save_memory: {result}")
            _nf = getattr(self.ui, "notify_tool_finish", None)
            if callable(_nf):
                _nf(_task_id, f"{category}/{key}", "completed")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": result if key and value else "Missing memory key or value.", "silent": True}
            )

        loop   = asyncio.get_event_loop()
        result = "Done."

        try:
            if name == "recall_memory":
                # Unified local Brain recall: searches personal memories,
                # uploaded Brain knowledge files, Forever Timeline, and outputs.
                try:
                    from memory.timeline import unified_brain_search
                    result = await loop.run_in_executor(None, lambda: unified_brain_search(args.get("query", ""), limit=8))
                except Exception:
                    result = await loop.run_in_executor(None, lambda: search_memory(args.get("query", ""), limit=8))

            elif name == "skill_read":
                # Skills live on disk as SKILL.md folders; metadata is already in
                # the prompt, this is Level 2/3 — body or a bundled file. Pure
                # read, dictionary-cheap: stays in the loop like recall_memory.
                sname = args.get("name", "")
                spath = args.get("path") or None
                if sname in self._skill_registry.names():
                    result = self._skill_registry.read(sname, spath)
                else:
                    from core.companions import CUSTOM_SKILLS_DIR
                    from core.skill_loader import discover_skills
                    cust_reg = discover_skills(CUSTOM_SKILLS_DIR, logger=lambda _: None)
                    if sname in cust_reg.names():
                        result = cust_reg.read(sname, spath)
                    else:
                        result = self._skill_registry.read(sname, spath)

            elif name == "skill_manage":
                # The learning loop's write path. Validation lives in
                # skill_loader.write() so whatever the model authors passes
                # the next restart's discovery scan by construction.
                action = str(args.get("action", "")).strip().lower()
                if action == "list":
                    result = ("Installed skills:\n" + self._skill_registry.get_listing())
                elif action in ("create", "update"):
                    from core.skill_governance import propose
                    sname = str(args.get("name") or "").strip()
                    desc = " ".join(str(args.get("description") or "").split())
                    body = str(args.get("body") or "").strip()
                    if not desc or not body:
                        raise ValueError("description and body are required")
                    folder = self._skill_registry.skill_dir(sname)
                    folder.mkdir(parents=True, exist_ok=True)
                    proposal = f"---\nname: {sname}\ndescription: {desc}\n---\n\n{body}\n"
                    propose(folder, proposal)
                    result = f"Skill '{sname}' is staged for review. Ask the user to approve it before activation."
                elif action == "approve":
                    from core import confirm as confirm_gate
                    from core.skill_loader import parse_frontmatter
                    from core.skill_governance import approve
                    sname = str(args.get("name") or "").strip()
                    folder = self._skill_registry.skill_dir(sname)
                    proposal_path = folder / "SKILL.md.proposed"
                    fm, body = parse_frontmatter(proposal_path.read_text(encoding="utf-8"))
                    def _approve_skill():
                        existed = sname in self._skill_registry.names()
                        backup = approve(folder)
                        self._skill_registry.write(sname, fm.get("description", ""), body, update=existed)
                        return f"Skill '{sname}' approved and activated." + (f" Backup: {backup}" if backup else "")
                    result = confirm_gate.request(f"skill-approve-{sname}", f"Approve skill {sname}?",
                                                  "Activate the reviewed skill proposal and preserve the previous version for rollback.", _approve_skill)
                elif action == "rollback":
                    from core import confirm as confirm_gate
                    from core.skill_governance import rollback
                    sname = str(args.get("name") or "").strip()
                    folder = self._skill_registry.skill_dir(sname)
                    backup = Path(str(args.get("backup") or ""))
                    result = confirm_gate.request(
                        f"skill-rollback-{sname}", f"Roll back skill {sname}?",
                        "Restore the selected reviewed backup. The current version will stop being active.",
                        lambda: (rollback(folder, backup) or f"Skill '{sname}' rolled back."),
                    )
                elif action == "reliability":
                    from core.skill_governance import reliability
                    result = str(reliability(str(args.get("name") or "")))
                else:
                    raise ValueError("action must be create, update, approve, reliability or list")

            elif name == "undo":
                if str(args.get("action", "")).lower().strip() == "list":
                    items = undo_stack.history()
                    result = ("Things I can undo, most recent first:\n"
                              + "\n".join(f"{i+1}. {t}" for i, t in enumerate(items))
                              ) if items else "I have not changed anything I can undo yet."
                else:
                    result = await loop.run_in_executor(None, undo_stack.undo_last)

            elif name == "screen_process":
                import time as _t_mod
                _now = _t_mod.monotonic()
                _cooldown = 4.0  # seconds — covers echo window after speaking ends
                if self._vision_busy or (_now - self._vision_last_time) < _cooldown:
                    _wait = max(0, _cooldown - (_now - self._vision_last_time))
                    print(f"[Vision] ⏳ Cooldown active ({_wait:.1f}s remaining) — ignoring duplicate call")
                    result = "Vision is still processing the previous request. I will not call this again."
                else:
                    self._vision_busy      = True
                    self._vision_last_time = _now
                    angle     = args.get("angle", "screen").lower()
                    user_text = args.get("text", "What do you see?")
                    # Region capture: angle="region" + region dict or model can pass x/y/w/h flat
                    region = args.get("region")
                    if angle == "region" or region:
                        try:
                            from actions.screen_processor import _capture_region as _cap_reg
                            # support both dict and flat args
                            bx = region if isinstance(region, dict) else {}
                            # also accept flat x,y,w,h top-level
                            for k in ("x","y","w","width","h","height"):
                                if k in args and k not in bx:
                                    bx[k] = args[k]
                            # string "x,y,w,h"
                            if isinstance(region, str) and "," in region:
                                try:
                                    xs = [int(s.strip()) for s in region.split(",")]
                                    if len(xs) == 4:
                                        bx = {"x": xs[0], "y": xs[1], "w": xs[2], "h": xs[3]}
                                except Exception:
                                    pass
                            rx = int(bx.get("x", bx.get("left", 0)))
                            ry = int(bx.get("y", bx.get("top", 0)))
                            rw = int(bx.get("w", bx.get("width", bx.get("h", 800))))
                            rh = int(bx.get("h", bx.get("height", 600)))
                            img_b, mime_t = await loop.run_in_executor(None, lambda: _cap_reg(rx, ry, rw, rh))
                            print(f"[Vision] 🖼️ Region {rx},{ry} {rw}x{rh}: {len(img_b):,} bytes")
                            _stall = "region"
                        except Exception as e:
                            print(f"[Vision] Region failed ({e}) — falling back to full screen")
                            img_b, mime_t = await loop.run_in_executor(None, _capture_screen)
                            _stall = "screen"
                    elif angle == "camera":
                        img_b, mime_t = await loop.run_in_executor(None, _capture_camera)
                        self.ui.start_camera_stream()
                        self._vision_cam_active = True
                        print(f"[Vision] 📷 Camera: {len(img_b):,} bytes")
                        _stall = "camera"
                    else:
                        img_b, mime_t = await loop.run_in_executor(None, _capture_screen)
                        print(f"[Vision] 🖥️  Screen: {len(img_b):,} bytes")
                        _stall = "screen"
                    self._pending_vision = (img_b, mime_t, user_text, angle)
                    # The image is attached to this same exchange, so there is
                    # nothing to stall for and nothing to announce. Asking for an
                    # acknowledgement here is what produced two spoken answers —
                    # the model filled that turn by answering the question from
                    # imagination, then answered it again once it could see.
                    result = (
                        f"[VISION_ACTIVE] {_stall.capitalize()} captured and attached to this "
                        f"same exchange. Do not acknowledge and do not answer yet — the image "
                        f"is arriving with this result. Reply once, from what you actually see "
                        f"in it."
                    )

            elif name == "close_camera":
                self.ui.stop_camera_stream()
                result = "Camera closed."

            elif name == "system_status":
                r = await loop.run_in_executor(None, get_system_status)
                result = str(r)

            elif name == "manage_monitor":
                action = args.get("action", "").lower().strip()
                topic  = args.get("topic", "").strip()
                if action == "add" and topic:
                    result = await asyncio.to_thread(add_monitor, topic)
                elif action == "remove" and topic:
                    result = await asyncio.to_thread(remove_monitor, topic)
                elif action == "list":
                    topics = await asyncio.to_thread(list_monitors)
                    result = ("Monitoring: " + ", ".join(topics)) if topics else "No topics are being monitored."
                else:
                    result = "Specify action (add/remove/list) and a topic."

            elif name == "heartbeat_ok":
                # Phase 4: user is happy with proactive state — pause suggestions.
                minutes = args.get("minutes") or 30
                result = self._heartbeat.heartbeat_ok(minutes=int(minutes))
                print(f"[Heartbeat] 🤐 {result}")

            elif name == "screen_memory_search":
                # Phase 7: search screen memory (OCR + a11y + FTS5).
                result = await loop.run_in_executor(None, lambda: screen_memory_search(args))

            elif name == "set_language":
                # Phase 9: 97-language switching. Store preference in memory;
                # Gemini 3.8 Live handles native mid-turn switching.
                lang = str(args.get("language", "")).strip()
                if not lang:
                    result = "set_language: no language specified."
                else:
                    update_memory({"identity": {"language": {"value": lang}}})
                    result = f"Language set to {lang}. I'll respond in {lang} from now on (and remember it for next session)."
                    print(f"[Language] 🗣️ {result}")

            elif name == "multi_channel":
                # Phase 10: multi-channel gateway.
                result = await loop.run_in_executor(None, lambda: multi_channel(args))

            elif name == "subagent":
                # Phase 11: subagent task decomposition.
                result = await loop.run_in_executor(None, lambda: subagent(args))

            elif name == "gws_pack":
                # Phase 12: GWS Pack — Google Workspace via computer_use.
                result = await loop.run_in_executor(None, lambda: gws_pack(args))
                if result and not result.startswith("gws_pack:"):
                    self.ui.show_content("GWS PACK — " + args.get("action", ""), result)

            elif name == "shutdown_jarvis":
                self.ui.write_log("SYS: Shutdown requested.")
                async def _do_shutdown():
                    await self._save_session_summary()
                    if self.session:
                        try:
                            await self.session.send_client_content(
                                turns={"role": "user", "parts": [{"text": "Say a brief natural goodbye to the user."}]},
                                turn_complete=True,
                            )
                        except Exception:
                            pass
                    await asyncio.sleep(1.5)
                    import os as _os
                    _os._exit(0)
                asyncio.create_task(_do_shutdown())

            elif self._action_registry.has(name):
                # file_processor: fall back to the currently-uploaded file when none is given
                if name == "file_processor" and not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                _ctx = {"player": self.ui, "speak": self.speak,
                        "response": None, "session_memory": None}
                r = await loop.run_in_executor(None, lambda: self._action_registry.run(name, args, _ctx))
                result = r or "Done."
                # web_search: mirror results to the on-screen content panel
                if (name in ("web_search", "deep_research", "computer_use",
                             "gws_pack") and r
                        and not r.startswith("No results")
                        and not r.startswith("Search failed")):
                    _query = args.get("query") or args.get("element_id") or ""
                    if name == "deep_research":
                        _label = "RESEARCH — " + _query[:38]
                    elif name == "computer_use":
                        _label = "COMPUTER USE — " + args.get("action", "som_capture")[:38]
                    else:
                        _label = f"{args.get('mode', 'search').upper()} — {_query[:38]}"
                    self.ui.show_content(_label, r)

            else:
                if self._plugin_registry.has(name):
                    r = await loop.run_in_executor(
                        None,
                        lambda: self._plugin_registry.run(name, args, player=self.ui, session_memory=None)
                    )
                    result = r or "Done."
                else:
                    result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        _nf = getattr(self.ui, "notify_tool_finish", None)
        if callable(_nf):
            _st = "failed" if str(result).startswith(f"Tool '{name}' failed:") else "completed"
            _nf(_task_id, str(result)[:220], _st)

        try:
            from core.security_vault import log_audit_event
            log_audit_event(
                actor=self._asst_name.lower(),
                action=name,
                args=args,
                result_summary=str(result)[:220],
                status="error" if str(result).startswith(f"Tool '{name}' failed:") else "ok",
            )
        except Exception:
            pass

        print(f"[JARVIS] 📤 {name} → {str(result)[:80]}")

        # A tool that declared itself NON_BLOCKING also says when its answer may
        # re-enter the conversation. Without this the model finishes whatever it
        # was saying and then reads the result out on top of it — which, for
        # something like a phone call already ringing, is exactly the noise the
        # non-blocking call was meant to avoid. Tools that declared nothing get
        # the API default and behave as they always have.
        _sched = (self._action_registry.scheduling(name)
                  or self._plugin_registry.scheduling(name))
        _extra = {"scheduling": _sched} if _sched else {}
        _resp = {"result": result}
        # ── Learning-loop hint ────────────────────────────────────────────
        # First tool response to cross 5 calls inside one window carries a
        # quiet, never-spoken reminder to consider saving the procedure
        # (skill_manage). ONCE per process: if the model doesn't act on it,
        # we do not nag again — the never-nag-twice rule applies to self-
        # improvement too. The prompt's [LEARNING] section carries the
        # standing rule; this is only the timing nudge.
        if (self._skill_window_tools >= 5 and not self._skill_hinted):
            self._skill_hinted = True
            _resp["learning_hint"] = (
                f"This turn has used {self._skill_window_tools} tools. If this "
                "is a procedure that will happen again, call skill_manage "
                "(create) to save it — ask the user in one short line first "
                "(skip the ask if they already asked you to save it). If a "
                "skill you followed turned out wrong or incomplete, fix it "
                "with skill_manage (update)."
            )
            print(f"[Skills] 💡 learning hint after {self._skill_window_tools} tools")
        return types.FunctionResponse(
            id=fc.id, name=name,
            response=_resp,
            **_extra
        )

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            # Drop stale pre-speech ambient/breath packets that were queued just
            # before JARVIS began speaking so they cannot trigger server-side
            # interruption mid-sentence. Confirmed barge-in packets carry
            # "barge": True (and _barge_open_until covers the follow-up phrase).
            with self._speaking_lock:
                _spk = self._is_speaking
            if (
                (_spk or (self.audio_in_queue is not None and not self.audio_in_queue.empty()))
                and not msg.get("barge")
                and not self._phone_active
                and time.monotonic() >= getattr(self, "_barge_open_until", 0.0)
            ):
                continue
            # Gemini 3.x Live rejects the old realtime_input.media_chunks field
            # (what `media=...` maps to) and closes the socket with a 1007. Send
            # mic / phone PCM through the new `audio` field instead. Queue items
            # are {"data": <bytes>, "mime_type": <str>} from _listen_audio and
            # the phone relay.
            #
            # Hard 10 s ceiling per send: a stalled write used to hang here
            # silently while the mic kept filling the queue behind it
            # (QueueFull flood, then a 1006 ping-timeout close). Convert the
            # stall into a normal reconnect instead — the session teardown path
            # is the proven recovery.
            try:
                await asyncio.wait_for(
                    self.session.send_realtime_input(
                        audio=types.Blob(
                            data=msg["data"],
                            mime_type=msg.get("mime_type", "audio/pcm"),
                        )
                    ),
                    timeout=10.0,
                )
                self._realtime_send_stalls = 0
            except asyncio.TimeoutError:
                self._realtime_send_stalls += 1
                raise ConnectionError(
                    "timed out: send_realtime_input stalled >10s — forcing reconnect"
                ) from None

    async def _listen_audio(self):
        print("[JARVIS] 🎤 Mic started")
        loop = asyncio.get_event_loop()

        def callback(indata, frames, time_info, status):
            # ── Wake-word gate + Grace window ───────────────────────────────
            if self._wake_enabled and not self._awake:
                # Grace period: follow-ups within N seconds don't need wake word
                if time.monotonic() < self._grace_until:
                    # treat as awake for this utterance
                    pass
                else:
                    det = self._wake_detector
                    if det is not None:
                        det.feed(indata)
                    return
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
            if not jarvis_speaking and self.audio_in_queue is not None and not self.audio_in_queue.empty():
                jarvis_speaking = True

            # ── Pause gate ───────────────────────────────────────────────────
            if self._paused:
                return

            # ── Barge-in (two-stage AEC + voiced speech interrupt, ~128 ms) ──
            # While JARVIS speaks:
            #  1) Rolling 256 ms mic ring (`_mic_ring`) retains leading consonants
            #     (/st/ in "Stop", /w/ in "Wait") before the vowel arrives.
            #  2) Low speech-band pre-gate (0.024..0.055) admits quiet desk speech
            #     down to ~115 int16 RMS while rejecting sub-190 Hz wind puffs.
            #  3) `EchoGuard.speech_score` runs linear waveform FDAF + residual
            #     spectral echo suppression + pre-emphasized vocal-fold pitch check
            #     (rejecting breathing, sighs, clicks, hum, and speaker echo).
            #  4) Leaky syllable-bridging `_barge_score` triggers at >= 2.0 (~128 ms
            #     = 2 voiced blocks) and tolerates intra-word consonants (/s/, /t/).
            if jarvis_speaking:
                if not self._barge_enabled:
                    self._barge_blocks = 0
                    self._barge_score = 0.0
                    self._barge_consonant_hold = 0
                    self._barge_preroll.clear()
                    self._mic_ring.clear()
                    return
                try:
                    raw_bytes = indata.tobytes()
                    self._mic_ring.append(raw_bytes)
                    sb_lvl = speech_band_level(indata, SEND_SAMPLE_RATE)
                    min_gate = max(0.024, min(0.055, self._ambient_floor + 0.015))

                    # Always feed EchoGuard so FDAF sample lock & headphone
                    # zero-coupling calibration track every 64 ms mic block.
                    raw_score = self._echo.speech_score(
                        indata, SEND_SAMPLE_RATE, sb_lvl
                    )
                    score_delta = raw_score if sb_lvl >= min_gate else 0.0

                    if score_delta >= 1.0:
                        need = max(2, int(getattr(self._echo, "required_blocks", 2)))
                        self._barge_score += score_delta
                        self._barge_blocks += 1
                        self._barge_consonant_hold = 1
                        self._barge_preroll = list(self._mic_ring)

                        if self._barge_score < float(need):
                            return

                        preroll_frames = list(self._mic_ring)
                        self._mic_ring.clear()
                        self._barge_preroll.clear()
                        self._barge_blocks = 0
                        self._barge_score = 0.0
                        self._barge_consonant_hold = 0
                        # Stop speaker thread immediately on the audio callback thread
                        # without waiting for the asyncio event loop tick.
                        with self._speaking_lock:
                            self._is_speaking = False
                        self._abort_playback.set()
                        self._barge_open_until = time.monotonic() + 2.5
                        print(
                            f"[Barge] ✋ voiced interrupt! sb_lvl={sb_lvl:.2f} "
                            f"amb={self._ambient_floor:.2f} "
                            f"exp={self._echo.gain * self._out_level:.2f} "
                            f"thr={self._echo.threshold:.2f} need={need} "
                            f"sim={self._echo.last_similarity:.2f}"
                        )
                        try:
                            loop.call_soon_threadsafe(self.interrupt)
                        except Exception:
                            pass
                        # Flush rolling 256 ms onset pre-roll unmodified so
                        # Gemini's server-side VAD hears natural audio levels.
                        try:
                            for chunk_bytes in preroll_frames:
                                loop.call_soon_threadsafe(
                                    out_put_drop_oldest,
                                    self.out_queue,
                                    {
                                        "data": chunk_bytes,
                                        "mime_type": "audio/pcm",
                                        "barge": True,
                                    },
                                )
                        except Exception:
                            pass
                        return
                    else:
                        if (
                            self._barge_score > 0.0
                            and self._barge_consonant_hold > 0
                            and sb_lvl >= min_gate * 0.8
                        ):
                            # Intra-word consonant (/s/, /t/, /k/) between syllables
                            self._barge_consonant_hold -= 1
                            self._barge_score = max(0.0, self._barge_score - 0.12)
                        elif self._barge_score > 0.0:
                            self._barge_score = max(0.0, self._barge_score - 0.75)
                            if self._barge_score == 0.0:
                                self._barge_blocks = 0
                                self._barge_consonant_hold = 0
                                self._barge_preroll.clear()
                        return
                except Exception as e:
                    print(f"[Barge] err {e}")
                    return

            # ── Echo tail ────────────────────────────────────────────────────
            # The speaking flag has dropped but the speakers have not finished.
            # Sending this to the model is how an assistant hears itself, decides
            # it was addressed, and answers its own last sentence. The microphone
            # stays OPEN — the guard only drops blocks that are our own voice, so
            # replying the instant it stops still works.
            if self._tail_active():
                try:
                    if not self._echo.is_user_speech(
                            indata, SEND_SAMPLE_RATE, speech_band_level(indata, SEND_SAMPLE_RATE)):
                        return
                    self._tail_until = 0.0      # a real voice ends the tail early
                except Exception:
                    return
            elif self._echo._hist or getattr(self._echo, "_spk_samples_pushed", 0):
                self._echo.reset()

            # Asymmetric true-floor room tracker: follows quiet moments downward
            # quickly (0.20) and creeps upward slowly (0.01) capped at 0.040 so
            # breathing or typing while idle never inflates the barge-in gate.
            try:
                _sb = speech_band_level(indata, SEND_SAMPLE_RATE)
                if _sb < self._ambient_floor:
                    self._ambient_floor = self._ambient_floor * 0.80 + _sb * 0.20
                elif _sb < 0.045 and not is_voiced_speech(indata, SEND_SAMPLE_RATE):
                    self._ambient_floor = min(
                        0.040, self._ambient_floor * 0.99 + _sb * 0.01
                    )
            except Exception:
                pass

            # ── Push-to-talk ─────────────────────────────────────────────────
            # When it is on the microphone is closed by default and the chord
            # opens it, which is the whole point: nothing leaves the machine
            # unless you are holding the key.
            # BUT a barge-in just happened — keep mic hot for 1.5s even if PTT
            # not held, otherwise 'stop' is heard but the follow-up is swallowed.
            if self._ptt_enabled and not self._ptt_held:
                if time.monotonic() >= getattr(self, "_barge_open_until", 0.0):
                    return
            
            if not self.ui.muted and not self._phone_active:
                data = indata.tobytes()
                in_barge_followup = time.monotonic() < getattr(self, "_barge_open_until", 0.0)
                loop.call_soon_threadsafe(
                    out_put_drop_oldest,
                    self.out_queue,
                    {
                        "data": data,
                        "mime_type": "audio/pcm",
                        **({"barge": True} if in_barge_followup else {}),
                    },
                )
                # Feed the live mic level to the HUD so the waveform reacts to
                # the user's actual voice while listening. Purely cosmetic — any
                # failure here must never disturb the mic.
                try:
                    self.ui.set_audio_level(_pcm_level(indata))
                except Exception:
                    pass

        try:
            def _open_mic(dev):
                return sd.InputStream(
                    samplerate=SEND_SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="int16",
                    blocksize=CHUNK_SIZE,
                    device=dev,
                    callback=callback,
                )

            # Which microphone. resolve() returns None for "system default" and
            # for a saved device that is no longer present — so a headset
            # unplugged since the last run falls back to the built-in mic
            # instead of raising on startup and taking the session with it.
            _mic_name = get_input_device()
            _mic_dev  = audio_devices.resolve(_mic_name, "input")
            if _mic_dev is not None:
                print("[JARVIS] 🎤 Configured input device selected")
            try:
                _mic_stream = _open_mic(_mic_dev)
            except Exception as _e:
                # A device the picker listed but the driver will not open right
                # now — exclusive mode, a webcam already in use, a virtual mic
                # whose source went away. Chosen hardware failing must never
                # mean the assistant cannot hear at all.
                if _mic_dev is None:
                    raise
                print(f"[JARVIS] ⚠️  Selected mic failed ({type(_e).__name__}) — using default")
                self.ui.write_log(
                    f"SYS: Microphone '{_mic_name}' unavailable — using system default."
                )
                _mic_stream = _open_mic(None)

            with _mic_stream:
                print("[JARVIS] 🎤 Mic stream open")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[JARVIS] ❌ Mic: {e}")
            raise

    async def _flush_pending_vision(self) -> bool:
        """Send a captured frame immediately after its tool response.

        The frame is already in hand by the time `screen_process` returns — the
        capture happened inside the tool call. The old flow still made the model
        speak a turn first and only injected the image on that turn's
        turn_complete, which cost a whole extra round trip AND produced two
        spoken answers: one improvised without the picture, then the real one.
        Sending it here means the model has the tool result and the image before
        it generates anything, so the user gets one answer, sooner.
        """
        if not (self._pending_vision and self.session):
            return False

        import base64 as _b64
        img_b, mime_t, question, angle = self._pending_vision
        self._pending_vision = None
        b64 = _b64.b64encode(img_b).decode("ascii")
        print(f"[Vision] 📤 {len(img_b):,} bytes (angle={angle}) → main session")

        # Label the source. Without it the image arrives carrying nothing but
        # the user's own sentence, and a screenshot of this app — which has a
        # face in the middle of it — got read as a photo of the user. What the
        # label *means* is explained once, in the generated [SELF] block.
        src = ("[IMAGE SOURCE: WEBCAM]" if angle == "camera"
               else "[IMAGE SOURCE: SCREEN CAPTURE]")
        await self.session.send_client_content(
            turns={"role": "user", "parts": [
                {"inline_data": {"mime_type": mime_t, "data": b64}},
                {"text": f"{src}\n\n{question}"},
            ]},
            turn_complete=True,
        )

        if self._vision_cam_active:
            # Camera: stay busy until JARVIS has finished speaking the answer,
            # then close the preview.
            self._vision_cam_active    = False
            self._vision_close_pending = True
        else:
            self._vision_busy = False
        return True

    async def _receive_audio(self):
        print("[JARVIS] 👂 Recv started")
        out_buf, in_buf, model_txt_buf = [], [], []

        try:
            while True:
                async for response in self.session.receive():

                    # ── Session resumption ───────────────────────────────────
                    # The server sends this periodically. `resumable` goes false
                    # while a turn is mid-flight — replaying a handle from that
                    # moment is what the flag exists to prevent — so only
                    # resumable handles are kept. This is three lines and it is
                    # the entire fix for "every reconnect forgets everything".
                    _sru = getattr(response, "session_resumption_update", None)
                    if _sru is not None:
                        if getattr(_sru, "resumable", False) and getattr(_sru, "new_handle", None):
                            if self._resume_handle is None:
                                print("[JARVIS] 🔗 Session resumption armed")
                            self._resume_handle = _sru.new_handle

                    # ── Server GoAway notice (Phase 13) ──────────────────────
                    # Google sends GoAway before terminating a long-lived
                    # WebSocket (~15 min ceiling or maintenance roll). Arm the
                    # recycler so we rebuild on the very next speech gap
                    # instead of being cut off mid-sentence.
                    _ga = getattr(response, "go_away", None)
                    if _ga is not None:
                        _left = parse_go_away_seconds(_ga)
                        self._session_recycler.on_go_away(_left)
                        print(f"[SessionRecycle] ⚠️ Server GoAway (time_left={_left}s) — scheduling seamless recycle")

                    if response.data:
                        if self._interrupted:
                            _now_rx = time.monotonic()
                            # Safety release: if >0.65s elapsed since the last
                            # discarded chunk (and >1.0s since interrupt()), the
                            # old cancelled stream already ended without sending
                            # turn_complete — this packet is a brand-new reply!
                            if (
                                _now_rx - getattr(self, "_interrupted_at", 0.0) > 1.0
                                and _now_rx - getattr(self, "_last_interrupted_rx", 0.0) > 0.65
                            ):
                                self._interrupted = False
                            else:
                                self._last_interrupted_rx = _now_rx
                        if not self._interrupted:
                            self._abort_playback.clear()
                            if self._turn_done_event and self._turn_done_event.is_set():
                                self._turn_done_event.clear()
                            # Split into ~40 ms chunks so interrupt() stops audio within ~50 ms
                            # (24000 Hz × 2 bytes/sample × 0.04 s = 1920 bytes per slice)
                            _audio_data = response.data
                            _SLICE = 1920
                            for _i in range(0, len(_audio_data), _SLICE):
                                self.audio_in_queue.put_nowait(_audio_data[_i : _i + _SLICE])

                    if response.server_content:
                        sc = response.server_content

                        # Server-side barge-in: Gemini explicitly confirmed the
                        # old generation is cancelled. Drain local playback AND
                        # clear `_interrupted` immediately — Gemini often streams
                        # the reply to the user's new utterance without sending a
                        # separate turn_complete for the cancelled turn!
                        if getattr(sc, "interrupted", False):
                            if not self._interrupted:
                                self.interrupt()
                            self._interrupted = False
                            in_buf = []
                            out_buf = []
                            model_txt_buf = []
                            self._visemes.reset()

                        _mt = getattr(sc, "model_turn", None)
                        if _mt and getattr(_mt, "parts", None) and not self._interrupted:
                            for _part in _mt.parts:
                                if getattr(_part, "thought", False):
                                    continue
                                _ptxt = getattr(_part, "text", None)
                                if _ptxt:
                                    _cleaned_ptxt = _clean_transcript(_ptxt)
                                    if _cleaned_ptxt and not _is_repeat_chunk(_cleaned_ptxt, model_txt_buf):
                                        model_txt_buf.append(_cleaned_ptxt)

                        if sc.output_transcription and sc.output_transcription.text:
                            if not self._interrupted:
                                txt = _clean_transcript(sc.output_transcription.text)
                                # A turn that involves a tool call passes through
                                # several turn_completes, and the API re-sends the
                                # tail of the transcript across them. Comparing only
                                # against the previous chunk missed that — once
                                # out_buf had been flushed and emptied, the repeat
                                # sailed straight back in, which logged the answer
                                # twice AND made the avatar mouth it twice.
                                if txt and not _is_repeat_chunk(txt, out_buf):
                                    out_buf.append(txt)
                                    # Hand the words to the mouth as they arrive, so
                                    # the avatar can form the consonants the audio
                                    # alone cannot show. Pure string work — it adds
                                    # nothing measurable to the response path.
                                    self._visemes.feed_text(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = _clean_transcript(sc.input_transcription.text)
                            if txt:
                                # Server is transcribing the user's new utterance —
                                # any subsequent response.data belongs to the new reply!
                                if self._interrupted:
                                    self._interrupted = False
                                    out_buf = []
                                    self._visemes.reset()
                                in_buf.append(txt)
                                self._last_user_speech = time.monotonic()

                        if sc.turn_complete:
                            if self._turn_done_event:
                                self._turn_done_event.set()

                            # If this turn_complete ends an interrupted response, clear the
                            # flag and skip all further processing for that turn.
                            if self._interrupted:
                                self._interrupted = False
                                in_buf  = []
                                out_buf = []
                                model_txt_buf = []
                                self._visemes.reset()
                                continue

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self._last_out_logged = ""   # new exchange
                                self.ui.write_log(f"You: {full_in}")
                                self._session_log.append(f"User: {full_in}")
                                try:
                                    from memory.timeline import append_turn
                                    append_turn("user", full_in, speaker="You", channel="voice")
                                except Exception:
                                    pass
                                try:
                                    from core.companions import detect_and_record_correction
                                    detect_and_record_correction(full_in)
                                except Exception:
                                    pass
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "user",
                                        "text": full_in,
                                        "ts": datetime.now().isoformat(),
                                    }))
                            in_buf = []

                            full_out = " ".join(out_buf).strip() or " ".join(model_txt_buf).strip()
                            # Second line of defence: even if a repeat slips
                            # into a *fresh* buffer after a flush, never log the
                            # same answer (or a tail of it) twice in a row.
                            if full_out and len(full_out) >= _REPEAT_MIN and self._last_out_logged:
                                if full_out in self._last_out_logged:
                                    full_out = ""
                            if full_out:
                                self._last_out_logged = full_out
                                self.ui.write_log(f"{self._asst_name}: {full_out}")
                                self._session_log.append(f"{self._asst_name}: {full_out}")
                                try:
                                    from memory.timeline import append_turn
                                    append_turn("jarvis", full_out, speaker=self._asst_name, channel="voice")
                                except Exception:
                                    pass
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "jarvis",
                                        "text": full_out,
                                        "ts": datetime.now().isoformat(),
                                    }))
                            out_buf = []
                            model_txt_buf = []
                            if (
                                not self._is_speaking
                                and (self.audio_in_queue is None or self.audio_in_queue.empty())
                                and not self.ui.muted
                                and not self._paused
                            ):
                                self.ui.set_state("LISTENING")

                            if self._vision_close_pending:
                                # This turn_complete IS the vision answer — close camera + release busy flag
                                self._vision_close_pending = False
                                self._vision_busy = False
                                async def _cam_close():
                                    await asyncio.sleep(2.0)
                                    self.ui.stop_camera_stream()
                                asyncio.create_task(_cam_close())

                    if response.tool_call:
                        self._interrupted = False
                        asyncio.create_task(self._dispatch_tool_call(response.tool_call))
        except Exception as e:
            print(f"[JARVIS] ❌ Recv: {e}")
            traceback.print_exc()
            raise

    async def _dispatch_tool_call(self, tool_call) -> None:
        """Execute single or multi-tool batches concurrently off the receive loop.

        Running this in its own task ensures `NON_BLOCKING` tools never stall
        `_receive_audio()` while Gemini is simultaneously streaming speech audio,
        and `asyncio.gather` executes multi-tool batches in parallel (`max`
        latency instead of `sum` latency).
        """
        fcs = list(getattr(tool_call, "function_calls", None) or [])
        if not fcs:
            return
        try:
            with self._session_recycler.track_tool():
                for fc in fcs:
                    print(f"[JARVIS] 📞 {fc.name}")
                if len(fcs) == 1:
                    fn_responses = [await self._execute_tool(fcs[0])]
                else:
                    fn_responses = list(
                        await asyncio.gather(*(self._execute_tool(fc) for fc in fcs))
                    )
                if self.session:
                    await self.session.send_tool_response(
                        function_responses=fn_responses
                    )
                    await self._flush_pending_vision()
        except Exception as e:
            print(f"[JARVIS] ⚠️ Tool batch dispatch error ({type(e).__name__})")
            traceback.print_exc()

    async def _play_audio(self):
        print("[JARVIS] 🔊 Play started")

        _spk_name = get_output_device()
        _spk_dev  = audio_devices.resolve(_spk_name, "output")
        if _spk_dev is not None:
            print("[JARVIS] 🔊 Configured output device selected")

        def _open_spk(dev):
            st = sd.RawOutputStream(
                samplerate=RECEIVE_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                device=dev,
            )
            st.start()
            return st

        try:
            stream = _open_spk(_spk_dev)
        except Exception as _e:
            # A chosen output that the host API accepts by name but refuses to
            # open (exclusive mode, wrong sample rate, device asleep) must not
            # cost the user their voice. Fall back to the default and say so.
            if _spk_dev is None:
                raise
            print(f"[JARVIS] ⚠️  Selected output failed ({type(_e).__name__}) — using default")
            self.ui.write_log(f"SYS: Speaker '{_spk_name}' unavailable — using system default.")
            stream = _open_spk(None)

        # Ask the device how far behind the speakers actually are, rather than
        # assuming. This is what the echo tail is sized from, so a machine with a
        # large audio buffer gets a correspondingly longer guard — and one with a
        # tiny buffer is not penalised with a delay it does not need.
        try:
            lat = float(getattr(stream, "latency", 0.0) or 0.0)
            if 0.0 < lat < 1.0:
                self._out_latency = lat
            print(f"[JARVIS] 🔊 Output latency {self._out_latency*1000:.0f} ms "
                  f"→ echo tail {(self._out_latency + _TAIL_MARGIN)*1000:.0f} ms")
        except Exception:
            pass

        def _drain_playback_queue() -> None:
            """Discard queued slices cleanly — never abort a blocking PortAudio
            RawOutputStream on Windows WASAPI/MME, which wedges future writes."""
            while not self.audio_in_queue.empty():
                try:
                    self.audio_in_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

        idle_ticks = 0
        try:
            while True:
                if self._abort_playback.is_set():
                    self._abort_playback.clear()
                    _drain_playback_queue()
                    if self._is_speaking:
                        self.set_speaking(False)
                    continue

                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(),
                        timeout=0.05
                    )
                except asyncio.TimeoutError:
                    idle_ticks += 1
                    if self._abort_playback.is_set():
                        self._abort_playback.clear()
                        _drain_playback_queue()
                        if self._is_speaking:
                            self.set_speaking(False)
                        continue
                    if self.audio_in_queue.empty() and (
                        (self._turn_done_event and self._turn_done_event.is_set())
                        or self._interrupted
                        or (self._is_speaking and idle_ticks >= 16)
                    ):
                        if self._is_speaking:
                            self.set_speaking(False)
                        if self._turn_done_event and self._turn_done_event.is_set():
                            self._turn_done_event.clear()
                    continue

                idle_ticks = 0
                if self._abort_playback.is_set() or self._interrupted:
                    self._abort_playback.clear()
                    _drain_playback_queue()
                    if self._is_speaking:
                        self.set_speaking(False)
                    continue

                self.set_speaking(True)

                # Batch immediately-available chunks up to ~50 ms (2400 bytes at
                # 24 kHz / 16-bit mono) so draining audio_in_queue halts audible
                # speech within ~50 ms cleanly via normal stream.write().
                batch = bytearray(chunk)
                while len(batch) < 2400:
                    try:
                        batch.extend(self.audio_in_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                # Drive the HUD waveform and the avatar's mouth from JARVIS's
                # own voice. The batch is up to 200 ms long, so we hand over a
                # *schedule* of 20 ms viseme frames instead of a single averaged
                # level and let the HUD play it out in step with the audio.
                try:
                    pcm = np.frombuffer(bytes(batch), dtype=np.int16)
                    hop = _VIS_HOP / RECEIVE_SAMPLE_RATE
                    frames = _pcm_visemes(pcm, sr=RECEIVE_SAMPLE_RATE)
                    # When does this batch become audible? The stream was
                    # started at launch and its callback has been pulling
                    # silence ever since, so the first bytes of a reply reach
                    # the speaker about one callback period later — NOT one
                    # buffer later. `stream.latency` reports the buffer's
                    # capacity, which is how much can be queued ahead, and on
                    # Windows that is commonly 300-500 ms. Anchoring on it put
                    # the entire schedule a buffer late; that is the half second
                    # of lag, and it grew with whatever the device reported.
                    #
                    # After the anchor nothing needs measuring: the device
                    # consumes at exactly realtime, so each batch sounds one
                    # batch-duration after the one before it. The cursor is
                    # re-anchored only when it leaves the range physically
                    # possible — behind `now` means the device drained and this
                    # batch starts a fresh stretch of speech, while further
                    # ahead than the buffer can hold means it has drifted.
                    now = time.time()
                    horizon = self._out_latency + _CURSOR_SLACK
                    if not (now <= self._play_cursor <= now + horizon):
                        self._play_cursor = now + _FIRST_SOUND
                    at = self._play_cursor
                    # Advance by the batch's own duration whether or not it
                    # yielded frames, so a block too short to analyse cannot
                    # shift everything after it out of step with the audio.
                    self._play_cursor += pcm.size / RECEIVE_SAMPLE_RATE
                    if frames:
                        frames = self._visemes.frames(frames, hop)
                        self.ui.push_visemes(frames, hop, at)
                        # Barge-in needs to know what we are playing, not just
                        # how loud: the guard subtracts this from the microphone.
                        self._out_level = max(f[0] for f in frames)
                        self._echo.note_output(pcm, RECEIVE_SAMPLE_RATE,
                                               self._out_level)
                    else:
                        lvl = _pcm_level(pcm)
                        self.ui.set_audio_level(lvl)
                        self._out_level = lvl
                        self._echo.note_output(pcm, RECEIVE_SAMPLE_RATE, lvl)
                except Exception:
                    pass

                try:
                    await asyncio.to_thread(stream.write, bytes(batch))
                except (RuntimeError, asyncio.CancelledError):
                    break   # executor shutting down — exit cleanly
                if self._abort_playback.is_set():
                    self._abort_playback.clear()
                    _drain_playback_queue()
                    if self._is_speaking:
                        self.set_speaking(False)
        except Exception as e:
            print(f"[JARVIS] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    # ── Morning briefing ────────────────────────────────────────────────────────

    async def _send_startup_briefing(self) -> None:
        """
        Two-phase briefing optimized for speed:
          Phase 1 — instant greeting (no tools) → speech starts in <1s
          Phase 2 — news pre-fetched in a background thread while Phase 1 plays,
                    delivered as ready text (no Gemini tool-call round-trip) and
                    shown on the UI content panel. Waits for turn_complete event
                    instead of a fixed sleep so there is no unnecessary gap.
        """
        memory   = load_memory()
        identity = memory.get("identity", {})

        def _val(k: str) -> str:
            e = identity.get(k, {})
            return (e.get("value", "") if isinstance(e, dict) else str(e)).strip()

        lang = _val("language")
        name = _val("name")
        time_str = datetime.now().strftime("%H:%M")

        # Start fetching news immediately — runs in parallel while phase 1 plays
        loop = asyncio.get_event_loop()
        news_future = loop.run_in_executor(None, _fetch_news_sync, "top world news today")

        await asyncio.sleep(0.3)
        if not self.session:
            return

        # ── Phase 1: instant greeting ─────────────────────────────────────────
        # The briefing fires before the user has said anything, so the
        # remembered language is the only signal there is. It is a starting
        # point, not a setting: the moment they reply, their language wins.
        lang_clause = (f" Speak this greeting in {lang}, then follow the "
                       f"user's own language from their first reply onward."
                       if lang else "")
        name_clause = f" Address the user as {name}." if name else ""

        # Inject last session context if available — pop removes it so it's never repeated
        last = await asyncio.to_thread(pop_last_session)
        session_clause = ""
        if last:
            try:
                _delta = (datetime.now() - datetime.strptime(last["date"], "%Y-%m-%d")).days
                _when  = "earlier today" if _delta == 0 else ("yesterday" if _delta == 1 else f"{_delta} days ago")
            except Exception:
                _when = "last time"
            session_clause = (
                f" Also briefly and naturally mention that {_when}: {last['summary']}"
            )

        p1 = (
            f"Greet the user warmly, mention it is {time_str}, and say you are fetching today's news now.{session_clause} "
            f"Keep it to 2 short sentences max. Do not call any tools.{lang_clause}{name_clause}"
        )

        # Clear the turn-done event so we can wait for Phase 1 to finish
        if self._turn_done_event:
            self._turn_done_event.clear()

        await self.session.send_client_content(
            turns={"role": "user", "parts": [{"text": p1}]},
            turn_complete=True,
        )
        print("[JARVIS] Briefing phase 1 (greeting) sent.")

        # ── Phase 2: fire as soon as Phase 1 audio is done ───────────────────
        async def _deliver_news():
            try:
                lang_str = (f" Speak in {lang} unless the user has since "
                            f"spoken another language, in which case use theirs."
                            if lang else "")

                # Wait for news fetch (already running) and Phase 1 turn-complete
                # in parallel — whichever takes longer determines the wait time
                news_done   = asyncio.wrap_future(news_future)
                turn_waited = False
                if self._turn_done_event:
                    try:
                        await asyncio.wait_for(self._turn_done_event.wait(), timeout=6.0)
                        turn_waited = True
                    except asyncio.TimeoutError:
                        pass

                # Extra buffer: turn_complete fires when Gemini finishes *generating*
                # Phase 1, but audio may still be playing.  Waiting a beat here
                # prevents Phase 2 audio from arriving while Phase 1 is mid-sentence
                # (which sounds like a "repeated first response" to the user).
                if turn_waited:
                    await asyncio.sleep(0.8)
                else:
                    await asyncio.sleep(1.0)

                try:
                    news_text = await asyncio.wait_for(news_done, timeout=8.0)
                except Exception as e:
                    self.ui.write_log(f"SYS: News fetch timed out/failed: {e!r}")
                    news_text = ""

                if not self.session:
                    return

                failed = (not news_text) or news_text.startswith(
                    ("No news found", "Search failed", "Please provide")
                )
                if not failed:
                    # Show on UI content panel immediately
                    self.ui.show_content("NEWS — top world news today", news_text)

                    p2 = (
                        f"[BRIEFING] Here are today's top news headlines:\n{news_text}\n\n"
                        "Pick ONE headline, summarise it in one sentence, then say the full list "
                        f"is displayed on screen. Do not call any tools.{lang_str}"
                    )
                else:
                    self.ui.write_log(
                        f"SYS: News unavailable — backend returned: {news_text[:120]!r}"
                    )
                    p2 = (
                        "News headlines could not be fetched right now. "
                        f"Let the user know briefly.{lang_str}"
                    )

                await self.session.send_client_content(
                    turns={"role": "user", "parts": [{"text": p2}]},
                    turn_complete=True,
                )
                print("[JARVIS] Briefing phase 2 (news) sent.")
            except Exception as e:
                print(f"[Briefing] Phase 2 error: {e}")
                print(f"[JARVIS] Briefing phase 2 failed: {e}")
                self.ui.write_log("SYS: Could not fetch the news for the briefing.")

        asyncio.create_task(_deliver_news())

    # ── Session memory ──────────────────────────────────────────────────────────

    async def _save_session_summary(self) -> None:
        """Summarise the current session in 1-2 sentences and save to long_term.json."""
        try:
            from core.session_privacy import enabled as incognito_enabled
            if incognito_enabled():
                self._session_log = []
                return
        except Exception:
            pass
        log = self._session_log
        if len(log) < 3:          # need at least one exchange to be worth saving
            return
        self._session_log = []    # reset immediately so the next session starts clean
        try:
            from memory.config_manager import get_adaptive_learning_enabled
            if not get_adaptive_learning_enabled():
                return
        except Exception:
            pass

        memory = load_memory()
        lang_entry = memory.get("identity", {}).get("language", {})
        lang = (lang_entry.get("value", "") if isinstance(lang_entry, dict) else str(lang_entry)).strip()
        lang = lang or "English"

        convo = "\n".join(log[-40:])   # cap at last 40 turns to stay within token budget
        prompt = (
            f"Summarize this conversation in 1-2 sentences in {lang}. "
            "Focus on what the user accomplished or discussed. "
            "Output ONLY the summary text, nothing else:\n\n" + convo
        )
        try:
            from core import gemini
            summary = await asyncio.to_thread(
                gemini.text, prompt, gemini.SMART, None, 30_000,
            )
            if summary:
                save_session_summary(summary, lang)
        except Exception as e:
            print(f"[Memory] ⚠️ Session summary failed: {e}")

    # ── System monitor ──────────────────────────────────────────────────────────

    async def _run_system_monitor(self) -> None:
        """Background task: voice alerts when metrics exceed thresholds."""
        while True:
            await asyncio.sleep(10)
            alert = await asyncio.to_thread(self._sys_monitor.check)
            if not alert or not self.session or not self._awake:
                continue
            # Don't interrupt an active conversation
            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking or (time.monotonic() - self._last_user_speech) < 10:
                continue
            try:
                await self.session.send_client_content(
                    turns={"role": "user", "parts": [{"text": alert}]},
                    turn_complete=True,
                )
            except Exception as e:
                print(f"[Monitor] ⚠️ Could not send alert: {e}")

    # ── Background monitor ──────────────────────────────────────────────────────

    async def _run_background_monitor(self) -> None:
        """Check user-configured topics once per day; speak alerts when new headlines appear."""
        await asyncio.sleep(300)          # wait 5 min after startup before first check
        while True:
            if self.session and self._awake:
                # Don't interrupt if user spoke recently or JARVIS is mid-sentence
                with self._speaking_lock:
                    speaking = self._is_speaking
                recent_speech = (time.monotonic() - self._last_user_speech) < 30
                if not speaking and not recent_speech:
                    try:
                        alerts = await asyncio.to_thread(monitor_check_all)
                        memory = load_memory()
                        lang_e = memory.get("identity", {}).get("language", {})
                        lang   = (lang_e.get("value", "") if isinstance(lang_e, dict) else str(lang_e)).strip() or "English"
                        for alert in alerts:
                            msg = (
                                f"{alert}\n\n"
                                f"Inform the user about this development naturally in {lang}. "
                                "One brief sentence only."
                            )
                            await self.session.send_client_content(
                                turns={"role": "user", "parts": [{"text": msg}]},
                                turn_complete=True,
                            )
                            print("[JARVIS] Monitor alert sent.")
                            await asyncio.sleep(6)   # gap between consecutive alerts
                    except Exception as e:
                        print(f"[Monitor] ⚠️ Background check error: {e}")
            await asyncio.sleep(1800)     # check every 30 minutes

    # ── Proactive mode ──────────────────────────────────────────────────────────

    async def _run_proactive_mode(self) -> None:
        """
        Background task: periodically checks if the user has been silent long enough,
        then hands time + memory context to Gemini so it can decide what (if anything)
        to say proactively. No hardcoded rules — Gemini makes the call.
        """
        while True:
            await asyncio.sleep(60)   # evaluate once per minute

            if not self.session or not self._awake:
                continue

            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking:
                continue

            if not self._proactive.should_trigger(self._last_user_speech):
                continue
            from core import proactive_permissions
            proactive_policy = proactive_permissions.load()
            if not proactive_permissions.allowed(proactive_policy):
                continue

            self._proactive.mark_triggered()

            try:
                memory       = await asyncio.to_thread(load_memory)
                monitors     = await asyncio.to_thread(list_monitors)
                recent_turns = self._session_log[-8:] if self._session_log else []
                memory, monitors, recent_turns = proactive_permissions.filter_context(
                    memory, monitors or None, recent_turns or None, proactive_policy,
                )
                prompt = self._proactive.build_prompt(
                    memory       = memory,
                    monitors     = monitors,
                    recent_turns = recent_turns,
                )
                await self.session.send_client_content(
                    turns={"role": "user", "parts": [{"text": prompt}]},
                    turn_complete=True,
                )
                proactive_permissions.record()
                print("[JARVIS] Proactive check-in.")
            except Exception as e:
                print(f"[Proactive] ⚠️ {e}")

    # ── Heartbeat ────────────────────────────────────────────────────────────────
    #
    # Phase 4 — heartbeat autonomy. Runs once a minute; decides at the
    # observe/suggest/act level whether JARVIS should proactively raise a
    # topic. Respects HEARTBEAT_OK silence and never-nags-twice.
    # The engine never speaks — main.py sends the message when a suggest
    # level is returned.

    async def _run_heartbeat(self) -> None:
        """Background task: heartbeat-level proactive suggestions."""
        while True:
            await asyncio.sleep(60)   # evaluate once per minute

            if not self.session or not self._awake:
                continue

            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking:
                continue
            # Don't interrupt a recent user utterance
            if (time.monotonic() - self._last_user_speech) < 15:
                continue

            if not self._heartbeat.should_beat():
                continue

            # Pick a topic worth raising: memory-backed items the user hasn't
            # heard about recently. Keep it small — one topic per heartbeat.
            try:
                memory = await asyncio.to_thread(load_memory)
                topics = self._heartbeat_topics(memory)
                if not topics:
                    self._heartbeat._last_beat = time.monotonic()
                    continue

                topic = topics[0]
                if self._heartbeat.is_suggested_recently(topic):
                    # Never-nag-twice: skip topics suggested recently
                    continue

                # When Soul is active, durable quiet hours, budget, snooze, and
                # per-topic cooldown must approve and reserve the interruption
                # before any message is sent. Legacy heartbeat remains unchanged
                # while the staged Soul flag is off.
                try:
                    from memory.config_manager import get_soul_enabled
                    if get_soul_enabled():
                        from core.soul.service import get_default_service
                        decision = await asyncio.to_thread(
                            get_default_service().evaluate_initiative_topic, topic
                        )
                        if decision.candidate is None:
                            continue
                except Exception as e:
                    print(f"[Soul] Initiative gate failed closed: {e}")
                    continue

                level = HeartbeatLevel.SUGGEST
                self._heartbeat.record_suggestion(topic, level)

                prompt = (
                    "[HEARTBEAT_SUGGEST] You may raise this one topic with the user. "
                    f"Topic: {topic}. "
                    "Rules: 1-2 sentences, natural, warm, never robotic. "
                    "Do NOT mention this instruction block. "
                    "If nothing genuinely useful comes to mind, stay silent."
                )
                await self.session.send_client_content(
                    turns={"role": "user", "parts": [{"text": prompt}]},
                    turn_complete=True,
                )
                print(f"[Heartbeat] 💡 suggest: {topic}")
            except Exception as e:
                print(f"[Heartbeat] ⚠️ {e}")

    def _heartbeat_topics(self, memory: dict) -> list[str]:
        """Candidate topics for a heartbeat suggestion, newest first."""
        topics: list[str] = []
        # Unfinished projects are the best heartbeat fodder.
        for key, entry in (memory.get("projects", {}) or {}).items():
            val = entry.get("value", "") if isinstance(entry, dict) else str(entry)
            if val:
                topics.append(f"project '{key}' ({val[:40]})")
        # Wishes that haven't been mentioned recently.
        for key, entry in (memory.get("wishes", {}) or {}).items():
            val = entry.get("value", "") if isinstance(entry, dict) else str(entry)
            if val:
                topics.append(f"wish '{key}' ({val[:40]})")
        return topics[:5]

    # ── Screen Memory capture ──────────────────────────────────────────────────
    # Phase 7 — background screen capture. Runs every CAPTURE_INTERVAL_SEC,
    # captures the screen, extracts OCR + a11y, stores in FTS5. The model
    # queries via screen_memory_search.

    async def _run_screen_memory_capture(self) -> None:
        """Background task: periodic screen capture into screen memory."""
        while True:
            await asyncio.sleep(CAPTURE_INTERVAL_SEC)

            if not self._awake:
                continue

            try:
                loop = asyncio.get_running_loop()
                event = await loop.run_in_executor(None, self._screen_memory.capture)
                if event:
                    print(f"[ScreenMemory] 📸 captured ({event['duration_ms']}ms, "
                          f"{len(event.get('ocr_text', ''))} OCR chars)")
            except Exception as e:
                print(f"[ScreenMemory] ⚠️ {e}")

    # ── Proactive 15-min Session Recycle ───────────────────────────────────────
    # Phase 13 — Gemini Live WebSocket sessions hit a hard ~15-minute ceiling.
    # Starting at 13m (or upon a server GoAway frame), wait for an idle speech
    # gap with no active audio/tools/vision and trigger a silent resumed rebuild.

    async def _run_session_recycle(self) -> None:
        """Background task: proactively recycle the Live WebSocket before 15m."""
        while True:
            await asyncio.sleep(RECYCLE_CHECK_SEC)

            if not self.session:
                continue

            with self._speaking_lock:
                speaking = self._is_speaking

            audio_queued = bool(
                self.audio_in_queue is not None and not self.audio_in_queue.empty()
            )
            speech_age = max(0.0, time.monotonic() - self._last_user_speech)

            should, reason = self._session_recycler.should_recycle(
                is_speaking=speaking,
                audio_queued=audio_queued,
                last_user_speech_age=speech_age,
                vision_busy=bool(self._vision_busy),
                has_resume_handle=bool(self._resume_handle),
            )
            if should:
                self._session_recycler.mark_recycled(reason)
                age_min = self._session_recycler.session_age() / 60.0
                print(
                    f"[SessionRecycle] ♻️ Recycling Live session at {age_min:.1f}m "
                    f"({reason}; resume={'yes' if self._resume_handle else 'no'})"
                )
                self._proactive_recycle_pending = True
                self.request_reconnect(
                    keep_context=True,
                    reason=reason,
                    silent=True,
                )
                return

    # ── Phone audio relay ────────────────────────────────────────────────────────

    async def _relay_phone_audio(self) -> None:
        """Forward phone mic PCM chunks from dashboard queue into the Gemini Live session."""
        q = self._dashboard._phone_audio_queue
        while True:
            try:
                chunk = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # No audio for 1 s → phone mic inactive, give PC mic back
                self._phone_active = False
                continue
            self._phone_active = True   # phone is streaming — silence PC mic
            with self._speaking_lock:
                speaking = self._is_speaking
            if not speaking and not self.ui.muted:
                out_put_drop_oldest(self.out_queue, chunk)

    def _on_phone_connected(self) -> None:
        self.ui.write_log("SYS: Phone connected via Remote Dashboard.")
        self.ui.notify_phone_connected()

    # ── dashboard command relay ─────────────────────────────────────────────

    async def _process_dashboard_commands(self) -> None:
        while True:
            try:
                text = await asyncio.wait_for(
                    self._dashboard._command_queue.get(), timeout=0.5
                )
                if not text:
                    continue
                # Wait up to 8s for session to become ready after a wake
                for _ in range(80):
                    if self.session:
                        break
                    await asyncio.sleep(0.1)
                if self.session:
                    # A remote command is deliberate control and the phone user
                    # has no desktop WAKE button — so it wakes JARVIS if asleep.
                    if self._wake_enabled and not self._awake:
                        self.wake(reason="remote command")
                    await self.session.send_client_content(
                        turns={"role": "user", "parts": [{"text": text}]},
                        turn_complete=True,
                    )
                    self.ui.write_log(f"[Web]: {text}")
                else:
                    print(f"[Dashboard] Dropped command (no session): {text}")
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                print(f"[Dashboard] Command error: {e}")
                await asyncio.sleep(0.5)

    # ── main loop ───────────────────────────────────────────────────────────

    async def run(self):
        self._loop = asyncio.get_event_loop()
        import concurrent.futures as _cf
        self._loop.set_default_executor(
            _cf.ThreadPoolExecutor(max_workers=16, thread_name_prefix="jarvis-worker")
        )
        # Callback errors must never be reprinted in full at mic rate: the
        # printing runs on this loop and starves keepalive pings (2026-10-22
        # flood -> 1006 close). Distinct errors print once; repeats count.
        self._loop.set_exception_handler(throttled_loop_exception_handler)
        self._reconnect_event = asyncio.Event()

        # ── Wire the shared core services to the interface ───────────────────
        # The confirmation gate is useless without a way to ask, and a memory
        # trim is invisible without a way to say so. Both are bound once here
        # rather than passed down through every action signature.
        confirm_gate.bind(
            show = self.ui.show_confirm,
            hide = self.ui.hide_confirm,
            log  = self.ui.write_log,
        )
        set_trim_notifier(self.ui.write_log)

        # Tell the device picker the exact rates the streams open at, from the
        # constants that actually open them — so it can never list a device that
        # cannot be opened at them.
        audio_devices.configure(SEND_SAMPLE_RATE, RECEIVE_SAMPLE_RATE)

        # Enumerate audio devices off-thread. The settings drawer must never pay
        # for host-API enumeration on the Qt thread.
        audio_devices.prefetch()

        # The LAN dashboard is intentionally not started here. It binds a LAN
        # port and opens a firewall rule, so it starts only after the owner
        # explicitly presses Remote Control (see _make_remote_key).

        # Start multi-channel webhook server (inbound from WhatsApp, Discord,
        # Slack, etc.). Injects inbound messages into the Live session.
        try:
            webhook_url = start_webhook()
            get_gateway().set_inbound_inject(
                lambda channel_id, sender, text: _inject_inbound(
                    self, channel_id, sender, text
                )
            )
            print(f"[MultiChannel] 🌐 Webhook: {webhook_url}")
        except Exception as e:
            print(f"[MultiChannel] Webhook disabled: {e}")

        while True:
            try:
                print("[JARVIS] Connecting...")
                if not self._proactive_recycle_pending:
                    self.ui.set_state("THINKING")
                # Pick active cloud engine ('gemini' or 'openai') based on user
                # provider preference and configured keys, with automatic failover.
                global LIVE_MODEL
                _forced_eng = getattr(self, "_force_engine_once", "")
                self._force_engine_once = ""
                active_engine = _forced_eng or _resolve_live_engine()
                self._active_engine = active_engine

                _resumed_with = self._resume_handle is not None and active_engine == "gemini"
                if active_engine == "openai":
                    from memory.config_manager import get_openai_cfg
                    live_model = get_openai_cfg().get("realtime_model") or "gpt-4o-realtime-preview"
                else:
                    live_model = _gemini.live_model()
                LIVE_MODEL = live_model
                config = self._build_config()

                if active_engine == "openai":
                    from core.openai_live import connect_openai_live
                    print("[JARVIS] Live engine: OpenAI")
                    live_cm = connect_openai_live(
                        api_key=_get_openai_key(),
                        live_config=config,
                        voice=get_voice(),
                        persona=get_persona(),
                    )
                else:
                    print("[JARVIS] Live engine: Gemini")
                    # Fresh client on every reconnect — avoids stale HTTP session state.
                    # Older rungs: v1alpha carries the proactivity field.
                    # gemini-3.8-live: GA surface is v1beta (Google's own examples),
                    # and the proactivity field must NOT be sent to it.
                    client = genai.Client(
                        api_key=_get_api_key(),
                        http_options={"api_version": (
                            "v1beta" if "gemini-3.8" in live_model
                            else ("v1alpha" if self._enhanced_live else "v1beta")
                        )}
                    )
                    live_cm = client.aio.live.connect(model=live_model, config=config)

                async with (
                    live_cm as session,
                    asyncio.TaskGroup() as tg,
                ):
                    if active_engine == "openai" and getattr(session, "model", None):
                        LIVE_MODEL = session.model
                        live_model = session.model
                    self.session          = session
                    self.audio_in_queue   = asyncio.Queue()
                    # 1024-sample mic blocks @16 kHz = 64 ms each, so 64 blocks
                    # ≈ 4 s of ceiling. Drop-oldest (out_put_drop_oldest) keeps
                    # freshness instead of building a stale replay backlog when
                    # the websocket send stalls — 200 (≈13 s) was both too much
                    # latency on recovery and, before PR #7, silent until full.
                    self.out_queue        = asyncio.Queue(maxsize=64)
                    self._turn_done_event = asyncio.Event()
                    self._session_recycler.on_connect()
                    _was_proactive_recycle = self._proactive_recycle_pending
                    self._proactive_recycle_pending = False

                    # Reset transient state that must not carry over from a previous session
                    self._pending_vision       = None
                    self._vision_cam_active    = False
                    self._vision_close_pending = False
                    self._vision_busy          = False
                    self._vision_last_time     = 0.0
                    self._interrupted          = False
                    self._interrupted_at       = 0.0
                    self._last_interrupted_rx  = 0.0
                    self._abort_playback.clear()

                    # Leaving offline? clear banner before new session
                    try:
                        self._exit_offline_mode()
                    except Exception:
                        pass
                    print("[JARVIS] Connected.")

                    if _was_proactive_recycle:
                        # Seamless 15-min background recycle: preserve current
                        # wake/sleep state and keep the HUD chat log noise-free.
                        if self._wake_enabled:
                            self._ensure_wake_detector()
                            self.ui.set_state("LISTENING" if self._awake else "SLEEPING")
                        else:
                            self._awake = True
                            self.ui.set_state("LISTENING")
                        print(
                            f"[SessionRecycle] ♻️ Recycled seamlessly "
                            f"(cycle #{self._session_recycler.recycle_count}, "
                            f"resumed={_resumed_with})"
                        )
                    else:
                        if _resumed_with:
                            # Say it plainly: the difference between "it reconnected"
                            # and "it reconnected and still knows what we were doing"
                            # is the whole point, and it is invisible otherwise.
                            self.ui.write_log("SYS: Reconnected — conversation restored.")

                        # Wake word: if enabled, come up ASLEEP on fresh start,
                        # but keep an already-awake resumed session awake.
                        if self._wake_enabled:
                            self._ensure_wake_detector()
                            if _resumed_with and self._awake:
                                self.ui.set_state("LISTENING")
                            else:
                                self._awake = False
                                self.ui.set_state("SLEEPING")
                                self.ui.write_log("SYS: JARVIS online — sleeping. Say 'Hey Jarvis' to wake me.")
                        else:
                            self._awake = True
                            self.ui.set_state("LISTENING")
                            self.ui.write_log("SYS: JARVIS online.")

                    if self._dashboard:
                        await self._dashboard.broadcast({"type": "status", "state": "active"})

                    self._reconnect_event.clear()  # ignore requests from before this session
                    tg.create_task(self._watch_reconnect())
                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    tg.create_task(self._run_system_monitor())
                    tg.create_task(self._run_background_monitor())
                    tg.create_task(self._run_proactive_mode())
                    tg.create_task(self._run_heartbeat())
                    tg.create_task(self._run_screen_memory_capture())
                    tg.create_task(self._run_session_recycle())
                    tg.create_task(self._run_sleep_watch())
                    if self._dashboard:
                        tg.create_task(self._relay_phone_audio())

                    # Morning briefing — fires once per process launch (if enabled).
                    # Skipped in wake-word mode: it comes up asleep, and a briefing
                    # would mean talking while "asleep".
                    if not self._briefing_sent and get_brief_enabled() and self._awake:
                        self._briefing_sent = True
                        tg.create_task(self._send_startup_briefing())

            except KeyboardInterrupt:
                raise
            except SystemExit:
                raise
            except BaseException as e:
                # Catches both Exception and BaseExceptionGroup (Python 3.11+
                # TaskGroup raises BaseExceptionGroup when tasks are cancelled
                # externally, which `except Exception` would miss, letting the
                # exception escape the while-loop and causing asyncio.run() to
                # start shutdown — resulting in "executor after shutdown" errors).
                # Voluntary reconnect (voice change) — not an error. Rebuild the
                # session immediately with no backoff and no scary logs.
                if _is_reconnect_signal(e):
                    print("[JARVIS] Voluntary reconnect requested.")
                    if not _keep_context_of(e):
                        # A deliberate clean slate (voice change) — drop the
                        # handle so the next connect really does start empty.
                        self._resume_handle = None
                    self._conn_backoff = 0
                    continue

                self._proactive_recycle_pending = False

                # A resumption handle the server will not accept — expired, or
                # belonging to a session it has since dropped. Without this, the
                # same dead handle would be replayed on every retry and the
                # assistant would never come back at all: the feature meant to
                # survive a reconnect would be the thing preventing one. Drop it
                # once and let the next attempt start clean.
                if _resumed_with and (
                    "resum" in str(e).lower()
                    or "handle" in str(e).lower()
                    or "INVALID_ARGUMENT" in str(e)
                    or "NOT_FOUND" in str(e)
                ):
                    print("[JARVIS] 🔗 Resumption handle rejected — starting a fresh session")
                    self.ui.write_log("SYS: Could not restore the conversation — starting fresh.")
                    self._resume_handle = None
                    self._conn_backoff = 0
                    continue

                # A TaskGroup's own message hides the actionable child error.
                err_str = _flatten_error_text(e)

                # The realtime sender watchdog is a transport recovery signal,
                # not evidence that Gemini rejected turn-taking/media tuning.
                # Previously the substring `realtime_input` incorrectly matched
                # the API-drift branch below, disabled valid features, dumped an
                # alarming ExceptionGroup traceback, and reconnected in a tight
                # loop. Rebuild quietly with bounded consecutive-stall backoff.
                if _is_realtime_send_stall(err_str):
                    delay = min(8.0, 2 ** max(0, self._realtime_send_stalls - 1))
                    print(
                        f"[JARVIS] Realtime audio transport stalled — "
                        f"reconnecting in {delay:g}s."
                    )
                    self.ui.write_log(
                        "NET: Live audio transport paused; reconnecting automatically."
                    )
                    self._conn_backoff = 0
                    await asyncio.sleep(delay)
                    continue

                _network_markers = (
                    "TimeoutError", "timed out", "getaddrinfo", "CancelledError",
                    "ConnectionRefusedError", "OSError", "Cannot connect",
                )
                _looks_like_network = any(marker in err_str for marker in _network_markers)
                try:
                    diagnostic_path = _write_connection_failure(
                        e,
                        engine=getattr(self, "_active_engine", "unknown"),
                    )
                except OSError:
                    diagnostic_path = None
                if _looks_like_network:
                    friendly = _connection_user_message(err_str)
                    print(f"[JARVIS] {friendly}")
                    self.ui.write_log(f"NET: {friendly}")
                    if diagnostic_path is not None:
                        print(f"[JARVIS] Technical details saved to {diagnostic_path}")
                else:
                    # Keep the console concise; the complete redacted traceback is
                    # available in the diagnostic log for support and debugging.
                    print(f"[JARVIS] Connection error ({type(e).__name__}): {err_str[:240]}")

                # Out of quota, or this model is not available to this key —
                # step down the ladder and reconnect straight away. If Gemini
                # rungs are exhausted AND an OpenAI key is configured in 'auto'
                # mode, seamlessly fail over to OpenAI Live!
                if getattr(self, "_active_engine", "gemini") == "gemini" and _gemini.note_live_failure(live_model, err_str):
                    nxt = _gemini.live_model()
                    if nxt != live_model:
                        self._tuned_live = True
                        self._enhanced_live = True
                        self._strip_tool_behavior = False
                        self.ui.write_log(
                            f"SYS: Switching to {nxt.split('/')[-1]} — the previous "
                            f"model is unavailable or out of quota."
                        )
                        self._conn_backoff = 0
                        continue
                    elif _get_openai_key() and _resolve_live_engine(skip_engine="gemini") == "openai":
                        self._force_engine_once = "openai"
                        self.ui.write_log(
                            "SYS: Gemini Live rate-limited — failing over seamlessly to OpenAI Live."
                        )
                        self._conn_backoff = 0
                        continue
                    else:
                        self.ui.write_log("SYS: Every live model is rate-limited — retrying.")
                        self._conn_backoff = 15
                        await asyncio.sleep(self._conn_backoff)
                        continue

                if getattr(self, "_active_engine", "") == "openai" and (
                    "429" in err_str or "quota" in err_str.lower() or "rate limit" in err_str.lower()
                ):
                    if _get_api_key() and _resolve_live_engine(skip_engine="openai") == "gemini":
                        self._force_engine_once = "gemini"
                        self.ui.write_log(
                            "SYS: OpenAI Live rate-limited — failing over seamlessly to Gemini Live."
                        )
                        self._conn_backoff = 0
                        continue

                err_low = err_str.lower()
                is_bad_api_key = any(
                    k in err_low
                    for k in (
                        "api key not valid",
                        "api_key_invalid",
                        "api key expired",
                        "invalid api key",
                        "incorrect api key",
                    )
                )

                # Invalid API key — stop hammering the API, prompt re-configuration
                if is_bad_api_key:
                    self.ui.write_log("ERR: API key invalid — please re-enter your key.")
                    self.ui.set_state("SLEEPING")
                    self.ui.prompt_reconfig()
                    while not self.ui._win._ready:
                        await asyncio.sleep(1)
                    print("[JARVIS] New API key saved — reconnecting...")
                    self._conn_backoff = 1
                    continue

                # Turn-taking / media / thinking knobs rejected by the server
                # (preview API drift) — drop them first, because they are the
                # newest fields and the cheapest to lose.
                if self._tuned_live and (
                    "INVALID_ARGUMENT" in err_str
                    or "1007" in err_str
                    or "Unknown name" in err_str
                    or "unexpected keyword" in err_str
                    or "media_resolution" in err_low
                    or "thinking" in err_low
                ):
                    self._tuned_live = False
                    print("[JARVIS] Live tuning rejected — reconnecting without it.")
                    continue

                # Proactive audio rejected by the server (preview API drift) —
                # drop it and reconnect with the plain config.
                if self._enhanced_live and (
                    "INVALID_ARGUMENT" in err_str
                    or "1007" in err_str
                    or "proactiv" in err_low
                    or "Unknown name" in err_str
                    or "unexpected keyword" in err_str
                ):
                    self._enhanced_live = False
                    self.ui.write_log(
                        "SYS: Proactive audio unavailable — reconnecting without it."
                    )
                    continue

                # Tool `behavior` or unsupported voice rejected on a fallback model
                if not self._strip_tool_behavior and (
                    "INVALID_ARGUMENT" in err_str
                    or "1007" in err_str
                    or "behavior" in err_low
                    or "voice" in err_low
                    or "Unknown name" in err_str
                ):
                    self._strip_tool_behavior = True
                    if "voice" in err_low:
                        try:
                            from memory.config_manager import save_voice
                            save_voice("Aoede" if get_persona() == "female" else "Charon")
                        except Exception:
                            pass
                    print("[JARVIS] Stripping tool behavior / resetting voice — reconnecting.")
                    continue

                # Persistent handshake rejection (1007 / 1008 / INVALID_ARGUMENT)
                # even on stripped config: step down to the next Live model rung
                # instead of falsely blaming the user's API key!
                if "1007" in err_str or "1008" in err_str or "INVALID_ARGUMENT" in err_str:
                    _gemini._cool(live_model, 1800)
                    nxt = _gemini.live_model()
                    if nxt != live_model:
                        self._tuned_live = True
                        self._enhanced_live = True
                        self._strip_tool_behavior = False
                        self.ui.write_log(
                            f"SYS: Switching Live model to {nxt.split('/')[-1]}..."
                        )
                        self._conn_backoff = 0
                        continue

                # Network / timeout errors — log clearly and back off
                is_net_err = _looks_like_network
                if is_net_err:
                    # Phase 2.1 — offer local LLM instead of just backing off
                    try:
                        from memory.config_manager import get_offline_fallback_enabled as _gofe
                        if _gofe():
                            try:
                                self.ui.set_offline(True, "no cloud — trying local LLM")
                            except Exception:
                                pass
                            try:
                                await asyncio.wait_for(
                                    self._run_offline_mode(reason=_connection_user_message(err_str)),
                                    timeout=600,
                                )
                            except asyncio.TimeoutError:
                                pass
                            except Exception as e:
                                print(f"[JARVIS] Offline mode ended: {e}")
                            try:
                                self._exit_offline_mode()
                            except Exception:
                                pass
                            self._conn_backoff = 3
                            continue
                    except Exception:
                        pass
                    _conn_backoff = min(getattr(self, "_conn_backoff", 3) * 2, 60)
                    self._conn_backoff = _conn_backoff
                    self.ui.write_log(
                        f"NET: Retrying automatically in {_conn_backoff}s. "
                        "Use Retry Connection to try immediately."
                    )
                elif "already connected" in err_str:
                    # 1008 — the server still holds the session that just died
                    # on OUR side. It reaps it on its own schedule; hammering a
                    # fresh connect every 3 s only prints the same wall of
                    # errors again. Give it room, then retry.
                    self._conn_backoff = 10
                else:
                    self._conn_backoff = 3
            finally:
                self.session = None
                # Only save if there was a real conversation (≥3 turns)
                if len(self._session_log) >= 3:
                    asyncio.create_task(self._save_session_summary())

            self.set_speaking(False)
            self.ui.set_state("SLEEPING")

            if self._dashboard:
                await self._dashboard.broadcast({"type": "status", "state": "sleeping"})

            delay = getattr(self, "_conn_backoff", 3)
            print(f"[JARVIS] Reconnecting in {delay}s...")
            await self._wait_before_reconnect(delay)

def _parse_cli_persona(argv: list[str]) -> str | None:
    for idx, arg in enumerate(argv):
        low = arg.strip().lower()
        if low in ("--female", "-f"):
            return "female"
        if low in ("--male", "-m"):
            return "male"
        if low == "--persona" and idx + 1 < len(argv):
            val = argv[idx + 1].strip().lower()
            if val in ("male", "female"):
                return val
        if low.startswith("--persona="):
            val = low.split("=", 1)[1].strip()
            if val in ("male", "female"):
                return val
    return None


def main():
    cli_persona = _parse_cli_persona(sys.argv[1:])
    skip_int = any(a.strip().lower() == "--skip-integrations" for a in sys.argv[1:])
    if skip_int:
        os.environ["JARVIS_SKIP_INTEGRATIONS_PROMPT"] = "1"
    ui = JarvisUI("face.png")
    if cli_persona:
        ui.select_persona(cli_persona)

    # Update checks are independent of provider setup. Bind the owner-only HUD
    # gate and check in the background as soon as the interface exists, so a
    # slow/offline Git host never delays first paint or onboarding.
    confirm_gate.bind(show=ui.show_confirm, hide=ui.hide_confirm, log=ui.write_log)
    update_manager.start_startup_check(player=ui, log=ui.write_log)

    def runner():
        ui.wait_for_api_key()
        ui.wait_for_integrations()
        ui.wait_for_persona()
        jarvis = JarvisLive(ui)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()

if __name__ == "__main__":
    main()