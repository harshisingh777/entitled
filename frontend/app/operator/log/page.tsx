"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Brand } from "@/components/Brand";
import { api, AuditEntry } from "@/lib/api";

export default function ActionLogPage() {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [onlyRefused, setOnlyRefused] = useState(false);

  useEffect(() => {
    api.audit().then(setEntries).catch(() => setFailed(true));
  }, []);

  const shown = (entries ?? []).filter((entry) => !onlyRefused || entry.outcome !== "ok");

  return (
    <div className="operator">
      <header className="home-bar">
        <Brand />
      </header>
      <main className="operator-main">
        <Link className="link-btn" href="/operator"><ArrowLeft size={18} aria-hidden="true" /> Back to operator mode</Link>
        <h1>Action log</h1>
        <p className="muted">Every agent action: when, which tool, who confirmed. Personal numbers stay masked.</p>
        <div className="filters">
          <button type="button" className="chip" aria-pressed={!onlyRefused} onClick={() => setOnlyRefused(false)}>All</button>
          <button type="button" className="chip" aria-pressed={onlyRefused} onClick={() => setOnlyRefused(true)}>Refused or failed</button>
        </div>
        {failed && <p className="error-text" role="alert">Could not reach the server.</p>}
        {!entries && !failed && <p role="status" className="muted">Opening…</p>}
        {entries && shown.length === 0 && <p className="empty">Nothing in this list right now.</p>}
        <ul className="log">
          {shown.map((entry) => (
            <li key={entry.id} className={entry.outcome === "ok" ? "" : "log-refused"}>
              <div className="log-head">
                <code>{entry.tool}</code>
                <span className={`stamp ${entry.outcome === "ok" ? "stamp-undecided" : "stamp-not_eligible"}`}>{entry.outcome}</span>
              </div>
              <small>{new Date(entry.at).toLocaleString("en-IN")} · {entry.actor}</small>
              <pre>{JSON.stringify({ in: entry.inputs, out: entry.output })}</pre>
            </li>
          ))}
        </ul>
      </main>
    </div>
  );
}
