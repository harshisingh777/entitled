"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Camera, LoaderCircle, Mic, Send, Square, Volume2 } from "lucide-react";
import { api, HouseholdState, TurnResult } from "@/lib/api";
import type { ListenState } from "@/lib/voice";
import { ConfirmCard } from "./ApplicationList";

export const KAMLA_INTRO = "My name is Kamla Devi, I am a 58 year old widow, I live in a village in Raebareli. I have a BPL card. My son has 1.2 acres of land and my granddaughter is 6 years old. Our yearly income is 40 thousand.";

type Voice = { state: ListenState; supported: boolean; toggleListening: () => void; speak: (text: string) => Promise<void> };
type Reply = { label: string; say?: string; tone?: "primary" };

const YES_NO: Reply[] = [
  { label: "Yes" },
  { label: "No" },
  { label: "Don't know" },
];

function quickReplies(state: HouseholdState): Reply[] {
  const { household } = state;
  if (household.stage === "CONFIRM") {
    return [{ label: "Do not send" }];
  }
  if (household.pending_digit) return YES_NO.slice(0, 2);
  if (household.pending_field) return [];
  switch (household.expected) {
    case "gender":
      return [{ label: "Woman" }, { label: "Man" }];
    case "area":
      return [{ label: "Village" }, { label: "Town" }];
    case "start_form":
      return [{ label: "Yes, fill it", say: "Yes", tone: "primary" }, { label: "Not now", say: "No" }];
    case "age": case "annual_income": case "girl_children_count": case "youngest_girl_age": case null:
      return [];
    default:
      return YES_NO;
  }
}

type Props = {
  id: string; state: HouseholdState; busy: boolean; demo: boolean; notice: string | null; voice: Voice; serverVoice: boolean;
  onSend: (text: string) => void; onConfirm: (applicationId: string) => void; onNotice: (text: string | null) => void;
  run: (work: () => Promise<TurnResult | HouseholdState>) => Promise<void>;
};

export default function Chat({ id, state, busy, demo, notice, voice, onSend, onConfirm, onNotice, run }: Props) {
  const [draft, setDraft] = useState("");
  const logRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const awaiting = state.applications.find((a) => a.awaiting_confirmation);
  const replies = useMemo(() => quickReplies(state), [state]);
  const hasNoFacts = state.facts.length === 0;

  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [state.messages.length, busy, awaiting?.id, awaiting?.frames]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!draft.trim() || busy) return;
    onSend(draft);
    setDraft("");
  }

  function upload(file: File | undefined) {
    if (!file) return;
    void run(() => api.ocr(id, file, file.name));
    if (fileRef.current) fileRef.current.value = "";
  }

  const listening = voice.state === "listening";
  const micLabel = listening ? "Stop listening" : voice.state === "transcribing" ? "Transcribing" : "Speak";

  return (
    <>
      <div className="chat-log" ref={logRef} role="log" aria-live="polite" aria-label="Conversation">
        {state.messages.map((message) => (
          <div key={message.id} className={`bubble bubble-${message.role}`}>
            <p>{message.en}</p>
            {message.role === "agent" && (
              <button type="button" className="bubble-speak" onClick={() => void voice.speak(message.en)} aria-label="Listen">
                <Volume2 size={16} aria-hidden="true" />
              </button>
            )}
          </div>
        ))}
        {busy && (
          <div className="bubble bubble-agent bubble-wait" role="status">
            <LoaderCircle className="spin" size={18} aria-hidden="true" />
            <p>Working on it…</p>
          </div>
        )}
        {awaiting && !busy && <ConfirmCard application={awaiting} busy={busy} onConfirm={onConfirm} onNotice={onNotice} />}
      </div>

      {notice && <p className="chat-notice" role="alert">{notice}</p>}

      <div className="composer">
        {(replies.length > 0 || (demo && hasNoFacts)) && (
          <div className="chips" aria-label="Quick replies">
            {demo && hasNoFacts && (
              <button type="button" className="chip chip-primary" disabled={busy} onClick={() => onSend(KAMLA_INTRO)}>
                Speak as Kamla Devi
              </button>
            )}
            {replies.map((reply) => (
              <button key={reply.label} type="button" className={`chip ${reply.tone === "primary" ? "chip-primary" : ""}`} disabled={busy} onClick={() => onSend(reply.say ?? reply.label)}>
                {reply.label}
              </button>
            ))}
          </div>
        )}
        <form className="composer-row" onSubmit={submit}>
          <input ref={fileRef} type="file" accept="image/*" capture="environment" hidden onChange={(event) => upload(event.target.files?.[0])} aria-label="Document photo" />
          <button type="button" className="icon-btn icon-btn-line" disabled={busy} onClick={() => fileRef.current?.click()} aria-label="Send a document photo">
            <Camera size={22} aria-hidden="true" />
          </button>
          <label className="sr-only" htmlFor="chat-input">Type your answer</label>
          <input id="chat-input" className="composer-input" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Type, or press the mic" autoComplete="off" />
          {draft.trim() ? (
            <button type="submit" className="mic" disabled={busy} aria-label="Send">
              <Send size={24} aria-hidden="true" />
            </button>
          ) : (
            <button type="button" className={`mic ${listening ? "mic-live" : ""}`} disabled={busy || !voice.supported || voice.state === "transcribing"} onClick={voice.toggleListening} aria-label={micLabel} aria-pressed={listening} title={voice.supported ? micLabel : "This browser has no speech support"}>
              {listening ? <Square size={22} aria-hidden="true" /> : voice.state === "transcribing" ? <LoaderCircle className="spin" size={24} aria-hidden="true" /> : <Mic size={26} aria-hidden="true" />}
            </button>
          )}
        </form>
      </div>
    </>
  );
}
