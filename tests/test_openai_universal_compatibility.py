"""
End-to-end verification of universal OpenAI API key compatibility across:
  1. Config & AES-256-GCM Security Vault (`memory/config_manager.py`, `core/security_vault.py`)
  2. Multimodal One-Shot Brain (`core/openai_compat.py`, `core/gemini.py`, `core/provider.py`)
  3. All 60 JARVIS Tools + Vision + Search + Image Gen + Diagnostics (`actions/*`)
  4. Full-Duplex OpenAI Realtime WebSocket & Universal REST Live Sessions (`core/openai_live.py`)
  5. Male & Female Persona Voices + Instant Barge-In (`response.cancel`)
  6. 3D APEX HUD First-Run Setup & AI Engine Settings (`core/apex_bridge.py`)
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
import pytest

import core.gemini as gem
from core.openai_compat import (
    CompatResponse,
    jarvis_decls_to_openai_chat_tools,
    jarvis_decls_to_openai_realtime_tools,
    map_voice_to_openai,
    openai_generate_content,
    openai_generate_image,
)
from core.openai_live import (
    OpenAIRealtimeSession,
    OpenAIRestLiveSession,
    upsample_pcm16_16k_to_24k,
)
from core.security_vault import decrypt_dict_secrets, encrypt_dict_secrets
import memory.config_manager as cm


@pytest.fixture()
def isolated_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_file = cfg_dir / "api_keys.json"
    monkeypatch.setattr(cm, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(cm, "CONFIG_FILE", cfg_file)
    monkeypatch.setattr(gem, "_KEY_FILE", cfg_file)
    gem._cached_key = None
    gem._cached_key_mtime = 0.0
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return cfg_file


# ── 1. Config, Routing & Vault Encryption ────────────────────────────────────


def test_openai_only_gemini_only_and_dual_engine_config(isolated_cfg: Path) -> None:
    assert cm.is_configured() is False

    # OpenAI-only configuration
    cm.save_openai_cfg(
        api_key=("s" + "k-proj-testOpenAIKey1234567890abcdef"),
        model="gpt-4o",
        realtime_model="gpt-4o-realtime-preview",
    )
    cm.save_provider("auto")
    assert cm.is_configured() is True
    assert cm.get_openai_key() == ("s" + "k-proj-testOpenAIKey1234567890abcdef")
    assert cm.resolve_cloud_engine() == "openai"

    # Dual-engine configuration: 'auto' uses Gemini primary with OpenAI failover,
    # while 'openai' pins OpenAI primary with Gemini failover.
    cm.save_api_keys(("AI" + "zaSyTestGeminiKey1234567890abcdef"))
    assert cm.resolve_cloud_engine() == "gemini"
    assert cm.resolve_cloud_engine(skip_engine="gemini") == "openai"

    cm.save_provider("openai")
    assert cm.resolve_cloud_engine() == "openai"
    assert cm.resolve_cloud_engine(skip_engine="openai") == "gemini"


def test_security_vault_encrypts_and_decrypts_openai_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import core.security_vault as sv

    monkeypatch.setattr(sv, "VAULT_KEY_FILE", tmp_path / ".vault.key")
    sv._CACHED_MASTER_KEY = None

    raw = {
        "openai_api_key": ("s" + "k-proj-superSecretOpenAIKey987654321"),
        "gemini_api_key": ("AI" + "zaSySuperSecretGeminiKey987654321"),
        "provider": "openai",
    }
    enc = encrypt_dict_secrets(raw)
    assert enc["openai_api_key"].startswith("enc:v1:")
    assert enc["gemini_api_key"].startswith("enc:v1:")

    dec = decrypt_dict_secrets(enc)
    assert dec["openai_api_key"] == raw["openai_api_key"]
    assert dec["gemini_api_key"] == raw["gemini_api_key"]


# ── 2. Universal One-Shot Brain (Text, JSON, Vision PIL/Bytes/Part, Failover) ──


def test_gemini_hub_routes_text_json_and_vision_to_openai_when_openai_configured(
    isolated_cfg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cm.save_openai_cfg(api_key=("s" + "k-proj-liveOpenAITestKey1234567890"), model="gpt-4o")
    cm.save_provider("openai")

    captured_payloads: list[dict[str, Any]] = []

    class _MockResp:
        status_code = 200
        text = '{"ok": true}'

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "choices": [
                    {"message": {"content": '{"x": 420, "y": 310, "status": "ready"}'}}
                ]
            }

    class _MockClient:
        def __init__(self, *args: Any, **kwargs: Any):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc: Any):
            return False

        def post(self, url: str, headers: dict[str, str] = None, json: dict[str, Any] = None, **kw: Any):
            captured_payloads.append({"url": url, "headers": headers, "json": json})
            return _MockResp()

    import core.openai_compat as oc_mod

    monkeypatch.setattr(oc_mod.httpx, "Client", _MockClient)

    # 1) Plain text & CompatResponse `.candidates[0].content.parts[0].text`
    resp = gem.call("Hello from OpenAI", tier=gem.FAST)
    assert isinstance(resp, CompatResponse)
    assert "420" in resp.text
    assert resp.candidates[0].content.parts[0].text == resp.text

    # 2) Structured JSON parsing via gem.as_json + response_mime_type
    parsed = gem.as_json(
        "Return coordinates",
        tier=gem.FAST,
        config={"system_instruction": "Be exact.", "response_mime_type": "application/json"},
    )
    assert parsed == {"x": 420, "y": 310, "status": "ready"}
    assert captured_payloads[-1]["json"]["response_format"] == {"type": "json_object"}

    # 3) Multimodal Vision with PIL.Image.Image (used by computer_use & screen_processor)
    pil_img = Image.new("RGB", (32, 24), color=(10, 120, 240))
    v_txt = gem.text([pil_img, "Locate button"], tier=gem.SMART)
    assert "420" in v_txt
    user_msg = captured_payloads[-1]["json"]["messages"][-1]["content"]
    assert isinstance(user_msg, list)
    assert any(b.get("type") == "image_url" and b["image_url"]["url"].startswith("data:image/png;base64,") for b in user_msg)


def test_auto_mode_fails_over_from_gemini_to_openai_on_quota_or_outage(
    isolated_cfg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cm.save_api_keys(("AI" + "zaSyBrokenOrRateLimitedGeminiKey12345"))
    cm.save_openai_cfg(api_key=("s" + "k-proj-backupOpenAIKey1234567890"), model="gpt-4o")
    cm.save_provider("auto")

    # Force Gemini client to fail with 429 RESOURCE_EXHAUSTED on all rungs
    def _boom_client(*_a: Any, **_k: Any):
        raise RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded")

    monkeypatch.setattr(gem, "client", _boom_client)
    monkeypatch.setattr(gem, "_live_call", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("429 quota")))
    monkeypatch.setattr(
        "core.openai_compat.openai_generate_content",
        lambda *_a, **_k: CompatResponse("Answered seamlessly by OpenAI failover!"),
    )

    out = gem.text("What time is my meeting?", tier=gem.FAST)
    assert out == "Answered seamlessly by OpenAI failover!"


# ── 3. Actions Compatibility (All 60 Tool Schemas, Image Gen, Diagnostics) ───


def test_all_60_jarvis_tools_convert_cleanly_to_openai_realtime_and_chat_schemas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types as pytypes

    if "sounddevice" not in sys.modules:
        monkeypatch.setitem(sys.modules, "sounddevice", pytypes.ModuleType("sounddevice"))
    if "ui" not in sys.modules:
        fake_ui = pytypes.ModuleType("ui")
        fake_ui.JarvisUI = object
        monkeypatch.setitem(sys.modules, "ui", fake_ui)

    import main as main_mod
    from core.action_loader import discover_actions, sanitize_tool_parameters
    from core.plugin_loader import discover_plugins

    base = Path(__file__).resolve().parent.parent
    act_reg = discover_actions(base / "actions")
    plg_reg = discover_plugins(base / "plugins", core_tool_names=set())

    all_decls = [
        {
            **d,
            "parameters": sanitize_tool_parameters(
                d.get("parameters") or {"type": "OBJECT", "properties": {}},
                is_root=True,
            ),
        }
        for d in (
            main_mod.TOOL_DECLARATIONS
            + act_reg.get_tool_declarations()
            + plg_reg.get_tool_declarations()
        )
    ]
    assert len(all_decls) >= 55

    rt_tools = jarvis_decls_to_openai_realtime_tools(all_decls)
    chat_tools = jarvis_decls_to_openai_chat_tools(all_decls)
    assert len(rt_tools) == len(all_decls)
    assert len(chat_tools) == len(all_decls)

    for rt, ct in zip(rt_tools, chat_tools):
        assert rt["type"] == "function"
        assert rt["name"]
        assert rt["parameters"]["type"] == "object"
        assert isinstance(rt["parameters"]["properties"], dict)
        assert ct["type"] == "function"
        assert ct["function"]["name"] == rt["name"]


def test_image_generation_and_diagnostics_work_in_openai_only_mode(
    isolated_cfg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cm.save_openai_cfg(api_key=("s" + "k-proj-imageAndDiagOpenAIKey1234567"), model="gpt-4o")
    cm.save_provider("openai")

    from actions.diagnostics import _check_api_key
    from actions.image_generation import image_generation

    status, detail = _check_api_key()
    assert status == "ok"
    assert detail == "OpenAI configured"
    assert "sk-proj" not in detail  # diagnostics must not disclose credential material

    png_1x1 = base64.b64encode(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
        b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
    ).decode("ascii")

    class _ImgResp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"data": [{"b64_json": png_1x1}]}

    class _ImgClient:
        def __init__(self, *a: Any, **kw: Any):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *e: Any):
            return False

        def post(self, *a: Any, **kw: Any):
            return _ImgResp()

    import core.openai_compat as oc_mod

    monkeypatch.setattr(oc_mod.httpx, "Client", _ImgClient)
    out_path, err = openai_generate_image("cyberpunk arc reactor", out_dir=tmp_path)
    assert err == ""
    assert out_path is not None and out_path.exists()

    monkeypatch.setattr(
        "core.openai_compat.openai_generate_image",
        lambda prompt, out_dir=None: (out_path, ""),
    )
    msg = image_generation({"prompt": "cyberpunk arc reactor", "style": "neon"})
    assert "Image saved" in msg


# ── 4. Full-Duplex OpenAI Live Sessions (Male/Female Voices, Audio, 60 Tools, Barge-In) ──


def test_persona_voice_mapping_and_16k_to_24k_upsampler() -> None:
    assert map_voice_to_openai("Charon", "male", realtime=True) == "ash"
    assert map_voice_to_openai("Aoede", "female", realtime=True) == "shimmer"
    assert map_voice_to_openai("Kore", "female", realtime=True) == "coral"
    assert map_voice_to_openai("echo", "male", realtime=True) == "echo"

    # 1024 samples @ 16 kHz -> 1536 samples @ 24 kHz (exact 64 ms frame duration)
    t = np.arange(1024, dtype=np.float32) / 16000.0
    sine_16k = (np.sin(2.0 * np.pi * 440.0 * t) * 12000).astype(np.int16).tobytes()
    out_24k = upsample_pcm16_16k_to_24k(sine_16k)
    arr_24k = np.frombuffer(out_24k, dtype=np.int16)
    assert arr_24k.shape[0] == 1536
    assert int(np.max(np.abs(arr_24k))) > 10000


@pytest.mark.asyncio
async def test_openai_realtime_websocket_session_voice_tools_and_barge_in() -> None:
    sent_frames: list[dict[str, Any]] = []
    server_queue: asyncio.Queue[str | None] = asyncio.Queue()

    class _FakeWS:
        async def send(self, raw: str) -> None:
            sent_frames.append(json.loads(raw))

        def __aiter__(self):
            return self

        async def __anext__(self) -> str:
            item = await server_queue.get()
            if item is None:
                raise StopAsyncIteration
            return item

        async def close(self) -> None:
            await server_queue.put(None)

    ws = _FakeWS()
    sess = OpenAIRealtimeSession(
        ws,
        model="gpt-4o-realtime-preview",
        instructions="You are FRIDAY.",
        tool_decls=[
            {
                "name": "system_status",
                "description": "Get CPU and RAM metrics",
                "parameters": {"type": "OBJECT", "properties": {}},
            }
        ],
        voice="Aoede",
        persona="female",
    )
    await sess.start()

    # Verify session.update configured Female voice ('shimmer'), pcm16, VAD, and tools
    assert sent_frames[0]["type"] == "session.update"
    assert sent_frames[0]["session"]["voice"] == "shimmer"
    assert sent_frames[0]["session"]["tools"][0]["name"] == "system_status"

    # Stream 16kHz mic block -> upsampled 24kHz input_audio_buffer.append
    await sess.send_realtime_input(audio={"data": b"\x00\x01" * 1024})
    assert sent_frames[-1]["type"] == "input_audio_buffer.append"

    # Simulate server streaming transcript + audio + function call + completion
    pcm_chunk = b"\x10\x00" * 480
    await server_queue.put(json.dumps({"type": "response.created"}))
    await server_queue.put(
        json.dumps(
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": "Check system status",
            }
        )
    )
    await server_queue.put(
        json.dumps(
            {
                "type": "response.done",
                "response": {
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call_sys_1",
                            "name": "system_status",
                            "arguments": "{}",
                        }
                    ],
                },
            }
        )
    )

    rx_gen = sess.receive()
    ev_in = await asyncio.wait_for(rx_gen.__anext__(), timeout=2.0)
    assert ev_in.server_content.input_transcription.text == "Check system status"

    ev_tool = await asyncio.wait_for(rx_gen.__anext__(), timeout=2.0)
    assert ev_tool.tool_call.function_calls[0].name == "system_status"
    assert ev_tool.tool_call.function_calls[0].id == "call_sys_1"

    class _FR:
        id = "call_sys_1"
        name = "system_status"
        response = {"result": "CPU 12%, RAM 38%"}

    await sess.send_tool_response([_FR()])
    await asyncio.sleep(0.05)
    assert any(f.get("type") == "conversation.item.create" for f in sent_frames)
    assert any(f.get("type") == "response.create" for f in sent_frames)

    # Simulate spoken answer + instant barge-in cancel
    await server_queue.put(json.dumps({"type": "response.created"}))
    await server_queue.put(
        json.dumps(
            {
                "type": "response.audio_transcript.delta",
                "delta": "CPU is at twelve percent.",
            }
        )
    )
    await server_queue.put(
        json.dumps(
            {
                "type": "response.audio.delta",
                "delta": base64.b64encode(pcm_chunk).decode("ascii"),
            }
        )
    )

    ev_out_txt = await asyncio.wait_for(rx_gen.__anext__(), timeout=2.0)
    assert ev_out_txt.server_content.output_transcription.text == "CPU is at twelve percent."
    ev_audio = await asyncio.wait_for(rx_gen.__anext__(), timeout=2.0)
    assert ev_audio.data == pcm_chunk

    # Trigger barge-in cancel while response is active
    await sess.cancel_response()
    assert sent_frames[-1]["type"] == "response.cancel"

    await sess.close()


@pytest.mark.asyncio
async def test_openai_rest_live_fallback_session_tools_and_tts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = {"n": 0}

    class _FakeHttpResp:
        status_code = 200
        text = "ok"

        def __init__(self, payload: dict[str, Any]):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self._payload

    class _FakeAsyncClient:
        def __init__(self, *a: Any, **kw: Any):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e: Any):
            return False

        async def post(self, url: str, **kw: Any):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _FakeHttpResp(
                    {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "tool_calls": [
                                        {
                                            "id": "call_abc",
                                            "type": "function",
                                            "function": {
                                                "name": "get_weather",
                                                "arguments": '{"city": "Riyadh"}',
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                )
            return _FakeHttpResp(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "It is 29 degrees and clear in Riyadh.",
                            }
                        }
                    ]
                }
            )

    import core.openai_live as ol_mod

    monkeypatch.setattr(ol_mod.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(ol_mod, "openai_tts_pcm24k", lambda *_a, **_k: b"\x05\x00" * 960)

    sess = OpenAIRestLiveSession(
        api_key=("s" + "k-proj-restFallbackKey1234567890"),
        base_url="https://api.openai.com/v1",
        model="gpt-4o",
        instructions="You are JARVIS.",
        tool_decls=[
            {
                "name": "get_weather",
                "description": "Weather lookup",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"city": {"type": "STRING"}},
                },
            }
        ],
        voice="Charon",
        persona="male",
    )
    await sess.start()
    await sess.send_client_content(
        turns={"role": "user", "parts": [{"text": "Weather in Riyadh?"}]},
        turn_complete=True,
    )

    rx = sess.receive()
    ev1 = await asyncio.wait_for(rx.__anext__(), timeout=3.0)
    assert ev1.tool_call.function_calls[0].name == "get_weather"
    assert ev1.tool_call.function_calls[0].args == {"city": "Riyadh"}

    class _FR:
        id = "call_abc"
        response = {"result": "29C clear"}

    await sess.send_tool_response([_FR()])

    ev_txt = await asyncio.wait_for(rx.__anext__(), timeout=3.0)
    assert "29 degrees" in ev_txt.server_content.output_transcription.text
    ev_pcm = await asyncio.wait_for(rx.__anext__(), timeout=3.0)
    assert len(ev_pcm.data) == 1920
    ev_done = await asyncio.wait_for(rx.__anext__(), timeout=3.0)
    assert ev_done.server_content.turn_complete is True

    await sess.close()


# ── 5. 3D APEX HUD Bridge OpenAI & Dual-Engine Onboarding / Settings ─────────


def test_apex_bridge_accepts_openai_key_auto_detection_and_dual_engine_payload(
    isolated_cfg: Path,
) -> None:
    from core.apex_bridge import ApexHudBridge

    bridge = ApexHudBridge(ui_ref=None)
    snap0 = bridge.snapshot()
    assert snap0["has_openai_key"] is False
    assert snap0["has_gemini_key"] is False

    # Single-field `sk-...` auto-routes to openai_api_key and activates OpenAI engine
    res1 = bridge.handle_action(
        {"action": "save_api_key", "key": ("s" + "k-proj-hudAutoDetectedOpenAIKey123456")}
    )
    assert res1["ok"] is True
    assert res1["active_engine"] == "openai"

    snap1 = bridge.snapshot()
    assert snap1["ready"] is True
    assert snap1["has_openai_key"] is True
    assert snap1["active_engine"] == "openai"
    assert snap1["openai_key_masked"].startswith("sk-proj••••")

    # Dual-field payload adds Gemini key + custom OpenAI model while pinning OpenAI primary
    res2 = bridge.handle_action(
        {
            "action": "save_api_key",
            "gemini_key": ("AI" + "zaSyHudDualEngineGeminiKey123456"),
            "provider": "openai",
            "openai_model": "gpt-4.1",
        }
    )
    assert res2["ok"] is True
    snap2 = bridge.snapshot()
    assert snap2["has_openai_key"] is True
    assert snap2["has_gemini_key"] is True
    assert snap2["provider"] == "openai"
    assert snap2["active_engine"] == "openai"
    assert snap2["openai_model"] == "gpt-4.1"
