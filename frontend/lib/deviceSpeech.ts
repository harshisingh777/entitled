/**
 * Speech to text on the person's own device with Whisper tiny.en (public/speech/worker.js), for browsers whose
 * built-in speech recognition does not work: Brave and Firefox, or any browser offline.
 * The recording never leaves the device. Only the words it heard are sent, exactly as if they had been typed.
 */
export const SPEECH_CACHE = "entitled-speech-v1";
export const SPEECH_MODEL_MB = 42;
const DECODER_URL = "/models/whisper-tiny.en/decoder_model_merged_quantized.onnx";
const TIMEOUT_MS = 240_000; // Includes the one-time model download on a slow connection.

export type SpeechProgress = { stage: "download" | "prepare" | "listen"; loaded?: number; total?: number };

let worker: Worker | null = null;
let nextId = 0;

/** Recording and running the model needs a modern browser in a secure context. */
export function canListenOnDevice(): boolean {
  if (typeof window === "undefined" || !window.isSecureContext) return false;
  if (typeof Worker === "undefined" || typeof WebAssembly === "undefined" || typeof MediaRecorder === "undefined"
    || typeof OfflineAudioContext === "undefined" || !navigator.mediaDevices?.getUserMedia) return false;
  const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory;
  return memory === undefined || memory >= 2;
}

export async function speechModelCached(): Promise<boolean> {
  try {
    return Boolean(await (await caches.open(SPEECH_CACHE)).match(DECODER_URL));
  } catch {
    return false;
  }
}

function ask(message: Record<string, unknown>, onProgress: (progress: SpeechProgress) => void, transfer: Transferable[] = []): Promise<string> {
  worker ??= new Worker("/speech/worker.js");
  const id = ++nextId;
  const listener = worker;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => finish(new Error("on-device speech timed out")), TIMEOUT_MS);
    function finish(error: Error | null, text = "") {
      clearTimeout(timer);
      listener.removeEventListener("message", listen);
      listener.removeEventListener("error", crash);
      if (error) {
        worker?.terminate();
        worker = null;
        reject(error);
      } else {
        resolve(text);
      }
    }
    function listen(event: MessageEvent) {
      const data = event.data;
      // Download progress belongs to whichever request started the download, so it is shown to every waiting request.
      if (data.type === "progress") onProgress({ stage: data.stage, loaded: data.loaded, total: data.total });
      else if (data.id !== id) return;
      else if (data.type === "done") finish(null, data.text);
      else if (data.type === "error") finish(new Error(data.error));
    }
    function crash(event: ErrorEvent) {
      finish(new Error(event.message || "on-device speech crashed"));
    }
    listener.addEventListener("message", listen);
    listener.addEventListener("error", crash);
    listener.postMessage({ ...message, id }, transfer);
  });
}

/** Starts the model download while the person is still speaking, so it is often ready by the time they stop. */
export function prepareSpeech(onProgress: (progress: SpeechProgress) => void): Promise<void> {
  return ask({ type: "load" }, onProgress).then(() => undefined);
}

/** Decodes a recording to the 16 kHz mono samples Whisper reads. */
export async function toSamples(recording: Blob): Promise<Float32Array> {
  const decoded = await new OfflineAudioContext(1, 1, 16000).decodeAudioData(await recording.arrayBuffer());
  if (decoded.numberOfChannels === 1) return decoded.getChannelData(0).slice();
  const mono = new Float32Array(decoded.length);
  for (let channel = 0; channel < decoded.numberOfChannels; channel++) {
    const data = decoded.getChannelData(channel);
    for (let i = 0; i < data.length; i++) mono[i] += data[i] / decoded.numberOfChannels;
  }
  return mono;
}

export async function transcribeOnDevice(recording: Blob, onProgress: (progress: SpeechProgress) => void): Promise<string> {
  const audio = await toSamples(recording);
  return ask({ type: "listen", audio }, onProgress, [audio.buffer]);
}
