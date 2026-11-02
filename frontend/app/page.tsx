"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowRight, Mic, RotateCcw, UsersRound } from "lucide-react";
import { Brand, LangToggle } from "@/components/Brand";
import { api } from "@/lib/api";
import { readPref, useLang, writePref } from "@/lib/lang";

const STEPS = [
  { hi: "बताइए", en: "Talk", detail: { hi: "हिन्दी में बोलिए। लंबा फॉर्म नहीं, 8 से 12 सवाल।", en: "Just speak. No long form, 8 to 12 questions." } },
  { hi: "जानिए क्यों", en: "Find out why", detail: { hi: "हर नतीजे के पीछे लिखा नियम, अंदाज़ा नहीं।", en: "A written rule behind every result, never a guess." } },
  { hi: "काग़ज़ तैयार", en: "Prepare papers", detail: { hi: "हर दस्तावेज़ एक बार। कहाँ बनेगा, यह भी।", en: "Each document once, and where to get it." } },
  { hi: "फॉर्म भरा", en: "Form filled", detail: { hi: "आपकी जानकारी से फॉर्म अपने आप भरता है।", en: "The form fills itself from your details." } },
  { hi: "आपकी हाँ", en: "Your yes", detail: { hi: "आपकी हाँ के बिना कुछ नहीं जाता।", en: "Nothing goes without your yes." } },
  { hi: "पैसे तक साथ", en: "Until the money lands", detail: { hi: "जाँच कहाँ अटकी है, कब जाना है, सब याद दिलाएगा।", en: "Tracks verification and reminds you when to go." } },
];

export default function Home() {
  const router = useRouter();
  const { t, L } = useLang();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [lastId, setLastId] = useState<string | null>(null);

  useEffect(() => setLastId(readPref("entitled.household")), []);

  async function start(demo: boolean) {
    setBusy(true);
    setFailed(false);
    try {
      const state = await api.createHousehold();
      writePref("entitled.household", state.household.id);
      router.push(`/h/${state.household.id}${demo ? "?demo=kamla" : ""}`);
    } catch {
      setFailed(true);
      setBusy(false);
    }
  }

  return (
    <div className="home">
      <header className="home-bar">
        <Brand />
        <LangToggle />
      </header>

      <main className="home-main">
        <section className="hero">
          <p className="hero-tag">{t("जो तुम्हारा हक़ है, वह तुम तक पहुँचे।", "What is rightfully yours should reach you.")}</p>
          <h1>{t("सरकारी योजना दान नहीं, आपका हक़ है।", "Government schemes are not charity. They are your right.")}</h1>
          <p className="hero-lead">
            {t(
              "बताइए आपका परिवार कैसा है। Entitled हर उस योजना को ढूँढता है जिसका आपको हक़ है, बताता है क्यों, और पैसा मिलने तक साथ रहता है।",
              "Tell it about your family. Entitled finds every scheme you are entitled to, shows why, and stays with you until the money arrives.",
            )}
          </p>
          <div className="hero-actions">
            <button type="button" className="btn btn-primary btn-lg" disabled={busy} onClick={() => start(false)}>
              <Mic size={22} aria-hidden="true" />
              {busy ? t("शुरू हो रहा है…", "Starting…") : t("बातचीत शुरू करें", "Start talking")}
            </button>
            {lastId && (
              <Link className="btn btn-quiet btn-lg" href={`/h/${lastId}`}>
                <RotateCcw size={20} aria-hidden="true" />
                {t("पिछली बातचीत जारी रखें", "Continue last conversation")}
              </Link>
            )}
          </div>
          {failed && <p className="error-text" role="alert">{t("सर्वर से जुड़ नहीं पाए। थोड़ी देर बाद फिर कोशिश कीजिए।", "Could not reach the server. Please try again shortly.")}</p>}
        </section>

        <aside className="story" aria-label={t("कमला देवी की कहानी", "Kamla Devi's story")}>
          <p className="story-eyebrow">{t("उदाहरण · रायबरेली, 58 वर्ष", "Example · Raebareli, age 58")}</p>
          <h2>{t("कमला देवी", "Kamla Devi")}</h2>
          <p className="story-text">{t("विधवा, BPL राशन कार्ड, बेटे के पास 1.2 एकड़ ज़मीन, पोती 6 साल की। कभी किसी योजना के लिए आवेदन नहीं किया।", "Widowed, BPL ration card, son farms 1.2 acres, granddaughter is 6. Has never applied for anything.")}</p>
          <dl className="story-ledger">
            <div><dt>{t("हर साल का हक़", "Entitled every year")}</dt><dd className="amount">₹18,000</dd></div>
            <div><dt>{t("अभी मिल रहा है", "Receiving now")}</dt><dd className="amount amount-zero">₹0</dd></div>
          </dl>
          <button type="button" className="btn btn-gold" disabled={busy} onClick={() => start(true)}>
            {t("कमला देवी की बातचीत देखें", "Walk through Kamla Devi's case")}
            <ArrowRight size={20} aria-hidden="true" />
          </button>
        </aside>

        <section className="steps" aria-label={t("यह कैसे काम करता है", "How it works")}>
          <ol>
            {STEPS.map((step, index) => (
              <li key={step.en}>
                <span className="step-no" aria-hidden="true">{index + 1}</span>
                <div>
                  <h3>{t(step.hi, step.en)}</h3>
                  <p>{L(step.detail)}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section className="operator-cta">
          <div>
            <h2>{t("गाँव साथी हैं? ASHA या CSC से जुड़े हैं?", "A Gram Saathi? With ASHA or a CSC?")}</h2>
            <p>{t("एक ही जगह से कई परिवारों के काम, दस्तावेज़ और तारीख़ें देखिए।", "See many families' tasks, documents and due dates in one place.")}</p>
          </div>
          <Link href="/operator" className="btn btn-quiet">
            <UsersRound size={20} aria-hidden="true" />
            {t("गाँव साथी मोड खोलें", "Open operator mode")}
          </Link>
        </section>
      </main>

      <footer className="home-foot">
        <p>{t("Entitled मदद करता है। अंतिम पात्रता का फ़ैसला विभाग करता है। यह डेमो नकली पोर्टल और नकली दस्तावेज़ों पर चलता है।", "Entitled assists. The department makes the final eligibility decision. This demo runs only on mock portals and synthetic documents.")}</p>
      </footer>
    </div>
  );
}
