"""
core/apex_bridge.py — Real-time WebSocket + HTTP bridge between JARVIS and APEX-UI.

Serves the pre-built `apex_ui/static_hud` bundle locally (zero Node.js required
at runtime) and streams JARVIS's live states, audio waveform levels, transcripts,
circuit-spoke tool traces, settings, and unforgeable action confirmations to the
APEX-UI desktop HUD.
"""

from __future__ import annotations

import asyncio
import html
import json
import mimetypes
import os
import platform
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections import deque
from pathlib import Path
from typing import Any, Callable

try:
    from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
    from fastapi.responses import (
        FileResponse,
        HTMLResponse,
        JSONResponse,
        Response,
        StreamingResponse,
    )
    from fastapi.staticfiles import StaticFiles
except ImportError:  # pragma: no cover
    FastAPI = Request = WebSocket = WebSocketDisconnect = None  # type: ignore[assignment,misc]
    FileResponse = HTMLResponse = JSONResponse = Response = StreamingResponse = StaticFiles = None  # type: ignore[assignment,misc]
from core import (
    audio_devices,
    automations,
    companions,
    desktop_shortcut,
    dev_workspace,
    mcp_adapter,
    security_vault,
)
from core import confirm as confirm_gate
from memory import accounts
from memory import config_manager as cfg
from memory import memory_manager as mm
from memory import timeline
from memory import taste_manager

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_HUD_DIR = BASE_DIR / "apex_ui" / "static_hud"

# Maps JARVIS built-in actions, plugins, and default skills onto the 18 nodes
# of APEX-UI's ReasoningWeb constellation so live cyan circuit particles stream
# along the exact specialist spokes whenever JARVIS invokes a tool.
TOOL_NODE_MAP: dict[str, list[str]] = {
    "web_search": ["researcher"],
    "youtube_video": ["researcher", "social_media"],
    "social_video": ["social_media", "researcher"],
    "social_hub": ["social_media", "comms"],
    "video_player": ["social_media", "design"],
    "memory": ["memory"],
    "brain_control": ["memory", "editor"],
    "topic_learning": ["memory", "researcher"],
    "smart_notes": ["memory", "editor"],
    "lecture_capture": ["memory", "editor"],
    "code_helper": ["developer", "engineering"],
    "cmd_control": ["ops", "developer"],
    "computer_settings": ["ops", "chief_of_staff"],
    "desktop_control": ["ops", "chief_of_staff"],
    "open_app": ["ops"],
    "system_doctor": ["engineering", "analytics"],
    "system_monitor": ["engineering", "analytics"],
    "printer_control": ["engineering"],
    "home_assistant": ["engineering", "ops"],
    "browser_control": ["social_media", "researcher"],
    "screen_process": ["design", "chief_of_staff"],
    "weather_report": ["design", "chief_of_staff"],
    "pushup_counter": ["design"],
    "clipboard_intelligence": ["editor"],
    "file_processor": ["editor", "drive"],
    "file_controller": ["drive", "ops"],
    "excel_writer": ["finance", "analytics"],
    "morning_briefing": ["chief_of_staff", "strategist"],
    "focus_guardian": ["chief_of_staff", "strategist"],
    "cloud_integrations": ["email", "drive", "calendar"],
    "custom_connector": ["developer", "ops"],
    "companion_os": ["chief_of_staff", "strategist"],
    "manage_accounts": ["chief_of_staff", "email"],
    "gws_pack": ["email", "drive", "calendar"],
    "github_automation": ["developer", "engineering"],
    "remote_relay": ["sales", "ops"],
    "music_selection": ["design", "social_media"],
    "gmail_control": ["email"],
    "calendar_control": ["calendar"],
    "whatsapp": ["sales"],
    "chat_takeover": ["sales"],
    "agent_task": ["strategist", "chief_of_staff"],
    "long_task": ["planner", "chief_of_staff"],
}


def map_tool_to_nodes(tool_name: str) -> list[str]:
    """Return 1–2 ReasoningWeb node keys matching a JARVIS tool or skill name."""
    key = (tool_name or "").strip().lower()
    if key in TOOL_NODE_MAP:
        return list(TOOL_NODE_MAP[key])
    for prefix, nodes in TOOL_NODE_MAP.items():
        if prefix in key or key in prefix:
            return list(nodes)
    return ["chief_of_staff", "developer"]


def _pick_port(host: str = "127.0.0.1", preferred: int = 8765) -> int:
    for candidate in (preferred, 8766, 8767, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, candidate))
                return int(s.getsockname()[1])
            except OSError:
                continue
    raise RuntimeError("Could not bind any local port for APEX-UI bridge")


_ACTIVE_BRIDGE: "ApexHudBridge | None" = None


def get_active_bridge() -> "ApexHudBridge | None":
    return _ACTIVE_BRIDGE


class ApexHudBridge:
    """Thread-safe local HTTP + WebSocket server driving the APEX-UI desktop HUD."""

    def __init__(
        self,
        ui_ref: Any = None,
        *,
        host: str | None = None,
        port: int | None = None,
        on_all_windows_closed: Callable[[], None] | None = None,
        auto_close_on_disconnect: bool = False,
    ) -> None:
        global _ACTIVE_BRIDGE
        _ACTIVE_BRIDGE = self
        self._ui = ui_ref
        self.host = host or os.environ.get("JARVIS_HUD_HOST", "127.0.0.1")
        env_port = int(os.environ.get("JARVIS_HUD_PORT", "0") or "0")
        self.port = port or (env_port if env_port > 0 else _pick_port(self.host))
        self.url = f"http://127.0.0.1:{self.port}/"

        self._on_all_windows_closed = on_all_windows_closed
        self._auto_close = auto_close_on_disconnect

        self._lock = threading.Lock()
        self._raw_state = "LISTENING"
        self._offline = False
        self._offline_reason = ""
        self._logs: deque[str] = deque(maxlen=140)
        try:
            for seed_ln in timeline.get_console_seed_lines(limit=80):
                self._logs.append(seed_ln)
        except Exception:
            pass
        self._confirm: dict[str, str] | None = None
        self._content: dict[str, str] | None = None
        self._video: dict[str, Any] | None = None
        self._social_hud: dict[str, Any] | None = None
        self._media_streams: dict[str, dict[str, Any]] = {}
        self._last_level_push = 0.0
        self._tool_tasks: dict[str, dict[str, Any]] = {}
        self._cancelled_task_ids: set[str] = set()

        try:
            from core.subagents import get_subagent_manager
            get_subagent_manager().add_listener(self.push_activity)
        except Exception:
            pass
        try:
            dev_workspace.get_terminal_manager().add_listener(self.push_terminal_session)
        except Exception:
            pass

        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: set[Any] = set()
        self._had_ws_client = False
        try:
            from core.provider import add_route_listener
            add_route_listener(lambda route: self._broadcast_threadsafe({'type':'route_attribution','last_route':route}))
        except Exception: pass
        self._background_mode = False
        self._close_timer: threading.Timer | None = None
        self._started = threading.Event()
        self._start_error: BaseException | None = None
        self._server: Any = None
        self._thread: threading.Thread | None = None

        self._wx_cache: dict[str, Any] | None = None
        self._wx_cached_at = 0.0
        self._auto_scheduler = automations.AutomationScheduler(on_log=self.push_log)
        from core.long_tasks import get_long_task_manager
        self._long_tasks = get_long_task_manager()
        self._long_tasks.add_listener(self.push_activity)
        self._long_tasks.add_notifier(self._notify_long_task_completion)

    # ── State inspection helpers ──────────────────────────────────────────────

    def _is_ready(self) -> bool:
        if os.environ.get("JARVIS_HUD_PREVIEW_READY") == "1":
            return True
        win = getattr(self._ui, "_win", None)
        if win is not None and hasattr(win, "_ready"):
            return bool(win._ready)
        return cfg.is_configured()

    def _is_persona_chosen(self) -> bool:
        if os.environ.get("JARVIS_HUD_PREVIEW_READY") == "1":
            return True
        if os.environ.get("JARVIS_SKIP_PERSONA_PROMPT", "").strip().lower() in (
            "1", "true", "yes",
        ):
            return True
        if self._ui is not None and hasattr(self._ui, "_persona_selected"):
            return bool(self._ui._persona_selected)
        if self._ui is not None:
            return True
        return cfg.is_persona_chosen()

    def _is_integrations_ready(self) -> bool:
        if os.environ.get("JARVIS_HUD_PREVIEW_READY") == "1":
            return True
        if os.environ.get("JARVIS_SKIP_INTEGRATIONS_PROMPT", "").strip().lower() in (
            "1", "true", "yes",
        ):
            return True
        if self._ui is not None and hasattr(self._ui, "_integrations_ready"):
            return bool(self._ui._integrations_ready)
        if self._ui is not None:
            return True
        return cfg.is_integrations_onboarding_done()

    def _is_muted(self) -> bool:
        if self._ui is not None and hasattr(self._ui, "muted"):
            try:
                return bool(self._ui.muted)
            except Exception:
                pass
        return False

    def _is_paused(self) -> bool:
        if self._ui is not None:
            gp_ui = getattr(self._ui, "get_pause_state", None)
            if callable(gp_ui):
                try:
                    return bool(gp_ui())
                except Exception:
                    pass
        win = getattr(self._ui, "_win", None)
        if win is not None:
            gp = getattr(win, "get_pause_state", None)
            if callable(gp):
                try:
                    return bool(gp())
                except Exception:
                    pass
            return bool(getattr(win, "_paused_ui", False))
        return False

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            logs_list = list(self._logs)
            confirm_obj = dict(self._confirm) if self._confirm else None
            content_obj = dict(self._content) if self._content else None
            video_obj = dict(self._video) if self._video else None
            social_hud_obj = dict(self._social_hud) if self._social_hud else None
            raw_state = self._raw_state
            offline = self._offline
            offline_reason = self._offline_reason

        try:
            in_devs = audio_devices.list_devices("input")
        except Exception:
            in_devs = [audio_devices.DEFAULT_LABEL]
        try:
            out_devs = audio_devices.list_devices("output")
        except Exception:
            out_devs = [audio_devices.DEFAULT_LABEL]

        try:
            b_counts = timeline.get_brain_snapshot()["counts"]
        except Exception:
            b_counts = {"memories": 0, "files": 0, "outputs": 0, "timeline": 0}

        gkey = cfg.get_gemini_key() or ""
        okey = cfg.get_openai_key() or ""
        akey = cfg.get_anthropic_key() or ""
        ocfg = cfg.get_openai_cfg()
        acfg = cfg.get_anthropic_cfg()
        shortcut_pref = cfg.get_desktop_shortcut_preference()
        shortcut_state = desktop_shortcut.status()
        onboarding_complete = bool(
            self._is_ready() and self._is_integrations_ready() and self._is_persona_chosen()
        )
        taste_state = taste_manager.status()
        taste_state["prompt_pending"] = bool(
            onboarding_complete and not taste_state["prompted"]
        )
        shortcut_state["prompt_pending"] = bool(
            onboarding_complete
            and taste_state["prompted"]
            and not shortcut_pref["prompted"]
        )

        def _mask_key(k: str) -> str:
            if not k or len(k) < 10:
                return ""
            return f"{k[:7]}••••{k[-4:]}"

        return {
            "type": "bootstrap",
            "ready": self._is_ready(),
            "integrations_ready": self._is_integrations_ready(),
            "integrations": accounts.get_integrations_status_summary(),
            "privacy": cfg.get_privacy_settings(),
            "brain_counts": b_counts,
            "workers": self.get_activity_snapshot(),
            "active_companion": companions.get_active_companion(),
            "theme_custom": companions.get_theme_customization(),
            "provider": cfg.get_provider(),
            "last_route": __import__('core.provider',fromlist=['last_route']).last_route(),
            "active_engine": (
                "anthropic" if cfg.get_provider() == "anthropic" and len(akey) > 15
                else cfg.resolve_cloud_engine()
            ),
            "has_gemini_key": bool(gkey and len(gkey) > 15),
            "has_openai_key": bool(okey and len(okey) > 15),
            "has_anthropic_key": bool(akey and len(akey) > 15),
            "gemini_key_masked": _mask_key(gkey),
            "openai_key_masked": _mask_key(okey),
            "anthropic_key_masked": _mask_key(akey),
            "anthropic_model": acfg.get("model", "claude-sonnet-4-5"),
            "openai_model": ocfg.get("model", "gpt-4o"),
            "openai_realtime_model": ocfg.get("realtime_model", "gpt-4o-realtime-preview"),
            "openai_base_url": ocfg.get("base_url", "https://api.openai.com/v1"),
            "persona": cfg.get_persona(),
            "persona_chosen": self._is_persona_chosen(),
            "desktop_shortcut": shortcut_state,
            "taste_profile": taste_state,
            "assistant_name": cfg.get_assistant_name(),
            "raw_state": raw_state,
            "muted": self._is_muted(),
            "paused": self._is_paused(),
            "offline": offline,
            "offline_reason": offline_reason,
            "voice": cfg.get_voice(),
            "voices": list(cfg.AVAILABLE_VOICES),
            "male_voices": list(cfg.MALE_VOICES),
            "female_voices": list(cfg.FEMALE_VOICES),
            "barge_enabled": cfg.get_barge_in_enabled(),
            "grace_period": cfg.get_grace_period(),
            "inputs": in_devs,
            "outputs": out_devs,
            "current_input": cfg.get_input_device(),
            "current_output": cfg.get_output_device(),
            "logs": logs_list,
            "confirm": confirm_obj,
            "content": content_obj,
            "video": video_obj,
            "social_hud": social_hud_obj,
            "background_mode": bool(self._background_mode),
        }

    # ── Push methods called from JarvisUI / audio threads ─────────────────────

    def _register_media_stream(
        self, source: str, headers: dict[str, str] | None = None
    ) -> str:
        raw = (source or "").strip()
        if not raw:
            return ""
        tok = secrets.token_urlsafe(12)
        with self._lock:
            self._media_streams[tok] = {
                "source": raw,
                "headers": dict(headers or {}),
                "created_at": time.time(),
            }
            if len(self._media_streams) > 28:
                oldest = sorted(
                    self._media_streams.items(),
                    key=lambda kv: kv[1].get("created_at", 0.0),
                )[:8]
                for k, _ in oldest:
                    self._media_streams.pop(k, None)
        return f"/api/hud/media/{tok}"

    def push_video(
        self,
        source: str,
        *,
        title: str = "",
        muted: bool = True,
        audio_source: str = "",
        headers: dict[str, str] | None = None,
        webpage_url: str = "",
        platform: str = "",
        queue: list[dict[str, Any]] | None = None,
        queue_index: int = 0,
        playlist_title: str = "",
        playlist_url: str = "",
        _keep_queue: bool = False,
    ) -> None:
        raw = (source or "").strip()
        if not raw:
            return
        v_url = self._register_media_stream(raw, headers=headers)
        a_url = (
            self._register_media_stream(audio_source, headers=headers)
            if (audio_source or "").strip()
            else ""
        )
        plat = (platform or "").strip()
        if not plat:
            try:
                from core.media_engine import detect_platform

                plat = detect_platform(webpage_url or raw)
            except Exception:
                plat = "Video"

        with self._lock:
            if queue is not None:
                self._video_queue = [dict(item) for item in queue if isinstance(item, dict)]
                self._video_queue_index = max(0, min(int(queue_index or 0), max(0, len(self._video_queue) - 1)))
                self._video_playlist_title = str(playlist_title or "").strip()[:120]
                self._video_playlist_url = str(playlist_url or "").strip()
            elif not _keep_queue:
                self._video_queue = []
                self._video_queue_index = 0
                self._video_playlist_title = ""
                self._video_playlist_url = ""

            q_copy = [dict(item) for item in getattr(self, "_video_queue", [])]
            q_idx = int(getattr(self, "_video_queue_index", 0))
            p_title = str(getattr(self, "_video_playlist_title", ""))
            p_url = str(getattr(self, "_video_playlist_url", ""))

            rec = {
                "id": secrets.token_hex(4),
                "video_url": v_url,
                "audio_url": a_url,
                "title": (title or Path(raw).name or "Video")[:120],
                "muted": bool(muted),
                "webpage_url": (webpage_url or "").strip(),
                "platform": plat,
                "playlist_title": p_title,
                "playlist_url": p_url,
                "queue_index": q_idx,
                "queue_total": len(q_copy),
                "queue": q_copy,
            }
            self._video = rec
            self._last_video_target = (webpage_url or raw).strip()
        self._broadcast_threadsafe({"type": "video", "video": dict(rec)})

    def jump_video_queue(self, index: int) -> dict[str, Any]:
        with self._lock:
            q = [dict(item) for item in getattr(self, "_video_queue", [])]
            cur_muted = bool(self._video.get("muted", True)) if self._video else False
            p_title = str(getattr(self, "_video_playlist_title", ""))
        if not q:
            return {"ok": False, "error": "No Mix or Playlist queue is currently loaded."}
        target_idx = int(index) % len(q)
        entry = q[target_idx]
        target_url = str(entry.get("url") or "").strip()
        if not target_url:
            return {"ok": False, "error": "Selected track has no playable URL."}

        try:
            from core.media_engine import resolve_playable_stream

            stream = resolve_playable_stream(target_url)
            if not stream.ok or not stream.video_url:
                return {"ok": False, "error": stream.error or "Could not resolve track stream."}
            with self._lock:
                self._video_queue_index = target_idx
            self.push_video(
                stream.video_url,
                title=stream.title or str(entry.get("title") or f"Track {target_idx + 1}"),
                muted=cur_muted,
                audio_source=stream.audio_url or "",
                headers=stream.http_headers,
                webpage_url=stream.webpage_url or target_url,
                platform=stream.platform or str(entry.get("platform") or "YouTube"),
                _keep_queue=True,
            )
            self.push_log(
                f"MIX [{target_idx + 1}/{len(q)}]: {stream.title or entry.get('title')}"
                + (f" ({p_title})" if p_title else "")
            )
            return {
                "ok": True,
                "index": target_idx,
                "total": len(q),
                "title": stream.title or str(entry.get("title") or ""),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def step_video_queue(self, delta: int = 1) -> dict[str, Any]:
        with self._lock:
            q = getattr(self, "_video_queue", [])
            cur_idx = int(getattr(self, "_video_queue_index", 0))
            total = len(q)
        if total == 0:
            return {"ok": False, "error": "No Mix or Playlist queue is currently loaded."}
        return self.jump_video_queue((cur_idx + int(delta)) % total)

    def current_video_target(self) -> str:
        with self._lock:
            if self._video is not None:
                return str(getattr(self, "_last_video_target", "") or self._video.get("webpage_url") or "")
        return ""

    def current_video_snapshot(self) -> dict[str, Any] | None:
        """Stable metadata used to bind an observable long-term media monitor."""
        with self._lock:
            return dict(self._video) if self._video else None

    def _notify_long_task_completion(self, task: dict[str, Any]) -> None:
        message = str(task.get("notify_message") or task.get("title") or "Task completed.")
        self.push_log(f"SYS: LONG TASK COMPLETE — {message}")

    def current_mix_target(self) -> str:
        with self._lock:
            if self._video is not None:
                return str(getattr(self, "_video_playlist_url", "") or "")
            return ""

    def stop_video(self) -> None:
        with self._lock:
            self._video = None
            self._video_queue = []
            self._video_queue_index = 0
            self._video_playlist_title = ""
            self._video_playlist_url = ""
        self._broadcast_threadsafe({"type": "video", "video": None})

    def set_video_muted(self, muted: bool) -> None:
        with self._lock:
            if self._video is None:
                return
            self._video["muted"] = bool(muted)
            snap = dict(self._video)
        self._broadcast_threadsafe({"type": "video", "video": snap})

    def video_is_playing(self) -> bool:
        with self._lock:
            return self._video is not None

    def set_social_hud(self, payload: dict[str, Any] | None) -> None:
        with self._lock:
            self._social_hud = dict(payload) if payload else None
            snap = dict(self._social_hud) if self._social_hud else None
        self._broadcast_threadsafe({"type": "social_hud", "social_hud": snap})

    def notify_background_mode(self, active: bool, native_dock: bool = False) -> None:
        self._background_mode = bool(active)
        self._broadcast_threadsafe(
            {
                "type": "background_mode",
                "active": bool(active),
                "native_dock": bool(native_dock),
            }
        )

    def _broadcast_threadsafe(self, payload: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        def dispatch():
            # Construct the coroutine on its owning loop, not on the audio/tool
            # thread: a close race must not leak an unawaited coroutine.
            if not loop.is_closed():
                asyncio.create_task(self._async_broadcast(payload))
        try:
            loop.call_soon_threadsafe(dispatch)
        except RuntimeError:
            pass

    async def _async_broadcast(self, payload: dict[str, Any]) -> None:
        if not self._clients:
            return
        raw = json.dumps(payload)
        locks = getattr(self, "_client_send_locks", None)
        if locks is None:
            locks = self._client_send_locks = {}
        async def ordered_send(ws):
            if ws not in self._clients:
                return
            lock = locks.setdefault(ws, asyncio.Lock())
            async with lock:
                if ws in self._clients:
                    await ws.send_text(raw)
        async def send(ws):
            try:
                # A stalled/closed window cannot hold up the other HUD clients
                # or accumulate indefinitely waiting for a socket write.
                await asyncio.wait_for(ordered_send(ws), timeout=2.0)
            except Exception:
                was_active = ws in self._clients
                self._clients.discard(ws)
                locks.pop(ws, None)
                # Force an actual reconnect rather than leaving an open but
                # permanently unsubscribed HUD socket after backpressure.
                if was_active and callable(getattr(ws, "close", None)):
                    try:
                        await asyncio.wait_for(ws.close(code=1013), timeout=.2)
                    except Exception:
                        pass
        await asyncio.gather(*(send(ws) for ws in tuple(self._clients)))

    def push_state(self, state: str) -> None:
        s = (state or "LISTENING").upper()
        with self._lock:
            self._raw_state = s
            offline = self._offline
            offline_reason = self._offline_reason
        self._broadcast_threadsafe(
            {
                "type": "state",
                "raw_state": s,
                "muted": self._is_muted(),
                "paused": self._is_paused(),
                "offline": offline,
                "offline_reason": offline_reason,
            }
        )

    def push_audio_level(self, level: float) -> None:
        now = time.monotonic()
        if now - self._last_level_push < 0.04:  # cap at ~25 Hz
            return
        self._last_level_push = now
        lv = max(0.0, min(1.0, float(level or 0.0)))
        self._broadcast_threadsafe({"type": "level", "level": round(lv, 4)})

    def push_log(self, text: str) -> None:
        line = str(text or "").strip()
        if not line:
            return
        with self._lock:
            self._logs.append(line)
        self._broadcast_threadsafe(
            {
                "type": "log",
                "line": line,
                "ts": time.strftime("%H:%M:%S"),
            }
        )

    def push_tool_trace(self, tool_names: list[str] | str) -> None:
        names = [tool_names] if isinstance(tool_names, str) else list(tool_names or [])
        nodes: list[str] = []
        for name in names:
            for n in map_tool_to_nodes(name):
                if n not in nodes:
                    nodes.append(n)
        if nodes:
            self._broadcast_threadsafe(
                {
                    "type": "trace",
                    "tool": ", ".join(names),
                    "nodes": nodes[:4],
                }
            )

    def get_activity_snapshot(self) -> list[dict[str, Any]]:
        """Unified live worker list combining SubagentManager + running/recent tool tasks."""
        items: list[dict[str, Any]] = []
        try:
            from core.subagents import get_subagent_manager
            items.extend(get_subagent_manager().list_detailed())
        except Exception:
            pass
        try:
            items.extend(self._long_tasks.list_detailed())
        except Exception:
            pass

        now = time.time()
        with self._lock:
            tasks = list(self._tool_tasks.values())
        for t in tasks:
            end_ts = t["updated_at"] if t["status"] in ("completed", "failed", "cancelled") else now
            items.append(
                {
                    **t,
                    "elapsed_s": round(max(0.0, end_ts - float(t["created_at"])), 1),
                }
            )

        # Sort active/pending first, then newest first
        rank = {"in_progress": 0, "needs_review": 0, "pending": 1, "completed": 2, "failed": 2, "cancelled": 2, "expired": 2}
        items.sort(key=lambda w: (rank.get(str(w.get("status")), 3), -float(w.get("created_at") or 0)))
        return items[:36]

    def push_activity(self) -> None:
        self._broadcast_threadsafe(
            {"type": "activity", "workers": self.get_activity_snapshot()}
        )

    def push_terminal_session(self, session: dict[str, Any]) -> None:
        self._broadcast_threadsafe({"type": "terminal", "session": session})

    def notify_tool_start(
        self, task_id: str, tool_name: str, args_summary: str = ""
    ) -> None:
        now = time.time()
        tid = str(task_id or f"tool-{int(now * 1000)}")
        label = f"{tool_name}" + (f" · {args_summary[:64]}" if args_summary else "")
        rec: dict[str, Any] = {
            "id": tid,
            "kind": "tool",
            "title": label,
            "goal": label,
            "status": "in_progress",
            "tools": [tool_name],
            "nodes": map_tool_to_nodes(tool_name)[:3],
            "steps": [{"step": 1, "action": tool_name, "result": args_summary[:180] or "Running…", "ts": now}],
            "step_count": 1,
            "max_steps": 1,
            "result": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._tool_tasks[tid] = rec
            if len(self._tool_tasks) > 32:
                # Prune oldest finished entries first
                finished = [
                    k for k, v in self._tool_tasks.items()
                    if v.get("status") in ("completed", "failed", "cancelled")
                ]
                for k in finished[:8]:
                    self._tool_tasks.pop(k, None)
        self.push_activity()

    def notify_tool_finish(
        self, task_id: str, result_summary: str = "", status: str = "completed"
    ) -> None:
        now = time.time()
        with self._lock:
            rec = self._tool_tasks.get(str(task_id))
            if rec is None:
                return
            if str(task_id) in self._cancelled_task_ids:
                rec["status"] = "cancelled"
            else:
                rec["status"] = status if status in ("completed", "failed", "cancelled") else "completed"
            rec["updated_at"] = now
            if rec["status"] == "failed":
                rec["error"] = str(result_summary or "")[:300]
            else:
                rec["result"] = str(result_summary or "")[:300]
            if rec.get("steps"):
                rec["steps"][-1]["result"] = str(result_summary or "Done.")[:220]
        self.push_activity()

    def is_task_cancelled(self, task_id: str) -> bool:
        with self._lock:
            return str(task_id) in self._cancelled_task_ids

    def push_integrations(self) -> None:
        """Publish observed session health to already-open Settings/LINKS panels."""
        self._broadcast_threadsafe({"type": "integrations", "integrations": accounts.get_integrations_status_summary()})

    def push_confirm(self, title: str, detail: str) -> None:
        obj = {"title": str(title)[:120], "detail": str(detail)[:4000]}
        with self._lock:
            self._confirm = obj
        self._broadcast_threadsafe({"type": "confirm", "confirm": obj})

    def hide_confirm(self) -> None:
        with self._lock:
            self._confirm = None
        self._broadcast_threadsafe({"type": "confirm", "confirm": None})

    def push_content(self, title: str, text: str) -> None:
        obj = {"title": str(title)[:64], "text": str(text)[:4000]}
        with self._lock:
            self._content = obj
        try:
            timeline.record_output(str(title)[:120], str(text)[:12000])
        except Exception:
            pass
        self._broadcast_threadsafe({"type": "content", "content": obj})

    def push_offline(self, offline: bool, reason: str = "") -> None:
        with self._lock:
            self._offline = bool(offline)
            self._offline_reason = str(reason or "")
            raw = self._raw_state
        self._broadcast_threadsafe(
            {
                "type": "state",
                "raw_state": raw,
                "muted": self._is_muted(),
                "paused": self._is_paused(),
                "offline": bool(offline),
                "offline_reason": str(reason or ""),
            }
        )

    def push_reconfig(self) -> None:
        self._broadcast_threadsafe({"type": "reconfig"})

    # ── Inbound HUD command execution ─────────────────────────────────────────

    def _get_soul_api(self):
        from core.soul.api import SoulStudioAPI
        from core.soul.service import get_default_service
        return SoulStudioAPI(get_default_service())

    def handle_soul_action(self, data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """Validated Soul Studio mutations with optimistic revision conflicts."""
        try:
            from core.soul.store import RevisionConflict
            api = self._get_soul_api()
            operation = str(data.get("operation") or "").strip()
            revision = data.get("expected_revision")
            if operation == "runtime":
                if not isinstance(data.get("enabled"), bool):
                    return 400, {"ok": False, "error": "enabled must be boolean"}
                cfg.save_soul_enabled(data["enabled"])
                return 200, {"ok": True, "soul": api.snapshot()}
            if operation == "identity":
                state = api.update_identity(data.get("values") if isinstance(data.get("values"), dict) else {}, revision)
            elif operation == "initiative":
                state = api.update_initiative(data.get("values") if isinstance(data.get("values"), dict) else {}, revision)
            elif operation == "privacy":
                state = api.update_privacy(data.get("values") if isinstance(data.get("values"), dict) else {}, revision)
            elif operation == "trait":
                state = api.decide_trait(str(data.get("trait_id") or ""), str(data.get("decision") or ""), revision)
            elif operation == "forget_relationship":
                state, claims, contradictions = api.forget_relationship(str(data.get("subject") or ""), revision)
                return 200, {"ok": True, "revision": state.revision, "forgotten": {"claims": claims, "contradictions": contradictions}, "soul": api.snapshot()}
            elif operation == "reset":
                state = api.reset(str(data.get("scope") or ""), revision)
            elif operation == "undo":
                state = api.undo(revision)
            else:
                return 400, {"ok": False, "error": "unsupported Soul operation"}
            return 200, {"ok": True, "revision": state.revision, "soul": api.snapshot()}
        except RevisionConflict as exc:
            return 409, {"ok": False, "error": str(exc), "code": "revision_conflict"}
        except Exception as exc:
            return 400, {"ok": False, "error": str(exc)}

    def handle_action(self, data: dict[str, Any]) -> dict[str, Any]:
        action = str(data.get("action") or "").strip()
        ui = self._ui
        win = getattr(ui, "_win", None) if ui is not None else None

        if action in ("save_api_key", "save_ai_providers"):
            single_key = str(data.get("key") or "").strip()
            g_key = str(data.get("gemini_key") or "").strip()
            o_key = str(data.get("openai_key") or "").strip()
            a_key = str(data.get("anthropic_key") or "").strip()
            prov = str(data.get("provider") or "").strip().lower()
            a_model = str(data.get("anthropic_model") or "").strip()
            o_model = str(data.get("openai_model") or "").strip()
            o_rt_model = str(data.get("openai_realtime_model") or "").strip()
            o_base = str(data.get("openai_base_url") or "").strip()

            # Smart single-field routing (`sk-...` -> OpenAI, `AIza...` -> Gemini)
            if single_key and not g_key and not o_key and not a_key:
                if single_key.startswith("sk-ant-"):
                    a_key = single_key
                elif single_key.startswith("sk-"):
                    o_key = single_key
                else:
                    g_key = single_key

            cfg.ensure_config_dir()
            existing = cfg.load_api_keys()
            was_live = self._is_persona_chosen() and self._is_ready()

            if action == "save_api_key":
                has_existing_any = bool(
                    (existing.get("gemini_api_key") and len(str(existing.get("gemini_api_key"))) > 15)
                    or (existing.get("openai_api_key") and len(str(existing.get("openai_api_key"))) > 15)
                    or (existing.get("anthropic_api_key") and len(str(existing.get("anthropic_api_key"))) > 15)
                )
                if len(g_key) < 15 and len(o_key) < 15 and len(a_key) < 15 and not has_existing_any:
                    return {"ok": False, "error": "Please enter a valid Claude, OpenAI, or Gemini API key"}

            if g_key and len(g_key) >= 15:
                existing["gemini_api_key"] = g_key
            if o_key and len(o_key) >= 15:
                existing["openai_api_key"] = o_key
            if a_key and len(a_key) >= 15:
                existing["anthropic_api_key"] = a_key
            if data.get("clear_gemini_key"):
                existing["gemini_api_key"] = ""
            if data.get("clear_openai_key"):
                existing["openai_api_key"] = ""
            if data.get("clear_anthropic_key"):
                existing["anthropic_api_key"] = ""

            if a_model:
                existing["anthropic_model"] = a_model
            if o_model:
                existing["openai_model"] = o_model
            if o_rt_model:
                existing["openai_realtime_model"] = o_rt_model
            if o_base:
                existing["openai_base_url"] = o_base.rstrip("/")

            if prov in cfg.PROVIDERS:
                existing["provider"] = prov
            else:
                # Auto-pick sensible provider when saving keys during setup
                has_g = bool(existing.get("gemini_api_key"))
                has_o = bool(existing.get("openai_api_key"))
                has_a = bool(existing.get("anthropic_api_key"))
                if has_a and not has_g and not has_o:
                    existing["provider"] = "anthropic"
                elif has_o and not has_g and not has_a:
                    existing["provider"] = "openai"
                elif has_g and not has_o and not has_a:
                    existing["provider"] = "auto"

            os_name = platform.system()
            existing.setdefault("os_system", os_name)

            # Credentials are always encrypted at rest; the legacy opt-in flags
            # remain readable only for backwards compatibility.
            to_write = security_vault.encrypt_dict_secrets(dict(existing))
            cfg._write_config_text(
                json.dumps(to_write, indent=4), encoding="utf-8"
            )
            try:
                from core import gemini as _gem_mod
                _gem_mod.api_key(refresh=True)
            except Exception:
                pass
            if win is not None:
                win._ready = True
                if not was_live:
                    self._invoke_qt(lambda: win._on_setup_done("", os_name))
            if was_live and ui is not None:
                cb = getattr(ui, "on_integrations_change", None)
                if callable(cb):
                    threading.Thread(target=cb, daemon=True).start()
            active_eng = (
                "anthropic"
                if cfg.get_provider() == "anthropic" and cfg.get_anthropic_key()
                else cfg.resolve_cloud_engine()
            )
            self.push_log(f"SYS: AI engine configured — active backend: {active_eng.upper()}.")
            self._broadcast_threadsafe(self.snapshot())
            return {"ok": True, "active_engine": active_eng, "provider": cfg.get_provider()}

        if action == "save_integrations":
            was_live = self._is_persona_chosen()
            payload = data.get("integrations")
            res = accounts.save_onboarding_integrations(
                payload if isinstance(payload, dict) else {}
            )
            if ui is not None:
                setattr(ui, "_integrations_ready", True)
            if win is not None and hasattr(win, "mark_integrations_done"):
                self._invoke_qt(win.mark_integrations_done)
            saved_list = res.get("saved") or []
            if saved_list:
                self.push_log(f"SYS: Connected integrations: {', '.join(saved_list)}.")
            else:
                self.push_log(
                    "SYS: Optional integrations saved (unfilled services ignored)."
                )
            if was_live and ui is not None:
                cb = getattr(ui, "on_integrations_change", None)
                if callable(cb):
                    threading.Thread(target=cb, daemon=True).start()
            self._broadcast_threadsafe(self.snapshot())
            return res

        if action == "skip_integrations":
            cfg.save_integrations_onboarding_done(True)
            if ui is not None:
                setattr(ui, "_integrations_ready", True)
            if win is not None and hasattr(win, "mark_integrations_done"):
                self._invoke_qt(win.mark_integrations_done)
            self.push_log(
                "SYS: Optional integrations skipped — connect any anytime in HUD -> Integrations."
            )
            self._broadcast_threadsafe(self.snapshot())
            return {"ok": True, "summary": accounts.get_integrations_status_summary()}

        if action == "taste_profile":
            operation = str(data.get("operation") or "get").strip().lower()
            try:
                if operation == "save_onboarding":
                    state = taste_manager.save_onboarding(data.get("values") or {})
                    message = "Taste profile saved."
                elif operation == "skip":
                    state = taste_manager.mark_onboarding_complete()
                    message = "Taste setup skipped. You can complete it later in Settings."
                elif operation == "add":
                    taste_manager.add_preference(
                        data.get("domain", "other"), data.get("item", ""),
                        data.get("sentiment", "like"), data.get("contexts") or [],
                        kind=data.get("kind", "preference"),
                    )
                    state, message = taste_manager.status(), "Taste preference saved."
                elif operation == "remove":
                    taste_manager.remove_preference(str(data.get("entry_id") or ""))
                    state, message = taste_manager.status(), "Taste preference removed."
                elif operation == "set_discovery":
                    state = taste_manager.set_discovery(data.get("domain", "other"), data.get("mode", "balanced"))
                    message = "Discovery preference updated."
                elif operation == "clear":
                    taste_manager.clear_profile()
                    state, message = taste_manager.status(), "Taste profile cleared."
                else:
                    state, message = taste_manager.status(), ""
                state["prompt_pending"] = False
                self._broadcast_threadsafe(self.snapshot())
                return {"ok": True, "taste_profile": state, "message": message}
            except ValueError as exc:
                return {"ok": False, "error": str(exc), "taste_profile": taste_manager.status()}
            except OSError as exc:
                return {
                    "ok": False,
                    "error": f"Taste profile could not be saved ({type(exc).__name__}).",
                    "taste_profile": taste_manager.status(),
                }

        if action == "installation_lifecycle":
            from core.system_doctor import installation_identity
            from core import installation_registry
            identity = installation_identity()
            operation = str(data.get("operation") or "status").strip().lower()
            if operation == "make_active":
                message = installation_registry.request_make_active(identity.installation_id)
                return {"ok": True, "message": message, "lifecycle": installation_registry.status(identity.installation_id)}
            if operation == "unregister":
                requested_id = str(data.get("installation_id") or identity.installation_id)
                known_ids = {str(row.get("installation_id")) for row in installation_registry.status(identity.installation_id)["installations"]}
                target_id = requested_id if requested_id in known_ids else identity.installation_id
                message = installation_registry.request_unregister(target_id)
                return {"ok": True, "message": message, "lifecycle": installation_registry.status(identity.installation_id)}
            return {"ok": True, "identity": identity.__dict__, "lifecycle": installation_registry.status(identity.installation_id)}

        if action == "system_doctor":
            operation = str(data.get("operation") or "run").strip().lower()
            try:
                if operation == "repair":
                    from core.system_repair import request_repair
                    message = request_repair(str(data.get("repair") or ""))
                    return {"ok": message.startswith("[CONFIRMATION_PENDING]"), "message": message}
                if operation == "repair_status":
                    from core.system_repair import repair_status
                    return {"ok": True, "repair_result": repair_status()}
                from core.system_doctor import run_doctor, write_support_report
                report = run_doctor()
                scheduler_thread = getattr(self._auto_scheduler, "_thread", None)
                runtime_ok = bool(
                    self._server is not None and self._server.started
                    and self._thread is not None and self._thread.is_alive()
                )
                scheduler_ok = bool(scheduler_thread and scheduler_thread.is_alive())
                runtime_results = [
                    {
                        "check": "hud_runtime", "status": "ok" if runtime_ok else "warning",
                        "state": "healthy" if runtime_ok else "degraded",
                        "code": "JARVIS-HUD-RUNTIME-" + ("OK" if runtime_ok else "WARNING"),
                        "summary": "The active HUD server is running." if runtime_ok else "No active HUD server was observed.",
                        "evidence": "observed by APEX bridge", "remediation": "Restart the HUD or use Classic UI." if not runtime_ok else "",
                    },
                    {
                        "check": "scheduler_runtime", "status": "ok" if scheduler_ok else "warning",
                        "state": "healthy" if scheduler_ok else "degraded",
                        "code": "JARVIS-SCHEDULER-RUNTIME-" + ("OK" if scheduler_ok else "WARNING"),
                        "summary": "The automation scheduler is running." if scheduler_ok else "The automation scheduler is not running.",
                        "evidence": "observed by APEX bridge", "remediation": "Restart JARVIS." if not scheduler_ok else "",
                    },
                ]
                report["results"].extend(runtime_results)
                for item in runtime_results:
                    report["counts"][item["status"]] += 1
                if any(item["status"] == "warning" for item in runtime_results) and report["overall"] == "ok":
                    report["overall"] = "warning"
                result = {"ok": True, "doctor": report}
                if operation == "report":
                    result["report_path"] = str(write_support_report())
                return result
            except Exception as exc:
                return {
                    "ok": False,
                    "error": f"System Doctor failed safely ({type(exc).__name__}).",
                }

        if action == "desktop_shortcut":
            operation = str(data.get("operation") or "status").strip().lower()
            try:
                if operation == "create":
                    path = desktop_shortcut.create()
                    cfg.save_desktop_shortcut_preference(True)
                    result = {"ok": True, "message": f"Desktop shortcut created at {path}."}
                elif operation == "remove":
                    desktop_shortcut.remove()
                    cfg.save_desktop_shortcut_preference(False)
                    result = {"ok": True, "message": "Desktop shortcut removed."}
                elif operation == "decline":
                    cfg.save_desktop_shortcut_preference(False)
                    result = {"ok": True, "message": "You can add it later from Settings or by asking JARVIS."}
                else:
                    result = {"ok": True}
            except (OSError, subprocess.SubprocessError) as exc:
                result = {"ok": False, "error": f"Could not update the desktop shortcut ({type(exc).__name__})."}
            snapshot = self.snapshot()
            result["desktop_shortcut"] = snapshot["desktop_shortcut"]
            self._broadcast_threadsafe(snapshot)
            return result

        if action == "disconnect_integration":
            svc = str(data.get("service") or "").strip().lower()
            if svc == "google":
                for g_svc in ("gmail", "google_drive", "google_calendar"):
                    accounts.disconnect_account(g_svc)
            elif svc in getattr(accounts, "SOCIAL_SERVICES", ()):
                try:
                    from core.social_hub import disconnect_social_account
                    disconnect_social_account(svc)
                except Exception:
                    accounts.disconnect_account(svc)
            elif svc:
                accounts.disconnect_account(svc)
            self.push_log(f"SYS: Disconnected {svc or 'integration'}.")
            if self._is_persona_chosen() and ui is not None:
                cb = getattr(ui, "on_integrations_change", None)
                if callable(cb):
                    threading.Thread(target=cb, daemon=True).start()
            self._broadcast_threadsafe(self.snapshot())
            return {"ok": True, "summary": accounts.get_integrations_status_summary()}

        if action == "social_open_hud":
            from core.social_hub import open_social_in_hud

            plat = str(data.get("platform") or "instagram").strip().lower()
            view = str(data.get("view") or "feed").strip().lower()
            layout = str(data.get("layout") or "").strip().lower()
            res_hud = open_social_in_hud(plat, view=view, layout=layout or "mobile")
            return {**res_hud, "summary": accounts.get_integrations_status_summary()}

        if action == "social_close_hud":
            from core.social_hub import close_social_hud

            close_social_hud()
            return {"ok": True}

        if action == "social_connect_web":
            from core.social_hub import start_social_login

            plat = str(data.get("platform") or "").strip().lower()
            handle = str(data.get("handle") or "").strip()
            perm = str(data.get("permission") or "ask").strip().lower()

            def _on_social_done() -> None:
                self.push_log(f"SYS: {plat.capitalize()} session authenticated ({perm}).")
                if self._is_persona_chosen() and ui is not None:
                    cb = getattr(ui, "on_integrations_change", None)
                    if callable(cb):
                        threading.Thread(target=cb, daemon=True).start()
                self._broadcast_threadsafe(self.snapshot())

            res_soc = start_social_login(
                plat,
                handle=handle,
                permission=perm,
                on_connected=_on_social_done,
            )
            self._broadcast_threadsafe(self.snapshot())
            return {**res_soc, "summary": accounts.get_integrations_status_summary()}

        if action == "social_import_cookies":
            from core.social_hub import import_cookies_from_browser

            plat = str(data.get("platform") or "").strip().lower()
            browser = str(data.get("browser") or "auto").strip().lower()
            handle = str(data.get("handle") or "").strip()
            perm = str(data.get("permission") or "ask").strip().lower()

            def _on_cookie_social_done() -> None:
                self.push_log(f"SYS: {plat.capitalize()} session authenticated ({perm}).")
                if self._is_persona_chosen() and ui is not None:
                    cb = getattr(ui, "on_integrations_change", None)
                    if callable(cb):
                        threading.Thread(target=cb, daemon=True).start()
                self._broadcast_threadsafe(self.snapshot())

            res_imp = import_cookies_from_browser(
                plat,
                browser,
                handle=handle,
                permission=perm,
                auto_open_window_on_lock=True,
                on_connected=_on_cookie_social_done,
            )
            if res_imp.get("ok"):
                self.push_log(
                    f"SYS: Connected {res_imp.get('label', plat)} via {res_imp.get('browser')} session ({perm})."
                )
                if self._is_persona_chosen() and ui is not None:
                    cb = getattr(ui, "on_integrations_change", None)
                    if callable(cb):
                        threading.Thread(target=cb, daemon=True).start()
            self._broadcast_threadsafe(self.snapshot())
            return {**res_imp, "summary": accounts.get_integrations_status_summary()}

        if action == "start_google_oauth":
            cid = str(data.get("client_id") or "").strip()
            csec = str(data.get("client_secret") or "").strip()
            if not cid or not csec:
                return {
                    "ok": False,
                    "error": "Enter Google OAuth Client ID and Client Secret first.",
                }
            for g_svc in ("gmail", "google_drive", "google_calendar"):
                accounts.connect_account(
                    g_svc, client_id=cid, client_secret=csec, permission="full"
                )
            redirect_uri = f"http://127.0.0.1:{self.port}/api/oauth/google/callback"
            auth_url = accounts.build_google_oauth_url(cid, redirect_uri)
            return {"ok": True, "auth_url": auth_url, "redirect_uri": redirect_uri}

        if action == "text_command":
            txt = str(data.get("text") or "").strip()
            if txt:
                self.push_log(f"You: {txt}")
                self.push_state("THINKING")
                cb = getattr(ui, "on_text_command", None) if ui else None
                if callable(cb):
                    threading.Thread(target=cb, args=(txt,), daemon=True).start()
                elif ui is not None and hasattr(ui, "_pending_text_commands"):
                    ui._pending_text_commands.append(txt)
                    if not self._is_persona_chosen():
                        self.push_log(
                            "SYS: Select Male or Female edition to start — your message is queued."
                        )
                else:
                    try:
                        timeline.append_turn("user", txt, speaker="You", channel="text")
                        companions.detect_and_record_correction(txt)
                    except Exception:
                        pass
            return {"ok": True}

        if action == "orb_tap":
            with self._lock:
                cur = self._raw_state
            if cur == "SPEAKING" and ui is not None and callable(getattr(ui, "on_interrupt", None)):
                ui.on_interrupt()
                self.push_state("LISTENING")
            elif self._is_muted() and ui is not None:
                self._invoke_qt(lambda: setattr(ui, "muted", False))
            elif self._is_paused() and win is not None:
                self._invoke_qt(win._toggle_pause)
                self.push_state("LISTENING")
            else:
                wake_cb = getattr(ui, "on_wake_manual", None) if ui else None
                ptt_cb = getattr(ui, "on_push_to_talk", None) if ui else None
                if callable(wake_cb):
                    threading.Thread(target=wake_cb, daemon=True).start()
                elif callable(ptt_cb):
                    threading.Thread(target=ptt_cb, daemon=True).start()
            return {"ok": True}

        if action == "retry_connection":
            retry = getattr(ui, "retry_live_connection", None) if ui is not None else None
            if not callable(retry):
                return {"ok": False, "error": "Live connection retry is not available yet."}
            retry()
            return {"ok": True, "message": "Retrying the live AI connection."}

        if action == "toggle_mute" and ui is not None:
            new_muted = not self._is_muted()
            self._invoke_qt(lambda: setattr(ui, "muted", new_muted))
            self.push_state("MUTED" if new_muted else "LISTENING")
            return {"ok": True, "muted": new_muted}

        if action == "toggle_pause":
            cb = getattr(ui, "on_pause_toggle", None) if ui is not None else None
            if callable(cb):
                try:
                    paused = bool(cb())
                except Exception:
                    paused = self._is_paused()
            elif win is not None and hasattr(win, "_toggle_pause"):
                self._invoke_qt(win._toggle_pause)
                time.sleep(0.02)
                paused = self._is_paused()
            else:
                paused = False
            self.push_state("PAUSED" if paused else "LISTENING")
            return {"ok": True, "paused": paused}

        if action == "interrupt" and ui is not None:
            cb = getattr(ui, "on_interrupt", None)
            if callable(cb):
                cb()
            self.push_state("LISTENING")
            return {"ok": True}

        if action == "stop_all":
            if ui is not None and callable(getattr(ui, "on_stop_all", None)):
                ui.on_stop_all()
            elif win is not None and hasattr(win, "_do_stop_all"):
                self._invoke_qt(win._do_stop_all)
            self.push_state("LISTENING")
            return {"ok": True}

        if action == "enter_background_mode":
            self._background_mode = True
            if self._close_timer is not None:
                self._close_timer.cancel()
            offscreen = os.environ.get("QT_QPA_PLATFORM", "").strip().lower() in (
                "offscreen",
                "minimal",
            )
            native_dock = False
            if ui is not None and callable(getattr(ui, "enter_background_mode", None)):
                ui.enter_background_mode()
                native_dock = not offscreen
            self.notify_background_mode(True, native_dock=native_dock)
            return {
                "ok": True,
                "background_mode": True,
                "native_dock": native_dock,
            }

        if action == "exit_background_mode":
            self._background_mode = False
            if ui is not None and callable(getattr(ui, "exit_background_mode", None)):
                ui.exit_background_mode()
            self.notify_background_mode(False, native_dock=False)
            return {"ok": True, "background_mode": False}

        if action == "video_ended":
            # Completion is accepted only from the local HUD's real media-ended
            # event. Matching and deduplication happen in the durable manager.
            event = {
                "video_id": str(data.get("video_id") or ""),
                "webpage_url": str(data.get("webpage_url") or ""),
                "playlist_url": str(data.get("playlist_url") or ""),
                "queue_index": int(data.get("queue_index") or 0),
                "queue_total": int(data.get("queue_total") or 0),
                "terminal": bool(data.get("terminal", False)),
            }
            matched = self._long_tasks.signal_media_ended(event)
            return {"ok": True, "completed_tasks": matched}

        if action == "video_close":
            if ui is not None and callable(getattr(ui, "stop_video", None)):
                ui.stop_video()
            else:
                self.stop_video()
            return {"ok": True}

        if action == "video_mute":
            muted_flag = bool(data.get("muted", True))
            if ui is not None and callable(getattr(ui, "set_video_muted", None)):
                ui.set_video_muted(muted_flag)
            else:
                self.set_video_muted(muted_flag)
            return {"ok": True, "muted": muted_flag}

        if action == "video_next":
            threading.Thread(target=self.step_video_queue, args=(1,), daemon=True).start()
            return {"ok": True}

        if action == "video_prev":
            threading.Thread(target=self.step_video_queue, args=(-1,), daemon=True).start()
            return {"ok": True}

        if action == "video_jump":
            idx = int(data.get("index", 0))
            threading.Thread(target=self.jump_video_queue, args=(idx,), daemon=True).start()
            return {"ok": True, "index": idx}

        if action == "region_capture" and win is not None:
            if ui is not None and getattr(ui, "_on_region_capture", None) and not getattr(win, "_on_region_capture", None):
                win._on_region_capture = ui._on_region_capture
            self._invoke_qt(win._start_region_pick)
            return {"ok": True}

        if action == "remote_qr" and ui is not None:
            cb = getattr(ui, "on_remote_clicked", None)
            if callable(cb):
                threading.Thread(target=cb, daemon=True).start()
            return {"ok": True}

        if action == "set_persona":
            raw_p = str(data.get("persona") or "male").strip().lower()
            req_voice = str(data.get("voice") or "").strip()
            was_chosen = self._is_persona_chosen()
            prev_voice = cfg.get_voice()
            res = cfg.save_persona(raw_p, req_voice or None)
            if ui is not None:
                setattr(ui, "_persona_selected", True)
                if hasattr(ui, "apply_persona_visuals"):
                    self._invoke_qt(
                        lambda p=res["persona"], c=res["ui_color"]: ui.apply_persona_visuals(p, c)
                    )
            if was_chosen and res["voice"] != prev_voice:
                cb = getattr(ui, "on_voice_change", None) if ui else None
                if callable(cb):
                    threading.Thread(target=cb, args=(res["voice"],), daemon=True).start()
            self.push_log(
                f"SYS: {res['persona'].capitalize()} interface activated · Voice: {res['voice']}."
            )
            self._broadcast_threadsafe(self.snapshot())
            return {"ok": True, **res}

        if action == "set_voice":
            v = str(data.get("voice") or "").strip()
            if v in cfg.AVAILABLE_VOICES:
                cfg.save_voice(v)
                cb = getattr(ui, "on_voice_change", None) if ui else None
                if callable(cb):
                    threading.Thread(target=cb, args=(v,), daemon=True).start()
                self._broadcast_threadsafe(self.snapshot())
            return {"ok": True}

        if action == "set_audio_devices":
            in_dev = str(data.get("input_device") or "")
            out_dev = str(data.get("output_device") or "")
            if in_dev == audio_devices.DEFAULT_LABEL:
                in_dev = ""
            if out_dev == audio_devices.DEFAULT_LABEL:
                out_dev = ""
            prev_in = cfg.get_input_device()
            prev_out = cfg.get_output_device()
            cfg.save_input_device(in_dev)
            cfg.save_output_device(out_dev)
            cb = getattr(ui, "on_audio_device_change", None) if ui else None
            if callable(cb):
                if in_dev != prev_in:
                    threading.Thread(
                        target=cb, args=("input", in_dev), daemon=True
                    ).start()
                if out_dev != prev_out:
                    threading.Thread(
                        target=cb, args=("output", out_dev), daemon=True
                    ).start()
            self._broadcast_threadsafe(self.snapshot())
            return {"ok": True}

        if action == "set_barge":
            enabled = bool(data.get("enabled", True))
            cfg.save_barge_in_enabled(enabled)
            gb = getattr(ui, "get_barge_state", None) if ui is not None else None
            tb = getattr(ui, "on_barge_toggle", None) if ui is not None else None
            if callable(tb):
                cur = bool(gb()) if callable(gb) else (not enabled)
                if cur != enabled:
                    tb()
            elif win is not None and hasattr(win, "_toggle_barge"):
                self._invoke_qt(win._toggle_barge)
            self._broadcast_threadsafe(self.snapshot())
            return {"ok": True}

        if action == "set_grace":
            sec = max(2, min(30, int(data.get("seconds") or 8)))
            cfg.save_grace_period(sec)
            if ui is not None and callable(getattr(ui, "on_grace_change", None)):
                ui.on_grace_change(sec)
            self._broadcast_threadsafe(self.snapshot())
            return {"ok": True}

        if action == "confirm_decision":
            approved = data.get("approved", False)
            if not isinstance(approved, bool):
                return {"ok": False, "error": "Confirmation decision must be a boolean."}
            confirm_gate.resolve(approved)
            self.hide_confirm()
            return {"ok": True}

        if action == "browser_companion_pair":
            from core.browser_companion import pairing_token, status
            return {"ok": True, "token": pairing_token(), "status": status(), "extension_path": str((Path(__file__).resolve().parent.parent / "browser_extension").resolve())}

        if action == "browser_companion_status":
            from core.browser_companion import status
            return {"ok": True, "status": status(), "extension_path": str((Path(__file__).resolve().parent.parent / "browser_extension").resolve())}

        if action == "browser_companion_revoke":
            from core.browser_companion import revoke
            revoke()
            return {"ok": True, "message": "Browser companion access revoked."}

        if action == "browser_companion_context":
            from core.browser_companion import current_context
            context = current_context(clear=bool(data.get("clear", False)))
            return {"ok": bool(context), "context": context}

        if action == "phone_devices_status":
            from core.telegram_bot import paired_devices
            return {"ok":True,"devices":paired_devices()}

        if action == "phone_device_revoke":
            from core.telegram_bot import revoke_device
            try: ok=revoke_device(int(data.get('device_id')))
            except (TypeError,ValueError): ok=False
            return {"ok":ok,"message":"Phone access revoked." if ok else "Paired phone was not found."}

        if action == "phone_devices_revoke_all":
            from core.telegram_bot import revoke_all_devices
            count=revoke_all_devices(); return {"ok":True,"message":f"Revoked {count} paired phone device(s)."}

        if action == "local_voice_diagnostics":
            from core.local_voice_setup import diagnostics
            return {"ok":True,"voice_setup":diagnostics()}

        if action == "local_voice_install":
            from core.local_voice_setup import install
            components=data.get("components") if isinstance(data.get("components"),list) else []
            result=install(components); return {"ok":result["ok"],"voice_setup":result.get("diagnostics",{}),"message":"Selected offline voice components installed and checked." if result["ok"] else result["error"]}

        if action == "owner_auth_status":
            from core.owner_auth import available, policy
            return {"ok":True,"available":available(),"policy":policy()}

        if action == "owner_auth_save":
            from core.owner_auth import available, save_policy
            enabled=bool(data.get("enabled",False))
            if enabled and not available(): return {"ok":False,"error":"OS-native owner authorization is unavailable on this device."}
            saved=save_policy(enabled,data.get("risks") if isinstance(data.get("risks"),list) else [],data.get("permissions") if isinstance(data.get("permissions"),list) else [])
            return {"ok":True,"policy":saved,"message":"Owner authorization policy saved."}

        if action == "workflow_review_status":
            from core.workflow_reviewer import latest_review
            return {"ok":True,"review":latest_review()}

        if action == "strategy_experiments_status":
            from core.strategy_experiments import snapshot
            return {"ok":True,"experiments":snapshot()}

        if action == "strategy_experiments_enable":
            from core.strategy_experiments import set_enabled, snapshot
            set_enabled(bool(data.get("enabled",False))); return {"ok":True,"experiments":snapshot()}

        if action == "strategy_experiment_propose":
            from core.strategy_experiments import propose, snapshot
            try: propose(str(data.get("name") or ""),str(data.get("baseline") or ""),str(data.get("candidate") or ""))
            except ValueError as exc: return {"ok":False,"error":str(exc)}
            return {"ok":True,"experiments":snapshot(),"message":"Experiment created with the user-provided strategies."}

        if action == "strategy_experiment_remove":
            from core.strategy_experiments import remove, snapshot
            found=remove(str(data.get("name") or "")); return {"ok":found,"experiments":snapshot(),"message":"Experiment removed." if found else "Experiment not found."}

        if action == "smart_home_status":
            from core.smart_home import status
            return {"ok": True, "smart_home": status()}

        if action == "smart_home_configure":
            from core.smart_home import configure
            try: result=configure(str(data.get("url") or ""),str(data.get("token") or ""),data.get("entities") if isinstance(data.get("entities"),list) else [])
            except Exception as exc: return {"ok":False,"error":str(exc)}
            return {"ok":True,"smart_home":result,"message":"Home Assistant credentials encrypted and permissions saved."}

        if action == "smart_home_discover":
            from core.smart_home import discover
            try: entities=discover()
            except Exception as exc: return {"ok":False,"error":f"Home Assistant discovery failed: {type(exc).__name__}."}
            return {"ok":True,"entities":entities}

        if action == "smart_home_undo":
            from core.smart_home import undo_last
            try: result=undo_last()
            except Exception as exc: return {"ok":False,"error":str(exc)}
            return {"ok":bool(result.get('verified')),"result":result,"message":"Previous smart-home state restored and verified." if result.get('verified') else "Undo was sent but could not be verified."}

        if action == "smart_home_disconnect":
            from core.smart_home import disconnect
            disconnect(); return {"ok":True,"message":"Home Assistant disconnected and credentials removed."}

        if action == "provider_routing_get":
            from core.provider_preferences import get
            return {"ok": True, "routing": get()}

        if action == "provider_routing_save":
            from core.provider_preferences import save
            try:
                routing = save(str(data.get("cost_priority") or "balanced"),
                               str(data.get("latency_priority") or "balanced"))
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "routing": routing}

        if action == "proactive_policy_get":
            from dataclasses import asdict
            from core.proactive_permissions import load
            return {"ok": True, "policy": asdict(load())}

        if action == "proactive_policy_save":
            from core.proactive_permissions import ProactivePolicy, save
            try:
                policy = ProactivePolicy(
                    enabled=bool(data.get("enabled", True)),
                    use_memory=bool(data.get("use_memory", False)),
                    use_monitors=bool(data.get("use_monitors", False)),
                    use_recent_conversation=bool(data.get("use_recent_conversation", True)),
                    quiet_start=max(0, min(23, int(data.get("quiet_start", 23)))),
                    quiet_end=max(0, min(23, int(data.get("quiet_end", 7)))),
                    daily_limit=max(0, min(48, int(data.get("daily_limit", 6)))),
                    allowed_topics=tuple(str(v)[:80] for v in (data.get("allowed_topics") or [])[:30]),
                    blocked_topics=tuple(str(v)[:80] for v in (data.get("blocked_topics") or [])[:30]),
                    minimum_urgency=str(data.get("minimum_urgency") or "normal")
                    if str(data.get("minimum_urgency") or "normal") in {"low", "normal", "high", "critical"} else "normal",
                )
            except (TypeError, ValueError):
                return {"ok": False, "error": "Invalid proactive policy."}
            save(policy)
            return {"ok": True, "message": "Proactive permissions updated."}

        if action == "brain_get":
            return {"ok": True, "brain": timeline.get_brain_snapshot()}

        if action == "brain_search":
            q = str(data.get("query") or "").strip()
            return {
                "ok": True,
                "memories": mm.all_entries_for_ui()
                if not q
                else [
                    m
                    for m in mm.all_entries_for_ui()
                    if q.lower() in m["key"].lower()
                    or q.lower() in m["value"].lower()
                    or q.lower() in m["category"].lower()
                ],
                "timeline": timeline.search_timeline(
                    q, limit=40, channel=str(data.get("channel") or "")
                ),
                "files": [
                    f
                    for f in timeline.list_knowledge_files()
                    if not q
                    or q.lower() in f["filename"].lower()
                    or q.lower() in f["preview"].lower()
                ],
                "outputs": timeline.list_outputs(q, limit=40),
            }

        if action == "brain_save_memory":
            cat = str(data.get("category") or "notes").strip().lower()
            key = str(data.get("key") or "").strip()
            val = str(data.get("value") or "").strip()
            if not key or not val:
                return {"ok": False, "error": "Both key and value are required."}
            mm.remember(key, val, category=cat, manual=True)
            snap = timeline.get_brain_snapshot()
            self._broadcast_threadsafe(self.snapshot())
            return {"ok": True, "brain": snap}

        if action == "brain_pin_memory":
            from memory import memory_governance
            cat = str(data.get("category") or "notes").strip().lower()
            key = str(data.get("key") or "").strip()
            message = memory_governance.pin(cat, key, bool(data.get("pinned", True)))
            return {"ok": not message.startswith("Memory not found"), "message": message,
                    "brain": timeline.get_brain_snapshot()}

        if action == "brain_resolve_conflict":
            from memory import memory_governance
            cat = str(data.get("category") or "notes").strip().lower()
            key = str(data.get("key") or "").strip()
            val = str(data.get("value") or "").strip()
            if not val:
                return {"ok": False, "error": "A resolved value is required."}
            message = memory_governance.resolve(cat, key, val)
            return {"ok": message.startswith("Resolved"), "message": message,
                    "brain": timeline.get_brain_snapshot()}

        if action == "brain_export_memories":
            from memory import memory_governance
            return {"ok": True, "export": memory_governance.export()}

        if action == "brain_forget_memory":
            cat = str(data.get("category") or "notes").strip().lower()
            key = str(data.get("key") or "").strip()
            mm.forget(key, category=cat)
            snap = timeline.get_brain_snapshot()
            self._broadcast_threadsafe(self.snapshot())
            return {"ok": True, "brain": snap}

        if action == "brain_clear_memories":
            def _clear_memories():
                message = mm.clear_all_memories()
                self._broadcast_threadsafe(self.snapshot())
                return message
            pending = confirm_gate.request(
                "brain-clear-all", "Clear all personal memories?",
                "This permanently deletes every stored personal memory. Export first if you may need a copy.",
                _clear_memories,
            )
            return {"ok": True, "pending_confirmation": True, "message": pending}

        if action == "brain_upload_file":
            fname = str(data.get("filename") or "note.md").strip()
            content_val = str(data.get("content") or "")
            is_b64 = bool(data.get("is_base64", False))
            if not content_val:
                return {"ok": False, "error": "Empty file content."}
            rec = timeline.ingest_knowledge_file(fname, content_val, is_base64=is_b64)
            snap = timeline.get_brain_snapshot()
            self._broadcast_threadsafe(self.snapshot())
            return {"ok": True, "file": rec, "brain": snap}

        if action == "brain_read_file":
            fid = int(data.get("file_id") or 0)
            doc = timeline.read_knowledge_file(fid)
            return {"ok": doc is not None, "file": doc}

        if action == "brain_delete_file":
            fid = int(data.get("file_id") or 0)
            timeline.delete_knowledge_file(fid)
            snap = timeline.get_brain_snapshot()
            self._broadcast_threadsafe(self.snapshot())
            return {"ok": True, "brain": snap}

        if action == "brain_delete_turn":
            mid = int(data.get("id") or 0)
            timeline.delete_timeline_message(mid)
            snap = timeline.get_brain_snapshot()
            self._broadcast_threadsafe(self.snapshot())
            return {"ok": True, "brain": snap}

        if action == "brain_clear_timeline":
            timeline.clear_timeline()
            with self._lock:
                self._logs.clear()
            snap = timeline.get_brain_snapshot()
            self._broadcast_threadsafe(self.snapshot())
            return {"ok": True, "brain": snap}

        if action == "brain_pin_output":
            oid = int(data.get("id") or 0)
            pinned = timeline.toggle_pin_output(oid)
            return {"ok": True, "pinned": pinned, "brain": timeline.get_brain_snapshot()}

        if action == "brain_delete_output":
            oid = int(data.get("id") or 0)
            timeline.delete_output(oid)
            snap = timeline.get_brain_snapshot()
            self._broadcast_threadsafe(self.snapshot())
            return {"ok": True, "brain": snap}

        if action == "brain_set_privacy":
            if "personalization_enabled" in data:
                cfg.save_personalization_enabled(bool(data["personalization_enabled"]))
            if "adaptive_learning_enabled" in data:
                cfg.save_adaptive_learning_enabled(bool(data["adaptive_learning_enabled"]))
            if "timeline_persistence_enabled" in data:
                cfg.save_timeline_persistence_enabled(bool(data["timeline_persistence_enabled"]))
            if self._is_persona_chosen() and ui is not None:
                cb = getattr(ui, "on_integrations_change", None)
                if callable(cb):
                    threading.Thread(target=cb, daemon=True).start()
            snap = timeline.get_brain_snapshot()
            self._broadcast_threadsafe(self.snapshot())
            return {"ok": True, "privacy": cfg.get_privacy_settings(), "brain": snap}

        if action == "brain_import_json":
            payload = data.get("payload")
            if not isinstance(payload, dict):
                return {"ok": False, "error": "Invalid Brain JSON payload."}
            restored = timeline.import_brain_json(payload)
            snap = timeline.get_brain_snapshot()
            self._broadcast_threadsafe(self.snapshot())
            return {"ok": True, "restored": restored, "brain": snap}

        # ── 3D World View Worker Orbs & Activity Timeline actions ─────────────

        if action == "activity_get":
            return {"ok": True, "workers": self.get_activity_snapshot()}

        if action == "spawn_worker":
            goal = str(data.get("goal") or "").strip()
            if not goal:
                return {"ok": False, "error": "Worker goal is required."}
            raw_tools = data.get("tools")
            tools = [str(t) for t in raw_tools] if isinstance(raw_tools, list) else []
            auto_start = bool(data.get("auto_start", True))
            from core.subagents import get_subagent_manager
            mgr = get_subagent_manager()
            wid = mgr.spawn(goal=goal, tools=tools, max_steps=int(data.get("max_steps") or 10))
            if auto_start:
                mgr.start(wid)
            self.push_log(f"SYS: Spawned worker {wid} — {goal[:72]}")
            if tools:
                self.push_tool_trace(tools)
            return {"ok": True, "worker_id": wid, "workers": self.get_activity_snapshot()}

        if action == "step_worker":
            wid = str(data.get("worker_id") or "").strip()
            step_act = str(data.get("step_action") or "step").strip()
            step_res = str(data.get("step_result") or "").strip()
            from core.subagents import get_subagent_manager
            ok = get_subagent_manager().add_step(wid, step_act, step_res)
            return {"ok": ok, "workers": self.get_activity_snapshot()}

        if action == "complete_worker":
            wid = str(data.get("worker_id") or "").strip()
            res_txt = str(data.get("result") or "Completed.").strip()
            from core.subagents import get_subagent_manager
            ok = get_subagent_manager().complete(wid, res_txt)
            return {"ok": ok, "workers": self.get_activity_snapshot()}

        if action == "long_task_control":
            task_id = str(data.get("task_id") or "").strip()
            operation = str(data.get("operation") or "status").strip().lower()
            if operation == "pause":
                ok = self._long_tasks.pause(task_id)
            elif operation == "resume":
                ok = self._long_tasks.resume(task_id)
            elif operation == "cancel":
                ok = self._long_tasks.cancel(task_id)
            elif operation == "retry":
                ok = self._long_tasks.retry_failed(task_id)
            elif operation == "resolve":
                ok = self._long_tasks.resolve_uncertain(task_id, str(data.get("resolution") or ""))
            elif operation == "revise":
                ok = self._long_tasks.revise_step(task_id, int(data.get("step_index") or 0), data.get("patch") or {})
            else:
                rec = self._long_tasks.get(task_id)
                return {"ok": bool(rec), "task": rec, "workers": self.get_activity_snapshot()}
            self.push_activity()
            return {"ok": ok, "task": self._long_tasks.get(task_id), "workers": self.get_activity_snapshot()}

        if action == "cancel_worker":
            wid = str(data.get("worker_id") or "").strip()
            cancelled = False
            try:
                from core.subagents import get_subagent_manager
                cancelled = get_subagent_manager().cancel(wid)
            except Exception:
                pass
            if not cancelled:
                try:
                    cancelled = self._long_tasks.cancel(wid)
                except Exception:
                    pass
            if not cancelled:
                with self._lock:
                    self._cancelled_task_ids.add(wid)
                    rec = self._tool_tasks.get(wid)
                    if rec and rec.get("status") in ("in_progress", "pending"):
                        rec["status"] = "cancelled"
                        rec["updated_at"] = time.time()
                        cancelled = True
                if cancelled:
                    self.push_activity()
            if cancelled:
                self.push_log(f"SYS: Cancelled worker {wid}.")
            return {"ok": cancelled, "workers": self.get_activity_snapshot()}

        if action == "clear_completed_workers":
            removed = 0
            try:
                from core.subagents import get_subagent_manager
                removed += get_subagent_manager().clear_finished()
            except Exception:
                pass
            try:
                removed += self._long_tasks.clear_finished()
            except Exception:
                pass
            with self._lock:
                done_keys = [
                    k for k, v in self._tool_tasks.items()
                    if v.get("status") in ("completed", "failed", "cancelled")
                ]
                for k in done_keys:
                    self._tool_tasks.pop(k, None)
                    removed += 1
            self.push_activity()
            return {"ok": True, "removed": removed, "workers": self.get_activity_snapshot()}

        # ── Behavior Interviews, Companions & Visual Skills/Themes Studio ─────

        if action == "studio_get":
            return {"ok": True, "studio": companions.get_studio_snapshot(list(TOOL_NODE_MAP.keys()))}

        if action == "studio_save_interview":
            answers = data.get("answers")
            iv = companions.save_behavior_interview(answers if isinstance(answers, dict) else {})
            if self._is_persona_chosen() and ui is not None:
                cb = getattr(ui, "on_integrations_change", None)
                if callable(cb):
                    threading.Thread(target=cb, daemon=True).start()
            return {"ok": True, "interview": iv, "studio": companions.get_studio_snapshot(list(TOOL_NODE_MAP.keys()))}

        if action == "studio_add_rule":
            rule_txt = str(data.get("rule") or "").strip()
            companions.add_learned_rule(rule_txt)
            return {"ok": True, "studio": companions.get_studio_snapshot(list(TOOL_NODE_MAP.keys()))}

        if action == "studio_delete_rule":
            rid = str(data.get("rule_id") or "").strip()
            companions.delete_learned_rule(rid)
            return {"ok": True, "studio": companions.get_studio_snapshot(list(TOOL_NODE_MAP.keys()))}

        if action == "studio_save_companion":
            try:
                comp = companions.save_companion(data.get("companion") if isinstance(data.get("companion"), dict) else data)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "companion": comp, "studio": companions.get_studio_snapshot(list(TOOL_NODE_MAP.keys()))}

        if action == "studio_delete_companion":
            cid = str(data.get("companion_id") or "").strip()
            companions.delete_companion(cid)
            self._broadcast_threadsafe(self.snapshot())
            return {"ok": True, "studio": companions.get_studio_snapshot(list(TOOL_NODE_MAP.keys()))}

        if action == "studio_activate_companion":
            cid = str(data.get("companion_id") or "default").strip()
            comp = companions.set_active_companion(cid)
            self.push_log(f"SYS: Active companion switched to {comp.get('name')} ({comp.get('role')}).")
            if self._is_persona_chosen() and ui is not None:
                cb = getattr(ui, "on_persona_change", None)
                if callable(cb):
                    threading.Thread(target=cb, args=(comp.get("persona", "male"), comp.get("voice", "")), daemon=True).start()
            self._broadcast_threadsafe(self.snapshot())
            return {"ok": True, "active_companion": comp, "studio": companions.get_studio_snapshot(list(TOOL_NODE_MAP.keys()))}

        if action == "studio_save_skill":
            try:
                res = companions.save_custom_skill(
                    name=str(data.get("name") or ""),
                    description=str(data.get("description") or ""),
                    body=str(data.get("body") or ""),
                )
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, **res, "studio": companions.get_studio_snapshot(list(TOOL_NODE_MAP.keys()))}

        if action == "studio_delete_skill":
            sname = str(data.get("name") or "").strip()
            ok = companions.delete_custom_skill(sname)
            return {"ok": ok, "studio": companions.get_studio_snapshot(list(TOOL_NODE_MAP.keys()))}

        if action == "studio_save_theme":
            th = companions.save_theme_customization(
                preset=str(data.get("preset") or "default"),
                custom_primary=str(data.get("custom_primary") or ""),
                custom_secondary=str(data.get("custom_secondary") or ""),
            )
            self._broadcast_threadsafe(self.snapshot())
            return {"ok": True, "theme": th}

        # ── Automations Center, Custom REST/Webhooks & MCP Builder ────────────

        def _auto_state() -> dict[str, Any]:
            return {
                "automations": automations.list_automations(),
                "rest_connectors": mcp_adapter.list_rest_connectors(),
                "mcp_servers": mcp_adapter.list_mcp_servers(),
                "available_tools": sorted(set(TOOL_NODE_MAP.keys())),
            }

        if action == "auto_get":
            return {"ok": True, **_auto_state()}

        if action == "auto_save":
            try:
                rec = automations.save_automation(data.get("automation") if isinstance(data.get("automation"), dict) else data)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "automation": rec, **_auto_state()}

        if action == "auto_toggle":
            aid = str(data.get("id") or "").strip()
            enabled = data.get("enabled") if isinstance(data.get("enabled"), bool) else None
            automations.toggle_automation(aid, enabled=enabled)
            return {"ok": True, **_auto_state()}

        if action == "auto_delete":
            aid = str(data.get("id") or "").strip()
            automations.delete_automation(aid)
            return {"ok": True, **_auto_state()}

        if action == "auto_run_now":
            aid = str(data.get("id") or "").strip()
            try:
                run_rec = automations.run_automation_now(aid, on_log=self.push_log)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            self._broadcast_threadsafe(self.snapshot())
            return {"ok": True, "run": run_rec, **_auto_state()}

        if action == "rest_save":
            try:
                rec = mcp_adapter.save_rest_connector(data.get("connector") if isinstance(data.get("connector"), dict) else data)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "connector": rec, **_auto_state()}

        if action == "rest_delete":
            cid = str(data.get("id") or data.get("name") or "").strip()
            mcp_adapter.delete_rest_connector(cid)
            return {"ok": True, **_auto_state()}

        if action == "rest_test":
            cid = str(data.get("id") or data.get("name") or "").strip()
            params = data.get("params") if isinstance(data.get("params"), dict) else {}
            try:
                out = mcp_adapter.invoke_rest_connector(cid, params)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "output": out, **_auto_state()}

        if action == "mcp_save":
            try:
                srv = mcp_adapter.save_mcp_server(data.get("server") if isinstance(data.get("server"), dict) else data)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "server": srv, **_auto_state()}

        if action == "mcp_delete":
            sid = str(data.get("id") or data.get("name") or "").strip()
            mcp_adapter.delete_mcp_server(sid)
            return {"ok": True, **_auto_state()}

        if action == "mcp_discover":
            sid = str(data.get("id") or data.get("name") or "").strip()
            try:
                tools = mcp_adapter.discover_mcp_tools(sid)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "tools": tools, **_auto_state()}

        if action == "mcp_call":
            sid = str(data.get("server") or "").strip()
            tname = str(data.get("tool_name") or "").strip()
            args = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
            try:
                out = mcp_adapter.call_mcp_tool(sid, tname, args)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "output": out}

        # ── Live Streaming Dev Terminal, Codebase Map & Diffs ─────────────────

        if action == "dev_run":
            cmd = str(data.get("command") or "").strip()
            cwd = str(data.get("cwd") or "").strip()
            try:
                sess = dev_workspace.get_terminal_manager().start_command(cmd, cwd=cwd)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            self.push_tool_trace(["shell_agent", "dev_agent"])
            return {"ok": True, "session": sess, "sessions": dev_workspace.get_terminal_manager().list_sessions()}

        if action == "dev_stdin":
            sid = str(data.get("session_id") or "").strip()
            txt = str(data.get("text") or "")
            ok = dev_workspace.get_terminal_manager().send_stdin(sid, txt)
            return {"ok": ok}

        if action == "dev_stop":
            sid = str(data.get("session_id") or "").strip()
            ok = dev_workspace.get_terminal_manager().stop_command(sid)
            return {"ok": ok, "sessions": dev_workspace.get_terminal_manager().list_sessions()}

        if action == "dev_tree":
            rdir = str(data.get("root_dir") or "").strip()
            return {"ok": True, "tree": dev_workspace.build_codebase_tree(rdir)}

        if action == "dev_read_file":
            rdir = str(data.get("root_dir") or "").strip()
            fpath = str(data.get("path") or "").strip()
            try:
                fobj = dev_workspace.read_workspace_file(rdir, fpath)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "file": fobj}

        if action == "dev_diffs":
            rdir = str(data.get("root_dir") or "").strip()
            return {"ok": True, "diffs": dev_workspace.get_workspace_diffs(rdir)}

        # ── Encrypted Vault, Hash-Chained Audit Log & Guest Portals ───────────

        def _sec_snap() -> dict[str, Any]:
            return security_vault.get_security_snapshot(
                accounts.ACCOUNTS_FILE, cfg.CONFIG_FILE
            )

        if action == "security_get":
            return {"ok": True, "security": _sec_snap()}

        if action == "vault_rotate_key":
            res = security_vault.rotate_vault_master_key(
                accounts.ACCOUNTS_FILE, cfg.CONFIG_FILE
            )
            return {**res, "security": _sec_snap()}

        if action == "vault_encrypt_config":
            enabled = bool(data.get("enabled", True))
            ok = cfg.set_strict_config_encryption(enabled)
            security_vault.log_audit_event(
                "hud",
                "vault_encrypt_config",
                {"enabled": enabled},
                f"Strict api_keys.json encryption={'ON' if enabled else 'OFF'}",
            )
            return {"ok": ok, "security": _sec_snap()}

        if action == "audit_verify":
            return {"ok": True, "chain": security_vault.verify_audit_chain(), "security": _sec_snap()}

        if action == "audit_search":
            q = str(data.get("query") or "")
            return {"ok": True, "audit_logs": security_vault.list_audit_events(q, limit=80)}

        if action == "portal_create":
            title = str(data.get("title") or "").strip()
            body = str(data.get("content_body") or "").strip()
            oid = data.get("output_id")
            if not body and oid:
                for o in timeline.list_outputs(limit=100):
                    if int(o["id"]) == int(oid):
                        title = title or o["title"]
                        body = o["body"]
                        break
            try:
                created = security_vault.create_portal(
                    title=title or "Shared Deliverable",
                    content_body=body,
                    scope_type=str(data.get("scope_type") or "output"),
                    expires_hours=float(data.get("expires_hours") or 24.0),
                    max_views=int(data.get("max_views") or 50),
                )
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "portal": created, "security": _sec_snap()}

        if action == "portal_revoke":
            pid = str(data.get("portal_id") or "").strip()
            ok = security_vault.revoke_portal(pid)
            return {"ok": ok, "security": _sec_snap()}

        if action == "portal_revoke_all":
            cnt = security_vault.revoke_all_portals()
            return {"ok": True, "revoked_count": cnt, "security": _sec_snap()}

        return {"ok": False, "error": f"Unknown action: {action}"}

    def _invoke_qt(self, fn: Callable[[], Any]) -> None:
        win = getattr(self._ui, "_win", None) if self._ui is not None else None
        if win is not None and hasattr(win, "_bridge_call_sig"):
            try:
                win._bridge_call_sig.emit(fn)
                return
            except Exception:
                pass
        try:
            fn()
        except Exception:
            pass

    # ── Weather helper ────────────────────────────────────────────────────────

    def _fetch_weather(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._wx_cache is not None and (now - self._wx_cached_at) < 900:
            return self._wx_cache

        city = cfg.get_assistant_name()
        result: dict[str, Any] = {"current": None, "city": city}
        try:
            with urllib.request.urlopen("https://ipapi.co/json/", timeout=2.0) as r:
                geo = json.loads(r.read().decode("utf-8", errors="ignore"))
            lat = geo.get("latitude")
            lon = geo.get("longitude")
            city = geo.get("city") or city
            if lat is not None and lon is not None:
                url = (
                    f"https://api.open-meteo.com/v1/forecast"
                    f"?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code"
                )
                with urllib.request.urlopen(url, timeout=2.5) as wr:
                    wd = json.loads(wr.read().decode("utf-8", errors="ignore"))
                result = {"current": wd.get("current"), "city": city}
        except Exception:
            pass

        self._wx_cache = result
        self._wx_cached_at = now
        return result

    # ── FastAPI / Uvicorn lifecycle ───────────────────────────────────────────

    def _build_app(self):
        if FastAPI is None:
            raise RuntimeError("fastapi is required for APEX-UI bridge")

        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

        @app.get("/api/hud/bootstrap")
        async def _bootstrap():
            return JSONResponse(self.snapshot())

        @app.get("/api/hud/brain")
        async def _brain_get():
            snap = await asyncio.to_thread(timeline.get_brain_snapshot)
            return JSONResponse({"ok": True, "brain": snap})

        @app.get("/api/hud/brain/export")
        async def _brain_export():
            exp = await asyncio.to_thread(timeline.export_brain_json)
            return JSONResponse(exp)

        @app.options("/api/hud/browser-companion/context")
        async def _browser_companion_options():
            return JSONResponse({}, headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Content-Type,X-JARVIS-Token", "Access-Control-Allow-Methods": "POST,OPTIONS"})

        @app.post("/api/hud/browser-companion/context")
        async def _browser_companion_context(req: Request):
            from core.browser_companion import authorized, store_context
            if not authorized(req.headers.get("x-jarvis-token", "")):
                return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401, headers={"Access-Control-Allow-Origin": "*"})
            try:
                context = store_context(await req.json())
            except Exception:
                return JSONResponse({"ok": False, "error": "invalid context"}, status_code=400, headers={"Access-Control-Allow-Origin": "*"})
            return JSONResponse({"ok": True, "received_at": context["received_at"]}, headers={"Access-Control-Allow-Origin": "*"})

        @app.get("/api/hud/activity")
        async def _activity_get():
            return JSONResponse({"ok": True, "workers": self.get_activity_snapshot()})

        @app.get("/api/hud/operations")
        async def _operations_get():
            from core.operations_center import snapshot as operations_snapshot
            return JSONResponse(await asyncio.to_thread(operations_snapshot))

        @app.get("/api/hud/studio")
        async def _studio_get():
            st = await asyncio.to_thread(
                companions.get_studio_snapshot, list(TOOL_NODE_MAP.keys())
            )
            return JSONResponse({"ok": True, "studio": st})

        @app.get("/api/hud/soul")
        async def _soul_get():
            try:
                snap = await asyncio.to_thread(self._get_soul_api().snapshot)
                return JSONResponse({"ok": True, "soul": snap})
            except Exception as exc:
                return JSONResponse({"ok": False, "error": "Service temporarily unavailable"}, status_code=503)

        @app.get("/api/hud/soul/export")
        async def _soul_export():
            try:
                export = await asyncio.to_thread(self._get_soul_api().export)
                return JSONResponse({"ok": True, "export": export})
            except Exception as exc:
                return JSONResponse({"ok": False, "error": "Service temporarily unavailable"}, status_code=503)

        @app.post("/api/hud/soul")
        async def _soul_post(req: Request):
            try:
                body = await req.json()
            except Exception:
                body = {}
            status, result = await asyncio.to_thread(self.handle_soul_action, body)
            return JSONResponse(result, status_code=status)

        @app.get("/api/hud/automations")
        async def _automations_get():
            return JSONResponse(
                {
                    "ok": True,
                    "automations": automations.list_automations(),
                    "rest_connectors": mcp_adapter.list_rest_connectors(),
                    "mcp_servers": mcp_adapter.list_mcp_servers(),
                    "available_tools": sorted(set(TOOL_NODE_MAP.keys())),
                }
            )

        @app.get("/api/hud/dev")
        async def _dev_get(req: Request):
            rdir = req.query_params.get("root_dir", "")
            tree = await asyncio.to_thread(dev_workspace.build_codebase_tree, rdir)
            diffs = await asyncio.to_thread(dev_workspace.get_workspace_diffs, rdir)
            return JSONResponse(
                {
                    "ok": True,
                    "sessions": dev_workspace.get_terminal_manager().list_sessions(),
                    "tree": tree,
                    "diffs": diffs,
                }
            )

        @app.get("/api/hud/security")
        async def _security_get():
            sec = await asyncio.to_thread(
                security_vault.get_security_snapshot,
                accounts.ACCOUNTS_FILE,
                cfg.CONFIG_FILE,
            )
            return JSONResponse({"ok": True, "security": sec})

        @app.get("/portal/{token}")
        async def _guest_portal(token: str, req: Request):
            ip = (req.client.host if req.client else "127.0.0.1") or "127.0.0.1"
            ua = req.headers.get("user-agent", "")
            status_code, html_doc = await asyncio.to_thread(
                security_vault.access_portal_by_token, token, ip, ua
            )
            return HTMLResponse(content=html_doc, status_code=status_code)

        @app.post("/api/hud/action")
        async def _action(req: Request):
            try:
                body = await req.json()
            except Exception:
                body = {}
            res = await asyncio.to_thread(self.handle_action, body)
            return JSONResponse(res)

        @app.get("/api/hud/social/frame")
        async def _social_frame(req: Request):
            from core.social_hub import get_hud_social_frame

            plat = req.query_params.get("platform", "")
            res = await asyncio.to_thread(get_hud_social_frame, plat)
            return JSONResponse(res)

        @app.post("/api/hud/social/interact")
        async def _social_interact(req: Request):
            from core.social_hub import interact_hud_social

            try:
                body = await req.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                return JSONResponse({"ok": False, "error": "Expected an interaction object."}, status_code=400)
            res = await asyncio.to_thread(interact_hud_social, body)
            return JSONResponse(res)

        @app.get("/api/hud/media/{token}")
        async def _stream_hud_media(token: str, req: Request):
            with self._lock:
                entry = self._media_streams.get(token)
            if not entry:
                return JSONResponse({"error": "Media stream expired or not found."}, status_code=404)

            src = str(entry.get("source") or "")
            saved_headers = dict(entry.get("headers") or {})
            range_hdr = req.headers.get("range")

            # 1. Local file with HTTP Range (206 Partial Content) support
            local_p = Path(src)
            if not src.lower().startswith(("http://", "https://")) and local_p.is_file():
                total = local_p.stat().st_size
                mime = mimetypes.guess_type(local_p.name)[0] or "video/mp4"
                if range_hdr and range_hdr.startswith("bytes="):
                    try:
                        spec = range_hdr.split("=", 1)[1].split(",", 1)[0].strip()
                        s_part, e_part = spec.split("-", 1)
                        start = int(s_part) if s_part else 0
                        end = int(e_part) if e_part else min(total - 1, start + 2 * 1024 * 1024 - 1)
                        start = max(0, min(start, total - 1))
                        end = max(start, min(end, total - 1))
                        length = end - start + 1
                        with local_p.open("rb") as fh:
                            fh.seek(start)
                            chunk = fh.read(length)
                        return Response(
                            content=chunk,
                            status_code=206,
                            media_type=mime,
                            headers={
                                "Content-Range": f"bytes {start}-{end}/{total}",
                                "Accept-Ranges": "bytes",
                                "Content-Length": str(length),
                            },
                        )
                    except Exception:
                        pass
                return FileResponse(local_p, media_type=mime, headers={"Accept-Ranges": "bytes"})

            # 2. Remote social/video CDN proxy (Instagram, Snapchat, TikTok, YouTube, X, Reddit, etc.)
            import httpx

            upstream_headers = {k: v for k, v in saved_headers.items() if k.lower() != "host"}
            if range_hdr:
                upstream_headers["Range"] = range_hdr

            client = httpx.AsyncClient(follow_redirects=True, timeout=30.0)
            try:
                up_req = client.build_request("GET", src, headers=upstream_headers)
                up_resp = await client.send(up_req, stream=True)
            except Exception as exc:
                await client.aclose()
                return JSONResponse({"error": "Upstream media unavailable"}, status_code=502)

            out_headers: dict[str, str] = {"Accept-Ranges": "bytes"}
            for hk in ("content-length", "content-range", "accept-ranges"):
                hv = up_resp.headers.get(hk)
                if hv:
                    out_headers[hk] = hv
            media_type = up_resp.headers.get("content-type", "video/mp4")

            async def _iter_remote():
                try:
                    async for chunk in up_resp.aiter_bytes(chunk_size=65536):
                        yield chunk
                finally:
                    await up_resp.aclose()
                    await client.aclose()

            return StreamingResponse(
                _iter_remote(),
                status_code=up_resp.status_code,
                media_type=media_type,
                headers=out_headers,
            )

        @app.get("/api/weather")
        async def _weather():
            wx = await asyncio.to_thread(self._fetch_weather)
            return JSONResponse(wx)

        @app.get("/api/oauth/google/callback")
        async def _google_oauth_cb(req: Request):
            code = req.query_params.get("code", "")
            err = req.query_params.get("error", "")
            if err or not code:
                return HTMLResponse(
                    f"<html><body style='background:#050b14;color:#ff8090;font-family:sans-serif;padding:40px;text-align:center'>"
                    f"<h2>Google Authorization Cancelled</h2><p>{html.escape(err or 'No authorization code received.')}</p></body></html>",
                    status_code=400,
                )
            rec = accounts.get_account("gmail") or accounts.get_account("google_drive") or {}
            cid = str(rec.get("client_id") or "")
            csec = str(rec.get("client_secret") or "")
            redirect_uri = f"http://127.0.0.1:{self.port}/api/oauth/google/callback"
            try:
                res = await asyncio.to_thread(
                    accounts.exchange_google_oauth_code, code, cid, csec, redirect_uri
                )
                self.push_log(
                    f"SYS: Google Workspace connected ({res.get('email') or 'Gmail, Drive & Calendar'}) ✓"
                )
                self._broadcast_threadsafe(self.snapshot())
                return HTMLResponse(
                    "<html><body style='background:#050b14;color:#6ef4ff;font-family:sans-serif;padding:48px;text-align:center'>"
                    "<h2>✓ Google Workspace Connected</h2>"
                    "<p style='color:#9ec5d6'>Gmail, Google Drive, and Google Calendar are now linked to JARVIS.<br/>You can close this tab and return to the HUD.</p>"
                    "<script>setTimeout(()=>window.close(),1800)</script></body></html>"
                )
            except Exception as exc:
                return HTMLResponse(
                    f"<html><body style='background:#050b14;color:#ff8090;font-family:sans-serif;padding:40px;text-align:center'>"
                    "<h2>Google OAuth Error</h2><p>Authorization failed. Return to JARVIS and try again.</p></body></html>",
                    status_code=500,
                )

        @app.websocket("/ws/hud")
        async def _ws_hud(ws: WebSocket):
            if self._loop is None:
                self._loop = asyncio.get_running_loop()
            await ws.accept()
            if self._close_timer is not None:
                self._close_timer.cancel()
                self._close_timer = None
            self._had_ws_client = True
            self._clients.add(ws)
            try:
                await ws.send_text(json.dumps(self.snapshot()))
                while True:
                    raw = await ws.receive_text()
                    try:
                        msg = json.loads(raw)
                        if isinstance(msg, dict) and msg.get("action"):
                            await asyncio.to_thread(self.handle_action, msg)
                    except Exception:
                        pass
            except WebSocketDisconnect:
                pass
            except Exception:
                pass
            finally:
                self._clients.discard(ws)
                getattr(self, "_client_send_locks", {}).pop(ws, None)
                if (
                    self._auto_close
                    and self._had_ws_client
                    and len(self._clients) == 0
                    and self._on_all_windows_closed is not None
                ):
                    self._schedule_auto_close()

        index_file = STATIC_HUD_DIR / "index.html"

        @app.get("/healthz")
        async def _healthz():
            return JSONResponse({"ok": True, "service": "jarvis-apex-hud"}, headers={"Cache-Control": "no-store"})

        @app.get("/")
        async def _root():
            if index_file.exists():
                return FileResponse(
                    index_file,
                    media_type="text/html",
                    headers={"Cache-Control": "no-cache"},
                )
            return JSONResponse(
                {"error": "static_hud bundle missing — run npm run build in apex_ui/"},
                status_code=503,
            )

        if STATIC_HUD_DIR.exists():
            app.mount(
                "/",
                StaticFiles(directory=str(STATIC_HUD_DIR), html=True),
                name="static_hud",
            )

        return app

    def _schedule_auto_close(self) -> None:
        if self._background_mode:
            return
        if self._close_timer is not None:
            self._close_timer.cancel()

        def _check():
            if self._background_mode:
                return
            if len(self._clients) == 0 and self._on_all_windows_closed is not None:
                try:
                    self._on_all_windows_closed()
                except Exception:
                    pass

        self._close_timer = threading.Timer(3.0, _check)
        self._close_timer.daemon = True
        self._close_timer.start()

    def _wait_until_http_ready(self, timeout: float) -> bool:
        """Verify the HTTP path itself, not only uvicorn's listening flag.

        Chromium can otherwise win a narrow Windows startup race and retain its
        own connection-error page even though uvicorn becomes ready immediately
        afterwards.  Disable environment proxies because this is loopback-only.
        """
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + max(0.2, timeout)
        health_url = f"{self.url.rstrip('/')}/healthz"
        while time.monotonic() < deadline:
            try:
                with opener.open(health_url, timeout=0.5) as response:
                    if response.status == 200:
                        payload = json.loads(response.read().decode("utf-8"))
                        if payload.get("ok") is True:
                            return True
            except (OSError, ValueError, urllib.error.URLError):
                time.sleep(0.04)
        return False

    def start(self, timeout: float = 5.0) -> str:
        """Start the local HTTP/WS server in a background daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            return self.url

        import uvicorn

        app = self._build_app()

        def _runner():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            config = uvicorn.Config(
                app,
                host=self.host,
                port=self.port,
                log_level="warning",
                access_log=False,
            )
            server = uvicorn.Server(config)
            self._server = server

            async def _serve():
                task = asyncio.create_task(server.serve())
                while not server.started and not task.done():
                    await asyncio.sleep(0.02)
                if server.started:
                    self._started.set()
                else:
                    try:
                        task.result()
                    except BaseException as exc:
                        self._start_error = exc
                    self._started.set()
                    return
                await task

            try:
                loop.run_until_complete(_serve())
            except BaseException as exc:
                self._start_error = exc
                print(f"[APEX-HUD] Bridge stopped: {exc}")
                self._started.set()

        self._thread = threading.Thread(
            target=_runner, daemon=True, name="jarvis-apex-hud"
        )
        self._thread.start()
        if not self._started.wait(timeout=timeout):
            raise TimeoutError(f"Local HUD server did not start within {timeout:.1f}s")
        if self._start_error is not None or self._server is None or not self._server.started:
            detail = type(self._start_error).__name__ if self._start_error else "server stopped"
            raise RuntimeError(f"Local HUD server failed to start ({detail})")
        if not self._wait_until_http_ready(timeout):
            self._server.should_exit = True
            raise RuntimeError("Local HUD server listened but did not answer its health check")
        self._auto_scheduler.start()
        self._long_tasks.start()
        return self.url

    def stop(self) -> None:
        self._auto_scheduler.stop()
        self._long_tasks.stop()
        if self._close_timer is not None:
            self._close_timer.cancel()
        if self._server is not None:
            self._server.should_exit = True


# ── Native App-Mode Window Discovery (Windows / macOS / Linux) ────────────────

def _find_chromium_app_binary() -> str | None:
    system = platform.system()
    candidates: list[str] = []

    if system == "Windows":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        candidates.extend(
            [
                os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
                os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
                os.path.join(local, "Microsoft", "Edge", "Application", "msedge.exe"),
                os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(local, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(
                    pf, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"
                ),
            ]
        )
        for name in ("msedge", "chrome", "brave"):
            found = shutil.which(name)
            if found:
                candidates.append(found)
    elif system == "Darwin":
        candidates.extend(
            [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            ]
        )
    else:
        for name in (
            "google-chrome",
            "chromium",
            "chromium-browser",
            "microsoft-edge",
            "brave-browser",
        ):
            found = shutil.which(name)
            if found:
                candidates.append(found)

    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def launch_app_window(url: str) -> bool:
    """Open `url` in a standalone frameless desktop app window (Edge/Chrome --app),
    falling back to the default system browser if no Chromium shell is present."""
    exe = _find_chromium_app_binary()
    if exe:
        profile_dir = cfg.CONFIG_DIR / "apex_hud_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        args = [
            exe,
            f"--app={url}",
            "--new-window",
            "--window-size=1440,920",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        popen_cls = getattr(subprocess, "_OrigPopen", subprocess.Popen)
        try:
            popen_cls(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as e:
            print(f"[APEX-HUD] App-window launch failed ({e}), falling back to browser.")

    try:
        return bool(webbrowser.open(url, new=1))
    except Exception:
        return False
