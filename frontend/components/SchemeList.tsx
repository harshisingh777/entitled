"use client";

import { AlertTriangle, Check, CircleHelp, Clock3, ExternalLink, Volume2, X } from "lucide-react";
import { HouseholdState, inr, Outcome, SchemeResult } from "@/lib/api";
import { useLang } from "@/lib/lang";

const GROUPS: { outcome: Outcome; hi: string; en: string }[] = [
  { outcome: "eligible", hi: "हक़ बनता है", en: "You are entitled" },
  { outcome: "near_miss", hi: "बस एक क़दम दूर", en: "One step away" },
  { outcome: "undecided", hi: "अभी तय नहीं", en: "Not decided yet" },
  { outcome: "not_eligible", hi: "नहीं मिलेगी", en: "Not available" },
];

const OUTCOME = {
  eligible: { icon: Check, hi: "हक़ है", en: "Entitled" },
  near_miss: { icon: Clock3, hi: "लगभग", en: "Near miss" },
  undecided: { icon: CircleHelp, hi: "बाकी", en: "Pending" },
  not_eligible: { icon: X, hi: "नहीं", en: "No" },
};

function spokenTrace(result: SchemeResult, lang: "hi" | "en"): string {
  const passed = result.trace.filter((item) => item.status === "pass").map((item) => item.label[lang]).join(", ");
  const failed = result.trace.filter((item) => item.status === "fail").map((item) => item.reason?.[lang]).join(", ");
  const gap = result.gaps[0]?.[lang];
  return [result.name[lang], passed, gap || failed].filter(Boolean).join(". ");
}

function Value({ result }: { result: SchemeResult }) {
  const { t } = useLang();
  if (result.annual_inr) return <span className="scheme-value">{inr(result.annual_inr)}<small>{t("/साल", "/yr")}</small></span>;
  if (result.one_time_inr) return <span className="scheme-value">{inr(result.one_time_inr)}<small>{t(" एक बार", " once")}</small></span>;
  if (result.cover_inr) return <span className="scheme-value">{inr(result.cover_inr)}<small>{t(" बीमा", " cover")}</small></span>;
  return null;
}

function SchemeCard({ result, busy, betterName, onSpeak, onApply }: { result: SchemeResult; busy: boolean; betterName?: string; onSpeak: (text: string) => void; onApply: (id: string) => void }) {
  const { t, L, lang } = useLang();
  const { icon: Icon, ...label } = OUTCOME[result.outcome];
  const showTraceOpen = result.outcome === "near_miss" || result.outcome === "eligible";
  const applied = result.application_status;

  return (
    <article className={`scheme scheme-${result.outcome}`} data-testid={`scheme-${result.id}`}>
      <header className="scheme-head">
        <span className={`stamp stamp-${result.outcome}`}><Icon size={16} aria-hidden="true" />{t(label.hi, label.en)}</span>
        <Value result={result} />
      </header>
      <h3>{L(result.name)}</h3>
      <p className="scheme-benefit">{L(result.benefit)}</p>
      {result.gaps[0] && <p className="scheme-gap">{L(result.gaps[0])}</p>}
      {betterName && <p className="scheme-note">{t(`${betterName} के साथ नहीं मिल सकती, वह ज़्यादा है।`, `Cannot be drawn with ${betterName}, which pays more.`)}</p>}

      <details className="trace" open={showTraceOpen}>
        <summary>{t("नियम की जाँच", "Rule check")}</summary>
        <ul>
          {result.trace.map((item) => (
            <li key={item.id} className={`trace-${item.status}`}>
              {item.status === "pass" ? <Check size={16} aria-label={t("सही", "Pass")} /> : item.status === "fail" ? <X size={16} aria-label={t("नहीं", "Fail")} /> : <CircleHelp size={16} aria-label={t("पता नहीं", "Unknown")} />}
              <span>{item.status === "fail" && item.reason ? L(item.reason) : L(item.label)}</span>
            </li>
          ))}
        </ul>
        <p className="trace-meta">
          {t("किसे मिलेगी:", "Beneficiary:")} {L(result.beneficiary)}
        </p>
        {result.verification.status === "conflicting" && (
          <p className="trace-warn"><AlertTriangle size={14} aria-hidden="true" /> <span>{t("स्रोतों में अंतर है, विभाग से पक्का करें।", "Sources differ, please confirm with the department.")} <small lang="en">{result.verification.note}</small></span></p>
        )}
        <p className="trace-meta">
          <a href={result.source_url} target="_blank" rel="noreferrer">{t("सरकारी स्रोत", "Official source")} <ExternalLink size={13} aria-hidden="true" /></a>
          {" · "}{t("जाँचा", "Checked")} {result.last_verified}
        </p>
      </details>

      <div className="scheme-actions">
        <button type="button" className="icon-btn icon-btn-line" onClick={() => onSpeak(spokenTrace(result, lang))} aria-label={t(`${result.name.hi} के नियम सुनिए`, `Listen to the rules for ${result.name.en}`)}>
          <Volume2 size={20} aria-hidden="true" />
        </button>
        {result.outcome === "eligible" && !applied && (
          <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => onApply(result.id)}>{t("फॉर्म भरें", "Fill the form")}</button>
        )}
        {applied && <span className="scheme-applied">{t("आवेदन शुरू", "Application started")}</span>}
      </div>
    </article>
  );
}

export function SchemeList({ state, busy, onSpeak, onApply }: { state: HouseholdState; busy: boolean; onSpeak: (text: string) => void; onApply: (id: string) => void }) {
  const { t, L } = useLang();
  const { results, conflicts } = state.eligibility;
  const names = Object.fromEntries(results.map((r) => [r.id, r.name]));

  return (
    <div className="stack">
      <p className="disclaimer">{t("नतीजे लिखे हुए नियमों से निकलते हैं। अंतिम फ़ैसला विभाग करता है।", "Results come from written rules. The department makes the final decision.")}</p>
      {conflicts.map((conflict) => (
        <div key={conflict.group} className="callout">
          <AlertTriangle size={20} aria-hidden="true" />
          <p>{L(conflict)}</p>
        </div>
      ))}
      {GROUPS.map((group) => {
        const items = results.filter((result) => result.outcome === group.outcome);
        if (!items.length) return null;
        const body = items.map((result) => (
          <SchemeCard key={result.id} result={result} busy={busy} onSpeak={onSpeak} onApply={onApply}
            betterName={result.suppressed_by ? L(names[result.suppressed_by]) : undefined} />
        ));
        if (group.outcome === "not_eligible") {
          return (
            <details key={group.outcome} className="group-fold">
              <summary>{t(group.hi, group.en)} <span className="count">{items.length}</span></summary>
              <div className="stack">{body}</div>
            </details>
          );
        }
        return (
          <section key={group.outcome} className="stack">
            <h2 className="section-title">{t(group.hi, group.en)} <span className="count">{items.length}</span></h2>
            {body}
          </section>
        );
      })}
    </div>
  );
}
