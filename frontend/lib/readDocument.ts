import { api, ApiError, TurnResult } from "./api";
import { canReadOnDevice, DeviceProgress, DOWNLOAD_MB, maskAadhaar, readOnDevice } from "./deviceOcr";

export type DocumentResult = TurnResult & { extracted: { doc_type: string | null; fields: Record<string, string>; engine: string } };

function describe(progress: DeviceProgress): string {
  if (progress.stage === "download") {
    const total = progress.total ? Math.round(progress.total / 1e6) : DOWNLOAD_MB;
    return `Getting the reader onto this device, ${Math.round((progress.loaded ?? 0) / 1e6)} of ${total} MB. This happens once.`;
  }
  return progress.stage === "prepare" ? "Starting the reader on this device…" : "Reading on this device…";
}

/**
 * Reads a document on the person's phone where it can, and on the server otherwise.
 * The server also gets the photo when the phone's reader found nothing it recognised, which is usually a Hindi
 * document: the phone's model reads Latin script, and the server adds a Devanagari reader.
 */
export async function readDocument(id: string, file: Blob, filename: string, onStatus: (text: string | null) => void): Promise<DocumentResult> {
  try {
    const isImage = file.type.startsWith("image/") || /\.(jpe?g|png|webp)$/i.test(filename);
    if (isImage && await canReadOnDevice()) {
      try {
        const rows = maskAadhaar(await readOnDevice(file, (progress) => onStatus(describe(progress))));
        const result = await api.ocrText(id, rows);
        if (!("needs_image" in result)) return result;
      } catch (error) {
        if (error instanceof ApiError) throw error;
        // The device could not run the reader, so the server reads the photo instead.
      }
    }
    onStatus("Reading on the server…");
    return await api.ocr(id, file, filename);
  } finally {
    onStatus(null);
  }
}
