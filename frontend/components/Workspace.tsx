"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { FileStack, FileText, MessageCircle, ScrollText, UserRound, Volume2, VolumeX } from "lucide-react";
import { api, ApiError, ClientConfig, errorMessage, HouseholdState, inr, onWaiting, Text2, TurnResult } from "@/lib/api";
import { readPref, writePref } from "@/lib/prefs";
import { useVoice } from "@/lib/voice";
import { Brand } from "./Brand";
import Chat from "./Chat";
import { SchemeList } from "./SchemeList";
import { DocumentList } from "./DocumentList";
import { ApplicationList } from "./ApplicationList";
import { ProfileList } from "./ProfileList";

export type Tab = "chat" | "schemes" | "documents" | "applications" | "profile";

export default function Workspace({ id }: { id: string }) {
  const demo = useSearchParams().get("demo") === "kamla";
  const router = useRouter();
  const [state, setState] = useState<HouseholdState | null>(null);
  const [config, setConfig] = useState<ClientConfig | null>(null);
  const [tab, setTab] = useState<Tab>("chat");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [gone, setGone] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [autoSpeak, setAutoSpeak] = useState(true);
  const resumed = useRef(false);

  useEffect(() => {
    writePref("entitled.household", id);
    setAutoSpeak(readPref("entitled.speak") !== "off");
    api.config().then(setConfig).catch(() => setConfig({ voice: { server: [], mode: "browser" }, llm: false, ocr: "", sms: "", schemes: 0 }));
    api.household(id).then(setState).catch((error) => {
      if (error instanceof ApiError && error.kind === "gone") setGone(true);
      else setLoadError(errorMessage(error));
    });
  }, [id]);

  useEffect(() => onWaiting((waiting) => {
    if (!waiting) return;
    setNotice(waiting.reason === "waking"
      ? "Waking up the server. The free server sleeps when nobody uses it, so this can take up to a minute…"
      : "The server is finishing another document or form. Waiting for it…");
  }), []);

  const startAgain = useCallback(async () => {
    setRestarting(true);
    try {
      const fresh = await api.createHousehold();
      writePref("entitled.household", fresh.household.id);
      router.replace(`/h/${fresh.household.id}${demo ? "?demo=kamla" : ""}`);
    } catch (error) {
      setLoadError(errorMessage(error));
      setGone(false);
      setRestarting(false);
    }
  }, [demo, router]);

  const voiceError = useCallback((code: string) => {
    const messages: Record<string, string> = {
      "not-allowed": "Microphone permission was denied. Allow it in the browser, or type instead.",
      "audio-capture": "No microphone was found. Connect one, or type instead.",
      "no-speech": "I did not hear anything. Tap the mic and try again.",
      unsupported: "This browser has no speech support. Please type instead.",
      "device-failed": "The speech reader on this device could not start. Please type instead, or try Chrome.",
      "stt-failed": "The speech service did not answer. Please type instead.",
      network: "This browser's speech service could not be reached. Check the connection, or type instead.",
    };
    setNotice(messages[code] ?? `Speech did not work (${code}). Please type instead.`);
  }, []);

  const sendRef = useRef<(text: string) => void>(() => undefined);
  const onSpoken = useCallback((text: string) => sendRef.current(text), []);
  const voice = useVoice(config, onSpoken, voiceError, setNotice);

  const speakReply = useCallback((reply: Text2) => {
    if (autoSpeak) void voice.speak(reply.en);
  }, [autoSpeak, voice]);

  const applyTurn = useCallback((result: TurnResult) => {
    setState(result.state);
    if (result.reply.en) speakReply(result.reply);
  }, [speakReply]);

  const run = useCallback(async (work: () => Promise<TurnResult | HouseholdState>) => {
    setBusy(true);
    setNotice(null);
    try {
      const result = await work();
      if ("reply" in result) applyTurn(result);
      else setState(result);
    } catch (error) {
      if (error instanceof ApiError && error.kind === "gone") setGone(true);
      else setNotice(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }, [applyTurn]);

  const send = useCallback((text: string) => {
    const clean = text.trim();
    if (!clean) return;
    voice.stopSpeaking();
    setState((current) => current && {
      ...current,
      messages: [...current.messages, { id: -Date.now(), role: "user", en: clean, kind: "text", at: new Date().toISOString() }],
    });
    void run(() => api.chat(id, clean));
  }, [id, run, voice]);
  sendRef.current = send;

  useEffect(() => {
    // A returning household with something in flight hears where things stand.
    if (!state || resumed.current) return;
    resumed.current = true;
    const live = state.applications.some((a) => a.reference);
    const last = state.messages[state.messages.length - 1];
    const quietFor = last ? Date.parse(state.now) - Date.parse(last.at) : 0;
    if (live && quietFor > 30 * 60 * 1000) void run(() => api.resume(id));
  }, [id, run, state]);

  const skipTime = useCallback(async (days: number) => {
    await run(async () => {
      await api.advance(days);
      return api.resume(id);
    });
  }, [id, run]);

  const toggleSpeak = () => {
    const next = !autoSpeak;
    setAutoSpeak(next);
    writePref("entitled.speak", next ? "on" : "off");
    if (!next) voice.stopSpeaking();
  };

  if (gone) {
    return (
      <div className="center-note" role="alert">
        <h1>This conversation was cleared</h1>
        <p>The free demo server forgets everything when it restarts or sleeps, and this household went with it. Start again and it takes a minute to catch up.</p>
        <div className="actions">
          <button type="button" className="btn btn-primary" disabled={restarting} onClick={() => void startAgain()}>
            {restarting ? "Starting…" : demo ? "Start Kamla Devi's case again" : "Start a new conversation"}
          </button>
          <Link className="btn btn-quiet" href="/">Go to start</Link>
        </div>
      </div>
    );
  }
  if (loadError) {
    return (
      <div className="center-note" role="alert">
        <h1>Could not open this household</h1>
        <p>{loadError}</p>
        <div className="actions">
          <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>Try again</button>
          <Link className="btn btn-quiet" href="/">Go to start</Link>
        </div>
      </div>
    );
  }
  if (!state) {
    return <div className="center-note" role="status"><p>Opening…</p></div>;
  }

  const { totals, counts } = state.eligibility;
  const decided = state.scheme_count - counts.undecided;
  const share = totals.annual_inr ? Math.min(100, Math.round((state.received_annual_inr / totals.annual_inr) * 100)) : 0;
  const pendingApps = state.applications.filter((a) => a.awaiting_confirmation).length;
  const tabs: { id: Tab; label: string; short?: string; icon: typeof MessageCircle; badge?: number; phoneOnly?: boolean }[] = [
    { id: "chat", label: "Chat", icon: MessageCircle, phoneOnly: true },
    { id: "schemes", label: "Schemes", icon: ScrollText, badge: counts.eligible || undefined },
    { id: "documents", label: "Documents", short: "Docs", icon: FileStack, badge: state.documents.missing.length || undefined },
    { id: "applications", label: "Applications", short: "Forms", icon: FileText, badge: pendingApps || undefined },
    { id: "profile", label: "Profile", icon: UserRound },
  ];
  const panelTab: Tab = tab === "chat" ? "schemes" : tab;
  const rightTab: Tab = panelTab === "schemes" ? "documents" : panelTab;

  const panels = {
    documents: <DocumentList state={state} id={id} busy={busy} run={run} onNotice={setNotice} />,
    applications: <ApplicationList state={state} busy={busy} onSkip={skipTime} />,
    profile: <ProfileList state={state} id={id} busy={busy} run={run} />,
  };

  return (
    <div className="app" data-tab={tab} data-panel={panelTab}>
      <header className="app-bar">
        <Brand />
        <div className="app-bar-who">
          <strong>{state.household.name || "New household"}</strong>
          {state.household.operator && <span>{state.household.operator}</span>}
        </div>
        <div className="app-bar-tools">
          <button type="button" className="icon-btn" onClick={toggleSpeak} aria-pressed={autoSpeak} aria-label={autoSpeak ? "Turn speech off" : "Turn speech on"}>
            {autoSpeak ? <Volume2 size={22} aria-hidden="true" /> : <VolumeX size={22} aria-hidden="true" />}
          </button>
        </div>
      </header>

      <section className="meter" aria-label="Entitlement ledger">
        <div className="meter-figure">
          <span className="meter-label">Entitled yearly</span>
          <span className="meter-value">{inr(totals.annual_inr)}</span>
        </div>
        <div className="meter-figure">
          <span className="meter-label">Receiving</span>
          <span className="meter-value meter-value-got">{inr(state.received_annual_inr)}</span>
        </div>
        <div className="meter-track" role="progressbar" aria-valuenow={share} aria-valuemin={0} aria-valuemax={100} aria-label="Share of entitlement received">
          <span style={{ width: `${share}%` }} />
        </div>
        <p className="meter-note">
          {counts.undecided
            ? `${decided} of ${state.scheme_count} schemes decided · ${state.household.questions_asked} ${state.household.questions_asked === 1 ? "question" : "questions"}`
            : `All ${state.scheme_count} schemes checked`}
        </p>
      </section>

      <div className="workspace">
        <div className="col col-chat">
          <Chat
            state={state} busy={busy} demo={demo} notice={notice} voice={voice} serverVoice={config?.voice.mode === "server"}
            onSend={send} onConfirm={(appId) => run(() => api.confirm(appId))} onNotice={setNotice} id={id} run={run}
          />
        </div>

        <div className="col col-panel">
          <nav className="panel-tabs" aria-label="Sections">
            {tabs.filter((item) => !item.phoneOnly).map((item) => (
              <button
                key={item.id} type="button"
                className={`panel-tab ${item.id === "schemes" ? "panel-tab-schemes" : ""}`}
                aria-current={(item.id === panelTab || (item.id !== "schemes" && item.id === rightTab)) ? "page" : undefined}
                data-active={item.id === panelTab}
                data-active-wide={item.id === rightTab}
                onClick={() => setTab(item.id)}
              >
                {item.label}
                {item.badge ? <span className="badge">{item.badge}</span> : null}
              </button>
            ))}
          </nav>
          <div className="panels">
            <section className="panel panel-schemes" aria-label="Schemes">
              <SchemeList state={state} busy={busy} onSpeak={(text) => void voice.speak(text)} onApply={(scheme) => { setTab("chat"); void run(() => api.startForm(id, scheme)); }} />
            </section>
            <section className="panel panel-right" aria-label="Details">
              {panels[rightTab as keyof typeof panels]}
            </section>
          </div>
        </div>
      </div>

      <nav className="bottom-nav" aria-label="Main">
        {tabs.map((item) => {
          const Icon = item.icon;
          return (
            <button key={item.id} type="button" onClick={() => setTab(item.id)} aria-current={tab === item.id ? "page" : undefined}>
              <Icon size={22} aria-hidden="true" />
              <span>{item.short ?? item.label}</span>
              {item.badge ? <em className="badge">{item.badge}</em> : null}
            </button>
          );
        })}
      </nav>
    </div>
  );
}
