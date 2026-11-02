"use client";

import { FormEvent, useState } from "react";
import { Pencil } from "lucide-react";
import { api, Fact, HouseholdState, TurnResult } from "@/lib/api";

const EDITABLE = new Set(["name", "guardian_name", "dob", "address", "district", "mobile", "aadhaar_last4", "bank_account", "ifsc", "land_acres", "girl_name", "girl_dob", "annual_income"]);
const SOURCE: Record<string, string> = {
  said: "You said",
  document: "From document",
  inferred: "Inferred",
  confirmed: "Confirmed",
};

function display(fact: Fact): string {
  if (fact.value === true) return "Yes";
  if (fact.value === false) return "No";
  if (fact.value === "female") return "Woman";
  if (fact.value === "male") return "Man";
  if (fact.value === "rural") return "Village";
  if (fact.value === "urban") return "Town";
  if (fact.key === "annual_income") return `₹${Number(fact.value).toLocaleString("en-IN")}`;
  return String(fact.value);
}

type Props = { id: string; state: HouseholdState; busy: boolean; run: (work: () => Promise<TurnResult | HouseholdState>) => Promise<void> };

export function ProfileList({ id, state, busy, run }: Props) {
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
    return <p className="empty">What you tell me is written here, along with where it came from.</p>;
  }

  return (
    <div className="stack">
      <p className="muted">Each detail shows where it came from. Changing anything cancels an earlier confirmation.</p>
      <ul className="facts">
        {state.facts.map((fact) => (
          <li key={fact.key}>
            {editing === fact.key ? (
              <form className="fact-edit" onSubmit={save}>
                <label htmlFor={`edit-${fact.key}`}>{fact.label.en}</label>
                <input id={`edit-${fact.key}`} className="composer-input" value={value} onChange={(event) => setValue(event.target.value)} autoFocus />
                <div className="sample-row">
                  <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>Save</button>
                  <button type="button" className="btn btn-quiet btn-sm" onClick={() => setEditing(null)}>Cancel</button>
                </div>
              </form>
            ) : (
              <>
                <div className="fact-main">
                  <span className="fact-label">{fact.label.en}</span>
                  <strong>{display(fact)}</strong>
                </div>
                <span className={`source source-${fact.source}`}>{SOURCE[fact.source] ?? fact.source}</span>
                {EDITABLE.has(fact.key) && (
                  <button type="button" className="icon-btn" aria-label={`Change ${fact.label.en}`} onClick={() => { setEditing(fact.key); setValue(fact.key === "bank_account" ? "" : String(fact.value)); }}>
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
