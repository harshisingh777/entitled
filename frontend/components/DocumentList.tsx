"use client";

import { useRef, useState } from "react";
import { Camera, Check, MapPin, Timer, Unlock, X } from "lucide-react";
import { api, HouseholdState, TurnResult } from "@/lib/api";
import { useLang } from "@/lib/lang";

const SAMPLES = [
  { file: "ration_card.jpg", hi: "राशन कार्ड", en: "Ration card" },
  { file: "aadhaar.jpg", hi: "आधार", en: "Aadhaar" },
  { file: "passbook.jpg", hi: "पासबुक", en: "Passbook" },
];

const FIELD_LABELS: Record<string, { hi: string; en: string }> = {
  name: { hi: "नाम", en: "Name" }, guardian_name: { hi: "पति / पिता", en: "Husband / father" }, dob: { hi: "जन्म तिथि", en: "Date of birth" },
  address: { hi: "पता", en: "Address" }, district: { hi: "ज़िला", en: "District" }, aadhaar_last4: { hi: "आधार के अंतिम 4 अंक", en: "Aadhaar last 4" },
  bank_account: { hi: "खाता", en: "Account" }, ifsc: { hi: "IFSC", en: "IFSC" },
};

type Props = {
  id: string; state: HouseholdState; busy: boolean;
  run: (work: () => Promise<TurnResult | HouseholdState>) => Promise<void>;
  onNotice: (text: string | null) => void;
};

export function DocumentList({ id, state, busy, run }: Props) {
  const { t, L } = useLang();
  const fileRef = useRef<HTMLInputElement>(null);
  const [extracted, setExtracted] = useState<Record<string, string> | null>(null);
  const { items, total, have, missing, requested_across_schemes: requested } = state.documents;

  async function read(source: Blob | (() => Promise<Blob>), filename: string) {
    await run(async () => {
      const blob = typeof source === "function" ? await source() : source;
      const result = await api.ocr(id, blob, filename);
      setExtracted((current) => ({ ...current, ...result.extracted.fields }));
      return result;
    });
  }

  function sample(file: string) {
    return read(() => fetch(`/static/samples/${file}`).then((response) => response.blob()), file);
  }

  return (
    <div className="stack">
      <section className="upload-box">
        <h2 className="section-title">{t("दस्तावेज़ की फ़ोटो भेजिए", "Send a document photo")}</h2>
        <p className="muted">{t("जानकारी अपने आप भर जाएगी। फ़ोटो रखी नहीं जाती, आधार के सिर्फ़ आख़िरी 4 अंक रहते हैं।", "Details fill in by themselves. The photo is not kept, and only the last 4 Aadhaar digits are stored.")}</p>
        <input ref={fileRef} type="file" accept="image/*" capture="environment" hidden aria-label={t("दस्तावेज़ की फ़ोटो", "Document photo")}
          onChange={(event) => { const file = event.target.files?.[0]; if (file) void read(file, file.name); event.target.value = ""; }} />
        <button type="button" className="btn btn-primary" disabled={busy} onClick={() => fileRef.current?.click()}>
          <Camera size={20} aria-hidden="true" /> {t("फ़ोटो लें या चुनें", "Take or choose a photo")}
        </button>
        <div className="sample-row">
          <span className="muted">{t("डेमो के नमूने:", "Demo samples:")}</span>
          {SAMPLES.map((item) => (
            <button key={item.file} type="button" className="chip" disabled={busy} onClick={() => void sample(item.file)}>{t(item.hi, item.en)}</button>
          ))}
        </div>
        {extracted && (
          <dl className="extracted" aria-live="polite">
            {Object.entries(extracted).map(([key, value]) => (
              <div key={key}><dt>{FIELD_LABELS[key] ? L(FIELD_LABELS[key]) : key}</dt><dd>{value}</dd></div>
            ))}
          </dl>
        )}
      </section>

      {total === 0 ? (
        <p className="empty">{t("जब कुछ योजनाओं का हक़ तय होगा, यहाँ उनके दस्तावेज़ दिखेंगे।", "Documents will appear here once some schemes are decided.")}</p>
      ) : (
        <>
          <p className="doc-summary">
            <strong>{t(`${total} में से ${have} तैयार`, `${have} of ${total} ready`)}</strong>
            {missing.length > 0 && <span> · {t(`${missing.length} बनवाने हैं`, `${missing.length} to get`)}</span>}
            <br />
            <small className="muted">{t(`योजनाओं ने कुल ${requested} बार माँगे, आपको ${total} ही देने हैं।`, `Schemes ask ${requested} times in all, you give only ${total}.`)}</small>
          </p>
          <ul className="doc-list">
            {items.map((doc) => (
              <li key={doc.id} className={`doc doc-${doc.have === true ? "have" : doc.have === false ? "missing" : "unknown"}`} data-testid={`doc-${doc.id}`}>
                <div className="doc-head">
                  <h3>{L(doc.name)}</h3>
                  <div className="segmented" role="group" aria-label={L(doc.name)}>
                    <button type="button" aria-pressed={doc.have === true} disabled={busy} onClick={() => run(() => api.setDocument(id, doc.id, true))}>
                      <Check size={16} aria-hidden="true" /> {t("है", "Have")}
                    </button>
                    <button type="button" aria-pressed={doc.have === false} disabled={busy} onClick={() => run(() => api.setDocument(id, doc.id, false))}>
                      <X size={16} aria-hidden="true" /> {t("नहीं", "No")}
                    </button>
                  </div>
                </div>
                <p className="doc-unlock"><Unlock size={15} aria-hidden="true" /> {t(`${doc.unlocks.length} योजनाएँ खोलता है:`, `Unlocks ${doc.unlocks.length}:`)} {doc.unlocks.map((u) => L(u.name)).join(", ")}</p>
                {doc.have !== true && (
                  <p className="doc-where">
                    <span><MapPin size={15} aria-hidden="true" /> {L(doc.where)}</span>
                    <span><Timer size={15} aria-hidden="true" /> {L(doc.time)}</span>
                  </p>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
