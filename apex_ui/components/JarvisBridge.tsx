"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { OrbState } from "./ApexHeroOrb";
import { PERSONA_THEMES, type PersonaMode, type PersonaTheme } from "./theme";

export type LogEntry = {
  id: number;
  line: string;
  role: "user" | "jarvis" | "sys" | "tool";
  ts: string;
};

export type TraceEvent = {
  n: number;
  trace: { helper: string }[];
  tool?: string;
};

export type ConfirmBanner = {
  title: string;
  detail: string;
};

export type ContentCard = {
  title: string;
  text: string;
};

export type HudVideoQueueItem = {
  index: number;
  id?: string;
  title: string;
  uploader?: string;
  duration?: number;
  url?: string;
  platform?: string;
};

export type HudVideoState = {
  id: string;
  video_url: string;
  audio_url?: string;
  title: string;
  muted: boolean;
  webpage_url?: string;
  platform?: string;
  playlist_title?: string;
  playlist_url?: string;
  queue_index?: number;
  queue_total?: number;
  queue?: HudVideoQueueItem[];
};

export type IntegrationServiceInfo = {
  service: string;
  connected: boolean;
  ignored: boolean;
  email: string;
  handle?: string;
  auth_mode?: string;
  cookies_browser?: string;
  session_health?: string;
  permission: string;
  has_oauth_client?: boolean;
  channel_id?: string;
};

export type IntegrationsSummary = {
  services: Record<string, IntegrationServiceInfo>;
  connected_count: number;
  connected_services: string[];
  connected_socials?: string[];
  onboarding_done: boolean;
};

export type TasteEntry = {
  id: string;
  domain: string;
  item: string;
  sentiment: string;
  kind: "preference" | "restriction";
  contexts: string[];
  source: "explicit";
  updated_at: string;
};

export type TasteProfileState = {
  prompted: boolean;
  prompt_pending: boolean;
  entry_count: number;
  entries: TasteEntry[];
  discovery: Record<string, string>;
  domains: string[];
};

export type DesktopShortcutState = {
  exists: boolean;
  path: string;
  supported: boolean;
  prompt_pending: boolean;
};

export type PrivacySettings = {
  personalization_enabled: boolean;
  adaptive_learning_enabled: boolean;
  timeline_persistence_enabled: boolean;
};

export type BrainCounts = {
  memories: number;
  files: number;
  outputs: number;
  timeline: number;
};

export type WorkerStep = {
  step: number;
  action: string;
  result: string;
  ts: number;
};

export type WorkerItem = {
  id: string;
  kind: "subagent" | "tool";
  title: string;
  goal: string;
  status: "pending" | "in_progress" | "needs_review" | "completed" | "failed" | "cancelled" | "expired";
  tools: string[];
  nodes?: string[];
  steps: WorkerStep[];
  step_count: number;
  max_steps: number;
  result?: string | null;
  error?: string | null;
  created_at: number;
  updated_at: number;
  elapsed_s: number;
};

export type CompanionSummary = {
  id: string;
  name: string;
  role: string;
  persona: PersonaMode;
  voice: string;
  instructions?: string;
  allowed_tools?: string[];
  assigned_skills?: string[];
  builtin?: boolean;
};

export type ThemeCustomConfig = {
  preset: string;
  custom_primary: string;
  custom_secondary: string;
  effective_primary: string;
  effective_secondary: string;
};

export type AiProviderState = {
  provider: string;
  activeEngine: string;
  hasGeminiKey: boolean;
  hasOpenaiKey: boolean;
  hasAnthropicKey: boolean;
  geminiKeyMasked: string;
  openaiKeyMasked: string;
  anthropicKeyMasked: string;
  anthropicModel: string;
  openaiModel: string;
  openaiRealtimeModel: string;
  openaiBaseUrl: string;
};

function hexToRgbTuple(hex: string): string | null {
  const m = /^#([0-9a-fA-F]{6})$/.exec((hex || "").trim());
  if (!m) return null;
  const v = parseInt(m[1], 16);
  return `${(v >> 16) & 255}, ${(v >> 8) & 255}, ${v & 255}`;
}

export type TerminalSession = {
  id: string;
  command: string;
  cwd: string;
  status: "running" | "completed" | "failed" | "stopped";
  exit_code?: number | null;
  started_at: number;
  elapsed_s: number;
  output: string;
};

export type SocialHudState = {
  active: boolean;
  platform: string;
  label: string;
  view: string;
  layout: "mobile" | "wide";
  width: number;
  height: number;
  url: string;
  connected: boolean;
  opened_at: number;
  session_health?: string;
};

export type JarvisContextValue = {
  connected: boolean;
  ready: boolean;
  integrationsReady: boolean;
  integrations: IntegrationsSummary;
  privacy: PrivacySettings;
  desktopShortcut: DesktopShortcutState;
  updateDesktopShortcut: (operation: "create" | "remove" | "decline") => Promise<boolean>;
  tasteProfile: TasteProfileState;
  updateTasteProfile: (operation: string, payload?: Record<string, unknown>) => Promise<boolean>;
  tasteModalOpen: boolean;
  setTasteModalOpen: React.Dispatch<React.SetStateAction<boolean>>;
  brainCounts: BrainCounts;
  workers: WorkerItem[];
  terminalSessions: TerminalSession[];
  activeCompanion: CompanionSummary | null;
  themeCustom: ThemeCustomConfig;
  aiProviders: AiProviderState;
  persona: PersonaMode;
  activePersona: PersonaMode;
  theme: PersonaTheme;
  personaChosen: boolean;
  assistantName: string;
  orbState: OrbState;
  rawState: string;
  muted: boolean;
  paused: boolean;
  offline: boolean;
  offlineReason: string;
  voice: string;
  voices: string[];
  maleVoices: string[];
  femaleVoices: string[];
  bargeEnabled: boolean;
  gracePeriod: number;
  inputs: string[];
  outputs: string[];
  currentInput: string;
  currentOutput: string;
  logs: LogEntry[];
  lastSubtitle: { role: string; text: string } | null;
  trace: TraceEvent | null;
  confirm: ConfirmBanner | null;
  content: ContentCard | null;
  video: HudVideoState | null;
  socialHud: SocialHudState | null;
  consoleOpen: boolean;
  settingsOpen: boolean;
  setupOpen: boolean;
  integrationsModalOpen: boolean;
  brainModalOpen: boolean;
  studioModalOpen: boolean;
  automationsModalOpen: boolean;
  devModalOpen: boolean;
  securityModalOpen: boolean;
  activityOpen: boolean;
  personaModalOpen: boolean;
  backgroundMode: boolean;
  backgroundSurface: "corner" | "notch";
  setBackgroundSurface: (surface: "corner" | "notch") => Promise<void>;
  setConsoleOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setSettingsOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setSetupOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setIntegrationsModalOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setBrainModalOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setStudioModalOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setAutomationsModalOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setDevModalOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setSecurityModalOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setTerminalSessions: React.Dispatch<React.SetStateAction<TerminalSession[]>>;
  setActivityOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setPersonaModalOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setPreviewPersona: React.Dispatch<React.SetStateAction<PersonaMode | null>>;
  setThemeCustom: React.Dispatch<React.SetStateAction<ThemeCustomConfig>>;
  choosePersona: (p: PersonaMode, voiceName?: string) => Promise<void>;
  saveIntegrations: (payload: Record<string, unknown>) => Promise<boolean>;
  skipIntegrations: () => Promise<void>;
  disconnectIntegration: (service: string) => Promise<void>;
  startGoogleOAuth: (
    clientId: string,
    clientSecret: string
  ) => Promise<{ ok: boolean; auth_url?: string; error?: string }>;
  connectSocialWeb: (
    platform: string,
    handle?: string,
    permission?: string
  ) => Promise<{ ok: boolean; message?: string; error?: string }>;
  importSocialCookies: (
    platform: string,
    browser?: string,
    handle?: string,
    permission?: string
  ) => Promise<{
    ok: boolean;
    browser?: string;
    cookie_count?: number;
    message?: string;
    auto_opened_window?: boolean;
    error?: string;
  }>;
  updatePrivacy: (patch: Partial<PrivacySettings>) => Promise<void>;
  spawnWorker: (goal: string, tools?: string[]) => Promise<void>;
  cancelWorker: (workerId: string) => Promise<void>;
  clearCompletedWorkers: () => Promise<void>;
  showContentCard: (card: ContentCard) => void;
  clearContent: () => void;
  sendText: (text: string, traceNode?: string) => void;
  tapOrb: () => void;
  fireLocalTrace: (nodes: string[]) => void;
  toggleMute: () => void;
  togglePause: () => void;
  retryConnection: () => Promise<void>;
  interrupt: () => void;
  stopAll: () => void;
  captureRegion: () => void;
  openRemoteQr: () => void;
  setVoice: (v: string) => void;
  setDevices: (inputName: string, outputName: string) => void;
  setBarge: (enabled: boolean) => void;
  setGrace: (seconds: number) => void;
  resolveConfirm: (approved: boolean) => void;
  saveApiKey: (
    keyOrPayload:
      | string
        | {
          openai_key?: string;
          gemini_key?: string;
          anthropic_key?: string;
          provider?: string;
          anthropic_model?: string;
          openai_model?: string;
          openai_realtime_model?: string;
          openai_base_url?: string;
        }
  ) => Promise<boolean>;
  enterBackgroundMode: () => Promise<void>;
  exitBackgroundMode: () => Promise<void>;
  closeVideo: () => Promise<void>;
  setVideoMuted: (muted: boolean) => Promise<void>;
  nextVideo: () => Promise<void>;
  prevVideo: () => Promise<void>;
  jumpVideo: (index: number) => Promise<void>;
  openSocialHud: (
    platform: string,
    view?: string,
    layout?: "mobile" | "wide"
  ) => Promise<{ ok: boolean; error?: string }>;
  closeSocialHud: () => Promise<void>;
};

const JarvisContext = createContext<JarvisContextValue | null>(null);
const JarvisAudioLevelContext = createContext<number>(0);

export function useJarvisAudioLevel(): number {
  return useContext(JarvisAudioLevelContext);
}

function mapRawToOrb(raw: string, muted: boolean, paused: boolean): OrbState {
  const s = (raw || "").toUpperCase();
  if (muted || paused || s === "MUTED" || s === "PAUSED" || s === "SLEEPING") {
    return "idle";
  }
  if (s === "SPEAKING") return "speaking";
  if (s === "THINKING" || s === "PROCESSING") return "thinking";
  if (s === "LISTENING") return "listening";
  return "idle";
}

function classifyLog(line: string): { role: LogEntry["role"]; clean: string } {
  const trimmed = (line || "").trim();
  if (/^(you|user)\s*:/i.test(trimmed)) {
    return { role: "user", clean: trimmed.replace(/^(you|user)\s*:\s*/i, "") };
  }
  if (/^(sys|net|err)\s*:/i.test(trimmed)) {
    return { role: "sys", clean: trimmed };
  }
  if (/^(tool|action)\s*:/i.test(trimmed)) {
    return { role: "tool", clean: trimmed };
  }
  if (/^[a-z0-9_ -]{2,18}:\s/i.test(trimmed)) {
    return { role: "jarvis", clean: trimmed.replace(/^[a-z0-9_ -]{2,18}:\s*/i, "") };
  }
  return { role: "sys", clean: trimmed };
}

export function JarvisProvider({ children }: { children: React.ReactNode }) {
  const [connected, setConnected] = useState(false);
  const [ready, setReady] = useState(true);
  const [integrationsReady, setIntegrationsReady] = useState(true);
  const [integrations, setIntegrations] = useState<IntegrationsSummary>({
    services: {},
    connected_count: 0,
    connected_services: [],
    onboarding_done: true,
  });
  const [privacy, setPrivacyState] = useState<PrivacySettings>({
    personalization_enabled: true,
    adaptive_learning_enabled: true,
    timeline_persistence_enabled: true,
  });
  const [desktopShortcut, setDesktopShortcut] = useState<DesktopShortcutState>({
    exists: false,
    path: "",
    supported: true,
    prompt_pending: false,
  });
  const [tasteProfile, setTasteProfile] = useState<TasteProfileState>({
    prompted: false,
    prompt_pending: false,
    entry_count: 0,
    entries: [],
    discovery: {},
    domains: ["music", "food", "drinks", "entertainment", "style", "travel", "other"],
  });
  const [tasteModalOpen, setTasteModalOpen] = useState(false);
  const [brainCounts, setBrainCounts] = useState<BrainCounts>({
    memories: 0,
    files: 0,
    outputs: 0,
    timeline: 0,
  });
  const [persona, setPersona] = useState<PersonaMode>("male");
  const [previewPersona, setPreviewPersona] = useState<PersonaMode | null>(null);
  const [personaChosen, setPersonaChosen] = useState(true);
  const [assistantName, setAssistantName] = useState("JARVIS");
  const [rawState, setRawState] = useState("STANDBY");
  const [demoState, setDemoState] = useState<OrbState>("idle");
  const [audioLevel, setAudioLevel] = useState(0);
  const [muted, setMuted] = useState(false);
  const [paused, setPaused] = useState(false);
  const [offline, setOffline] = useState(false);
  const [offlineReason, setOfflineReason] = useState("");
  const [voice, setVoiceState] = useState("Charon");
  const [voices, setVoices] = useState<string[]>([
    "Charon",
    "Puck",
    "Kore",
    "Fenrir",
    "Aoede",
  ]);
  const [maleVoices, setMaleVoices] = useState<string[]>([
    "Charon",
    "Fenrir",
    "Puck",
  ]);
  const [femaleVoices, setFemaleVoices] = useState<string[]>(["Aoede", "Kore"]);
  const [bargeEnabled, setBargeEnabled] = useState(true);
  const [gracePeriod, setGracePeriod] = useState(8);
  const [inputs, setInputs] = useState<string[]>(["System default"]);
  const [outputs, setOutputs] = useState<string[]>(["System default"]);
  const [currentInput, setCurrentInput] = useState("");
  const [currentOutput, setCurrentOutput] = useState("");
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [lastSubtitle, setLastSubtitle] = useState<{ role: string; text: string } | null>(null);
  const [trace, setTrace] = useState<TraceEvent | null>(null);
  const [confirm, setConfirm] = useState<ConfirmBanner | null>(null);
  const [content, setContent] = useState<ContentCard | null>(null);
  const [video, setVideo] = useState<HudVideoState | null>(null);
  const [socialHud, setSocialHud] = useState<SocialHudState | null>(null);
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [setupOpen, setSetupOpen] = useState(false);
  const [integrationsModalOpen, setIntegrationsModalOpen] = useState(false);
  const [brainModalOpen, setBrainModalOpen] = useState(false);
  const [studioModalOpen, setStudioModalOpen] = useState(false);
  const [automationsModalOpen, setAutomationsModalOpen] = useState(false);
  const [devModalOpen, setDevModalOpen] = useState(false);
  const [securityModalOpen, setSecurityModalOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);
  const [personaModalOpen, setPersonaModalOpen] = useState(false);
  const [backgroundMode, setBackgroundMode] = useState(false);
  const [backgroundSurface, setBackgroundSurfaceState] = useState<"corner" | "notch">("corner");
  const [workers, setWorkers] = useState<WorkerItem[]>([]);
  const [terminalSessions, setTerminalSessions] = useState<TerminalSession[]>([]);
  const [activeCompanion, setActiveCompanion] = useState<CompanionSummary | null>(null);
  const [themeCustom, setThemeCustom] = useState<ThemeCustomConfig>({
    preset: "default",
    custom_primary: "",
    custom_secondary: "",
    effective_primary: "",
    effective_secondary: "",
  });
  const [aiProviders, setAiProviders] = useState<AiProviderState>({
    provider: "auto",
    activeEngine: "gemini",
    hasGeminiKey: false,
    hasOpenaiKey: false,
    hasAnthropicKey: false,
    geminiKeyMasked: "",
    openaiKeyMasked: "",
    anthropicKeyMasked: "",
    anthropicModel: "claude-sonnet-4-5",
    openaiModel: "gpt-4o",
    openaiRealtimeModel: "gpt-4o-realtime-preview",
    openaiBaseUrl: "https://api.openai.com/v1",
  });

  const wsRef = useRef<WebSocket | null>(null);
  const seqRef = useRef(1);
  const logIdRef = useRef(1);
  const demoTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const subtitleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const targetLevelRef = useRef(0);

  const activePersona: PersonaMode = previewPersona ?? persona;
  const theme = useMemo<PersonaTheme>(() => {
    const base = PERSONA_THEMES[activePersona];
    const pri = themeCustom.effective_primary || "";
    const sec = themeCustom.effective_secondary || "";
    if (!pri && !sec) return base;
    const priRgb = pri ? hexToRgbTuple(pri) : null;
    const secRgb = sec ? hexToRgbTuple(sec) : null;
    return {
      ...base,
      ...(pri
        ? {
            primary: pri,
            primaryBright: pri,
            spokeHot: pri,
            primarySoftBg: priRgb ? `rgba(${priRgb}, 0.09)` : base.primarySoftBg,
            primaryBorder: priRgb ? `rgba(${priRgb}, 0.30)` : base.primaryBorder,
            orbGlowRgb: priRgb || base.orbGlowRgb,
          }
        : {}),
      ...(sec
        ? {
            secondary: sec,
            secondaryBright: sec,
            secondarySoftBg: secRgb ? `rgba(${secRgb}, 0.10)` : base.secondarySoftBg,
          }
        : {}),
    };
  }, [activePersona, themeCustom]);

  const pushLogLine = useCallback((line: string, ts?: string) => {
    if (!line || !line.trim()) return;
    const { role, clean } = classifyLog(line);
    const stamp =
      ts ||
      new Date().toLocaleTimeString("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    const id = logIdRef.current++;
    setLogs((prev) => {
      const next = [...prev, { id, line: line.trim(), role, ts: stamp }];
      return next.length > 140 ? next.slice(next.length - 140) : next;
    });
    if (role === "jarvis" || role === "user") {
      setLastSubtitle({ role, text: clean });
      if (subtitleTimerRef.current) clearTimeout(subtitleTimerRef.current);
      subtitleTimerRef.current = setTimeout(() => {
        setLastSubtitle(null);
      }, 9000);
    }
  }, []);

  const fireLocalTrace = useCallback((nodes: string[]) => {
    if (!nodes || nodes.length === 0) return;
    const n = seqRef.current++;
    setTrace({
      n,
      trace: nodes.map((helper) => ({ helper })),
    });
  }, []);

  const sendAction = useCallback((payload: Record<string, unknown>) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload));
      return true;
    }
    fetch("/api/hud/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).catch(() => {});
    return false;
  }, []);

  // Smooth audio envelope decay isolated in JarvisAudioLevelContext; skips state
  // updates completely when silent so 0 React re-renders occur at rest.
  useEffect(() => {
    const id = setInterval(() => {
      const tgt = targetLevelRef.current;
      targetLevelRef.current = tgt < 0.004 ? 0 : tgt * 0.84;
      setAudioLevel((cur) => {
        if (cur === 0 && tgt === 0) return 0;
        const next = cur + (tgt - cur) * 0.45;
        const clamped = next < 0.005 ? 0 : Math.min(1, next);
        return Math.abs(clamped - cur) < 0.004 ? cur : clamped;
      });
    }, 40);
    return () => clearInterval(id);
  }, []);

  const applyBootstrap = useCallback(
    (d: Record<string, unknown>) => {
      if (!d || typeof d !== "object") return;
      const isReady = d.ready !== false;
      const isIntegrationsReady = d.integrations_ready !== false;
      const isPersonaChosen = d.persona_chosen !== false;
      setReady(isReady);
      setIntegrationsReady(isIntegrationsReady);
      setPersonaChosen(isPersonaChosen);

      if (d.integrations && typeof d.integrations === "object") {
        setIntegrations(d.integrations as IntegrationsSummary);
      }
      if (d.privacy && typeof d.privacy === "object") {
        setPrivacyState(d.privacy as PrivacySettings);
      }
      if (d.desktop_shortcut && typeof d.desktop_shortcut === "object") {
        setDesktopShortcut(d.desktop_shortcut as DesktopShortcutState);
      }
      if (d.taste_profile && typeof d.taste_profile === "object") {
        setTasteProfile(d.taste_profile as TasteProfileState);
      }
      if (d.brain_counts && typeof d.brain_counts === "object") {
        setBrainCounts(d.brain_counts as BrainCounts);
      }
      if (Array.isArray(d.workers)) {
        setWorkers(d.workers as WorkerItem[]);
      }
      if (d.active_companion && typeof d.active_companion === "object") {
        setActiveCompanion(d.active_companion as CompanionSummary);
      }
      if (d.theme_custom && typeof d.theme_custom === "object") {
        setThemeCustom(d.theme_custom as ThemeCustomConfig);
      }
      setAiProviders((prev) => ({
        provider: typeof d.provider === "string" ? d.provider : prev.provider,
        activeEngine:
          typeof d.active_engine === "string" ? d.active_engine : prev.activeEngine,
        hasGeminiKey:
          typeof d.has_gemini_key === "boolean" ? d.has_gemini_key : prev.hasGeminiKey,
        hasOpenaiKey:
          typeof d.has_openai_key === "boolean" ? d.has_openai_key : prev.hasOpenaiKey,
        hasAnthropicKey:
          typeof d.has_anthropic_key === "boolean" ? d.has_anthropic_key : prev.hasAnthropicKey,
        geminiKeyMasked:
          typeof d.gemini_key_masked === "string"
            ? d.gemini_key_masked
            : prev.geminiKeyMasked,
        openaiKeyMasked:
          typeof d.openai_key_masked === "string"
            ? d.openai_key_masked
            : prev.openaiKeyMasked,
        anthropicKeyMasked:
          typeof d.anthropic_key_masked === "string"
            ? d.anthropic_key_masked
            : prev.anthropicKeyMasked,
        anthropicModel:
          typeof d.anthropic_model === "string" ? d.anthropic_model : prev.anthropicModel,
        openaiModel:
          typeof d.openai_model === "string" ? d.openai_model : prev.openaiModel,
        openaiRealtimeModel:
          typeof d.openai_realtime_model === "string"
            ? d.openai_realtime_model
            : prev.openaiRealtimeModel,
        openaiBaseUrl:
          typeof d.openai_base_url === "string"
            ? d.openai_base_url
            : prev.openaiBaseUrl,
      }));

      if (d.persona === "female" || d.persona === "male") {
        setPersona(d.persona);
      }

      if (!isReady) {
        setSetupOpen(true);
        setIntegrationsModalOpen(false);
        setPersonaModalOpen(false);
      } else if (!isIntegrationsReady) {
        setSetupOpen(false);
        setIntegrationsModalOpen(true);
        setPersonaModalOpen(false);
      } else if (!isPersonaChosen) {
        setSetupOpen(false);
        setIntegrationsModalOpen(false);
        setPersonaModalOpen(true);
      }

      if (typeof d.assistant_name === "string" && d.assistant_name) {
        setAssistantName(d.assistant_name);
      }
      if (typeof d.raw_state === "string") setRawState(d.raw_state);
      if (d.background_surface === "corner" || d.background_surface === "notch") {
        setBackgroundSurfaceState(d.background_surface);
      }
      if (typeof d.muted === "boolean") setMuted(d.muted);
      if (typeof d.paused === "boolean") setPaused(d.paused);
      if (typeof d.offline === "boolean") setOffline(d.offline);
      if (typeof d.offline_reason === "string") setOfflineReason(d.offline_reason);
      if (typeof d.voice === "string") setVoiceState(d.voice);
      if (Array.isArray(d.voices) && d.voices.length > 0) {
        setVoices(d.voices as string[]);
      }
      if (Array.isArray(d.male_voices) && d.male_voices.length > 0) {
        setMaleVoices(d.male_voices as string[]);
      }
      if (Array.isArray(d.female_voices) && d.female_voices.length > 0) {
        setFemaleVoices(d.female_voices as string[]);
      }
      if (typeof d.barge_enabled === "boolean") setBargeEnabled(d.barge_enabled);
      if (typeof d.grace_period === "number") setGracePeriod(d.grace_period);
      if (Array.isArray(d.inputs) && d.inputs.length > 0) {
        setInputs(d.inputs as string[]);
      }
      if (Array.isArray(d.outputs) && d.outputs.length > 0) {
        setOutputs(d.outputs as string[]);
      }
      if (typeof d.current_input === "string") setCurrentInput(d.current_input);
      if (typeof d.current_output === "string") setCurrentOutput(d.current_output);
      if (Array.isArray(d.logs)) {
        const mapped: LogEntry[] = (d.logs as string[]).map((ln) => {
          const { role } = classifyLog(String(ln));
          return {
            id: logIdRef.current++,
            line: String(ln),
            role,
            ts: "",
          };
        });
        setLogs(mapped.slice(-120));
      }
      if (d.confirm && typeof d.confirm === "object") {
        setConfirm(d.confirm as ConfirmBanner);
      } else {
        setConfirm(null);
      }
      if (d.content && typeof d.content === "object") {
        setContent(d.content as ContentCard);
      }
      if (d.video && typeof d.video === "object") {
        setVideo(d.video as HudVideoState);
      } else if (d.video === null) {
        setVideo(null);
      }
      if (d.social_hud && typeof d.social_hud === "object") {
        setSocialHud(d.social_hud as SocialHudState);
      } else if (d.social_hud === null) {
        setSocialHud(null);
      }
    },
    []
  );

  // Connect WebSocket `/ws/hud` with automatic reconnect
  useEffect(() => {
    let alive = true;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    fetch("/api/hud/bootstrap")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (alive && d) {
          setConnected(true);
          applyBootstrap(d);
        }
      })
      .catch(() => {});

    const connectWs = () => {
      if (!alive || typeof window === "undefined") return;
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${proto}//${window.location.host}/ws/hud`;
      let ws: WebSocket;
      try {
        ws = new WebSocket(url);
      } catch {
        retryTimer = setTimeout(connectWs, 2500);
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        if (!alive) return;
        setConnected(true);
      };

      ws.onmessage = (ev) => {
        if (!alive) return;
        try {
          const msg = JSON.parse(ev.data);
          switch (msg.type) {
            case "integrations":
              if (msg.integrations) setIntegrations(msg.integrations as IntegrationsSummary);
              break;
            case "bootstrap":
              applyBootstrap(msg);
              break;
            case "state":
              if (typeof msg.raw_state === "string") setRawState(msg.raw_state);
              if (typeof msg.muted === "boolean") setMuted(msg.muted);
              if (typeof msg.paused === "boolean") setPaused(msg.paused);
              if (typeof msg.offline === "boolean") setOffline(msg.offline);
              if (typeof msg.offline_reason === "string") {
                setOfflineReason(msg.offline_reason);
              }
              break;
            case "level":
              targetLevelRef.current = Math.max(
                0,
                Math.min(1, Number(msg.level) || 0)
              );
              break;
            case "log":
              pushLogLine(String(msg.line || ""), msg.ts);
              break;
            case "trace": {
              const nodes: string[] = Array.isArray(msg.nodes) ? msg.nodes : [];
              if (nodes.length > 0) {
                const n = seqRef.current++;
                setTrace({
                  n,
                  tool: msg.tool,
                  trace: nodes.map((helper) => ({ helper })),
                });
              }
              break;
            }
            case "confirm":
              setConfirm(msg.confirm || null);
              break;
            case "content":
              setContent(msg.content || null);
              break;
            case "video":
              setVideo((msg.video as HudVideoState) || null);
              break;
            case "social_hud":
              setSocialHud((msg.social_hud as SocialHudState) || null);
              break;
            case "activity":
              if (Array.isArray(msg.workers)) {
                setWorkers(msg.workers as WorkerItem[]);
              }
              break;
            case "terminal":
              if (msg.session && typeof msg.session === "object") {
                const incoming = msg.session as TerminalSession;
                setTerminalSessions((prev) => {
                  const rest = prev.filter((x) => x.id !== incoming.id);
                  return [incoming, ...rest].slice(0, 20);
                });
              }
              break;
            case "reconfig":
              setReady(false);
              setSetupOpen(true);
              break;
            case "background_mode":
              if (typeof msg.active === "boolean") {
                setBackgroundMode(msg.active);
              }
              break;
            case "config":
              applyBootstrap(msg);
              break;
            default:
              break;
          }
        } catch {
          // ignore malformed packets
        }
      };

      ws.onclose = () => {
        if (!alive) return;
        wsRef.current = null;
        setConnected(false);
        retryTimer = setTimeout(connectWs, 1800);
      };

      ws.onerror = () => {
        try {
          ws.close();
        } catch {}
      };
    };

    connectWs();

    return () => {
      alive = false;
      if (retryTimer) clearTimeout(retryTimer);
      if (demoTimerRef.current) clearTimeout(demoTimerRef.current);
      if (subtitleTimerRef.current) clearTimeout(subtitleTimerRef.current);
      try {
        wsRef.current?.close();
      } catch {}
    };
  }, [applyBootstrap, pushLogLine]);

  const orbState: OrbState = connected
    ? mapRawToOrb(rawState, muted, paused)
    : demoState;

  const choosePersona = useCallback(
    async (p: PersonaMode, voiceName?: string) => {
      const normalized: PersonaMode = p === "female" ? "female" : "male";
      setPersona(normalized);
      setPreviewPersona(null);
      setPersonaChosen(true);
      setPersonaModalOpen(false);
      if (voiceName) {
        setVoiceState(voiceName);
      } else if (normalized === "female" && !femaleVoices.includes(voice)) {
        setVoiceState(PERSONA_THEMES.female.defaultVoice);
      } else if (normalized === "male" && !maleVoices.includes(voice)) {
        setVoiceState(PERSONA_THEMES.male.defaultVoice);
      }
      fireLocalTrace(["chief_of_staff", "design"]);
      try {
        const res = await fetch("/api/hud/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: "set_persona",
            persona: normalized,
            ...(voiceName ? { voice: voiceName } : {}),
          }),
        });
        if (res.ok) {
          const data = await res.json();
          if (typeof data.voice === "string") setVoiceState(data.voice);
        }
      } catch {
        sendAction({
          action: "set_persona",
          persona: normalized,
          ...(voiceName ? { voice: voiceName } : {}),
        });
      }
    },
    [femaleVoices, fireLocalTrace, maleVoices, sendAction, voice]
  );

  const tapOrb = useCallback(() => {
    if (!connected) {
      const next: OrbState =
        demoState === "idle"
          ? "listening"
          : demoState === "listening"
          ? "thinking"
          : demoState === "thinking"
          ? "speaking"
          : "idle";
      setDemoState(next);
      if (next === "thinking") {
        fireLocalTrace(["chief_of_staff", "researcher", "memory"]);
      } else if (next === "speaking") {
        targetLevelRef.current = 0.72;
      }
      if (demoTimerRef.current) clearTimeout(demoTimerRef.current);
      demoTimerRef.current = setTimeout(() => setDemoState("idle"), 8000);
      return;
    }
    fireLocalTrace(["chief_of_staff"]);
    sendAction({ action: "orb_tap" });
  }, [connected, demoState, fireLocalTrace, sendAction]);

  const sendText = useCallback(
    (text: string, traceNode?: string) => {
      const clean = text.trim();
      if (!clean) return;
      fireLocalTrace(
        traceNode ? [traceNode, "chief_of_staff"] : ["chief_of_staff"]
      );
      if (!connected) {
        pushLogLine(`You: ${clean}`);
        setDemoState("thinking");
        if (demoTimerRef.current) clearTimeout(demoTimerRef.current);
        demoTimerRef.current = setTimeout(() => {
          setDemoState("idle");
        }, 3500);
        return;
      }
      setRawState("THINKING");
      sendAction({ action: "text_command", text: clean });
    },
    [connected, fireLocalTrace, pushLogLine, sendAction]
  );

  const toggleMute = useCallback(() => {
    if (!connected) {
      setMuted((m) => !m);
      return;
    }
    sendAction({ action: "toggle_mute" });
  }, [connected, sendAction]);

  const togglePause = useCallback(() => {
    if (!connected) {
      setPaused((p) => !p);
      return;
    }
    sendAction({ action: "toggle_pause" });
  }, [connected, sendAction]);

  const retryConnection = useCallback(async () => {
    if (!connected) return;
    setOfflineReason("Retrying live AI connection…");
    try {
      await fetch("/api/hud/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "retry_connection" }),
      });
    } catch {
      sendAction({ action: "retry_connection" });
    }
  }, [connected, sendAction]);

  const interrupt = useCallback(() => {
    if (!connected) {
      setDemoState("idle");
      return;
    }
    sendAction({ action: "interrupt" });
  }, [connected, sendAction]);

  const stopAll = useCallback(() => {
    sendAction({ action: "stop_all" });
  }, [sendAction]);

  const captureRegion = useCallback(() => {
    fireLocalTrace(["design"]);
    sendAction({ action: "region_capture" });
  }, [fireLocalTrace, sendAction]);

  const openRemoteQr = useCallback(() => {
    sendAction({ action: "remote_qr" });
  }, [sendAction]);

  const setVoice = useCallback(
    (v: string) => {
      setVoiceState(v);
      sendAction({ action: "set_voice", voice: v });
    },
    [sendAction]
  );

  const setDevices = useCallback(
    (inputName: string, outputName: string) => {
      setCurrentInput(inputName);
      setCurrentOutput(outputName);
      sendAction({
        action: "set_audio_devices",
        input_device: inputName,
        output_device: outputName,
      });
    },
    [sendAction]
  );

  const setBarge = useCallback(
    (enabled: boolean) => {
      setBargeEnabled(enabled);
      sendAction({ action: "set_barge", enabled });
    },
    [sendAction]
  );

  const setGrace = useCallback(
    (seconds: number) => {
      setGracePeriod(seconds);
      sendAction({ action: "set_grace", seconds });
    },
    [sendAction]
  );

  const resolveConfirm = useCallback(
    (approved: boolean) => {
      setConfirm(null);
      sendAction({ action: "confirm_decision", approved });
    },
    [sendAction]
  );

  const saveApiKey = useCallback(
    async (
      keyOrPayload:
        | string
        | {
            openai_key?: string;
            gemini_key?: string;
            anthropic_key?: string;
            provider?: string;
            anthropic_model?: string;
            openai_model?: string;
            openai_realtime_model?: string;
            openai_base_url?: string;
          }
    ): Promise<boolean> => {
      const bodyPayload =
        typeof keyOrPayload === "string"
          ? { action: "save_api_key", key: keyOrPayload.trim() }
          : { action: "save_api_key", ...keyOrPayload };
      try {
        const r = await fetch("/api/hud/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(bodyPayload),
        });
        if (r.ok) {
          const data = await r.json().catch(() => ({}));
          if (data && data.ok === false) return false;
          setReady(true);
          setSetupOpen(false);
          if (!integrationsReady) {
            setIntegrationsModalOpen(true);
          } else if (!personaChosen) {
            setPersonaModalOpen(true);
          }
          return true;
        }
      } catch {}
      return false;
    },
    [integrationsReady, personaChosen]
  );

  const saveIntegrations = useCallback(
    async (payload: Record<string, unknown>): Promise<boolean> => {
      fireLocalTrace(["email", "drive", "calendar"]);
      try {
        const r = await fetch("/api/hud/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: "save_integrations",
            integrations: payload,
          }),
        });
        if (r.ok) {
          const data = await r.json();
          if (data.summary && typeof data.summary === "object") {
            setIntegrations(data.summary as IntegrationsSummary);
          }
          setIntegrationsReady(true);
          setIntegrationsModalOpen(false);
          if (!personaChosen) {
            setPersonaModalOpen(true);
          }
          return true;
        }
      } catch {}
      return false;
    },
    [fireLocalTrace, personaChosen]
  );

  const skipIntegrations = useCallback(async () => {
    setIntegrationsReady(true);
    setIntegrationsModalOpen(false);
    if (!personaChosen) {
      setPersonaModalOpen(true);
    }
    try {
      const r = await fetch("/api/hud/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "skip_integrations" }),
      });
      if (r.ok) {
        const data = await r.json();
        if (data.summary && typeof data.summary === "object") {
          setIntegrations(data.summary as IntegrationsSummary);
        }
      }
    } catch {
      sendAction({ action: "skip_integrations" });
    }
  }, [personaChosen, sendAction]);

  const disconnectIntegration = useCallback(
    async (service: string) => {
      try {
        const r = await fetch("/api/hud/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "disconnect_integration", service }),
        });
        if (r.ok) {
          const data = await r.json();
          if (data.summary && typeof data.summary === "object") {
            setIntegrations(data.summary as IntegrationsSummary);
          }
        }
      } catch {
        sendAction({ action: "disconnect_integration", service });
      }
    },
    [sendAction]
  );

  const startGoogleOAuth = useCallback(
    async (
      clientId: string,
      clientSecret: string
    ): Promise<{ ok: boolean; auth_url?: string; error?: string }> => {
      try {
        const r = await fetch("/api/hud/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: "start_google_oauth",
            client_id: clientId,
            client_secret: clientSecret,
          }),
        });
        const data = await r.json();
        if (data.ok && typeof data.auth_url === "string") {
          window.open(data.auth_url, "_blank", "noopener,noreferrer");
        }
        return data;
      } catch {
        return { ok: false, error: "Could not start Google OAuth flow." };
      }
    },
    []
  );

  const connectSocialWeb = useCallback(
    async (
      platform: string,
      handle = "",
      permission = "ask"
    ): Promise<{ ok: boolean; message?: string; error?: string }> => {
      try {
        const r = await fetch("/api/hud/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: "social_connect_web",
            platform,
            handle,
            permission,
          }),
        });
        const data = await r.json();
        if (data.summary && typeof data.summary === "object") {
          setIntegrations(data.summary as IntegrationsSummary);
        }
        return data;
      } catch {
        return { ok: false, error: "Could not start social sign-in session." };
      }
    },
    []
  );

  const importSocialCookies = useCallback(
    async (
      platform: string,
      browser = "auto",
      handle = "",
      permission = "ask"
    ): Promise<{
      ok: boolean;
      browser?: string;
      cookie_count?: number;
      message?: string;
      auto_opened_window?: boolean;
      error?: string;
    }> => {
      try {
        const r = await fetch("/api/hud/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: "social_import_cookies",
            platform,
            browser,
            handle,
            permission,
          }),
        });
        const data = await r.json();
        if (data.summary && typeof data.summary === "object") {
          setIntegrations(data.summary as IntegrationsSummary);
        }
        return data;
      } catch {
        return { ok: false, error: "Could not import browser cookies." };
      }
    },
    []
  );

  const updateDesktopShortcut = useCallback(
    async (operation: "create" | "remove" | "decline") => {
      try {
        const r = await fetch("/api/hud/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "desktop_shortcut", operation }),
        });
        const data = await r.json();
        if (data.desktop_shortcut && typeof data.desktop_shortcut === "object") {
          setDesktopShortcut(data.desktop_shortcut as DesktopShortcutState);
        }
        return Boolean(r.ok && data.ok);
      } catch {
        return false;
      }
    },
    []
  );

  const updateTasteProfile = useCallback(
    async (operation: string, payload: Record<string, unknown> = {}) => {
      try {
        const r = await fetch("/api/hud/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "taste_profile", operation, ...payload }),
        });
        const data = await r.json();
        if (data.taste_profile && typeof data.taste_profile === "object") {
          setTasteProfile(data.taste_profile as TasteProfileState);
        }
        return Boolean(r.ok && data.ok);
      } catch {
        return false;
      }
    },
    []
  );

  const updatePrivacy = useCallback(
    async (patch: Partial<PrivacySettings>) => {
      setPrivacyState((prev) => ({ ...prev, ...patch }));
      try {
        const r = await fetch("/api/hud/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "brain_set_privacy", ...patch }),
        });
        if (r.ok) {
          const data = await r.json();
          if (data.privacy && typeof data.privacy === "object") {
            setPrivacyState(data.privacy as PrivacySettings);
          }
        }
      } catch {
        sendAction({ action: "brain_set_privacy", ...patch });
      }
    },
    [sendAction]
  );

  const showContentCard = useCallback((card: ContentCard) => {
    setContent(card);
  }, []);

  const clearContent = useCallback(() => setContent(null), []);

  const spawnWorker = useCallback(
    async (goal: string, tools?: string[]) => {
      if (!goal.trim()) return;
      fireLocalTrace(["strategist", "chief_of_staff"]);
      try {
        const r = await fetch("/api/hud/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: "spawn_worker",
            goal: goal.trim(),
            tools: tools || [],
            auto_start: true,
          }),
        });
        if (r.ok) {
          const data = await r.json();
          if (Array.isArray(data.workers)) setWorkers(data.workers as WorkerItem[]);
        }
      } catch {
        sendAction({ action: "spawn_worker", goal: goal.trim(), tools: tools || [] });
      }
    },
    [fireLocalTrace, sendAction]
  );

  const cancelWorker = useCallback(
    async (workerId: string) => {
      if (!workerId) return;
      try {
        const r = await fetch("/api/hud/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "cancel_worker", worker_id: workerId }),
        });
        if (r.ok) {
          const data = await r.json();
          if (Array.isArray(data.workers)) setWorkers(data.workers as WorkerItem[]);
        }
      } catch {
        sendAction({ action: "cancel_worker", worker_id: workerId });
      }
    },
    [sendAction]
  );

  const clearCompletedWorkers = useCallback(async () => {
    try {
      const r = await fetch("/api/hud/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "clear_completed_workers" }),
      });
      if (r.ok) {
        const data = await r.json();
        if (Array.isArray(data.workers)) setWorkers(data.workers as WorkerItem[]);
      }
    } catch {
      sendAction({ action: "clear_completed_workers" });
    }
  }, [sendAction]);

  const setBackgroundSurface = useCallback(async (surface: "corner" | "notch") => {
    const previous = backgroundSurface;
    setBackgroundSurfaceState(surface);
    try {
      const r = await fetch("/api/hud/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "set_background_surface", surface }),
      });
      if (!r.ok) setBackgroundSurfaceState(previous);
    } catch {
      setBackgroundSurfaceState(previous);
    }
  }, [backgroundSurface]);

  const enterBackgroundMode = useCallback(async () => {
    setBackgroundMode(true);
    try {
      const r = await fetch("/api/hud/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "enter_background_mode" }),
      });
      if (r.ok) {
        const data = await r.json();
        if (data?.native_dock && typeof window !== "undefined") {
          try {
            window.close();
          } catch {}
        }
      }
    } catch {
      sendAction({ action: "enter_background_mode" });
    }
  }, [sendAction]);

  const exitBackgroundMode = useCallback(async () => {
    setBackgroundMode(false);
    try {
      await fetch("/api/hud/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "exit_background_mode" }),
      });
    } catch {
      sendAction({ action: "exit_background_mode" });
    }
  }, [sendAction]);

  const closeVideo = useCallback(async () => {
    setVideo(null);
    try {
      await fetch("/api/hud/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "video_close" }),
      });
    } catch {
      sendAction({ action: "video_close" });
    }
  }, [sendAction]);

  const setVideoMuted = useCallback(
    async (nextMuted: boolean) => {
      setVideo((prev) => (prev ? { ...prev, muted: nextMuted } : prev));
      try {
        await fetch("/api/hud/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "video_mute", muted: nextMuted }),
        });
      } catch {
        sendAction({ action: "video_mute", muted: nextMuted });
      }
    },
    [sendAction]
  );

  const nextVideo = useCallback(async () => {
    try {
      await fetch("/api/hud/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "video_next" }),
      });
    } catch {
      sendAction({ action: "video_next" });
    }
  }, [sendAction]);

  const prevVideo = useCallback(async () => {
    try {
      await fetch("/api/hud/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "video_prev" }),
      });
    } catch {
      sendAction({ action: "video_prev" });
    }
  }, [sendAction]);

  const jumpVideo = useCallback(
    async (index: number) => {
      try {
        await fetch("/api/hud/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "video_jump", index }),
        });
      } catch {
        sendAction({ action: "video_jump", index });
      }
    },
    [sendAction]
  );

  const openSocialHud = useCallback(
    async (
      platform: string,
      view = "feed",
      layout?: "mobile" | "wide"
    ): Promise<{ ok: boolean; error?: string }> => {
      try {
        const r = await fetch("/api/hud/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: "social_open_hud",
            platform,
            view,
            layout: layout || "",
          }),
        });
        const data = await r.json();
        if (data.social_hud && typeof data.social_hud === "object") {
          setSocialHud(data.social_hud as SocialHudState);
        }
        if (data.summary && typeof data.summary === "object") {
          setIntegrations(data.summary as IntegrationsSummary);
        }
        return data;
      } catch {
        return { ok: false, error: "Could not open HUD social viewport." };
      }
    },
    []
  );

  const closeSocialHud = useCallback(async () => {
    setSocialHud(null);
    try {
      await fetch("/api/hud/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "social_close_hud" }),
      });
    } catch {
      sendAction({ action: "social_close_hud" });
    }
  }, [sendAction]);

  const value = useMemo<JarvisContextValue>(
    () => ({
      connected,
      ready,
      integrationsReady,
      integrations,
      privacy,
      desktopShortcut,
      updateDesktopShortcut,
      tasteProfile,
      updateTasteProfile,
      tasteModalOpen,
      setTasteModalOpen,
      brainCounts,
      workers,
      terminalSessions,
      activeCompanion,
      themeCustom,
      aiProviders,
      persona,
      activePersona,
      theme,
      personaChosen,
      assistantName,
      orbState,
      rawState: connected ? rawState : demoState.toUpperCase(),
      muted,
      paused,
      offline,
      offlineReason,
      voice,
      voices,
      maleVoices,
      femaleVoices,
      bargeEnabled,
      gracePeriod,
      inputs,
      outputs,
      currentInput,
      currentOutput,
      logs,
      lastSubtitle,
      trace,
      confirm,
      content,
      video,
      socialHud,
      consoleOpen,
      settingsOpen,
      setupOpen,
      integrationsModalOpen,
      brainModalOpen,
      studioModalOpen,
      automationsModalOpen,
      devModalOpen,
      securityModalOpen,
      activityOpen,
      personaModalOpen,
      backgroundMode,
      backgroundSurface,
      setBackgroundSurface,
      setConsoleOpen,
      setSettingsOpen,
      setSetupOpen,
      setIntegrationsModalOpen,
      setBrainModalOpen,
      setStudioModalOpen,
      setAutomationsModalOpen,
      setDevModalOpen,
      setSecurityModalOpen,
      setTerminalSessions,
      setActivityOpen,
      setPersonaModalOpen,
      setPreviewPersona,
      setThemeCustom,
      choosePersona,
      saveIntegrations,
      skipIntegrations,
      disconnectIntegration,
      startGoogleOAuth,
      connectSocialWeb,
      importSocialCookies,
      updatePrivacy,
      spawnWorker,
      cancelWorker,
      clearCompletedWorkers,
      showContentCard,
      clearContent,
      sendText,
      tapOrb,
      fireLocalTrace,
      toggleMute,
      togglePause,
      retryConnection,
      interrupt,
      stopAll,
      captureRegion,
      openRemoteQr,
      setVoice,
      setDevices,
      setBarge,
      setGrace,
      resolveConfirm,
      saveApiKey,
      enterBackgroundMode,
      exitBackgroundMode,
      closeVideo,
      setVideoMuted,
      nextVideo,
      prevVideo,
      jumpVideo,
      openSocialHud,
      closeSocialHud,
    }),
    [
      connected,
      ready,
      integrationsReady,
      integrations,
      privacy,
      desktopShortcut,
      updateDesktopShortcut,
      tasteProfile,
      updateTasteProfile,
      tasteModalOpen,
      setTasteModalOpen,
      brainCounts,
      workers,
      terminalSessions,
      activeCompanion,
      themeCustom,
      aiProviders,
      persona,
      activePersona,
      theme,
      personaChosen,
      assistantName,
      orbState,
      rawState,
      demoState,
      muted,
      paused,
      offline,
      offlineReason,
      voice,
      voices,
      maleVoices,
      femaleVoices,
      bargeEnabled,
      gracePeriod,
      inputs,
      outputs,
      currentInput,
      currentOutput,
      logs,
      lastSubtitle,
      trace,
      confirm,
      content,
      video,
      socialHud,
      consoleOpen,
      settingsOpen,
      setupOpen,
      integrationsModalOpen,
      brainModalOpen,
      studioModalOpen,
      automationsModalOpen,
      devModalOpen,
      securityModalOpen,
      activityOpen,
      personaModalOpen,
      backgroundMode,
      backgroundSurface,
      setBackgroundSurface,
      choosePersona,
      saveIntegrations,
      skipIntegrations,
      disconnectIntegration,
      startGoogleOAuth,
      connectSocialWeb,
      importSocialCookies,
      updatePrivacy,
      spawnWorker,
      cancelWorker,
      clearCompletedWorkers,
      showContentCard,
      clearContent,
      sendText,
      tapOrb,
      fireLocalTrace,
      toggleMute,
      togglePause,
      retryConnection,
      interrupt,
      stopAll,
      captureRegion,
      openRemoteQr,
      setVoice,
      setDevices,
      setBarge,
      setGrace,
      resolveConfirm,
      saveApiKey,
      enterBackgroundMode,
      exitBackgroundMode,
      closeVideo,
      setVideoMuted,
      nextVideo,
      prevVideo,
      jumpVideo,
      openSocialHud,
      closeSocialHud,
    ]
  );

  return (
    <JarvisContext.Provider value={value}>
      <JarvisAudioLevelContext.Provider value={audioLevel}>
        {children}
      </JarvisAudioLevelContext.Provider>
    </JarvisContext.Provider>
  );
}

export function useJarvis(): JarvisContextValue {
  const ctx = useContext(JarvisContext);
  if (!ctx) {
    throw new Error("useJarvis must be used inside <JarvisProvider>");
  }
  return ctx;
}
