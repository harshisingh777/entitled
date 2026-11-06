"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowRight, Mic, RotateCcw, UsersRound } from "lucide-react";
import { Brand } from "@/components/Brand";
import { api, errorMessage, onWaiting } from "@/lib/api";
import { readPref, writePref } from "@/lib/prefs";

const STEPS = [
  { title: "Talk", detail: "Just speak. No long form, 8 to 12 questions." },
  { title: "Find out why", detail: "A written rule behind every result, never a guess." },
  { title: "Prepare papers", detail: "Each document once, and where to get it." },
  { title: "Form filled", detail: "The form fills itself from your details." },
  { title: "Your yes", detail: "Nothing goes without your yes." },
  { title: "Until the money lands", detail: "Tracks verification and reminds you when to go." },
];

export default function Home() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [lastId, setLastId] = useState<string | null>(null);
  const [waking, setWaking] = useState(false);

  useEffect(() => onWaiting((waiting) => setWaking(waiting?.reason === "waking")), []);

  useEffect(() => {
    setLastId(readPref("entitled.household"));
    // Wakes a sleeping free server while the person reads the page, so their first tap is quick.
    api.health().catch(() => undefined);
  }, []);

  async function start(demo: boolean) {
    setBusy(true);
    setFailed(null);
    try {
      const state = await api.createHousehold();
      writePref("entitled.household", state.household.id);
      router.push(`/h/${state.household.id}${demo ? "?demo=kamla" : ""}`);
    } catch (error) {
      setFailed(errorMessage(error));
      setBusy(false);
    }
  }

  return (
    <div className="home">
      <header className="home-bar">
        <Brand />
      </header>

      <main className="home-main">
        <section className="hero">
          <p className="hero-tag">What is rightfully yours should reach you.</p>
          <h1>Government schemes are not charity. They are your right.</h1>
          <p className="hero-lead">
            Tell it about your family. Entitled finds every scheme you are entitled to, shows why, and stays with you until the money arrives.
          </p>
          <div className="hero-actions">
            <button type="button" className="btn btn-primary btn-lg" disabled={busy} onClick={() => start(false)}>
              <Mic size={22} aria-hidden="true" />
              {busy ? "Starting…" : "Start talking"}
            </button>
            {lastId && (
              <Link className="btn btn-quiet btn-lg" href={`/h/${lastId}`}>
                <RotateCcw size={20} aria-hidden="true" />
                Continue last conversation
              </Link>
            )}
          </div>
          {waking && busy && <p className="muted" role="status">Waking up the server. The free server sleeps when nobody uses it, so this can take up to a minute…</p>}
          {failed && <p className="error-text" role="alert">{failed}</p>}
        </section>

        <aside className="story" aria-label="Kamla Devi's story">
          <p className="story-eyebrow">Example · Raebareli, age 58</p>
          <h2>Kamla Devi</h2>
          <p className="story-text">Widowed, BPL ration card, son farms 1.2 acres, granddaughter is 6. Has never applied for anything.</p>
          <dl className="story-ledger">
            <div><dt>Entitled every year</dt><dd className="amount">₹18,000</dd></div>
            <div><dt>Receiving now</dt><dd className="amount amount-zero">₹0</dd></div>
          </dl>
          <button type="button" className="btn btn-gold" disabled={busy} onClick={() => start(true)}>
            Walk through Kamla Devi's case
            <ArrowRight size={20} aria-hidden="true" />
          </button>
        </aside>

        <section className="steps" aria-label="How it works">
          <ol>
            {STEPS.map((step, index) => (
              <li key={step.title}>
                <span className="step-no" aria-hidden="true">{index + 1}</span>
                <div>
                  <h3>{step.title}</h3>
                  <p>{step.detail}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section className="operator-cta">
          <div>
            <h2>A Gram Saathi? With ASHA or a CSC?</h2>
            <p>See many families' tasks, documents and due dates in one place.</p>
          </div>
          <Link href="/operator" className="btn btn-quiet">
            <UsersRound size={20} aria-hidden="true" />
            Open operator mode
          </Link>
        </section>
      </main>

      <footer className="home-foot">
        <p>Entitled assists. The department makes the final eligibility decision. This demo runs only on mock portals and synthetic documents.</p>
      </footer>
    </div>
  );
}
