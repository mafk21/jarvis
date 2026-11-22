"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  Mic,
  MicOff,
  Minimize2,
  Pause,
  Play,
  Send,
  Sliders,
  Square,
  Terminal,
  Scan,
  ShieldAlert,
  ShieldCheck,
  Brain,
  Code2,
  ExternalLink,
  KeyRound,
  Link2,
  Sparkles,
  Volume2,
  X,
  Zap,
} from "lucide-react";
import AutomationsModal from "./AutomationsModal";
import BackgroundCornerDock from "./BackgroundCornerDock";
import BrainModal from "./BrainModal";
import DevWorkspaceModal from "./DevWorkspaceModal";
import HudSocialModal from "./HudSocialModal";
import HudVideoModal from "./HudVideoModal";
import IntegrationsModal from "./IntegrationsModal";
import SecurityModal from "./SecurityModal";
import StudioModal from "./StudioModal";
import TasteModal from "./TasteModal";
import SystemDoctorModal from "./SystemDoctorModal";
import { useJarvis } from "./JarvisBridge";
import { PERSONA_THEMES, type PersonaMode } from "./theme";
import { ActivityTimelineHud } from "./WorkerOrbsLayer";

const RED = "#ff5b79";
const GREEN = "#34d399";
const WARN_AMBER = "#f5a623";

export default function JarvisHudOverlays() {
  const {
    connected,
    integrationsReady,
    integrations,
    privacy,
    desktopShortcut,
    updateDesktopShortcut,
    tasteProfile,
    setTasteModalOpen,
    brainCounts,
    aiProviders,
    persona,
    activePersona,
    theme,
    personaChosen,
    assistantName,
    orbState,
    rawState,
    muted,
    paused,
    offline,
    offlineReason,
    voice,
    voices,
    femaleVoices,
    bargeEnabled,
    gracePeriod,
    inputs,
    outputs,
    currentInput,
    currentOutput,
    logs,
    confirm,
    content,
    consoleOpen,
    settingsOpen,
    setupOpen,
    integrationsModalOpen,
    brainModalOpen,
    studioModalOpen,
    automationsModalOpen,
    devModalOpen,
    securityModalOpen,
    personaModalOpen,
    activityOpen,
    backgroundMode,
    backgroundSurface,
    startupView,
    saveStartupView,
    setConsoleOpen,
    setSettingsOpen,
    setSetupOpen,
    setIntegrationsModalOpen,
    setBrainModalOpen,
    setStudioModalOpen,
    setAutomationsModalOpen,
    setDevModalOpen,
    setSecurityModalOpen,
    setPersonaModalOpen,
    setActivityOpen,
    setPreviewPersona,
    choosePersona,
    updatePrivacy,
    clearContent,
    sendText,
    toggleMute,
    togglePause,
    retryConnection,
    interrupt,
    stopAll,
    captureRegion,
    setVoice,
    setDevices,
    setBarge,
    setGrace,
    resolveConfirm,
    saveApiKey,
    enterBackgroundMode,
  } = useJarvis();

  const PRIMARY = theme.primary;
  const SECONDARY = theme.secondary;
  const isMale = activePersona === "male";

  const [cmd, setCmd] = useState("");
  const [maleMenuOpen, setMaleMenuOpen] = useState(false);
  const [maleContentExpanded, setMaleContentExpanded] = useState(false);
  const [openaiKeyInput, setOpenaiKeyInput] = useState("");
  const [geminiKeyInput, setGeminiKeyInput] = useState("");
  const [anthropicKeyInput, setAnthropicKeyInput] = useState("");
  const [anthropicModelInput, setAnthropicModelInput] = useState("claude-sonnet-4-5");
  const [shortcutBusy, setShortcutBusy] = useState(false);
  const [shortcutFeedback, setShortcutFeedback] = useState("");
  const [systemDoctorOpen, setSystemDoctorOpen] = useState(false);
  const [providerPref, setProviderPref] = useState<string>("auto");
  const [openaiModelInput, setOpenaiModelInput] = useState<string>("gpt-4o");
  const [openaiRealtimeInput, setOpenaiRealtimeInput] = useState<string>(
    "gpt-4o-realtime-preview"
  );
  const [savingKey, setSavingKey] = useState(false);
  const [keyError, setKeyError] = useState("");
  const [draftPersona, setDraftPersona] = useState<PersonaMode>("male");
  const [activatingPersona, setActivatingPersona] = useState(false);
  const [consoleWidth, setConsoleWidth] = useState<number>(390);
  const resizingRef = useRef<boolean>(false);
  const logEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      const saved = Number(window.localStorage.getItem("jarvis_console_width"));
      if (saved >= 320 && saved <= 860) setConsoleWidth(saved);
    } catch {}
  }, []);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!resizingRef.current) return;
      const next = Math.max(320, Math.min(860, window.innerWidth - e.clientX - 16));
      setConsoleWidth(next);
      try {
        window.localStorage.setItem("jarvis_console_width", String(next));
      } catch {}
    };
    const onUp = () => {
      resizingRef.current = false;
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  const activePersonaRef = useRef<PersonaMode>(activePersona);
  activePersonaRef.current = activePersona;

  useEffect(() => {
    if (personaModalOpen) {
      setDraftPersona(activePersonaRef.current);
      setPreviewPersona(activePersonaRef.current);
    } else if (!setupOpen && !integrationsModalOpen) {
      setPreviewPersona(null);
    }
  }, [personaModalOpen, setupOpen, integrationsModalOpen, setPreviewPersona]);

  useEffect(() => {
    setMaleContentExpanded(false);
  }, [content?.title, content?.text]);

  useEffect(() => {
    if (consoleOpen) {
      logEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs, consoleOpen]);

  const onSubmitCmd = (e: React.FormEvent) => {
    e.preventDefault();
    if (!cmd.trim()) return;
    sendText(cmd);
    setCmd("");
  };

  useEffect(() => {
    if (setupOpen) {
      setProviderPref(aiProviders.provider || "auto");
      setAnthropicModelInput(aiProviders.anthropicModel || "claude-sonnet-4-5");
      setOpenaiModelInput(aiProviders.openaiModel || "gpt-4o");
      setOpenaiRealtimeInput(
        aiProviders.openaiRealtimeModel || "gpt-4o-realtime-preview"
      );
      setKeyError("");
    }
  }, [
    setupOpen,
    aiProviders.provider,
    aiProviders.anthropicModel,
    aiProviders.openaiModel,
    aiProviders.openaiRealtimeModel,
  ]);

  const onSaveKey = async (e: React.FormEvent) => {
    e.preventDefault();
    const oClean = openaiKeyInput.trim();
    const gClean = geminiKeyInput.trim();
    const aClean = anthropicKeyInput.trim();
    const hasAlready = aiProviders.hasOpenaiKey || aiProviders.hasGeminiKey || aiProviders.hasAnthropicKey;
    if (oClean.length < 15 && gClean.length < 15 && aClean.length < 15 && !hasAlready) {
      setKeyError(
        "Enter a Claude (sk-ant-...), OpenAI (sk-...), or Gemini (AIza...) API key."
      );
      return;
    }
    setSavingKey(true);
    setKeyError("");
    const ok = await saveApiKey({
      openai_key: oClean || undefined,
      gemini_key: gClean || undefined,
      anthropic_key: aClean || undefined,
      provider: providerPref,
      anthropic_model: anthropicModelInput,
      openai_model: openaiModelInput,
      openai_realtime_model: openaiRealtimeInput,
    });
    setSavingKey(false);
    if (!ok) {
      setKeyError("Could not save API keys — check that JARVIS is running.");
    } else {
      setOpenaiKeyInput("");
      setGeminiKeyInput("");
      setAnthropicKeyInput("");
    }
  };

  const selectDraft = (p: PersonaMode) => {
    setDraftPersona(p);
    setPreviewPersona(p);
  };

  const onActivatePersona = async (target?: PersonaMode) => {
    const chosen = target ?? draftPersona;
    setActivatingPersona(true);
    await choosePersona(chosen);
    setActivatingPersona(false);
  };

  const pillBase: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
    fontFamily: "var(--font-mono)",
    fontSize: "0.64rem",
    letterSpacing: "0.18em",
    textTransform: "uppercase",
    color: "rgba(240,237,232,0.84)",
    border: "1px solid rgba(240,237,232,0.18)",
    borderRadius: 20,
    padding: "7px 13px",
    background: theme.barBg,
    backdropFilter: "blur(10px)",
    cursor: "pointer",
    transition: "all 0.2s",
  };

  const dotColor = offline
    ? WARN_AMBER
    : muted
    ? RED
    : paused
    ? SECONDARY
    : orbState === "speaking"
    ? SECONDARY
    : connected
    ? GREEN
    : PRIMARY;

  const statusText = offline
    ? `OFFLINE${offlineReason ? ` · ${offlineReason.slice(0, 42)}${offlineReason.length > 42 ? "…" : ""}` : ""}`
    : muted
    ? "MIC MUTED"
    : paused
    ? "PAUSED"
    : connected
    ? rawState || "ONLINE"
    : "PREVIEW";

  if (backgroundMode) {
    return <BackgroundCornerDock />;
  }

  return (
    <>
      <ActivityTimelineHud />
      <HudVideoModal />
      <HudSocialModal />
      <StudioModal />
      <AutomationsModal />
      <DevWorkspaceModal />
      <SecurityModal />
      <TasteModal />
      {/* ── Unified Sleek Top-Right HUD Controls (Male Cyan & Female Rose-Orchid) ── */}
      <div
        style={{
          position: "fixed",
          top: 14,
          right: "clamp(14px, 2.2vw, 28px)",
          zIndex: 42,
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        {content && (
          <button
            type="button"
            onClick={() => setMaleContentExpanded((o) => !o)}
            title="View latest tool / search output"
            style={{
              ...pillBase,
              padding: "5px 10px",
              fontSize: "0.58rem",
              background: maleContentExpanded ? `${PRIMARY}22` : theme.barBg,
              borderColor: `${PRIMARY}48`,
              color: PRIMARY,
            }}
          >
            <ExternalLink size={11} />
            OUTPUT
          </button>
        )}

        <button
          type="button"
          onClick={toggleMute}
          title={muted ? "Click to unmute microphone" : "Click to mute microphone"}
          style={{
            ...pillBase,
            padding: "5px 11px",
            fontSize: "0.58rem",
            background: theme.barBg,
            borderColor: muted ? `${RED}44` : `${PRIMARY}2a`,
            color: "rgba(240, 237, 232, 0.86)",
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: dotColor,
              boxShadow: `0 0 8px ${dotColor}`,
            }}
          />
          {statusText}
        </button>

        {offline && (
          <button
            type="button"
            onClick={() => retryConnection()}
            title="Retry the live AI connection now"
            style={{
              ...pillBase,
              padding: "5px 10px",
              fontSize: "0.58rem",
              background: `${WARN_AMBER}18`,
              borderColor: `${WARN_AMBER}66`,
              color: WARN_AMBER,
            }}
          >
            RETRY CONNECTION
          </button>
        )}

        <button
          type="button"
          onClick={() => setPersonaModalOpen(true)}
          title="Switch between Male and Female interface editions"
          style={{
            ...pillBase,
            padding: "5px 10px",
            fontSize: "0.58rem",
            background: theme.barBg,
            borderColor: `${PRIMARY}38`,
            color: PRIMARY,
          }}
        >
          {activePersona === "female" ? "♀ FEMALE" : "♂ MALE"}
        </button>

        <button
          type="button"
          onClick={() => setConsoleOpen((o) => !o)}
          title="Toggle live transcript console"
          style={{
            ...pillBase,
            padding: "5px 10px",
            fontSize: "0.58rem",
            background: consoleOpen ? `${PRIMARY}20` : theme.barBg,
            borderColor: consoleOpen ? `${PRIMARY}55` : `${PRIMARY}26`,
            color: consoleOpen ? PRIMARY : "rgba(240, 237, 232, 0.80)",
          }}
        >
          <Terminal size={11} />
          {logs.length > 0 ? logs.length : "LOG"}
        </button>

        <button
          type="button"
          data-testid="enter-bg-mode-btn"
          onClick={() => enterBackgroundMode()}
          title={`Background Mode — uses the ${backgroundSurface === "notch" ? "top-centre notch" : "bottom-right corner dock"} while keeping live voice & mic active`}
          style={{
            ...pillBase,
            padding: "5px 10px",
            fontSize: "0.58rem",
            background: theme.barBg,
            borderColor: `${PRIMARY}38`,
            color: "rgba(240, 237, 232, 0.86)",
          }}
        >
          <Minimize2 size={11} />
          BG
        </button>

        <button
          type="button"
          onClick={() => setMaleMenuOpen((o) => !o)}
          aria-label="Open JARVIS workspace menu"
          style={{
            ...pillBase,
            padding: "5px 11px",
            fontSize: "0.58rem",
            background: maleMenuOpen ? `${PRIMARY}20` : theme.barBg,
            borderColor: maleMenuOpen ? `${PRIMARY}55` : `${PRIMARY}28`,
            color: maleMenuOpen ? PRIMARY : "rgba(240, 237, 232, 0.84)",
          }}
        >
          <Sliders size={11} />
          HUD ▾
        </button>

        {maleMenuOpen && (
          <div
            role="menu"
            aria-label="JARVIS HUD workspaces"
            style={{
              position: "absolute",
              top: 38,
              right: 0,
              width: 236,
              padding: "10px 8px",
              borderRadius: 15,
              background: theme.drawerBg,
              border: `1px solid ${PRIMARY}36`,
              backdropFilter: "blur(22px)",
              boxShadow: "0 18px 48px rgba(0, 0, 0, 0.74)",
              display: "flex",
              flexDirection: "column",
              gap: 3,
            }}
          >
            {[
              {
                section: "INTELLIGENCE",
                items: [
                  {
                    label: `Brain & Memory${
                      brainCounts.memories + brainCounts.files + brainCounts.outputs > 0
                        ? ` (${brainCounts.memories + brainCounts.files + brainCounts.outputs})`
                        : ""
                    }`,
                    icon: <Brain size={12} />,
                    active: brainModalOpen,
                    run: () => setBrainModalOpen(true),
                  },
                  {
                    label: "Companions & Studio",
                    icon: <Sparkles size={12} />,
                    active: studioModalOpen,
                    run: () => setStudioModalOpen(true),
                  },
                ],
              },
              {
                section: "WORKSPACE & OPS",
                items: [
                  {
                    label: "Automations & MCP",
                    icon: <Zap size={12} />,
                    active: automationsModalOpen,
                    run: () => setAutomationsModalOpen(true),
                  },
                  {
                    label: "Dev Workspace",
                    icon: <Code2 size={12} />,
                    active: devModalOpen,
                    run: () => setDevModalOpen(true),
                  },
                  {
                    label: "Worker Activity",
                    icon: <Play size={12} />,
                    active: activityOpen,
                    run: () => setActivityOpen((o) => !o),
                  },
                  {
                    label: `Integrations${
                      integrations.connected_count > 0
                        ? ` (${integrations.connected_count})`
                        : ""
                    }`,
                    icon: <Link2 size={12} />,
                    active: integrationsModalOpen,
                    run: () => setIntegrationsModalOpen(true),
                  },
                ],
              },
              {
                section: "SYSTEM",
                items: [
                  {
                    label: `Launch View · ${startupView.view === "notch" ? "Notch" : "Interface"}`,
                    icon: <Minimize2 size={12} />,
                    active: startupView.view === "notch",
                    run: () => saveStartupView(startupView.view === "notch" ? "interface" : "notch"),
                  },
                  {
                    label: "Enter Background Mode",
                    icon: <Minimize2 size={12} />,
                    active: backgroundMode,
                    run: () => enterBackgroundMode(),
                  },
                  {
                    label: "Security & Vault",
                    icon: <ShieldCheck size={12} />,
                    active: securityModalOpen,
                    run: () => setSecurityModalOpen(true),
                  },
                  {
                    label: "Audio & HUD Settings",
                    icon: <Sliders size={12} />,
                    active: settingsOpen,
                    run: () => setSettingsOpen(true),
                  },
                ],
              },
            ].map((group, gi) => (
              <div
                key={group.section}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 2,
                  marginTop: gi > 0 ? 6 : 0,
                  paddingTop: gi > 0 ? 6 : 0,
                  borderTop: gi > 0 ? "1px solid rgba(255,255,255,0.06)" : "none",
                }}
              >
                <div
                  style={{
                    padding: "2px 10px 3px",
                    fontFamily: "var(--font-mono)",
                    fontSize: 8.5,
                    letterSpacing: "0.2em",
                    color: `${PRIMARY}99`,
                  }}
                >
                  {group.section}
                </div>
                {group.items.map((item) => (
                  <button
                    key={item.label}
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      item.run();
                      setMaleMenuOpen(false);
                    }}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 9,
                      width: "100%",
                      padding: "7px 10px",
                      borderRadius: 9,
                      border: "none",
                      background: item.active ? `${PRIMARY}22` : "transparent",
                      color: item.active ? PRIMARY : "rgba(240, 237, 232, 0.88)",
                      fontFamily: "var(--font-mono)",
                      fontSize: 10,
                      letterSpacing: "0.07em",
                      textAlign: "left",
                      cursor: "pointer",
                    }}
                  >
                    <span style={{ color: PRIMARY, display: "flex" }}>{item.icon}</span>
                    <span>{item.label}</span>
                  </button>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Unforgeable Confirmation Banner (core/confirm.py) ── */}
      {confirm && (
        <div
          role="alertdialog"
          aria-label="Action confirmation required"
          style={{
            position: "fixed",
            top: 66,
            left: "50%",
            transform: "translateX(-50%)",
            width: "min(520px, 92vw)",
            zIndex: 85,
            background: "rgba(12, 8, 4, 0.94)",
            border: `1px solid ${WARN_AMBER}88`,
            borderRadius: 14,
            padding: "14px 18px",
            boxShadow: `0 0 36px ${WARN_AMBER}2e, 0 12px 36px rgba(0,0,0,0.75)`,
            backdropFilter: "blur(20px)",
            display: "flex",
            alignItems: "center",
            gap: 14,
          }}
        >
          <ShieldAlert size={22} style={{ color: WARN_AMBER, flexShrink: 0 }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                letterSpacing: "0.14em",
                color: WARN_AMBER,
                textTransform: "uppercase",
              }}
            >
              CONFIRMATION REQUIRED · {confirm.title}
            </div>
            {confirm.detail && (
              <div
                style={{
                  fontSize: 12,
                  color: "rgba(240,237,232,0.78)",
                  marginTop: 3,
                  maxHeight: 180,
                  overflowY: "auto",
                  whiteSpace: "pre-wrap",
                  overflowWrap: "anywhere",
                }}
              >
                {confirm.detail}
              </div>
            )}
          </div>
          <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
            <button
              type="button"
              onClick={() => resolveConfirm(false)}
              style={{
                ...pillBase,
                padding: "7px 12px",
                borderColor: "rgba(255,255,255,0.22)",
              }}
            >
              CANCEL
            </button>
            <button
              type="button"
              onClick={() => resolveConfirm(true)}
              style={{
                ...pillBase,
                padding: "7px 14px",
                background: `${WARN_AMBER}26`,
                borderColor: WARN_AMBER,
                color: "#ffe4a3",
              }}
            >
              CONFIRM
            </button>
          </div>
        </div>
      )}

      {/* ── Rich Content Card (show_content from tools/skills) ── */}
      {content && maleContentExpanded && (
        <div
          role="dialog"
          aria-label={content.title || "JARVIS output"}
          style={{
            position: "fixed",
            left: 20,
            bottom: 72,
            width: "min(440px, 92vw)",
            maxHeight: "52vh",
            zIndex: 55,
            background: theme.panelBg,
            border: `1px solid ${PRIMARY}3a`,
            borderRadius: 14,
            backdropFilter: "blur(22px)",
            boxShadow: `0 0 32px ${PRIMARY}18, 0 10px 30px rgba(0,0,0,0.65)`,
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              padding: "10px 14px",
              borderBottom: `1px solid ${PRIMARY}22`,
            }}
          >
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10.5,
                letterSpacing: "0.16em",
                color: PRIMARY,
                textTransform: "uppercase",
                flex: 1,
              }}
            >
              {content.title || assistantName}
            </span>
            <button
              type="button"
              onClick={clearContent}
              aria-label="Close content card"
              style={{
                background: "none",
                border: "none",
                color: "rgba(255,255,255,0.45)",
                cursor: "pointer",
                padding: 2,
              }}
            >
              <X size={15} />
            </button>
          </div>
          <pre
            style={{
              margin: 0,
              padding: "12px 14px",
              overflowY: "auto",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              fontFamily: "inherit",
              fontSize: 12,
              lineHeight: 1.55,
              color: "rgba(240,237,232,0.85)",
            }}
          >
            {content.text}
          </pre>
        </div>
      )}

      {/* ── Collapsible & Resizable Right-Side Live Console Drawer ── */}
      {consoleOpen && (
        <aside
          aria-label="JARVIS live transcript console"
          style={{
            position: "fixed",
            top: 56,
            right: 16,
            bottom: 68,
            width: `min(${consoleWidth}px, 92vw)`,
            zIndex: 50,
            background: theme.drawerBg,
            border: `1px solid ${PRIMARY}33`,
            borderRadius: 16,
            backdropFilter: "blur(24px)",
            boxShadow: "0 12px 44px rgba(0,0,0,0.65)",
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
          }}
        >
          {/* Left-edge drag resize grip */}
          <div
            role="separator"
            aria-orientation="vertical"
            title="Drag to resize console"
            onMouseDown={(e) => {
              e.preventDefault();
              resizingRef.current = true;
            }}
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              bottom: 0,
              width: 6,
              cursor: "ew-resize",
              zIndex: 2,
            }}
          />

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "12px 16px",
              borderBottom: `1px solid ${PRIMARY}22`,
            }}
          >
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                letterSpacing: "0.24em",
                color: PRIMARY,
                flex: 1,
              }}
            >
              {assistantName.toUpperCase()} · LIVE STREAM
            </span>
            <button
              type="button"
              onClick={() => {
                window.open(
                  "/?view=console",
                  "jarvis_console",
                  "width=580,height=880,noopener"
                );
              }}
              title="Pop out console to secondary monitor"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                padding: "3px 8px",
                borderRadius: 999,
                border: `1px solid ${PRIMARY}44`,
                background: `${PRIMARY}14`,
                color: PRIMARY,
                fontFamily: "var(--font-mono)",
                fontSize: 8.5,
                letterSpacing: "0.1em",
                cursor: "pointer",
              }}
            >
              <ExternalLink size={10} />
              POP OUT
            </button>
            <button
              type="button"
              onClick={() => setConsoleOpen(false)}
              aria-label="Close console"
              style={{
                background: "none",
                border: "none",
                color: "rgba(255,255,255,0.45)",
                cursor: "pointer",
              }}
            >
              <X size={16} />
            </button>
          </div>

          <div
            style={{
              flex: 1,
              overflowY: "auto",
              padding: "12px 14px",
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            {logs.length === 0 ? (
              <div
                style={{
                  fontSize: 11.5,
                  color: "rgba(240,237,232,0.4)",
                  textAlign: "center",
                  marginTop: 32,
                }}
              >
                Speak naturally or type below — live transcripts and tool actions
                appear here.
              </div>
            ) : (
              logs.map((entry) => {
                const accent =
                  entry.role === "user"
                    ? PRIMARY
                    : entry.role === "jarvis"
                    ? SECONDARY
                    : "rgba(160,185,205,0.65)";
                return (
                  <div
                    key={entry.id}
                    style={{
                      padding: "8px 11px",
                      borderRadius: 10,
                      background:
                        entry.role === "user"
                          ? theme.primarySoftBg
                          : entry.role === "jarvis"
                          ? theme.secondarySoftBg
                          : "rgba(255,255,255,0.03)",
                      borderLeft: `2px solid ${accent}`,
                      fontSize: 12,
                      lineHeight: 1.5,
                      color:
                        entry.role === "sys"
                          ? "rgba(200,215,228,0.68)"
                          : "rgba(240,237,232,0.92)",
                      wordBreak: "break-word",
                    }}
                  >
                    {entry.line}
                  </div>
                );
              })
            )}
            <div ref={logEndRef} />
          </div>
        </aside>
      )}

      {/* ── Bottom Slim Glass Command Bar ── */}
      <form
        onSubmit={onSubmitCmd}
        style={{
          position: "fixed",
          left: "50%",
          bottom: 12,
          transform: "translateX(-50%)",
          width: "min(510px, 88vw)",
          zIndex: 40,
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "4px 7px",
          borderRadius: 999,
          background: isMale ? "rgba(3, 8, 15, 0.48)" : "rgba(14, 5, 16, 0.54)",
          border: `1px solid ${PRIMARY}28`,
          backdropFilter: "blur(16px)",
          boxShadow: "0 6px 24px rgba(0,0,0,0.44)",
          transition: "border-color 0.35s ease, background 0.35s ease",
        }}
      >
        <button
          type="button"
          onClick={toggleMute}
          title={muted ? "Unmute microphone" : "Mute microphone"}
          style={{
            width: 32,
            height: 32,
            borderRadius: "50%",
            border: `1px solid ${muted ? `${RED}66` : `${PRIMARY}44`}`,
            background: muted ? `${RED}1f` : `${PRIMARY}14`,
            color: muted ? RED : PRIMARY,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            cursor: "pointer",
            flexShrink: 0,
          }}
        >
          {muted ? <MicOff size={15} /> : <Mic size={15} />}
        </button>

        <button
          type="button"
          onClick={togglePause}
          title={paused ? "Resume listening" : "Pause listening"}
          style={{
            width: 32,
            height: 32,
            borderRadius: "50%",
            border: `1px solid ${paused ? `${SECONDARY}66` : "rgba(255,255,255,0.14)"}`,
            background: paused ? `${SECONDARY}22` : "transparent",
            color: paused ? SECONDARY : "rgba(240,237,232,0.7)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            cursor: "pointer",
            flexShrink: 0,
          }}
        >
          {paused ? <Play size={14} /> : <Pause size={14} />}
        </button>

        <input
          type="text"
          value={cmd}
          onChange={(e) => setCmd(e.target.value)}
          placeholder={`Message ${assistantName}, or speak naturally…`}
          aria-label={`Command input for ${assistantName}`}
          style={{
            flex: 1,
            minWidth: 0,
            background: "transparent",
            border: "none",
            outline: "none",
            color: "#f0ede8",
            fontSize: 12.5,
            padding: "6px 8px",
            fontFamily: "inherit",
          }}
        />

        {orbState === "speaking" && (
          <button
            type="button"
            onClick={interrupt}
            title="Interrupt speech"
            style={{
              height: 30,
              padding: "0 11px",
              borderRadius: 999,
              border: `1px solid ${SECONDARY}66`,
              background: `${SECONDARY}22`,
              color: SECONDARY,
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              letterSpacing: "0.12em",
              display: "flex",
              alignItems: "center",
              gap: 5,
              cursor: "pointer",
              flexShrink: 0,
            }}
          >
            <Square size={11} />
            STOP
          </button>
        )}

        <button
          type="button"
          onClick={captureRegion}
          title="Capture screen region for vision"
          style={{
            width: 32,
            height: 32,
            borderRadius: "50%",
            border: "1px solid rgba(255,255,255,0.14)",
            background: "transparent",
            color: "rgba(240,237,232,0.72)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            cursor: "pointer",
            flexShrink: 0,
          }}
        >
          <Scan size={14} />
        </button>

        <button
          type="submit"
          title="Send command"
          style={{
            width: 32,
            height: 32,
            borderRadius: "50%",
            border: `1px solid ${PRIMARY}55`,
            background: `${PRIMARY}1c`,
            color: PRIMARY,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            cursor: "pointer",
            flexShrink: 0,
          }}
        >
          <Send size={14} />
        </button>
      </form>

      {systemDoctorOpen && (
        <SystemDoctorModal
          primary={PRIMARY}
          panelBg={theme.panelBg}
          onClose={() => setSystemDoctorOpen(false)}
        />
      )}

      {/* ── Settings Modal (Edition, Voice, Mic/Speaker, Barge-In, API Key) ── */}
      {settingsOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="JARVIS HUD Settings"
          onClick={() => setSettingsOpen(false)}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 75,
            background: "rgba(2, 6, 12, 0.72)",
            backdropFilter: "blur(10px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 16,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: "min(450px, 94vw)",
              background: theme.panelBg,
              border: `1px solid ${PRIMARY}44`,
              borderRadius: 18,
              padding: "20px 22px",
              boxShadow: `0 0 44px ${PRIMARY}22, 0 16px 48px rgba(0,0,0,0.8)`,
              display: "flex",
              flexDirection: "column",
              gap: 16,
            }}
          >
            <div style={{ display: "flex", alignItems: "center" }}>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                  letterSpacing: "0.24em",
                  color: PRIMARY,
                  flex: 1,
                }}
              >
                {assistantName.toUpperCase()} · SYSTEM CONTROLS
              </span>
              <button
                type="button"
                onClick={() => setSettingsOpen(false)}
                style={{
                  background: "none",
                  border: "none",
                  color: "rgba(255,255,255,0.5)",
                  cursor: "pointer",
                }}
              >
                <X size={18} />
              </button>
            </div>

            {/* Interface Edition (Male / Female) */}
            <div>
              <div
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 9.5,
                  letterSpacing: "0.16em",
                  color: "rgba(240,237,232,0.55)",
                  marginBottom: 8,
                }}
              >
                INTERFACE EDITION (COLORS + VOICE)
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                {(["male", "female"] as const).map((pKey) => {
                  const pTheme = PERSONA_THEMES[pKey];
                  const active = persona === pKey;
                  return (
                    <button
                      key={pKey}
                      type="button"
                      onClick={() => choosePersona(pKey)}
                      style={{
                        padding: "9px 12px",
                        borderRadius: 12,
                        border: `1px solid ${
                          active ? pTheme.primary : "rgba(255,255,255,0.14)"
                        }`,
                        background: active
                          ? `${pTheme.primary}20`
                          : "rgba(255,255,255,0.03)",
                        color: active ? "#ffffff" : "rgba(240,237,232,0.72)",
                        cursor: "pointer",
                        textAlign: "left",
                        transition: "all 0.2s",
                      }}
                    >
                      <div
                        style={{
                          fontFamily: "var(--font-mono)",
                          fontSize: 10.5,
                          letterSpacing: "0.12em",
                          color: pTheme.primary,
                          fontWeight: 600,
                        }}
                      >
                        {pKey === "female" ? "♀ FEMALE" : "♂ MALE"}
                      </div>
                      <div
                        style={{
                          fontSize: 10.5,
                          color: "rgba(240,237,232,0.62)",
                          marginTop: 2,
                        }}
                      >
                        {pTheme.voiceHint}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Voice selector */}
            <div>
              <div
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 9.5,
                  letterSpacing: "0.16em",
                  color: "rgba(240,237,232,0.55)",
                  marginBottom: 8,
                }}
              >
                ASSISTANT VOICE
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {voices.map((v) => {
                  const isFemVoice = femaleVoices.includes(v);
                  return (
                    <button
                      key={v}
                      type="button"
                      onClick={() => setVoice(v)}
                      style={{
                        padding: "6px 12px",
                        borderRadius: 16,
                        border: `1px solid ${
                          voice === v ? PRIMARY : "rgba(255,255,255,0.15)"
                        }`,
                        background: voice === v ? `${PRIMARY}22` : "transparent",
                        color: voice === v ? PRIMARY : "rgba(240,237,232,0.75)",
                        fontSize: 11.5,
                        cursor: "pointer",
                      }}
                    >
                      {v} {isFemVoice ? "♀" : "♂"}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Microphone & Speaker pickers */}
            <div style={{ display: "grid", gap: 10 }}>
              <label style={{ display: "grid", gap: 5 }}>
                <span
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 9.5,
                    letterSpacing: "0.16em",
                    color: "rgba(240,237,232,0.55)",
                  }}
                >
                  MICROPHONE INPUT
                </span>
                <select
                  value={currentInput}
                  onChange={(e) => setDevices(e.target.value, currentOutput)}
                  style={{
                    background: theme.inputBg,
                    color: "#f0ede8",
                    border: `1px solid ${theme.primaryBorder}`,
                    borderRadius: 8,
                    padding: "8px 10px",
                    fontSize: 12,
                  }}
                >
                  <option value="">System default</option>
                  {inputs
                    .filter((n) => n && n !== "System default")
                    .map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                </select>
              </label>

              <label style={{ display: "grid", gap: 5 }}>
                <span
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 9.5,
                    letterSpacing: "0.16em",
                    color: "rgba(240,237,232,0.55)",
                  }}
                >
                  SPEAKER OUTPUT
                </span>
                <select
                  value={currentOutput}
                  onChange={(e) => setDevices(currentInput, e.target.value)}
                  style={{
                    background: theme.inputBg,
                    color: "#f0ede8",
                    border: `1px solid ${theme.primaryBorder}`,
                    borderRadius: 8,
                    padding: "8px 10px",
                    fontSize: 12,
                  }}
                >
                  <option value="">System default</option>
                  {outputs
                    .filter((n) => n && n !== "System default")
                    .map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                </select>
              </label>
            </div>

            {/* Barge-in & Grace period */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
              }}
            >
              <button
                type="button"
                onClick={() => setBarge(!bargeEnabled)}
                style={{
                  ...pillBase,
                  borderColor: bargeEnabled ? `${GREEN}66` : "rgba(255,255,255,0.2)",
                  color: bargeEnabled ? GREEN : "rgba(240,237,232,0.65)",
                }}
              >
                BARGE-IN: {bargeEnabled ? "ON" : "OFF"}
              </button>

              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  color: "rgba(240,237,232,0.65)",
                }}
              >
                GRACE (S)
                <input
                  type="number"
                  min={2}
                  max={30}
                  value={gracePeriod}
                  onChange={(e) => setGrace(Number(e.target.value) || 8)}
                  style={{
                    width: 54,
                    background: theme.inputBg,
                    color: "#f0ede8",
                    border: `1px solid ${theme.primaryBorder}`,
                    borderRadius: 6,
                    padding: "5px 7px",
                    fontSize: 12,
                  }}
                />
              </label>
            </div>

            {/* Privacy Tier Toggles */}
            <div>
              <div
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 9.5,
                  letterSpacing: "0.16em",
                  color: "rgba(240,237,232,0.55)",
                  marginBottom: 8,
                }}
              >
                BRAIN & PRIVACY GOVERNANCE
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                <button
                  type="button"
                  onClick={() =>
                    updatePrivacy({
                      personalization_enabled: !privacy.personalization_enabled,
                    })
                  }
                  style={{
                    ...pillBase,
                    padding: "5px 10px",
                    borderColor: privacy.personalization_enabled
                      ? `${GREEN}66`
                      : "rgba(255,255,255,0.18)",
                    color: privacy.personalization_enabled
                      ? GREEN
                      : "rgba(240,237,232,0.58)",
                  }}
                >
                  PERSONALIZATION: {privacy.personalization_enabled ? "ON" : "OFF"}
                </button>
                <button
                  type="button"
                  onClick={() =>
                    updatePrivacy({
                      adaptive_learning_enabled: !privacy.adaptive_learning_enabled,
                    })
                  }
                  style={{
                    ...pillBase,
                    padding: "5px 10px",
                    borderColor: privacy.adaptive_learning_enabled
                      ? `${GREEN}66`
                      : "rgba(255,255,255,0.18)",
                    color: privacy.adaptive_learning_enabled
                      ? GREEN
                      : "rgba(240,237,232,0.58)",
                  }}
                >
                  ADAPTIVE: {privacy.adaptive_learning_enabled ? "ON" : "OFF"}
                </button>
              </div>
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 8,
                paddingTop: 6,
                borderTop: "1px solid rgba(255,255,255,0.08)",
                flexWrap: "wrap",
              }}
            >
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <button
                  type="button"
                  onClick={() => setSystemDoctorOpen(true)}
                  style={{
                    ...pillBase,
                    borderColor: `${GREEN}66`,
                    color: GREEN,
                  }}
                >
                  <ShieldCheck size={12} />
                  SYSTEM DOCTOR
                </button>

                <button
                  type="button"
                  onClick={() => {
                    setSettingsOpen(false);
                    setBrainModalOpen(true);
                  }}
                  style={{
                    ...pillBase,
                    borderColor: `${SECONDARY}66`,
                    color: SECONDARY,
                  }}
                >
                  <Brain size={12} />
                  BRAIN
                </button>

                <button
                  type="button"
                  onClick={() => {
                    setSettingsOpen(false);
                    setSetupOpen(true);
                  }}
                  style={{
                    ...pillBase,
                    borderColor: `${GREEN}66`,
                    color: GREEN,
                  }}
                >
                  <KeyRound size={12} />
                  AI ENGINES ({(aiProviders.activeEngine || "gemini").toUpperCase()})
                </button>

                <button
                  type="button"
                  onClick={() => {
                    setSettingsOpen(false);
                    setTasteModalOpen(true);
                  }}
                  style={{
                    ...pillBase,
                    borderColor: `${SECONDARY}55`,
                    color: SECONDARY,
                  }}
                >
                  TASTE PROFILE ({tasteProfile.entry_count})
                </button>

                <button
                  type="button"
                  onClick={() => {
                    setSettingsOpen(false);
                    setIntegrationsModalOpen(true);
                  }}
                  style={{
                    ...pillBase,
                    borderColor: `${PRIMARY}55`,
                    color: PRIMARY,
                  }}
                >
                  <Link2 size={12} />
                  INTEGRATIONS
                  {integrations.connected_count > 0
                    ? ` (${integrations.connected_count})`
                    : ""}
                </button>
              </div>

              <button
                type="button"
                disabled={shortcutBusy}
                onClick={async () => {
                  setShortcutBusy(true);
                  setShortcutFeedback("");
                  const operation = desktopShortcut.exists ? "remove" : "create";
                  const ok = await updateDesktopShortcut(operation);
                  setShortcutFeedback(ok
                    ? (operation === "create" ? `Shortcut created at ${desktopShortcut.path}` : "Desktop shortcut removed.")
                    : "Could not update the shortcut. Check Desktop permissions and try again.");
                  setShortcutBusy(false);
                }}
                style={{
                  ...pillBase,
                  borderColor: `${PRIMARY}66`,
                  color: PRIMARY,
                  opacity: shortcutBusy ? 0.55 : 1,
                }}
              >
                {desktopShortcut.exists ? "REMOVE DESKTOP SHORTCUT" : "ADD DESKTOP SHORTCUT"}
              </button>
              {shortcutFeedback && (
                <div role="status" style={{
                  color: shortcutFeedback.startsWith("Could not") ? RED : PRIMARY,
                  fontSize: 11,
                  lineHeight: 1.45,
                  overflowWrap: "anywhere",
                }}>
                  {shortcutFeedback}
                </div>
              )}

              <button
                type="button"
                onClick={() => {
                  stopAll();
                  setSettingsOpen(false);
                }}
                style={{
                  ...pillBase,
                  borderColor: `${RED}66`,
                  color: RED,
                }}
              >
                <Square size={11} />
                EMERGENCY STOP
              </button>
            </div>
          </div>
        </div>
      )}

      {/* First-run desktop shortcut offer. Declining is remembered, while the
          same action remains available in Settings and through voice/text. */}
      {desktopShortcut.prompt_pending && !setupOpen && !integrationsModalOpen && !personaModalOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Create JARVIS desktop shortcut"
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 90,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 18,
            background: "rgba(2, 6, 12, 0.78)",
            backdropFilter: "blur(12px)",
          }}
        >
          <div style={{
            width: "min(430px, 94vw)",
            padding: "26px 24px",
            borderRadius: 18,
            border: `1px solid ${PRIMARY}55`,
            background: theme.panelBg,
            boxShadow: `0 0 50px ${PRIMARY}22, 0 20px 60px rgba(0,0,0,.75)`,
          }}>
            <div style={{ color: PRIMARY, fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: ".2em" }}>
              READY FOR QUICK LAUNCH
            </div>
            <h2 style={{ margin: "12px 0 8px", color: "#f0ede8", fontSize: 22 }}>
              Add JARVIS to your Desktop?
            </h2>
            <p style={{ color: "rgba(240,237,232,.68)", fontSize: 13, lineHeight: 1.6, margin: "0 0 20px" }}>
              Create a native shortcut so JARVIS launches like a real desktop app. You can always add it later from Settings or just ask JARVIS.
            </p>
            {shortcutFeedback && (
              <p role="alert" style={{ color: RED, fontSize: 12, lineHeight: 1.5, margin: "0 0 14px" }}>
                {shortcutFeedback}
              </p>
            )}
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button
                type="button"
                disabled={shortcutBusy}
                onClick={async () => {
                  setShortcutBusy(true);
                  await updateDesktopShortcut("decline");
                  setShortcutBusy(false);
                }}
                style={{ ...pillBase, color: "rgba(240,237,232,.65)" }}
              >
                NOT NOW
              </button>
              <button
                type="button"
                disabled={shortcutBusy}
                onClick={async () => {
                  setShortcutBusy(true);
                  setShortcutFeedback("");
                  const ok = await updateDesktopShortcut("create");
                  if (!ok) {
                    setShortcutFeedback("Could not create the shortcut. Check Desktop permissions and try again.");
                  }
                  setShortcutBusy(false);
                }}
                style={{ ...pillBase, color: "#061016", background: PRIMARY, borderColor: PRIMARY, fontWeight: 700 }}
              >
                {shortcutBusy ? "CREATING…" : "CREATE SHORTCUT"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── The Brain & Forever Timeline Modal ── */}
      <BrainModal />

      {/* ── Optional Integrations Onboarding / Manager Modal ── */}
      <IntegrationsModal />

      {/* ── Startup / Edition Selector Modal (Male vs Female Version) ── */}
      {personaModalOpen && !setupOpen && !integrationsModalOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Choose JARVIS Interface Edition"
          onClick={() => {
            if (personaChosen) {
              setPreviewPersona(null);
              setPersonaModalOpen(false);
            }
          }}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 88,
            background: "rgba(3, 6, 14, 0.56)",
            backdropFilter: "blur(9px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 16,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: "min(580px, 95vw)",
              background: theme.panelBg,
              border: `1px solid ${PRIMARY}55`,
              borderRadius: 22,
              padding: "26px 26px 22px",
              boxShadow: `0 0 60px ${PRIMARY}28, 0 22px 64px rgba(0,0,0,0.88)`,
              display: "flex",
              flexDirection: "column",
              gap: 18,
              transition: "border-color 0.35s ease, box-shadow 0.35s ease, background 0.35s ease",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <Sparkles size={18} style={{ color: PRIMARY }} />
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 11.5,
                  letterSpacing: "0.24em",
                  color: PRIMARY,
                  flex: 1,
                }}
              >
                {personaChosen
                  ? `${assistantName.toUpperCase()} · SWITCH INTERFACE EDITION`
                  : `${assistantName.toUpperCase()} · CHOOSE INTERFACE VERSION`}
              </span>
              {personaChosen && (
                <button
                  type="button"
                  onClick={() => {
                    setPreviewPersona(null);
                    setPersonaModalOpen(false);
                  }}
                  aria-label="Close edition selector"
                  style={{
                    background: "none",
                    border: "none",
                    color: "rgba(255,255,255,0.48)",
                    cursor: "pointer",
                  }}
                >
                  <X size={18} />
                </button>
              )}
            </div>

            <div
              style={{
                fontSize: 12.5,
                lineHeight: 1.55,
                color: "rgba(240,237,232,0.74)",
              }}
            >
              Select whether to use the <strong>Male</strong> or{" "}
              <strong>Female</strong> edition. Your choice is remembered
              automatically whenever you open {assistantName}, and you can
              switch anytime later from the top-right{" "}
              <strong>♂ / ♀</strong> button, Settings (⚙), or by voice.
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                gap: 14,
              }}
            >
              {(["male", "female"] as const).map((pKey) => {
                const pTheme = PERSONA_THEMES[pKey];
                const selected = draftPersona === pKey;
                return (
                  <div
                    key={pKey}
                    role="button"
                    tabIndex={0}
                    onMouseEnter={() => setPreviewPersona(pKey)}
                    onMouseLeave={() => setPreviewPersona(draftPersona)}
                    onClick={() => selectDraft(pKey)}
                    onDoubleClick={() => onActivatePersona(pKey)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onActivatePersona(pKey);
                      }
                    }}
                    style={{
                      borderRadius: 16,
                      padding: "16px 16px 15px",
                      background: selected
                        ? `linear-gradient(155deg, ${pTheme.primary}20 0%, ${pTheme.secondary}14 100%)`
                        : "rgba(255,255,255,0.03)",
                      border: selected
                        ? `1.5px solid ${pTheme.primary}`
                        : "1.5px solid rgba(255,255,255,0.12)",
                      boxShadow: selected
                        ? `0 0 28px ${pTheme.primary}2e`
                        : "none",
                      cursor: "pointer",
                      display: "flex",
                      flexDirection: "column",
                      gap: 10,
                      transition: "all 0.22s ease",
                    }}
                  >
                    {/* Live Mini Orb Color Swatch */}
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                      }}
                    >
                      <span
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 8,
                        }}
                      >
                        <span
                          style={{
                            width: 18,
                            height: 18,
                            borderRadius: "50%",
                            background: `radial-gradient(circle at 38% 38%, ${pTheme.primaryBright}, ${pTheme.primary})`,
                            boxShadow: `0 0 12px ${pTheme.primary}, 0 0 0 3px ${pTheme.secondary}55`,
                          }}
                        />
                        <span
                          style={{
                            fontFamily: "var(--font-mono)",
                            fontSize: 11.5,
                            letterSpacing: "0.16em",
                            color: pTheme.primary,
                            fontWeight: 700,
                          }}
                        >
                          {pKey === "female" ? "♀ FEMALE" : "♂ MALE"}
                        </span>
                      </span>

                      <span
                        style={{
                          fontFamily: "var(--font-mono)",
                          fontSize: 9,
                          letterSpacing: "0.14em",
                          color: pTheme.secondaryBright,
                          padding: "3px 7px",
                          borderRadius: 999,
                          background: `${pTheme.secondary}22`,
                          border: `1px solid ${pTheme.secondary}55`,
                        }}
                      >
                        {pTheme.badge}
                      </span>
                    </div>

                    <div
                      style={{
                        fontSize: 12,
                        lineHeight: 1.48,
                        color: "rgba(240,237,232,0.82)",
                      }}
                    >
                      {pTheme.subtitle}
                    </div>

                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        fontFamily: "var(--font-mono)",
                        fontSize: 10,
                        letterSpacing: "0.1em",
                        color: "rgba(240,237,232,0.68)",
                        marginTop: "auto",
                        paddingTop: 6,
                        borderTop: "1px solid rgba(255,255,255,0.08)",
                      }}
                    >
                      <Volume2 size={13} style={{ color: pTheme.secondary }} />
                      VOICE: {pTheme.voiceHint.toUpperCase()}
                    </div>

                    <button
                      type="button"
                      disabled={activatingPersona}
                      onClick={(e) => {
                        e.stopPropagation();
                        onActivatePersona(pKey);
                      }}
                      style={{
                        ...pillBase,
                        justifyContent: "center",
                        width: "100%",
                        padding: "9px 12px",
                        marginTop: 2,
                        background: selected
                          ? `${pTheme.primary}2c`
                          : "rgba(255,255,255,0.04)",
                        borderColor: pTheme.primary,
                        color: "#ffffff",
                        fontWeight: 600,
                      }}
                    >
                      {activatingPersona && draftPersona === pKey
                        ? "ACTIVATING..."
                        : `LAUNCH ${pTheme.shortLabel} VERSION`}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* ── First-run launch surface choice ── */}
      {!startupView.prompted && integrationsReady && personaChosen && !setupOpen && !integrationsModalOpen && !personaModalOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Choose how JARVIS opens"
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 88,
            background: "rgba(2, 6, 12, 0.84)",
            backdropFilter: "blur(14px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 16,
          }}
        >
          <div style={{
            width: "min(540px, 95vw)",
            background: theme.panelBg,
            border: `1px solid ${PRIMARY}55`,
            borderRadius: 18,
            padding: 24,
            boxShadow: `0 0 50px ${PRIMARY}24, 0 18px 50px rgba(0,0,0,0.85)`,
          }}>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.2em", color: PRIMARY }}>
              CHOOSE YOUR LAUNCH VIEW
            </div>
            <h2 style={{ margin: "12px 0 7px", fontSize: 22, color: "#f0ede8" }}>How should JARVIS open?</h2>
            <p style={{ margin: "0 0 18px", fontSize: 12.5, lineHeight: 1.55, color: "rgba(240,237,232,0.68)" }}>
              Choose the full interface or a tiny always-on-top notch. You can switch anytime from HUD ▾ under System.
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 12 }}>
              <button
                type="button"
                onClick={() => saveStartupView("interface")}
                style={{ ...pillBase, minHeight: 112, padding: 16, borderRadius: 14, display: "flex", flexDirection: "column", alignItems: "flex-start", justifyContent: "center", background: `${PRIMARY}0d`, borderColor: `${PRIMARY}44`, color: "#f0ede8" }}
              >
                <span style={{ fontSize: 15, fontWeight: 700 }}>FULL INTERFACE</span>
                <span style={{ marginTop: 7, fontSize: 11, lineHeight: 1.45, textAlign: "left", color: "rgba(240,237,232,0.62)" }}>Open directly into the complete JARVIS HUD every time.</span>
              </button>
              <button
                type="button"
                onClick={async () => {
                  await saveStartupView("notch");
                  await enterBackgroundMode();
                }}
                style={{ ...pillBase, minHeight: 112, padding: 16, borderRadius: 14, display: "flex", flexDirection: "column", alignItems: "flex-start", justifyContent: "center", background: `${SECONDARY}0d`, borderColor: `${SECONDARY}55`, color: "#f0ede8" }}
              >
                <span style={{ fontSize: 15, fontWeight: 700 }}>COMPACT NOTCH</span>
                <span style={{ marginTop: 7, fontSize: 11, lineHeight: 1.45, textAlign: "left", color: "rgba(240,237,232,0.62)" }}>Start quietly in a tiny top-centre notch with voice still active.</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── First-Boot / Reconfigure OpenAI & Gemini AI Engines Modal ── */}
      {setupOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Configure OpenAI and Gemini API Keys"
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 90,
            background: "rgba(2, 6, 12, 0.84)",
            backdropFilter: "blur(14px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 16,
          }}
        >
          <form
            onSubmit={onSaveKey}
            style={{
              width: "min(480px, 95vw)",
              background: theme.panelBg,
              border: `1px solid ${PRIMARY}55`,
              borderRadius: 18,
              padding: "24px 24px",
              boxShadow: `0 0 50px ${PRIMARY}24, 0 18px 50px rgba(0,0,0,0.85)`,
              display: "flex",
              flexDirection: "column",
              gap: 13,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <KeyRound size={18} style={{ color: PRIMARY }} />
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                  letterSpacing: "0.2em",
                  color: PRIMARY,
                  flex: 1,
                }}
              >
                {!integrationsReady
                  ? `STEP 1 OF 3 · AI ENGINES (${assistantName.toUpperCase()})`
                  : `AI ENGINES · OPENAI & GEMINI`}
              </span>
              {(["male", "female"] as PersonaMode[]).map((pKey) => {
                const pTheme = PERSONA_THEMES[pKey];
                const isAct = activePersona === pKey;
                return (
                  <button
                    key={pKey}
                    type="button"
                    onClick={() =>
                      personaChosen
                        ? choosePersona(pKey)
                        : setPreviewPersona(pKey)
                    }
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: 9,
                      letterSpacing: "0.12em",
                      padding: "3px 8px",
                      borderRadius: 999,
                      border: `1px solid ${
                        isAct ? pTheme.primary : "rgba(255,255,255,0.14)"
                      }`,
                      background: isAct ? `${pTheme.primary}22` : "transparent",
                      color: isAct ? pTheme.primary : "rgba(240,237,232,0.58)",
                      cursor: "pointer",
                    }}
                  >
                    {pKey === "female" ? "♀" : "♂"}
                  </button>
                );
              })}
              {personaChosen && (
                <button
                  type="button"
                  onClick={() => setSetupOpen(false)}
                  style={{
                    background: "none",
                    border: "none",
                    color: "rgba(255,255,255,0.45)",
                    cursor: "pointer",
                  }}
                >
                  <X size={17} />
                </button>
              )}
            </div>

            <div
              style={{
                fontSize: 12,
                lineHeight: 1.52,
                color: "rgba(240,237,232,0.75)",
              }}
            >
              Connect <strong>Claude</strong>, <strong>OpenAI</strong>, or{" "}
              <strong>Google Gemini</strong>. Claude powers high-quality text reasoning;
              realtime voice still requires OpenAI or Gemini.
            </div>

            {/* Anthropic Claude API Key */}
            <div style={{ display: "grid", gap: 5 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontFamily: "var(--font-mono)", fontSize: 9.5, letterSpacing: "0.14em", color: "rgba(240,237,232,0.7)" }}>
                <span>ANTHROPIC CLAUDE API KEY (TEXT REASONING)</span>
                {aiProviders.hasAnthropicKey && (
                  <span style={{ color: GREEN }}>✓ {aiProviders.anthropicKeyMasked || "CONFIGURED"}</span>
                )}
              </div>
              <input
                type="password"
                value={anthropicKeyInput}
                onChange={(e) => setAnthropicKeyInput(e.target.value)}
                placeholder={aiProviders.hasAnthropicKey ? "Leave blank to keep saved Claude key" : "sk-ant-..."}
                autoFocus={!aiProviders.hasAnthropicKey && !aiProviders.hasOpenaiKey && !aiProviders.hasGeminiKey}
                style={{ background: theme.inputBg, color: "#f0ede8", border: `1px solid ${SECONDARY}55`, borderRadius: 10, padding: "9px 12px", fontSize: 12.5, outline: "none", fontFamily: "var(--font-mono)" }}
              />
              <input
                type="text"
                value={anthropicModelInput}
                onChange={(e) => setAnthropicModelInput(e.target.value)}
                aria-label="Claude model ID"
                placeholder="claude-sonnet-4-5"
                style={{ background: theme.inputBg, color: "#f0ede8", border: `1px solid ${SECONDARY}33`, borderRadius: 10, padding: "8px 12px", fontSize: 11.5, outline: "none", fontFamily: "var(--font-mono)" }}
              />
            </div>

            {/* OpenAI API Key */}
            <div style={{ display: "grid", gap: 5 }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  fontFamily: "var(--font-mono)",
                  fontSize: 9.5,
                  letterSpacing: "0.14em",
                  color: "rgba(240,237,232,0.7)",
                }}
              >
                <span>OPENAI API KEY (REALTIME VOICE · GPT-4O VISION · TOOLS)</span>
                {aiProviders.hasOpenaiKey && (
                  <span style={{ color: GREEN }}>
                    ✓ {aiProviders.openaiKeyMasked || "CONFIGURED"}
                  </span>
                )}
              </div>
              <input
                type="password"
                value={openaiKeyInput}
                onChange={(e) => setOpenaiKeyInput(e.target.value)}
                placeholder={
                  aiProviders.hasOpenaiKey
                    ? "Leave blank to keep saved OpenAI key (sk-...)"
                    : "sk-proj-..."
                }
                autoFocus={!aiProviders.hasOpenaiKey && !aiProviders.hasAnthropicKey && !aiProviders.hasGeminiKey}
                style={{
                  background: theme.inputBg,
                  color: "#f0ede8",
                  border: `1px solid ${PRIMARY}44`,
                  borderRadius: 10,
                  padding: "9px 12px",
                  fontSize: 12.5,
                  outline: "none",
                  fontFamily: "var(--font-mono)",
                }}
              />
            </div>

            {/* Gemini API Key */}
            <div style={{ display: "grid", gap: 5 }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  fontFamily: "var(--font-mono)",
                  fontSize: 9.5,
                  letterSpacing: "0.14em",
                  color: "rgba(240,237,232,0.7)",
                }}
              >
                <span>GOOGLE GEMINI API KEY (OPTIONAL IF OPENAI SET)</span>
                {aiProviders.hasGeminiKey && (
                  <span style={{ color: GREEN }}>
                    ✓ {aiProviders.geminiKeyMasked || "CONFIGURED"}
                  </span>
                )}
              </div>
              <input
                type="password"
                value={geminiKeyInput}
                onChange={(e) => setGeminiKeyInput(e.target.value)}
                placeholder={
                  aiProviders.hasGeminiKey
                    ? "Leave blank to keep saved Gemini key (AIza...)"
                    : "AIzaSy..."
                }
                style={{
                  background: theme.inputBg,
                  color: "#f0ede8",
                  border: `1px solid ${PRIMARY}33`,
                  borderRadius: 10,
                  padding: "9px 12px",
                  fontSize: 12.5,
                  outline: "none",
                  fontFamily: "var(--font-mono)",
                }}
              />
            </div>

            {/* Active Engine Routing & OpenAI Model */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 8,
              }}
            >
              <label style={{ display: "grid", gap: 4 }}>
                <span
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 9,
                    letterSpacing: "0.14em",
                    color: "rgba(240,237,232,0.58)",
                  }}
                >
                  ENGINE ROUTING
                </span>
                <select
                  value={providerPref}
                  onChange={(e) => setProviderPref(e.target.value)}
                  style={{
                    background: theme.inputBg,
                    color: "#f0ede8",
                    border: `1px solid ${theme.primaryBorder}`,
                    borderRadius: 8,
                    padding: "7px 9px",
                    fontSize: 11.5,
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  <option value="auto">AUTO (Cloud Failover)</option>
                  <option value="anthropic">CLAUDE PRIMARY (TEXT)</option>
                  <option value="openai">OPENAI PRIMARY</option>
                  <option value="gemini">GEMINI PRIMARY</option>
                </select>
              </label>

              <label style={{ display: "grid", gap: 4 }}>
                <span
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 9,
                    letterSpacing: "0.14em",
                    color: "rgba(240,237,232,0.58)",
                  }}
                >
                  OPENAI BRAIN MODEL
                </span>
                <select
                  value={openaiModelInput}
                  onChange={(e) => setOpenaiModelInput(e.target.value)}
                  style={{
                    background: theme.inputBg,
                    color: "#f0ede8",
                    border: `1px solid ${theme.primaryBorder}`,
                    borderRadius: 8,
                    padding: "7px 9px",
                    fontSize: 11.5,
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  <option value="gpt-4o">gpt-4o (Multimodal)</option>
                  <option value="gpt-4o-mini">gpt-4o-mini (Fast)</option>
                  <option value="gpt-4.1">gpt-4.1</option>
                  <option value="gpt-4.1-mini">gpt-4.1-mini</option>
                </select>
              </label>
            </div>

            {keyError && (
              <div style={{ fontSize: 11.5, color: RED }}>{keyError}</div>
            )}

            <button
              type="submit"
              disabled={savingKey}
              style={{
                ...pillBase,
                justifyContent: "center",
                padding: "10px 16px",
                background: `${PRIMARY}24`,
                borderColor: PRIMARY,
                color: "#ffffff",
                fontWeight: 600,
              }}
            >
              {savingKey
                ? "SAVING..."
                : !integrationsReady
                ? "NEXT · OPTIONAL INTEGRATIONS →"
                : "SAVE AI ENGINE SETTINGS"}
            </button>
          </form>
        </div>
      )}
    </>
  );
}
