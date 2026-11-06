/* On-device document reading with UniOCR (uniocr_mobile.bin): PP-OCRv6 detection and recognition in ONNX Runtime Web.
 *
 * The photo never leaves the phone. This worker returns text rows, and the page masks an Aadhaar number to its
 * last 4 digits before anything is sent. Pre- and post-processing follow RapidOCR 3.10, which UniOCR is built on:
 * BGR input scaled to [-1, 1], DB post-processing on the probability map, and greedy CTC decoding over the
 * vocabulary embedded in the recognizer's metadata.
 *
 * In:  { type: "read", id, file: Blob, model: url }
 * Out: { type: "progress", id, stage, loaded?, total? } then { type: "done", id, rows, ms } or { type: "error", id, error }
 */
/* global ort, fflate */
importScripts("/ort/ort.wasm.min.js", "/ort/fflate.min.js");

ort.env.wasm.wasmPaths = "/ort/";
ort.env.wasm.numThreads = 1; // Threads need cross-origin isolation, and one keeps a phone responsive.
ort.env.logLevel = "error";

const CACHE = "entitled-ocr-v1";
const MAX_SIDE = 1600; // UniOCR's tuned detection size, downscale only.
const DET = { thresh: 0.3, boxThresh: 0.5, unclipRatio: 1.6, minSize: 3, maxCandidates: 1000 };
const REC_HEIGHT = 48;
const REC_MIN_RATIO = 320 / 48;
const TEXT_SCORE = 0.5;

let loading = null;

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
  if (cache) {
    try { await cache.put(url, new Response(bytes, { headers: { "content-type": "application/octet-stream" } })); } catch { /* quota */ }
  }
  return bytes;
}

async function sha256(bytes) {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return Array.from(digest, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Reads ModelProto.metadata_props (field 14) without a protobuf library: the recognizer's vocabulary lives there. */
function onnxMetadata(bytes) {
  let pos = 0;
  const varint = () => {
    let result = 0, shift = 0, byte;
    do { byte = bytes[pos++]; result += (byte & 0x7f) * 2 ** shift; shift += 7; } while (byte & 0x80);
    return result;
  };
  const skip = (wire) => {
    if (wire === 0) varint();
    else if (wire === 1) pos += 8;
    else if (wire === 2) { const length = varint(); pos += length; } // Not pos += varint(): that reads pos first.
    else if (wire === 5) pos += 4;
    else throw new Error("unexpected protobuf wire type");
  };
  const text = new TextDecoder();
  const meta = {};
  while (pos < bytes.length) {
    const key = varint();
    const field = Math.floor(key / 8), wire = key & 7;
    if (field === 14 && wire === 2) {
      const end = varint() + pos;
      let k = "", v = "";
      while (pos < end) {
        const inner = varint();
        const len = varint();
        const s = text.decode(bytes.subarray(pos, pos + len));
        pos += len;
        if (inner >> 3 === 1) k = s; else if (inner >> 3 === 2) v = s;
      }
      meta[k] = v;
    } else {
      skip(wire);
    }
  }
  return meta;
}

async function loadModels(modelUrl, progress) {
  const bundle = await fetchCached(modelUrl, (loaded, total) => progress({ stage: "download", loaded, total }));
  progress({ stage: "prepare" });
  const files = fflate.unzipSync(bundle, { filter: (f) => f.name === "manifest.json" || /PP-OCRv6_(det|rec)_small\.onnx$/.test(f.name) });
  const manifest = JSON.parse(new TextDecoder().decode(files["manifest.json"]));
  for (const name of ["PP-OCRv6_det_small.onnx", "PP-OCRv6_rec_small.onnx"]) {
    if (!files[name] || (await sha256(files[name])) !== manifest.files[name].sha256) {
      try { await (await caches.open(CACHE)).delete(modelUrl); } catch { /* nothing cached */ }
      throw new Error(`model file ${name} failed its checksum`);
    }
  }
  const characters = onnxMetadata(files["PP-OCRv6_rec_small.onnx"]).character;
  if (!characters) throw new Error("recognizer has no vocabulary");
  const vocab = ["blank", ...characters.split("\n"), " "];
  const options = { executionProviders: ["wasm"], graphOptimizationLevel: "all" };
  const det = await ort.InferenceSession.create(files["PP-OCRv6_det_small.onnx"], options);
  const rec = await ort.InferenceSession.create(files["PP-OCRv6_rec_small.onnx"], options);
  return { det, rec, vocab };
}

function canvasOf(width, height) {
  const canvas = new OffscreenCanvas(width, height);
  const context = canvas.getContext("2d", { willReadFrequently: true });
  return { canvas, context };
}

/** Pixels to a [1, 3, h, w] tensor in BGR order, scaled to [-1, 1], padded with zeros to padWidth. */
function toTensor(context, width, height, padWidth = width) {
  const pixels = context.getImageData(0, 0, width, height).data;
  const plane = height * padWidth;
  const data = new Float32Array(3 * plane);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4, o = y * padWidth + x;
      data[o] = pixels[i + 2] / 127.5 - 1;
      data[plane + o] = pixels[i + 1] / 127.5 - 1;
      data[2 * plane + o] = pixels[i] / 127.5 - 1;
    }
  }
  return new ort.Tensor("float32", data, [1, 3, height, padWidth]);
}

async function detect(models, source) {
  const { width: w, height: h } = source.canvas;
  const dw = Math.max(32, Math.round(w / 32) * 32), dh = Math.max(32, Math.round(h / 32) * 32);
  const scaled = canvasOf(dw, dh);
  scaled.context.drawImage(source.canvas, 0, 0, dw, dh);
  const feeds = { [models.det.inputNames[0]]: toTensor(scaled.context, dw, dh) };
  const output = (await models.det.run(feeds))[models.det.outputNames[0]];
  const prob = output.data;
  const [mh, mw] = [output.dims[2], output.dims[3]];

  // Threshold, then a 2x2 dilation as in RapidOCR, then 8-connected regions.
  const mask = new Uint8Array(mh * mw);
  for (let y = 0; y < mh; y++) {
    for (let x = 0; x < mw; x++) {
      const at = (yy, xx) => yy >= 0 && xx >= 0 && prob[yy * mw + xx] > DET.thresh;
      mask[y * mw + x] = at(y, x) || at(y - 1, x) || at(y, x - 1) || at(y - 1, x - 1) ? 1 : 0;
    }
  }
  const label = new Int32Array(mh * mw);
  const stack = new Int32Array(mh * mw);
  const boxes = [];
  let next = 0;
  for (let start = 0; start < mask.length && boxes.length < DET.maxCandidates; start++) {
    if (!mask[start] || label[start]) continue;
    next += 1;
    let top = 0, minX = mw, minY = mh, maxX = -1, maxY = -1;
    stack[top++] = start;
    label[start] = next;
    while (top) {
      const p = stack[--top], py = (p / mw) | 0, px = p - py * mw;
      if (px < minX) minX = px; if (px > maxX) maxX = px;
      if (py < minY) minY = py; if (py > maxY) maxY = py;
      for (let dy = -1; dy <= 1; dy++) {
        for (let dx = -1; dx <= 1; dx++) {
          const ny = py + dy, nx = px + dx;
          if (ny < 0 || nx < 0 || ny >= mh || nx >= mw) continue;
          const q = ny * mw + nx;
          if (mask[q] && !label[q]) { label[q] = next; stack[top++] = q; }
        }
      }
    }
    const bw = maxX - minX + 1, bh = maxY - minY + 1;
    if (Math.min(bw, bh) < DET.minSize) continue;
    let sum = 0;
    for (let y = minY; y <= maxY; y++) for (let x = minX; x <= maxX; x++) sum += prob[y * mw + x];
    if (sum / (bw * bh) < DET.boxThresh) continue;
    const grow = (bw * bh * DET.unclipRatio) / (2 * (bw + bh));
    if (Math.min(bw, bh) + 2 * grow < DET.minSize + 2) continue;
    const sx = w / mw, sy = h / mh;
    boxes.push({
      left: Math.max(0, (minX - grow) * sx), top: Math.max(0, (minY - grow) * sy),
      right: Math.min(w, (maxX + 1 + grow) * sx), bottom: Math.min(h, (maxY + 1 + grow) * sy),
    });
  }
  return boxes;
}

async function recognize(models, source, box) {
  const bw = Math.round(box.right - box.left), bh = Math.round(box.bottom - box.top);
  if (bw < 2 || bh < 2) return null;
  const ratio = bw / bh;
  const padWidth = Math.floor(REC_HEIGHT * Math.max(REC_MIN_RATIO, ratio));
  const width = Math.min(padWidth, Math.ceil(REC_HEIGHT * ratio));
  const line = canvasOf(width, REC_HEIGHT);
  line.context.drawImage(source.canvas, box.left, box.top, bw, bh, 0, 0, width, REC_HEIGHT);
  const feeds = { [models.rec.inputNames[0]]: toTensor(line.context, width, REC_HEIGHT, padWidth) };
  const output = (await models.rec.run(feeds))[models.rec.outputNames[0]];
  const [, steps, classes] = output.dims;
  const probs = output.data;
  let text = "", total = 0, count = 0, previous = -1;
  for (let t = 0; t < steps; t++) {
    let best = 0, bestP = -1;
    for (let c = 0; c < classes; c++) {
      const p = probs[t * classes + c];
      if (p > bestP) { bestP = p; best = c; }
    }
    if (best !== 0 && best !== previous) { text += models.vocab[best] ?? ""; total += bestP; count += 1; }
    previous = best;
  }
  const score = count ? total / count : 0;
  return score >= TEXT_SCORE && text.trim() ? { ...box, text: text.trim(), score } : null;
}

/** Labels and values that sit on one visual row become one line, read left to right. */
function toRows(reads) {
  reads.sort((a, b) => a.top - b.top || a.left - b.left);
  const rows = [];
  for (const item of reads) {
    const centre = (item.top + item.bottom) / 2;
    const row = rows[rows.length - 1];
    if (row && row[0].top <= centre && centre <= row[0].bottom) row.push(item);
    else rows.push([item]);
  }
  return rows.map((row) => row.sort((a, b) => a.left - b.left).map((r) => r.text).join(" "));
}

self.onmessage = async (event) => {
  const { id, file, model } = event.data;
  const progress = (extra) => self.postMessage({ type: "progress", id, ...extra });
  const started = performance.now();
  try {
    loading = loading || loadModels(model, progress);
    let models;
    try {
      models = await loading;
    } catch (error) {
      loading = null; // A failed download may succeed next time.
      throw error;
    }
    progress({ stage: "read" });
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    const source = canvasOf(Math.round(bitmap.width * scale), Math.round(bitmap.height * scale));
    source.context.drawImage(bitmap, 0, 0, source.canvas.width, source.canvas.height);
    bitmap.close();
    const boxes = await detect(models, source);
    const reads = [];
    for (const box of boxes) {
      const read = await recognize(models, source, box);
      if (read) reads.push(read);
    }
    self.postMessage({ type: "done", id, rows: toRows(reads), ms: Math.round(performance.now() - started) });
  } catch (error) {
    self.postMessage({ type: "error", id, error: String(error && error.message ? error.message : error) });
  }
};
