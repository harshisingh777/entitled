"use client";

import { useRef, useState } from "react";
import { Camera, Check, MapPin, ShieldCheck, Timer, Unlock, X } from "lucide-react";
import { api, HouseholdState, TurnResult } from "@/lib/api";
import { readDocument } from "@/lib/readDocument";

const SAMPLES = [
  { file: "ration_card.jpg", label: "Ration card" },
  { file: "aadhaar.jpg", label: "Aadhaar" },
  { file: "passbook.jpg", label: "Passbook" },
];

const FIELD_LABELS: Record<string, string> = {
  name: "Name", guardian_name: "Husband / father", dob: "Date of birth",
  address: "Address", district: "District", aadhaar_last4: "Aadhaar last 4",
  bank_account: "Account", ifsc: "IFSC",
};

type Props = {
  id: string; state: HouseholdState; busy: boolean;
  run: (work: () => Promise<TurnResult | HouseholdState>) => Promise<void>;
  onNotice: (text: string | null) => void;
};

export function DocumentList({ id, state, busy, run }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [extracted, setExtracted] = useState<Record<string, string> | null>(null);
  const { items, total, have, missing, requested_across_schemes: requested } = state.documents;

  const [reading, setReading] = useState<string | null>(null);
  const [onDevice, setOnDevice] = useState(false);

  async function read(source: Blob | (() => Promise<Blob>), filename: string) {
    await run(async () => {
      const blob = typeof source === "function" ? await source() : source;
      const result = await readDocument(id, blob, filename, setReading);
      setOnDevice(result.extracted.engine === "uniocr_device");
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
        <h2 className="section-title">Send a document photo</h2>
        <p className="muted">Details fill in by themselves. Where the phone can, it reads the photo itself and the photo never leaves it. Only the last 4 Aadhaar digits are stored.</p>
        <input ref={fileRef} type="file" accept="image/*,application/pdf,.pdf" hidden aria-label="Document photo or PDF"
          onChange={(event) => { const file = event.target.files?.[0]; if (file) void read(file, file.name); event.target.value = ""; }} />
        <button type="button" className="btn btn-primary" disabled={busy} onClick={() => fileRef.current?.click()}>
          <Camera size={20} aria-hidden="true" /> Take or choose a photo
        </button>
        {reading && <p className="reading-status" role="status">{reading}</p>}
        <div className="sample-row">
          <span className="muted">Demo samples:</span>
          {SAMPLES.map((item) => (
            <button key={item.file} type="button" className="chip" disabled={busy} onClick={() => void sample(item.file)}>{item.label}</button>
          ))}
        </div>
        {extracted && onDevice && !reading && (
          <p className="device-note"><ShieldCheck size={16} aria-hidden="true" /> Read on this device with UniOCR. The photo never left it.</p>
        )}
        {extracted && (
          <dl className="extracted" aria-live="polite">
            {Object.entries(extracted).map(([key, value]) => (
              <div key={key}><dt>{FIELD_LABELS[key] ?? key}</dt><dd>{value}</dd></div>
            ))}
          </dl>
        )}
      </section>

      {total === 0 ? (
        <p className="empty">Documents will appear here once some schemes are decided.</p>
      ) : (
        <>
          <p className="doc-summary">
            <strong>{`${have} of ${total} ready`}</strong>
            {missing.length > 0 && <span> · {`${missing.length} to get`}</span>}
            <br />
            <small className="muted">{`Schemes ask ${requested} times in all, you give only ${total}.`}</small>
          </p>
          <ul className="doc-list">
            {items.map((doc) => (
              <li key={doc.id} className={`doc doc-${doc.have === true ? "have" : doc.have === false ? "missing" : "unknown"}`} data-testid={`doc-${doc.id}`}>
                <div className="doc-head">
                  <h3>{doc.name.en}</h3>
                  <div className="segmented" role="group" aria-label={doc.name.en}>
                    <button type="button" aria-pressed={doc.have === true} disabled={busy} onClick={() => run(() => api.setDocument(id, doc.id, true))}>
                      <Check size={16} aria-hidden="true" /> Have
                    </button>
                    <button type="button" aria-pressed={doc.have === false} disabled={busy} onClick={() => run(() => api.setDocument(id, doc.id, false))}>
                      <X size={16} aria-hidden="true" /> No
                    </button>
                  </div>
                </div>
                <p className="doc-unlock"><Unlock size={15} aria-hidden="true" /> {`Unlocks ${doc.unlocks.length}:`} {doc.unlocks.map((u) => u.name.en).join(", ")}</p>
                {doc.have !== true && (
                  <p className="doc-where">
                    <span><MapPin size={15} aria-hidden="true" /> {doc.where.en}</span>
                    <span><Timer size={15} aria-hidden="true" /> {doc.time.en}</span>
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
