/**
 * Reads a document photo on the person's own phone with UniOCR (public/models/uniocr_mobile.bin).
 * The photo never leaves the device: only text rows go to the server, with any Aadhaar number cut to its last 4 digits.
 * The server's reader stays as the fallback, for old browsers, slow connections and Hindi documents.
 */
import { readPref } from "./prefs";

export const MODEL_URL = "/models/uniocr_mobile.bin";
const MODEL_CACHE = "entitled-ocr-v1";
const READ_TIMEOUT_MS = 180_000; // Includes the one-time model download on a slow connection.
export const DOWNLOAD_MB = 41; // The model bundle plus the ONNX Runtime engine.

export type DeviceProgress = { stage: "download" | "prepare" | "read"; loaded?: number; total?: number };

type Connection = { saveData?: boolean; effectiveType?: string };

let worker: Worker | null = null;
let nextId = 0;
let failedHere = false;

async function modelCached(): Promise<boolean> {
  try {
    return Boolean(await (await caches.open(MODEL_CACHE)).match(MODEL_URL));
  } catch {
    return false;
  }
}

/** On-device reading needs a modern browser, and a fair connection unless the model is already on the phone. */
export async function canReadOnDevice(): Promise<boolean> {
  if (failedHere || typeof window === "undefined" || readPref("entitled.ocr") === "server") return false;
  if (typeof Worker === "undefined" || typeof OffscreenCanvas === "undefined" || typeof createImageBitmap === "undefined"
    || typeof WebAssembly === "undefined" || !window.isSecureContext) return false;
  const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory;
  if (memory !== undefined && memory < 2) return false;
  if (await modelCached()) return true;
  const connection = (navigator as Navigator & { connection?: Connection }).connection;
  if (connection?.saveData) return false;
  return !connection?.effectiveType || connection.effectiveType === "4g";
}

export function readOnDevice(file: Blob, onProgress: (progress: DeviceProgress) => void): Promise<string[]> {
  worker ??= new Worker("/ocr/worker.js");
  const id = ++nextId;
  const reader = worker;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => finish(new Error("on-device reading timed out")), READ_TIMEOUT_MS);
    function finish(error: Error | null, rows?: string[]) {
      clearTimeout(timer);
      reader.removeEventListener("message", listen);
      reader.removeEventListener("error", crash);
      if (error) {
        failedHere = true; // Once it fails on this phone, the server reads for the rest of the visit.
        worker?.terminate();
        worker = null;
        reject(error);
      } else {
        resolve(rows ?? []);
      }
    }
    function listen(event: MessageEvent) {
      const data = event.data;
      if (data.id !== id) return;
      if (data.type === "progress") onProgress({ stage: data.stage, loaded: data.loaded, total: data.total });
      else if (data.type === "done") finish(null, data.rows);
      else finish(new Error(data.error));
    }
    function crash(event: ErrorEvent) {
      finish(new Error(event.message || "on-device reader crashed"));
    }
    reader.addEventListener("message", listen);
    reader.addEventListener("error", crash);
    reader.postMessage({ type: "read", id, file, model: MODEL_URL });
  });
}

/**
 * Cuts an Aadhaar number to XXXX XXXX 1234 before it leaves the phone. A passbook is left alone,
 * because a 12-digit bank account number looks the same and the form needs all of it.
 */
export function maskAadhaar(rows: string[]): string[] {
  const text = rows.join("\n");
  const passbook = /ifsc|passbook|पासबुक/i.test(text);
  const aadhaar = /aadhaar|aadhar|uidai|आधार/i.test(text) || /\b\d{4}\s\d{4}\s\d{4}\b/.test(text);
  if (passbook || !aadhaar) return rows;
  return rows.map((row) => row.replace(/\b\d{4}\s?\d{4}\s?(\d{4})\b/g, "XXXX XXXX $1"));
}
