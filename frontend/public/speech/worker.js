/* On-device speech to text with Whisper (tiny.en, int8) in ONNX Runtime Web, the same engine UniOCR runs on.
 *
 * Used when the browser has no working speech service of its own: Brave and Firefox, or Chrome offline.
 * The recording never leaves the phone; only the words it heard go to the server, as if they had been typed.
 * Features follow OpenAI's Whisper exactly: 16 kHz audio padded to 30 s, a 400-point Hann STFT every 160 samples,
 * 80 Slaney mel bands, log10, clamped to 8 below the peak and scaled by (x + 4) / 4. Decoding is greedy.
 *
 * In:  { type: "load", id } to fetch the model early, or { type: "listen", id, audio: Float32Array (16 kHz mono) }
 * Out: { type: "progress", id, stage, loaded?, total? } then { type: "done", id, text, ms } or { type: "error", id, error }
 */
/* global ort */
importScripts("/ort/ort.wasm.min.js");

ort.env.wasm.wasmPaths = "/ort/";
ort.env.wasm.numThreads = 1; // Threads need cross-origin isolation, and one keeps a phone responsive.
ort.env.logLevel = "error";

const CACHE = "entitled-speech-v1";
// The files are checked before use, so a broken download or a swapped file is never run.
// onnx-community/whisper-tiny.en, int8. The merged decoder carries a key/value cache, so each new word costs one step.
const BASE = "/models/whisper-tiny.en/";
const FILES = {
  vocab: { name: "vocab.json", bytes: 999186, sha256: "f6bd25a65e4e63ca31360e9fb11c7e4f9a391a78385d640acd814092dd6eee4f" },
  encoder: { name: "encoder_model_quantized.onnx", bytes: 10124993, sha256: "e93ec822f16a8fd264e7de972ad17d615ea7334b75a52d54c50c2e18dd503a25" },
  decoder: { name: "decoder_model_merged_quantized.onnx", bytes: 30718858, sha256: "c0592d0749413c960569e1c7fb806b060d5d18f3ebad4a95cbf9a77dc6e9be52" },
};
const DOWNLOAD_BYTES = FILES.vocab.bytes + FILES.encoder.bytes + FILES.decoder.bytes;
const LAYERS = 4;
const HEADS = 6;
const HEAD_SIZE = 64;

const RATE = 16000;
const N_FFT = 400;
const HOP = 160;
const BINS = N_FFT / 2 + 1;
const MELS = 80;
const FRAMES = 3000; // 30 seconds
const SAMPLES = FRAMES * HOP;

const START = 50257; // <|startoftranscript|>
const NO_TIMESTAMPS = 50362;
const PREVIOUS = 50360; // <|startofprev|>: text Whisper treats as already said, which steers its spelling.
// GPT-2 tokens of: " Raebareli, Lucknow, Kanpur, Varanasi, Prayagraj, Gorakhpur, Ayodhya, Sitapur, Unnao, Amethi, Sultanpur,
// Pratapgarh, Jaunpur, Azamgarh, Ballia, Gonda, Bahraich, Hardoi. BPL card, Antyodaya, Aadhaar, ration card, widow pension,
// yearly income." Made by backend/scripts/whisper_prompt.py. Without it, Raebareli is heard as "Raya Valley".
const PROMPT = [7567, 1765, 533, 4528, 11, 14546, 2197, 11, 14248, 14225, 11, 12372, 15991, 72, 11, 1736, 323, 45429, 73, 11, 19097,
  11322, 14225, 11, 13709, 375, 48812, 11, 21131, 499, 333, 11, 791, 2616, 78, 11, 1703, 2788, 72, 11, 37399, 14225, 11, 1736, 265,
  499, 4563, 71, 11, 449, 1942, 14225, 11, 7578, 321, 4563, 71, 11, 6932, 544, 11, 402, 13533, 11, 13081, 430, 488, 11, 6912, 23013,
  13, 347, 6489, 2657, 11, 3738, 88, 4348, 64, 11, 47727, 11, 36535, 2657, 11, 27075, 13553, 11, 24169, 3739, 13];
const END = 50256; // <|endoftext|>
const MAX_TOKENS = 96;
// From the model's generation_config.json: symbols Whisper should never emit, and what it may not start with.
const SUPPRESS = [1, 2, 7, 8, 9, 10, 14, 25, 26, 27, 28, 29, 31, 58, 59, 60, 61, 62, 63, 90, 91, 92, 93, 357, 366, 438, 532, 685,
  705, 796, 930, 1058, 1220, 1267, 1279, 1303, 1343, 1377, 1391, 1635, 1782, 1875, 2162, 2361, 2488, 3467, 4008, 4211, 4600, 4808,
  5299, 5855, 6329, 7203, 9609, 9959, 10563, 10786, 11420, 11709, 11907, 13163, 13697, 13700, 14808, 15306, 16410, 16791, 17992,
  19203, 19510, 20724, 22305, 22935, 27007, 30109, 30420, 33409, 34949, 40283, 40493, 40549, 47282, 49146];
const BEGIN_SUPPRESS = [220, END];
// Below this loudness the clip is treated as silence. Whisper given silence invents text ("Thank you."), so it is never asked.
const SILENCE_RMS = 0.004;

let loading = null;
let timings = {};

async function fetchCached(url, onProgress) {
  let cache = null;
  try {
    cache = await caches.open(CACHE);
    const hit = await cache.match(url);
    if (hit) return new Uint8Array(await hit.arrayBuffer());
  } catch {
    cache = null; // No Cache API (private window): download every time.
  }
  const response = await fetch(url);
  if (!response.ok || !response.body) throw new Error(`model download failed: ${response.status}`);
  const total = Number(response.headers.get("content-length")) || 0;
  const reader = response.body.getReader();
  const parts = [];
  let loaded = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parts.push(value);
    loaded += value.length;
    onProgress(loaded, total);
  }
  const bytes = new Uint8Array(loaded);
  let offset = 0;
  for (const part of parts) { bytes.set(part, offset); offset += part.length; }
  return { bytes, store: () => cache?.put(url, new Response(bytes, { headers: { "content-type": "application/octet-stream" } })).catch(() => undefined) };
}

async function sha256(bytes) {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return Array.from(digest, (b) => b.toString(16).padStart(2, "0")).join("");
}

async function fetchVerified(file, onProgress) {
  const url = BASE + file.name;
  const got = await fetchCached(url, onProgress);
  const bytes = got instanceof Uint8Array ? got : got.bytes;
  if (await sha256(bytes) !== file.sha256) {
    try { await (await caches.open(CACHE)).delete(url); } catch { /* nothing cached */ }
    throw new Error(`${file.name} failed its checksum`);
  }
  if (!(got instanceof Uint8Array)) await got.store(); // Only a verified file is kept.
  return bytes;
}

/** GPT-2's byte-level BPE writes each byte as a printable character. This undoes that. */
function byteDecoder() {
  const bytes = [];
  for (let b = 33; b <= 126; b++) bytes.push(b);
  for (let b = 161; b <= 172; b++) bytes.push(b);
  for (let b = 174; b <= 255; b++) bytes.push(b);
  const chars = bytes.slice();
  let extra = 0;
  for (let b = 0; b < 256; b++) {
    if (!bytes.includes(b)) { bytes.push(b); chars.push(256 + extra++); }
  }
  const map = new Map();
  bytes.forEach((b, i) => map.set(String.fromCharCode(chars[i]), b));
  return map;
}

/** Slaney-style mel filters, as librosa.filters.mel(sr=16000, n_fft=400, n_mels=80) builds them for Whisper. */
function melFilters() {
  const toMel = (hz) => (hz < 1000 ? (3 * hz) / 200 : 15 + Math.log(hz / 1000) / (Math.log(6.4) / 27));
  const toHz = (mel) => (mel < 15 ? (200 * mel) / 3 : 1000 * Math.exp((Math.log(6.4) / 27) * (mel - 15)));
  const top = toMel(RATE / 2);
  const points = Array.from({ length: MELS + 2 }, (_, i) => toHz((top * i) / (MELS + 1)));
  const filters = new Float32Array(MELS * BINS);
  for (let m = 0; m < MELS; m++) {
    const [low, centre, high] = [points[m], points[m + 1], points[m + 2]];
    const norm = 2 / (high - low);
    for (let k = 0; k < BINS; k++) {
      const hz = (k * RATE) / N_FFT;
      const weight = Math.max(0, Math.min((hz - low) / (centre - low), (high - hz) / (high - centre)));
      filters[m * BINS + k] = weight * norm;
    }
  }
  return filters;
}

function spectrumTables() {
  const window = new Float32Array(N_FFT);
  for (let i = 0; i < N_FFT; i++) window[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / N_FFT); // periodic Hann
  const cos = new Float32Array(BINS * N_FFT);
  const sin = new Float32Array(BINS * N_FFT);
  for (let k = 0; k < BINS; k++) {
    for (let n = 0; n < N_FFT; n++) {
      const angle = (2 * Math.PI * k * n) / N_FFT;
      cos[k * N_FFT + n] = Math.cos(angle);
      sin[k * N_FFT + n] = Math.sin(angle);
    }
  }
  return { window, cos, sin };
}

/** Whisper's log-mel input, shape [80, 3000]. Frames past the end of the speech are silence and are computed once. */
function logMel(audio, tables, filters) {
  const padded = new Float32Array(SAMPLES);
  padded.set(audio.subarray(0, SAMPLES));
  const half = N_FFT / 2;
  // torch.stft(center=True) reflects the signal at both ends.
  const at = (i) => padded[i < 0 ? -i : i >= SAMPLES ? 2 * (SAMPLES - 1) - i : i];
  const spoken = Math.min(FRAMES, Math.ceil((audio.length + half) / HOP) + 1);
  const mel = new Float32Array(MELS * FRAMES);
  const frame = new Float32Array(N_FFT);
  const power = new Float32Array(BINS);
  let silentColumn = null;
  for (let t = 0; t < FRAMES; t++) {
    if (t >= spoken && silentColumn) {
      for (let m = 0; m < MELS; m++) mel[m * FRAMES + t] = silentColumn[m];
      continue;
    }
    const start = t * HOP - half;
    for (let n = 0; n < N_FFT; n++) frame[n] = at(start + n) * tables.window[n];
    for (let k = 0; k < BINS; k++) {
      let re = 0;
      let im = 0;
      const row = k * N_FFT;
      for (let n = 0; n < N_FFT; n++) { re += frame[n] * tables.cos[row + n]; im -= frame[n] * tables.sin[row + n]; }
      power[k] = re * re + im * im;
    }
    for (let m = 0; m < MELS; m++) {
      let sum = 0;
      const row = m * BINS;
      for (let k = 0; k < BINS; k++) sum += filters[row + k] * power[k];
      mel[m * FRAMES + t] = Math.log10(Math.max(sum, 1e-10));
    }
    if (t >= spoken) silentColumn = Array.from({ length: MELS }, (_, m) => mel[m * FRAMES + t]);
  }
  let peak = -Infinity;
  for (const v of mel) if (v > peak) peak = v;
  for (let i = 0; i < mel.length; i++) mel[i] = (Math.max(mel[i], peak - 8) + 4) / 4;
  return mel;
}

function trimSilence(audio) {
  // Leading and trailing quiet is cut so a long pause before speaking does not push words past 30 s.
  const block = RATE / 50;
  const loud = (i) => {
    let sum = 0;
    for (let j = i; j < Math.min(audio.length, i + block); j++) sum += audio[j] * audio[j];
    return Math.sqrt(sum / block) > SILENCE_RMS;
  };
  let first = 0;
  while (first < audio.length && !loud(first)) first += block;
  let last = audio.length;
  while (last > first && !loud(Math.max(first, last - block))) last -= block;
  if (first >= last) return null;
  return audio.subarray(Math.max(0, first - RATE / 5), Math.min(audio.length, last + RATE / 5));
}

async function load(post) {
  const report = (offset) => (loaded) => post({ type: "progress", stage: "download", loaded: offset + loaded, total: DOWNLOAD_BYTES });
  const vocab = await fetchVerified(FILES.vocab, report(0));
  const encoderBytes = await fetchVerified(FILES.encoder, report(FILES.vocab.bytes));
  const decoderBytes = await fetchVerified(FILES.decoder, report(FILES.vocab.bytes + FILES.encoder.bytes));
  post({ type: "progress", stage: "prepare" });
  const options = { executionProviders: ["wasm"], graphOptimizationLevel: "all" };
  const encoder = await ort.InferenceSession.create(encoderBytes, options);
  const decoder = await ort.InferenceSession.create(decoderBytes, options);
  const tokens = [];
  for (const [token, id] of Object.entries(JSON.parse(new TextDecoder().decode(vocab)))) tokens[id] = token;
  return { encoder, decoder, tokens, bytes: byteDecoder(), tables: spectrumTables(), filters: melFilters() };
}

function detokenize(model, ids) {
  const out = [];
  for (const id of ids) {
    for (const char of model.tokens[id] ?? "") {
      const byte = model.bytes.get(char);
      if (byte !== undefined) out.push(byte);
    }
  }
  return new TextDecoder().decode(new Uint8Array(out)).trim();
}

/** The most likely next token, with the symbols Whisper must not produce taken out. */
function pick(logits, first) {
  const vocab = logits.dims[2];
  const rows = logits.dims[1];
  const last = logits.data.subarray((rows - 1) * vocab, rows * vocab);
  for (const id of SUPPRESS) last[id] = -Infinity;
  for (let id = START; id < vocab; id++) last[id] = -Infinity; // special and timestamp tokens
  if (first) for (const id of BEGIN_SUPPRESS) last[id] = -Infinity;
  let best = 0;
  for (let id = 1; id < vocab; id++) if (last[id] > last[best]) best = id;
  return best;
}

async function transcribe(model, audio, prompted) {
  const speech = trimSilence(audio);
  if (!speech) return "";
  let clock = performance.now();
  const lap = (name) => { const now = performance.now(); timings[name] = Math.round(now - clock); clock = now; };
  const features = logMel(speech, model.tables, model.filters);
  lap("features");
  const encoded = await model.encoder.run({ input_features: new ort.Tensor("float32", features, [1, MELS, FRAMES]) });
  const states = encoded.last_hidden_state;
  lap("encode");

  // The first pass reads the prompt and start tokens. After that each step feeds one token and the cached keys and values.
  const empty = () => new ort.Tensor("float32", new Float32Array(0), [1, HEADS, 0, HEAD_SIZE]);
  const past = {};
  for (let layer = 0; layer < LAYERS; layer++) {
    for (const part of ["decoder.key", "decoder.value", "encoder.key", "encoder.value"]) past[`past_key_values.${layer}.${part}`] = empty();
  }
  let input = [...(prompted ? [PREVIOUS, ...PROMPT] : []), START, NO_TIMESTAMPS];
  const said = [];
  for (let step = 0; step < MAX_TOKENS; step++) {
    const outputs = await model.decoder.run({
      input_ids: new ort.Tensor("int64", BigInt64Array.from(input, BigInt), [1, input.length]),
      encoder_hidden_states: states,
      use_cache_branch: new ort.Tensor("bool", [step > 0], [1]),
      ...past,
    });
    const best = pick(outputs.logits, step === 0);
    for (let layer = 0; layer < LAYERS; layer++) {
      for (const part of ["decoder.key", "decoder.value"]) past[`past_key_values.${layer}.${part}`] = outputs[`present.${layer}.${part}`];
      // The encoder's keys and values are worked out on the first pass and stay the same for the rest.
      if (step === 0) for (const part of ["encoder.key", "encoder.value"]) past[`past_key_values.${layer}.${part}`] = outputs[`present.${layer}.${part}`];
    }
    if (best === END) break;
    // A model stuck on one token would otherwise fill the whole budget.
    if (said.length >= 6 && said.slice(-6).every((id) => id === best)) break;
    said.push(best);
    input = [best];
  }
  lap("decode");
  timings.tokens = said.length;
  return detokenize(model, said);
}

self.onmessage = async (event) => {
  const { type, id, audio, prompted = true } = event.data;
  const post = (message) => self.postMessage({ id, ...message });
  try {
    loading ??= load(post);
    const model = await loading.catch((error) => { loading = null; throw error; });
    if (type === "load") return post({ type: "done", text: "", ms: 0 });
    const started = performance.now();
    post({ type: "progress", stage: "listen" });
    timings = {};
    const text = await transcribe(model, audio, prompted);
    post({ type: "done", text, ms: Math.round(performance.now() - started), timings });
  } catch (error) {
    post({ type: "error", error: String(error?.message || error) });
  }
};
