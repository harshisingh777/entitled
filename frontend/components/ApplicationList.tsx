"use client";

import { useEffect, useState } from "react";
import { Ban, Check, CircleCheck, FastForward, FileDown, MessageSquareText, Play, ShieldAlert } from "lucide-react";
import { api, ApiError, Application, HouseholdState, Text2 } from "@/lib/api";
import { useLang } from "@/lib/lang";

const STEPS: { status: string; hi: string; en: string }[] = [
  { status: "submitted", hi: "जमा", en: "Submitted" },
  { status: "under_verification", hi: "जाँच में", en: "Verification" },
  { status: "approved", hi: "मंज़ूर", en: "Approved" },
  { status: "first_instalment", hi: "पहली किस्त", en: "First instalment" },
];

function FramePlayer({ application }: { application: Application }) {
  const { t } = useLang();
  const last = application.frames - 1;
  const [index, setIndex] = useState(last);
  const [run, setRun] = useState(0);

  useEffect(() => {
    if (application.frames < 2) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return setIndex(last);
    setIndex(0);
    const timer = window.setInterval(() => {
      setIndex((current) => {
        if (current >= last) {
          window.clearInterval(timer);
          return last;
        }
        return current + 1;
      });
    }, 420);
    return () => window.clearInterval(timer);
  }, [application.frames, last, run]);

  if (application.frames < 1) return null;
  return (
    <figure className="frames">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={`/api/applications/${application.id}/frames/${index}`} alt={t("डेमो पोर्टल पर भरा जा रहा फॉर्म", "The form being filled on the demo portal")} />
      <figcaption>
        <span>{index < last ? t("फॉर्म भरा जा रहा है…", "Filling the form…") : t("डेमो पोर्टल पर फॉर्म भरा गया", "Form filled on the demo portal")}</span>
        <button type="button" className="link-btn" onClick={() => setRun((n) => n + 1)}>
          <Play size={15} aria-hidden="true" /> {t("फिर देखें", "Replay")}
        </button>
      </figcaption>
    </figure>
  );
}

export function ConfirmCard({ application, busy, onConfirm, onNotice }: { application: Application; busy: boolean; onConfirm: (id: string) => void; onNotice: (text: string | null) => void }) {
  const { t, L } = useLang();
  const [refusal, setRefusal] = useState<string | null>(null);

  async function tryWithoutConfirmation() {
    onNotice(null);
    try {
      await api.submitWithoutConfirmation(application.id);
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) setRefusal(L(error.body as Text2));
      else setRefusal(t("सर्वर से जवाब नहीं मिला।", "The server did not respond."));
    }
  }

  const fields = application.fields.filter((field) => field.value);
  return (
    <section className="confirm-card" aria-label={t("भेजने से पहले पुष्टि", "Confirm before sending")}>
      <h3>{t("भेजने से पहले देख लीजिए", "Check before it is sent")}</h3>
      <p className="confirm-scheme">{L(application.scheme_name)}</p>
      <FramePlayer application={application} />
      <dl className="field-list">
        {fields.map((field) => (<div key={field.id}><dt>{L(field.label)}</dt><dd>{field.value}</dd></div>))}
      </dl>
      <p className="confirm-docs"><strong>{t("साथ में:", "Attached:")}</strong> {application.documents.map((doc) => L(doc.name)).join(", ") || t("कोई नहीं", "none")}</p>
      <button type="button" className="btn btn-confirm" disabled={busy} onClick={() => onConfirm(application.id)}>
        <Check size={22} aria-hidden="true" /> {t("हाँ, भेज दो", "Yes, send it")}
      </button>
      <p className="muted confirm-hint">{t("जानकारी ग़लत हो तो \"जानकारी\" में बदलिए। बदलते ही पहली पुष्टि रद्द हो जाती है।", "If something is wrong, change it under Profile. Any change cancels the earlier confirmation.")}</p>
      <div className="gate-demo">
        <button type="button" className="link-btn" onClick={() => void tryWithoutConfirmation()}>
          <ShieldAlert size={16} aria-hidden="true" /> {t("डेमो: बिना पुष्टि भेजकर देखें", "Demo: try sending without confirmation")}
        </button>
        {refusal && <p className="refusal" role="alert"><Ban size={18} aria-hidden="true" /> <span><strong>{t("रोक दिया गया।", "Refused.")}</strong> {refusal}</span></p>}
      </div>
    </section>
  );
}

function Tracker({ application }: { application: Application }) {
  const { t, L } = useLang();
  const reached = STEPS.findIndex((step) => step.status === application.status);
  return (
    <ol className="tracker" aria-label={t("आवेदन की स्थिति", "Application status")}>
      {STEPS.map((step, index) => {
        const event = application.events.find((item) => item.status === step.status);
        return (
          <li key={step.status} data-done={index <= reached} aria-current={index === reached ? "step" : undefined}>
            <span className="tracker-dot">{index <= reached && <Check size={14} aria-hidden="true" />}</span>
            <span className="tracker-label">{t(step.hi, step.en)}</span>
            {event && <small>{new Date(event.at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}</small>}
          </li>
        );
      })}
      <span className="sr-only">{L(application.status_label)}</span>
    </ol>
  );
}

type Props = { state: HouseholdState; busy: boolean; onSkip: (days: number) => Promise<void> };

export function ApplicationList({ state, busy, onSkip }: Props) {
  const { t, L } = useLang();
  const live = state.applications.some((application) => application.reference);

  if (!state.applications.length) {
    return <p className="empty">{t("अभी कोई आवेदन नहीं। योजनाओं में \"फॉर्म भरें\" दबाइए, या बोलिए: फॉर्म भरो।", "No applications yet. Press \"Fill the form\" on a scheme, or say: fill the form.")}</p>;
  }

  return (
    <div className="stack">
      {state.applications.map((application) => (
        <article key={application.id} className="application" data-testid={`application-${application.scheme_id}`}>
          <header>
            <h3>{L(application.scheme_name)}</h3>
            <span className={`stamp ${application.reference ? "stamp-eligible" : "stamp-undecided"}`}>{L(application.status_label)}</span>
          </header>
          {application.reference && <p className="app-ref">{t("संदर्भ", "Reference")}: <strong>{application.reference}</strong></p>}
          {application.reference && <Tracker application={application} />}
          {application.next_action && (
            <p className={`app-next ${application.overdue ? "app-next-late" : ""}`}>
              <strong>{application.overdue ? t("देर हो रही है:", "Overdue:") : t("अगला काम:", "Next:")}</strong> {L(application.next_action)}
              {application.due_at && <small> · {new Date(application.due_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}</small>}
            </p>
          )}
          {application.awaiting_confirmation && (
            <p className="app-next">{t("आपकी पुष्टि बाकी है। बातचीत में सारांश देखकर बोलिए: हाँ, भेज दो।", "Your confirmation is pending. Check the summary in the chat and say: yes, send it.")}</p>
          )}
          {application.fill_accuracy !== null && application.frames > 0 && (
            <div className="app-links">
              <a className="btn btn-quiet btn-sm" href={`/api/applications/${application.id}/pdf`} target="_blank" rel="noreferrer">
                <FileDown size={18} aria-hidden="true" /> {t("भरा हुआ फॉर्म (PDF)", "Filled form (PDF)")}
              </a>
              {application.confirmed_by && <span className="muted"><CircleCheck size={15} aria-hidden="true" /> {t("पुष्टि:", "Confirmed by:")} {application.confirmed_by}</span>}
            </div>
          )}
        </article>
      ))}

      {live && (
        <section className="demo-skip">
          <h2 className="section-title">{t("डेमो: समय आगे बढ़ाइए", "Demo: move time forward")}</h2>
          <p className="muted">{t("जाँच की स्थिति, याद दिलाना और अगली बातचीत देखने के लिए।", "To see the status change, the reminder and the next conversation.")}</p>
          <div className="sample-row">
            <button type="button" className="btn btn-quiet btn-sm" disabled={busy} onClick={() => void onSkip(12)}><FastForward size={18} aria-hidden="true" /> {t("12 दिन आगे", "12 days on")}</button>
            <button type="button" className="btn btn-quiet btn-sm" disabled={busy} onClick={() => void onSkip(20)}><FastForward size={18} aria-hidden="true" /> {t("20 दिन आगे", "20 days on")}</button>
          </div>
        </section>
      )}

      {state.notifications.length > 0 && (
        <section className="stack">
          <h2 className="section-title">{t("संदेश", "Messages")}</h2>
          <ul className="notices">
            {state.notifications.map((notice) => (
              <li key={notice.id}>
                <MessageSquareText size={18} aria-hidden="true" />
                <div>
                  <p>{L(notice)}</p>
                  <small>
                    {notice.delivery === "sms" ? "SMS" : notice.delivery === "simulated" ? t("SMS (डेमो, भेजा नहीं गया)", "SMS (demo, not actually sent)") : t("SMS नहीं जा सका", "SMS failed")}
                    {" · "}{new Date(notice.at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                  </small>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
