"use client";

import { FormEvent, useState } from "react";
import { Pencil } from "lucide-react";
import { api, Fact, HouseholdState, TurnResult } from "@/lib/api";
import { useLang } from "@/lib/lang";

const EDITABLE = new Set(["name", "guardian_name", "dob", "address", "district", "mobile", "aadhaar_last4", "bank_account", "ifsc", "land_acres", "girl_name", "girl_dob", "annual_income"]);
const SOURCE = {
  said: { hi: "आपने बताया", en: "You said" },
  document: { hi: "दस्तावेज़ से", en: "From document" },
  inferred: { hi: "अंदाज़ा", en: "Inferred" },
  confirmed: { hi: "पुष्टि हुई", en: "Confirmed" },
};

function display(fact: Fact, t: (hi: string, en: string) => string): string {
  if (fact.value === true) return t("हाँ", "Yes");
  if (fact.value === false) return t("नहीं", "No");
  if (fact.value === "female") return t("महिला", "Woman");
  if (fact.value === "male") return t("पुरुष", "Man");
  if (fact.value === "rural") return t("गाँव", "Village");
  if (fact.value === "urban") return t("शहर", "Town");
  if (fact.key === "annual_income") return `₹${Number(fact.value).toLocaleString("en-IN")}`;
  return String(fact.value);
}

type Props = { id: string; state: HouseholdState; busy: boolean; run: (work: () => Promise<TurnResult | HouseholdState>) => Promise<void> };

export function ProfileList({ id, state, busy, run }: Props) {
  const { t, L } = useLang();
  const [editing, setEditing] = useState<string | null>(null);
  const [value, setValue] = useState("");

  function save(event: FormEvent) {
    event.preventDefault();
    if (!editing || !value.trim()) return;
    const key = editing;
    setEditing(null);
    void run(() => api.editFact(id, key, value.trim()));
  }

  if (!state.facts.length) {
    return <p className="empty">{t("जो आप बताएँगे, वह यहाँ लिखा जाएगा, और यह भी कि कहाँ से पता चला।", "What you tell me is written here, along with where it came from.")}</p>;
  }

  return (
    <div className="stack">
      <p className="muted">{t("हर बात के साथ लिखा है कि वह कहाँ से आई। कुछ बदलने पर पिछली पुष्टि रद्द हो जाती है।", "Each detail shows where it came from. Changing anything cancels an earlier confirmation.")}</p>
      <ul className="facts">
        {state.facts.map((fact) => (
          <li key={fact.key}>
            {editing === fact.key ? (
              <form className="fact-edit" onSubmit={save}>
                <label htmlFor={`edit-${fact.key}`}>{L(fact.label)}</label>
                <input id={`edit-${fact.key}`} className="composer-input" value={value} onChange={(event) => setValue(event.target.value)} autoFocus />
                <div className="sample-row">
                  <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>{t("सहेजें", "Save")}</button>
                  <button type="button" className="btn btn-quiet btn-sm" onClick={() => setEditing(null)}>{t("रहने दें", "Cancel")}</button>
                </div>
              </form>
            ) : (
              <>
                <div className="fact-main">
                  <span className="fact-label">{L(fact.label)}</span>
                  <strong>{display(fact, t)}</strong>
                </div>
                <span className={`source source-${fact.source}`}>{L(SOURCE[fact.source as keyof typeof SOURCE] ?? { hi: fact.source, en: fact.source })}</span>
                {EDITABLE.has(fact.key) && (
                  <button type="button" className="icon-btn" aria-label={t(`${fact.label.hi} बदलें`, `Change ${fact.label.en}`)} onClick={() => { setEditing(fact.key); setValue(fact.key === "bank_account" ? "" : String(fact.value)); }}>
                    <Pencil size={18} aria-hidden="true" />
                  </button>
                )}
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
