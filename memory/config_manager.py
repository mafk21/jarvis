import json
import copy
import threading
import time
import os
import sys
from pathlib import Path

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR    = get_base_dir()
CONFIG_DIR  = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "api_keys.json"

def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def config_exists() -> bool:
    return CONFIG_FILE.exists()

def save_api_keys(gemini_api_key: str) -> None:
    ensure_config_dir()

    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    data["gemini_api_key"] = gemini_api_key.strip()

    from core.security_vault import encrypt_dict_secrets
    disk_data = encrypt_dict_secrets(data)
    _write_config_text(
        json.dumps(disk_data, indent=2),
        encoding="utf-8"
    )

# Cache only the on-disk object, never decrypted credentials. Stat each access
# so settings edits, atomic replacements and deletion take effect immediately.
_CONFIG_READ_LOCK = threading.RLock()
_CONFIG_READ_CACHE = None


def invalidate_config_cache():
    global _CONFIG_READ_CACHE
    with _CONFIG_READ_LOCK:
        _CONFIG_READ_CACHE = None


def _write_config_text(encrypted_text, encoding="utf-8"):
    """Persist an already encrypted config without a high-level text sink.

    ``save_config`` is the sole caller and encrypts secret-bearing fields before
    serialization.  Using an exclusive low-level descriptor also narrows the
    period in which the config file is open and applies owner-only permissions
    on POSIX systems.
    """
    payload = encrypted_text.encode(encoding)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    # Managed writes invalidate even on filesystems with coarse timestamps.
    with _CONFIG_READ_LOCK:
        invalidate_config_cache()
        fd = os.open(CONFIG_FILE, flags, 0o600)
        try:
            total = 0
            while total < len(payload):
                total += os.write(fd, payload[total:])
            return total
        finally:
            os.close(fd)
            invalidate_config_cache()


def _config_stamp(path):
    st = path.stat()
    return (str(path.absolute()), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _read_config_object():
    global _CONFIG_READ_CACHE
    with _CONFIG_READ_LOCK:
        path = CONFIG_FILE
        try:
            stamp = _config_stamp(path)
        except FileNotFoundError:
            _CONFIG_READ_CACHE = None
            return {}
        if (_CONFIG_READ_CACHE is not None and _CONFIG_READ_CACHE[0] == stamp
                and time.monotonic() - _CONFIG_READ_CACHE[2] < .25):
            return _CONFIG_READ_CACHE[1]
        # A failed/partial external write must never serve stale credentials.
        _CONFIG_READ_CACHE = None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        if _config_stamp(path) == stamp:
            _CONFIG_READ_CACHE = (stamp, raw, time.monotonic())
        return raw


def load_api_keys() -> dict:
    try:
        raw = _read_config_object()
        try:
            from core.security_vault import decrypt_dict_secrets
            return decrypt_dict_secrets(raw)
        except Exception:
            return copy.deepcopy(raw)
    except Exception as e:
        print(f"❌ Failed to load api_keys.json: {e}")
        return {}


def set_strict_config_encryption(enabled: bool) -> bool:
    """Encrypt or decrypt secret keys inside config/api_keys.json on disk."""
    if not CONFIG_FILE.exists():
        return False
    plain = load_api_keys()
    plain["strict_vault_config"] = bool(enabled)
    if enabled:
        from core.security_vault import encrypt_dict_secrets
        disk_obj = encrypt_dict_secrets(plain)
    else:
        disk_obj = plain
    _write_config_text(json.dumps(disk_obj, indent=2), encoding="utf-8")
    return True

def get_gemini_key() -> str | None:
    val = (load_api_keys().get("gemini_api_key") or os.environ.get("GEMINI_API_KEY") or "").strip()
    return val or None


def get_api_key() -> str | None:
    return get_gemini_key()


def get_openai_key() -> str | None:
    val = (load_api_keys().get("openai_api_key") or os.environ.get("OPENAI_API_KEY") or "").strip()
    return val or None


def get_anthropic_key() -> str | None:
    val = (load_api_keys().get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    return val or None


def is_configured() -> bool:
    gkey = get_gemini_key()
    okey = get_openai_key()
    akey = get_anthropic_key()
    return bool(
        (gkey and len(gkey) > 15)
        or (okey and len(okey) > 15)
        or (akey and len(akey) > 15)
    )


def is_integrations_onboarding_done() -> bool:
    """Whether the first-run optional integrations setup step has been completed or skipped."""
    return bool(load_api_keys().get("integrations_onboarding_done", False))


def save_integrations_onboarding_done(done: bool = True) -> None:
    _save_flag("integrations_onboarding_done", bool(done))


def get_desktop_shortcut_preference() -> dict:
    """Return whether first-run shortcut choice was shown and accepted."""
    data = load_api_keys()
    return {
        "prompted": bool(data.get("desktop_shortcut_prompted", False)),
        "enabled": bool(data.get("desktop_shortcut_enabled", False)),
    }


def save_desktop_shortcut_preference(enabled: bool, *, prompted: bool = True) -> None:
    _patch_config(
        desktop_shortcut_prompted=bool(prompted),
        desktop_shortcut_enabled=bool(enabled),
    )


# ── Brain & Privacy Tier Toggles ─────────────────────────────────────────────

def get_personalization_enabled() -> bool:
    """Tier 3: Whether stored memories & timeline context are injected into prompts."""
    return bool(load_api_keys().get("personalization_enabled", True))


def save_personalization_enabled(enabled: bool) -> None:
    _save_flag("personalization_enabled", bool(enabled))


def get_adaptive_learning_enabled() -> bool:
    """Tier 4: Whether JARVIS automatically records new preferences/facts during chats."""
    return bool(load_api_keys().get("adaptive_learning_enabled", True))


def save_adaptive_learning_enabled(enabled: bool) -> None:
    from core.adaptation_privacy import persistence_guard
    with persistence_guard():
        _save_flag("adaptive_learning_enabled", bool(enabled))


def get_timeline_persistence_enabled() -> bool:
    """Whether spoken, typed, and Telegram turns are persisted to the Forever Timeline."""
    return bool(load_api_keys().get("timeline_persistence_enabled", True))


def save_timeline_persistence_enabled(enabled: bool) -> None:
    _save_flag("timeline_persistence_enabled", bool(enabled))


def get_soul_enabled() -> bool:
    """Feature flag for the persistent Soul context; off until staged rollout."""
    return bool(load_api_keys().get("soul_enabled", False))


def save_soul_enabled(enabled: bool) -> None:
    _save_flag("soul_enabled", bool(enabled))


def get_privacy_settings() -> dict:
    cfg = load_api_keys()
    return {
        "personalization_enabled": bool(cfg.get("personalization_enabled", True)),
        "adaptive_learning_enabled": bool(cfg.get("adaptive_learning_enabled", True)),
        "timeline_persistence_enabled": bool(cfg.get("timeline_persistence_enabled", True)),
    }


def get_assistant_name() -> str:
    """Return the configured assistant name, or 'JARVIS' if not set."""
    return load_api_keys().get("assistant_name", "JARVIS") or "JARVIS"


def get_user_name() -> str:
    """Return the configured user name for addressing."""
    return load_api_keys().get("user_name", "")


def save_assistant_config(assistant_name: str, user_name: str) -> None:
    """Persist assistant name and user name to config."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["assistant_name"] = assistant_name.strip() or "JARVIS"
    data["user_name"] = user_name.strip()
    _write_config_text(json.dumps(data, indent=4), encoding="utf-8")


# ── Assistant voice & persona ("male" | "female") ────────────────────────────
# Gemini Live prebuilt voices. Names are proper nouns — identical in every
# language, so this list is safe to show verbatim in any locale.
AVAILABLE_VOICES     = ["Charon", "Puck", "Kore", "Fenrir", "Aoede"]
MALE_VOICES          = ("Charon", "Fenrir", "Puck")
FEMALE_VOICES        = ("Aoede", "Kore")
DEFAULT_VOICE        = "Charon"
DEFAULT_MALE_VOICE   = "Charon"
DEFAULT_FEMALE_VOICE = "Aoede"

PERSONAS         = ("male", "female")
MALE_UI_COLOR    = "#00d4ff"
FEMALE_UI_COLOR  = "#ff4db8"


def get_voice() -> str:
    """Return the configured Live voice, falling back to the persona default if
    unset or if the stored value is not a voice we recognise."""
    data = load_api_keys()
    v = data.get("voice_name", "") or ""
    if v in AVAILABLE_VOICES:
        return v
    if str(data.get("persona", "")).strip().lower() == "female":
        return DEFAULT_FEMALE_VOICE
    return DEFAULT_VOICE


def save_voice(voice_name: str) -> None:
    """Persist the chosen Live voice. Unknown names collapse to the default so a
    bad value can never reach the API and break the session."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    v = (voice_name or "").strip()
    data["voice_name"] = v if v in AVAILABLE_VOICES else DEFAULT_VOICE
    _write_config_text(json.dumps(data, indent=4), encoding="utf-8")


def get_persona() -> str:
    """Return 'male' or 'female'. Infers from voice_name when unset."""
    data = load_api_keys()
    raw = str(data.get("persona", "") or "").strip().lower()
    if raw in PERSONAS:
        return raw
    if str(data.get("voice_name", "") or "").strip() in FEMALE_VOICES:
        return "female"
    return "male"


def get_ui_color() -> str:
    """Return a valid saved #RRGGBB accent, or the inferred edition's default.

    Read-only: startup must not reset custom colours, overwrite credentials, or
    mark a first-run persona as chosen merely to obtain an accent.
    """
    data = load_api_keys()
    saved = data.get("ui_color")
    if isinstance(saved, str):
        color = saved.strip().lower()
        if len(color) == 7 and color.startswith("#") and all(c in "0123456789abcdef" for c in color[1:]):
            return color
    return FEMALE_UI_COLOR if get_persona() == "female" else MALE_UI_COLOR


def is_persona_chosen() -> bool:
    """Return True once the user has chosen Male or Female at least once."""
    data = load_api_keys()
    if bool(data.get("persona_chosen", False)):
        return True
    raw = str(data.get("persona", "") or "").strip().lower()
    return raw in PERSONAS


def save_persona(persona: str, voice_name: str | None = None) -> dict:
    """Persist the chosen interface persona ('male' or 'female'), matching
    Gemini Live voice, and UI accent colour in one atomic update."""
    p = "female" if str(persona or "").strip().lower() == "female" else "male"
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    cur_voice = str(data.get("voice_name", "") or "").strip()
    explicit_voice = str(voice_name or "").strip()
    if explicit_voice in AVAILABLE_VOICES:
        chosen_voice = explicit_voice
    elif p == "female":
        chosen_voice = cur_voice if cur_voice in FEMALE_VOICES else DEFAULT_FEMALE_VOICE
    else:
        chosen_voice = cur_voice if cur_voice in MALE_VOICES else DEFAULT_MALE_VOICE

    ui_color = FEMALE_UI_COLOR if p == "female" else MALE_UI_COLOR
    data["persona"] = p
    data["persona_chosen"] = True
    data["voice_name"] = chosen_voice
    data["ui_color"] = ui_color
    _write_config_text(json.dumps(data, indent=4), encoding="utf-8")
    return {"persona": p, "voice": chosen_voice, "ui_color": ui_color}


def get_wake_word_enabled() -> bool:
    """Whether local wake-word gating is on (assistant sleeps until 'Hey Jarvis')."""
    return load_api_keys().get("wake_word_enabled", False)


def save_wake_word_enabled(enabled: bool) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["wake_word_enabled"] = bool(enabled)
    _write_config_text(json.dumps(data, indent=4), encoding="utf-8")


def get_push_to_talk_enabled() -> bool:
    """Hold-a-key-to-speak. When on, the mic is closed unless the chord is held."""
    return load_api_keys().get("push_to_talk_enabled", False)


def save_push_to_talk_enabled(enabled: bool) -> None:
    _save_flag("push_to_talk_enabled", enabled)


HUD_STYLES = ("face", "core")


def get_hud_style() -> str:
    """Which centrepiece the HUD draws: the animated head, or the reactor core.

    Taste, not capability — both render in the same software painter and cost
    about the same. Defaults to the head because that is what MARK LIV shipped
    with; anyone who preferred the older look can switch back in ⚙ and the
    choice survives a restart.
    """
    v = str(load_api_keys().get("hud_style", "face")).strip().lower()
    return v if v in HUD_STYLES else "face"


def save_hud_style(style: str) -> None:
    s = str(style or "").strip().lower()
    _save_flag("hud_style", s if s in HUD_STYLES else "face")


# ── Live-session tuning ──────────────────────────────────────────────────────
# Everything here is optional and has a working default, so an untouched
# config behaves exactly like a configured one. Each value is also a way out:
# if a future model dislikes one of these, set it back and nothing else changes.

def get_thinking_enabled() -> bool:
    """Whether the Live model may spend tokens thinking before it answers.

    Off by default. A voice assistant is judged on how fast it starts talking,
    and the reasoning that actually needs deliberation in this app is delegated
    to the planning tools, which run on a separate non-Live model.
    """
    return bool(load_api_keys().get("thinking_enabled", False))


def save_thinking_enabled(enabled: bool) -> None:
    _save_flag("thinking_enabled", enabled)


def get_turn_tuning() -> dict:
    """How eagerly the server decides you have stopped speaking.

    OFF by default, and that default was earned. Cutting turns shorter looks
    like a free speed win and is not: proactive audio has to judge whether an
    utterance was even addressed to the assistant, and a turn clipped early
    gives it less to judge, so it stays quiet — and the reply to your first
    sentence only arrives once your second one has given it enough context.
    That reads as the assistant being a turn behind, which is far worse than
    the fraction of a second the tuning saves.

    Turn it on with "turn_tuning": {"enabled": true} if your own microphone and
    speaking pace suit it. `silence_ms` is the one that is felt: the pause the
    server sits through before accepting your turn is over.
    """
    cfg = load_api_keys().get("turn_tuning")
    cfg = cfg if isinstance(cfg, dict) else {}

    def _int(key, default, lo, hi):
        try:
            return max(lo, min(hi, int(cfg.get(key, default))))
        except (TypeError, ValueError):
            return default

    return {
        "enabled":    bool(cfg.get("enabled", False)),
        "silence_ms": _int("silence_ms", 550, 200, 3000),
        "prefix_ms":  _int("prefix_ms", 150, 0, 1000),
        # "high" = quicker to decide speech has ended.
        "end_sensitivity":   str(cfg.get("end_sensitivity", "high")).lower(),
        "start_sensitivity": str(cfg.get("start_sensitivity", "default")).lower(),
    }


def save_turn_tuning(values: dict) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    cur = data.get("turn_tuning")
    cur = dict(cur) if isinstance(cur, dict) else {}
    cur.update(values or {})
    data["turn_tuning"] = cur
    _write_config_text(json.dumps(data, indent=4), encoding="utf-8")


def get_proactive_audio_enabled() -> bool:
    """Whether the model gets to decide an utterance was not aimed at it and
    stay quiet.

    On by default — it is what stops the assistant answering the room. But it
    is also the first thing to switch off if replies ever seem to arrive a turn
    late: what looks like lag is usually the model having judged your previous
    sentence as not addressed to it, and only changing its mind once the next
    one arrives.
    """
    return bool(load_api_keys().get("proactive_audio", True))


def save_proactive_audio_enabled(enabled: bool) -> None:
    _save_flag("proactive_audio", enabled)


MEDIA_RESOLUTIONS = ("default", "low", "medium", "high")


def get_media_resolution() -> str:
    """How finely the model tokenises the screenshots and camera frames it is
    sent. 'medium' keeps on-screen text readable at a fraction of the tokens a
    full-resolution frame costs; 'low' is cheaper still but starts losing small
    text, which is most of what screen captures are for."""
    v = str(load_api_keys().get("media_resolution", "medium")).strip().lower()
    return v if v in MEDIA_RESOLUTIONS else "medium"


def save_media_resolution(value: str) -> None:
    v = str(value or "").strip().lower()
    _save_flag("media_resolution", v if v in MEDIA_RESOLUTIONS else "medium")


def _save_flag(key: str, value) -> None:
    """Read-modify-write one key without disturbing the rest of the config."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[key] = bool(value) if isinstance(value, bool) else value
    _write_config_text(json.dumps(data, indent=4), encoding="utf-8")


def get_brief_enabled() -> bool:
    return load_api_keys().get("morning_brief_enabled", True)


def save_brief_enabled(enabled: bool) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["morning_brief_enabled"] = enabled
    _write_config_text(json.dumps(data, indent=4), encoding="utf-8")


# ── Audio devices ────────────────────────────────────────────────────────────
# Stored as device NAMES, not sounddevice indices. Indices shift every time a
# USB device is plugged in or removed, so a saved index silently starts pointing
# at a different microphone. The empty string means "system default", which is
# both the factory setting and what an unresolvable saved device falls back to —
# so unplugging a headset degrades to the built-in speakers instead of crashing.

def _patch_config(**fields) -> None:
    """Read-modify-write one or more keys in api_keys.json.

    Every setter in this file open-coded this. Collapsing it here means a new
    setting is one line, and there is one place where a corrupt config file is
    handled instead of nine."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data.update(fields)
    _write_config_text(json.dumps(data, indent=4), encoding="utf-8")


def get_input_device() -> str:
    """Microphone device name, or '' for the system default."""
    return (load_api_keys().get("input_device", "") or "").strip()


def save_input_device(name: str) -> None:
    _patch_config(input_device=(name or "").strip())


def get_output_device() -> str:
    """Speaker device name, or '' for the system default."""
    return (load_api_keys().get("output_device", "") or "").strip()


def save_output_device(name: str) -> None:
    _patch_config(output_device=(name or "").strip())


def get_plugin_enabled(plugin_name: str) -> bool:
    """Plugins are enabled by default the moment they're discovered (opt-out model)."""
    return load_api_keys().get("plugins_enabled", {}).get(plugin_name, True)


# ── Per-plugin settings ("tokens" / connection details) ───────────────────────
# Generic store so a plugin can declare its own config fields (PLUGIN_SETTINGS)
# and the settings UI renders + persists them WITHOUT any core edit — keeping the
# drop-in model intact. Values live under plugin_config[<namespace>][<key>].
# A namespace defaults to the plugin name, but a suite of plugins (e.g. the
# several printer plugins) can share ONE namespace.
def get_plugin_config(namespace: str) -> dict:
    """All stored values for a namespace (empty dict if none set yet)."""
    cfg = load_api_keys().get("plugin_config")
    val = cfg.get(namespace) if isinstance(cfg, dict) else None
    return dict(val) if isinstance(val, dict) else {}


def get_plugin_setting(namespace: str, key: str, default=None):
    """A single value from a namespace, or `default` if unset."""
    return get_plugin_config(namespace).get(key, default)


def save_plugin_config(namespace: str, values: dict) -> None:
    """Merge `values` into a namespace's stored config (read-modify-write, like
    every other helper here). Only the provided keys are touched."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    pc = data.get("plugin_config")
    if not isinstance(pc, dict):
        pc = {}
    cur = pc.get(namespace)
    if not isinstance(cur, dict):
        cur = {}
    cur.update(values)
    pc[namespace] = cur
    data["plugin_config"] = pc
    _write_config_text(json.dumps(data, indent=4), encoding="utf-8")


def save_plugin_enabled(plugin_name: str, enabled: bool) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    plugins_cfg = data.get("plugins_enabled")
    if not isinstance(plugins_cfg, dict):
        plugins_cfg = {}
    plugins_cfg[plugin_name] = enabled
    data["plugins_enabled"] = plugins_cfg
    _write_config_text(json.dumps(data, indent=4), encoding="utf-8")


# ── Phase 1: Voice Foundations ───────────────────────────────────────────────
# Grace window: follow-ups don't need wake word for N seconds after Jarvis stops.
# Barge-in: voice can interrupt while Jarvis is speaking (uses EchoGuard).
# Pause: listening off but reply/task continues (distinct from Stop).

def get_barge_in_enabled() -> bool:
    """Voice barge-in — talk over Jarvis to cut it short. FORCED ON this build.

    Previous releases defaulted to OFF / migrated existing `false` values.
    Users reported 'won't stop when I talk' because the saved `false` stuck.
    For reliability barge-in is now always ON — toggle in ⚙ still persists but
    the getter never returns False so a stale config can never silence interrupt.
    """
    # Always ON — ignore stored value. UI toggle still writes but we override.
    return True


def save_barge_in_enabled(enabled: bool) -> None:
    _save_flag("barge_in_enabled", bool(enabled))


def get_grace_period() -> int:
    """Seconds after Jarvis stops that wake word is not required (0 to disable)."""
    try:
        v = int(load_api_keys().get("wake_grace_period", 8))
        return max(0, min(30, v))
    except Exception:
        return 8


def save_grace_period(seconds: int) -> None:
    _save_flag("wake_grace_period", max(0, min(30, int(seconds))))


def get_pause_enabled() -> bool:
    """Internal — whether Pause control is available (always true once Phase 1 ships)."""
    return True
# ── Phase 2: Offline & Multi-Provider ───────────────────────────────────────
# Provider abstraction + offline fallback controls. All additive; existing
# gemini_api_key install keeps behaving exactly as before (provider=auto).

PROVIDERS = ("auto", "gemini", "openai", "anthropic", "local", "ollama", "lmstudio")

def get_provider() -> str:
    v = str(load_api_keys().get("provider", "auto")).strip().lower()
    return v if v in PROVIDERS else "auto"

def save_provider(name: str) -> None:
    v = str(name or "auto").strip().lower()
    _save_flag("provider", v if v in PROVIDERS else "auto")

def get_offline_fallback_enabled() -> bool:
    return bool(load_api_keys().get("offline_fallback", True))

def save_offline_fallback_enabled(enabled: bool) -> None:
    _save_flag("offline_fallback", bool(enabled))

def get_openai_cfg() -> dict:
    cfg = load_api_keys()
    api_k = str(cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY") or "").strip()
    return {
        "api_key":        api_k,
        "base_url":       str(cfg.get("openai_base_url", "https://api.openai.com/v1") or "https://api.openai.com/v1").rstrip("/"),
        "model":          str(cfg.get("openai_model", "gpt-4o") or "gpt-4o").strip(),
        "realtime_model": str(cfg.get("openai_realtime_model", "gpt-4o-realtime-preview") or "gpt-4o-realtime-preview").strip(),
    }


def save_openai_cfg(
    api_key: str = None,
    base_url: str = None,
    model: str = None,
    realtime_model: str = None,
) -> None:
    cur = get_openai_cfg()
    if api_key is not None:
        cur["api_key"] = str(api_key or "").strip()
    if base_url is not None:
        cur["base_url"] = str(base_url or "https://api.openai.com/v1").rstrip("/")
    if model is not None:
        cur["model"] = str(model or "gpt-4o").strip()
    if realtime_model is not None:
        cur["realtime_model"] = str(realtime_model or "gpt-4o-realtime-preview").strip()
    ensure_config_dir()
    data = load_api_keys()
    data["openai_api_key"] = cur["api_key"]
    data["openai_base_url"] = cur["base_url"]
    data["openai_model"] = cur["model"]
    data["openai_realtime_model"] = cur["realtime_model"]
    from core.security_vault import encrypt_dict_secrets
    disk_data = encrypt_dict_secrets(data)
    _write_config_text(json.dumps(disk_data, indent=4), encoding="utf-8")


def get_anthropic_cfg() -> dict:
    cfg = load_api_keys()
    return {
        "api_key": str(cfg.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY") or "").strip(),
        "model": str(cfg.get("anthropic_model", "claude-sonnet-4-5") or "claude-sonnet-4-5").strip(),
    }


def save_anthropic_cfg(api_key: str = None, model: str = None) -> None:
    cur = get_anthropic_cfg()
    if api_key is not None:
        cur["api_key"] = str(api_key or "").strip()
    if model is not None:
        cur["model"] = str(model or "claude-sonnet-4-5").strip()
    data = load_api_keys()
    data["anthropic_api_key"] = cur["api_key"]
    data["anthropic_model"] = cur["model"]
    from core.security_vault import encrypt_dict_secrets
    _write_config_text(json.dumps(encrypt_dict_secrets(data), indent=4), encoding="utf-8")


def resolve_cloud_engine(skip_engine: str = "") -> str:
    """Choose 'openai' or 'gemini' based on provider preference and configured keys."""
    pref = get_provider()
    gkey = get_gemini_key()
    okey = get_openai_key()
    has_g = bool(gkey and len(gkey) > 15) and skip_engine != "gemini"
    has_o = bool(okey and len(okey) > 15) and skip_engine != "openai"

    if pref == "openai":
        if has_o:
            return "openai"
        if has_g:
            return "gemini"
    elif pref == "gemini":
        if has_g:
            return "gemini"
        if has_o:
            return "openai"
    else:
        # 'auto' — use Gemini first when present, else OpenAI, with full failover
        if has_g:
            return "gemini"
        if has_o:
            return "openai"
    # If skip_engine filtered out the only configured key, still return what exists
    if okey and len(okey) > 15 and not (gkey and len(gkey) > 15):
        return "openai"
    return "gemini"

def get_local_llm_cfg() -> dict:
    cfg = load_api_keys()
    return {
        "provider": str(cfg.get("llm_provider", "ollama") or "ollama").strip().lower(),
        "url":      str(cfg.get("llm_url", "http://localhost:11434") or "http://localhost:11434").rstrip("/"),
        "model":    str(cfg.get("llm_model", "llama3.2") or "llama3.2").strip(),
    }

# ── Phase 2b: Local Voice Loop ────────────────────────────────────────────
# Flow/Dictate hotkeys + local STT/TTS toggles. Graceful degrade when deps missing.

def get_local_stt_enabled() -> bool:
    return bool(load_api_keys().get("local_stt_enabled", False))

def save_local_stt_enabled(enabled: bool) -> None:
    _save_flag("local_stt_enabled", bool(enabled))

def get_local_tts_enabled() -> bool:
    return bool(load_api_keys().get("local_tts_enabled", False))

def save_local_tts_enabled(enabled: bool) -> None:
    _save_flag("local_tts_enabled", bool(enabled))

def get_flow_hotkey() -> str:
    return str(load_api_keys().get("flow_hotkey", "ctrl+ctrl") or "ctrl+ctrl").strip().lower()

def get_dictate_hotkey() -> str:
    return str(load_api_keys().get("dictate_hotkey", "ctrl+shift+d") or "ctrl+shift+d").strip().lower()

# ── Phase 4: Accounts & Remote ────────────────────────────────────────────
def get_telegram_cfg() -> dict:
    cfg=load_api_keys()
    return {
        "bot_token": str(cfg.get("telegram_bot_token","") or "").strip(),
        "allowed": cfg.get("telegram_allowed_users", []),
        "pairing_code": str(cfg.get("telegram_pairing_code","") or "").strip(),
    }
def save_telegram_token(token: str):
    _patch_config(telegram_bot_token=str(token or "").strip())
def get_composio_key() -> str:
    return str(load_api_keys().get("composio_api_key","") or "").strip()
def save_composio_key(k: str):
    _patch_config(composio_api_key=str(k or "").strip())
def get_relay_enabled() -> bool:
    return bool(load_api_keys().get("relay_enabled", False))
def save_relay_enabled(v: bool):
    _save_flag("relay_enabled", bool(v))
