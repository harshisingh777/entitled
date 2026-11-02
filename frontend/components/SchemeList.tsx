"use client";

import { AlertTriangle, Check, CircleHelp, Clock3, ExternalLink, Volume2, X } from "lucide-react";
import { HouseholdState, inr, Outcome, SchemeResult } from "@/lib/api";

const GROUPS: { outcome: Outcome; title: string }[] = [
  { outcome: "eligible", title: "You are entitled" },
  { outcome: "near_miss", title: "One step away" },
  { outcome: "undecided", title: "Not decided yet" },
  { outcome: "not_eligible", title: "Not available" },
];

const OUTCOME = {
  eligible: { icon: Check, label: "Entitled" },
  near_miss: { icon: Clock3, label: "Near miss" },
  undecided: { icon: CircleHelp, label: "Pending" },
  not_eligible: { icon: X, label: "No" },
};

function spokenTrace(result: SchemeResult): string {
  const passed = result.trace.filter((item) => item.status === "pass").map((item) => item.label.en).join(", ");
  const failed = result.trace.filter((item) => item.status === "fail").map((item) => item.reason?.en).join(", ");
  const gap = result.gaps[0]?.en;
  return [result.name.en, passed, gap || failed].filter(Boolean).join(". ");
}

function Value({ result }: { result: SchemeResult }) {
  if (result.annual_inr) return <span className="scheme-value">{inr(result.annual_inr)}<small>/yr</small></span>;
  if (result.one_time_inr) return <span className="scheme-value">{inr(result.one_time_inr)}<small>{" once"}</small></span>;
  if (result.cover_inr) return <span className="scheme-value">{inr(result.cover_inr)}<small>{" cover"}</small></span>;
  return null;
}

function SchemeCard({ result, busy, betterName, onSpeak, onApply }: { result: SchemeResult; busy: boolean; betterName?: string; onSpeak: (text: string) => void; onApply: (id: string) => void }) {
  const { icon: Icon, label } = OUTCOME[result.outcome];
  const showTraceOpen = result.outcome === "near_miss" || result.outcome === "eligible";
  const applied = result.application_status;

  return (
    <article className={`scheme scheme-${result.outcome}`} data-testid={`scheme-${result.id}`}>
      <header className="scheme-head">
        <span className={`stamp stamp-${result.outcome}`}><Icon size={16} aria-hidden="true" />{label}</span>
        <Value result={result} />
      </header>
      <h3>{result.name.en}</h3>
      <p className="scheme-benefit">{result.benefit.en}</p>
      {result.gaps[0] && <p className="scheme-gap">{result.gaps[0].en}</p>}
      {betterName && <p className="scheme-note">{`Cannot be drawn with ${betterName}, which pays more.`}</p>}

      <details className="trace" open={showTraceOpen}>
        <summary>Rule check</summary>
        <ul>
          {result.trace.map((item) => (
            <li key={item.id} className={`trace-${item.status}`}>
              {item.status === "pass" ? <Check size={16} aria-label="Pass" /> : item.status === "fail" ? <X size={16} aria-label="Fail" /> : <CircleHelp size={16} aria-label="Unknown" />}
              <span>{item.status === "fail" && item.reason ? item.reason.en : item.label.en}</span>
            </li>
          ))}
        </ul>
        <p className="trace-meta">
          Beneficiary: {result.beneficiary.en}
        </p>
        {result.verification.status === "conflicting" && (
          <p className="trace-warn"><AlertTriangle size={14} aria-hidden="true" /> <span>Sources differ, please confirm with the department. <small>{result.verification.note}</small></span></p>
        )}
        <p className="trace-meta">
          <a href={result.source_url} target="_blank" rel="noreferrer">Official source <ExternalLink size={13} aria-hidden="true" /></a>
          {" · "}Checked {result.last_verified}
        </p>
      </details>

      <div className="scheme-actions">
        <button type="button" className="icon-btn icon-btn-line" onClick={() => onSpeak(spokenTrace(result))} aria-label={`Listen to the rules for ${result.name.en}`}>
          <Volume2 size={20} aria-hidden="true" />
        </button>
        {result.outcome === "eligible" && !applied && (
          <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => onApply(result.id)}>Fill the form</button>
        )}
        {applied && <span className="scheme-applied">Application started</span>}
      </div>
    </article>
  );
}

export function SchemeList({ state, busy, onSpeak, onApply }: { state: HouseholdState; busy: boolean; onSpeak: (text: string) => void; onApply: (id: string) => void }) {
  const { results, conflicts } = state.eligibility;
  const names = Object.fromEntries(results.map((r) => [r.id, r.name]));

  return (
    <div className="stack">
      <p className="disclaimer">Results come from written rules. The department makes the final decision.</p>
      {conflicts.map((conflict) => (
        <div key={conflict.group} className="callout">
          <AlertTriangle size={20} aria-hidden="true" />
          <p>{conflict.en}</p>
        </div>
      ))}
      {GROUPS.map((group) => {
        const items = results.filter((result) => result.outcome === group.outcome);
        if (!items.length) return null;
        const body = items.map((result) => (
          <SchemeCard key={result.id} result={result} busy={busy} onSpeak={onSpeak} onApply={onApply}
            betterName={result.suppressed_by ? names[result.suppressed_by].en : undefined} />
        ));
        if (group.outcome === "not_eligible") {
          return (
            <details key={group.outcome} className="group-fold">
              <summary>{group.title} <span className="count">{items.length}</span></summary>
              <div className="stack">{body}</div>
            </details>
          );
        }
        return (
          <section key={group.outcome} className="stack">
            <h2 className="section-title">{group.title} <span className="count">{items.length}</span></h2>
            {body}
          </section>
        );
      })}
    </div>
  );
}
