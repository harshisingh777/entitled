// Copies ONNX Runtime Web and fflate out of node_modules so the on-device reader can load them as plain files.
// They are served from our own origin, so reading works offline once cached and needs no third-party CDN.
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "public", "ort");
mkdirSync(out, { recursive: true });
const ort = join(root, "node_modules", "onnxruntime-web", "dist");
for (const file of ["ort.wasm.min.js", "ort-wasm-simd-threaded.mjs", "ort-wasm-simd-threaded.wasm"]) {
  copyFileSync(join(ort, file), join(out, file));
}
copyFileSync(join(root, "node_modules", "fflate", "umd", "index.js"), join(out, "fflate.min.js"));
console.log("on-device OCR runtime copied to public/ort");
