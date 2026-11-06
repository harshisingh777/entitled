"""
UniOCR v2 — universal offline OCR engine, by Gaurav Tiwari. Vendored into Entitled.

Changes from the standalone engine: the dashboard server and CLI are removed (Entitled has its own API),
the repair layer is imported from this package, and configure() lets a small server use fewer threads and
a smaller detection size. Entitled calls _extract(img, repair=False): the dictionary repair layer is built
for notes and would rewrite names on identity documents (Kamla -> Kamala).

Stack (chosen after benchmarking, see README):
  * Text detection:  PP-OCRv6 det small  (9.6 MB ONNX)
  * Orientation:      PP-OCR cls mobile  (0.6 MB ONNX, handles 180° photos)
  * Recognition:      PP-OCRv6 rec small (20.7 MB ONNX, 50 languages)
  * Runtime:          onnxruntime — no GPU, no framework, no network.

All three ONNX models ship inside the rapidocr wheel, so once
`pip install -r requirements.txt` has run, everything works with the
network cable pulled out.

Measured on the synthetic bench in engine/tests (clean print, dark-mode
screenshot, phone-photo warp+noise+JPEG, heavy blur, handwriting-style,
degraded cursive, mixed page):  99.9% corpus character accuracy,
99.1% corpus word accuracy, ~1 s per page on CPU.

CLI:
    python ocr_engine.py test --file image_or_pdf
    python ocr_engine.py serve              # dashboard + API on :8000
"""
import io
import os
import re

import numpy as np
from PIL import Image

from rapidocr import RapidOCR

# Tuned on the bench: downscale-only detection at 1600 px keeps large
# scans fast and recovers lines the default (736/min) misses on photos.
PARAMS = {"Det.limit_side_len": 1600, "Det.limit_type": "max"}

_here = os.path.dirname(os.path.abspath(__file__))

_reader = None
_dev_reader = None
_repair = None


def configure(params: dict) -> None:
    """Overrides engine settings. Call before the first read: engines are built once and kept."""
    global _reader, _dev_reader
    PARAMS.update(params)
    _reader = _dev_reader = None


def get_engine():
    global _reader
    if _reader is None:
        _reader = RapidOCR(params=PARAMS)
    return _reader


def _get_dev_engine():
    """Second recognition model for Devanagari (Hindi script). Loaded lazily."""
    global _dev_reader
    if _dev_reader is None:
        from rapidocr.utils.typings import ModelType, OCRVersion
        params = {
            "Rec.lang_type": "devanagari",
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_type": ModelType.MOBILE,
        }
        # repo-local model file (7.6 MB, committed) keeps a fresh clone
        # fully offline; falls back to the packaged cache otherwise
        # Same detection and thread settings as the main pass, so its boxes line up and a large photo stays small.
        params.update({k: v for k, v in PARAMS.items() if not k.startswith("Rec.")})
        local = os.path.join(_here, "models", "devanagari_PP-OCRv5_rec_mobile.onnx")
        if os.path.exists(local):
            params["Rec.model_path"] = local
        _dev_reader = RapidOCR(params=params)
    return _dev_reader


def _get_repair():
    """Evidence-gated repair layer (math + dictionary + Hinglish)."""
    global _repair
    if _repair is None:
        from . import repair_layer
        _repair = repair_layer
    return _repair


def _crop_line(img: Image.Image, box, pad: int = 4) -> Image.Image:
    """Crop a detected quad (as a padded bbox) from a PIL image."""
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    x0 = max(0, int(min(xs)) - pad)
    y0 = max(0, int(min(ys)) - pad)
    x1 = min(img.width, int(max(xs)) + pad)
    y1 = min(img.height, int(max(ys)) + pad)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return img.crop((x0, y0, x1, y1))


_TAG_RE = re.compile(r"^\[[A-Za-z]{2,6}\]$")


_CODE_FMT_RE = re.compile(
    r"[;{}]|^#|<\w+\.h>|^[A-Za-z_][\w\s]*\([^()]*\)\s*\{?\s*$")


def _line_kind(t, rl):
    """Classify a repaired line for document formatting.

    Code needs STRUCTURE (a semicolon, a brace, a preprocessor line, an
    include, or a bare function signature) — prose that merely contains a
    parenthesis ('Engg (3rd year)') is never code.
    """
    if _TAG_RE.match(t):
        return "tag"
    if _Q_MARK_RE.match(t):
        return "qnum"
    if _OPT_MARK_RE.match(t):
        return "opt"
    if _CODE_FMT_RE.search(t):
        return "code"
    return "prose"


def _alnum_ratio(t: str) -> float:
    t = t.strip()
    if not t:
        return 1.0
    return sum(ch.isalnum() for ch in t) / len(t)


def _dedup_reads(items):
    """Drop symbol-soup duplicate boxes.

    A failed line recognition sometimes emits a WIDE symbols-only box that
    horizontally contains a clean read of the same line ('-(+)+)' over
    'return 0;'). The clean read wins; the soup is dropped. A genuinely
    separate short line is never affected — it does not contain another
    full line's box.
    """
    n = len(items)
    drop = set()
    for i in range(n):
        ti = items[i][0].strip()
        if len(ti) < 3 or _alnum_ratio(ti) >= 0.4:
            continue                          # only symbol-soup candidates
        gi = _bbox(items[i][2])
        for j in range(n):
            if i == j or j in drop:
                continue
            tj = items[j][0].strip()
            if len(tj) < 2 or _alnum_ratio(tj) < 0.5:
                continue                     # need a clean read to keep
            gj = _bbox(items[j][2])
            if gj[0] >= gi[0] and gj[2] <= gi[2]:
                if min(gi[3], gj[3]) - max(gi[1], gj[1]) > 1:
                    drop.add(i)
                    break
    return [it for k, it in enumerate(items) if k not in drop]


def _format_paper(raw):
    """Final human-readable arrangement for question papers and worksheets.

    Every question becomes its own block: a blank line before it, the
    [MCQ]-style tag joined onto the question line, code lines indented as
    a code block, answer options indented under their question. Pages
    with no tags or question numbers (plain notes, prose) pass through
    untouched; bills are never formatted (bill rows stay as read).
    """
    rl = _get_repair()
    kinds = [(_line_kind(t, rl), t, s, b) for t, s, b in raw]
    if not any(k in ("tag", "qnum") for k, _, _, _ in kinds):
        return raw
    out = []
    n = len(kinds)
    i = 0
    while i < n:
        k, t, s, b = kinds[i]
        if t == "":                             # column break
            if out and out[-1][0] != "":
                out.append(("", 1.0, b))
            i += 1
            continue
        if k in ("tag", "qnum"):
            if out and out[-1][0] != "":
                out.append(("", 1.0, b))
            head, score, box = t, s, b
            # join a tag onto the question line it labels
            if k == "tag" and i + 1 < n and kinds[i + 1][1] != "" \
                    and kinds[i + 1][0] in ("qnum", "prose"):
                k2, t2, s2, b2 = kinds[i + 1]
                head = f"{t} {t2}"
                score = min(s, s2)
                box = np.vstack([np.asarray(b, dtype=float),
                                 np.asarray(b2, dtype=float)]).tolist()
                i += 1
            out.append((head, score, box))
            i += 1
            continue
        if k == "code":
            out.append(("    " + t, s, b))
        elif k == "opt":
            out.append(("  " + t, s, b))
        else:
            out.append((t, s, b))
        i += 1
    return out


def _extract(img: Image.Image, repair: bool = True):
    """Run OCR on a PIL image. Returns (full_text, details)."""
    eng = get_engine()
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    out = eng(img)

    lines, details = [], []
    if out is not None and out.txts:
        items = _merge_scripts(img, out, eng)
        items = _dedup_reads(items)
        items = _hmerge_math(items)
        items = _fraction_join(items, _dark_map(img))
        items = _arrange(items, img.width)
        bill = sum(1 for t, _, _ in items if _BILL_RE.search(t)) >= 2
        raw = []
        for txt, score, box in items:
            if txt == "":                       # column-break sentinel
                raw.append(("", float(score), box))
                continue
            txt = txt.strip()
            if not txt:
                continue
            if repair:
                txt = _get_repair().repair_line(txt)
            raw.append((txt, float(score), box))
        if not bill:
            raw = _format_paper(raw)
        for txt, score, box in raw:
            if txt == "":
                if lines and lines[-1] != "":
                    lines.append("")
                continue
            lines.append(txt)
            details.append({
                "text": txt,
                "confidence": round(float(score) * 100, 1),
                "box": np.asarray(box, dtype=int).tolist(),
            })
    return "\n".join(lines), details


def _box_center(box):
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return (sum(xs) / 4.0, sum(ys) / 4.0)


def _merge_scripts(img, out_def, eng_def):
    """Best-of-both recognition passes (Latin v6 + Devanagari v5).

    Fast path: every line confident -> Latin output as-is.
    Otherwise: run the same detection with the Devanagari recognizer and,
    for each box, keep the higher-scoring read.
    """
    items = list(zip(out_def.txts, out_def.scores, out_def.boxes))
    if not items or min(s for _, s, _ in items) >= 0.80:
        return items

    try:
        out_dev = _get_dev_engine()(img)
    except Exception:
        return items
    if not out_dev or not out_dev.txts:
        return items

    dev_items = list(zip(out_dev.txts, out_dev.scores, out_dev.boxes))
    h = np.median([max(p[1] for p in b) - min(p[1] for p in b) for _, _, b in items]) \
        if items else 40

    merged = []
    for txt, score, box in items:
        cx, cy = _box_center(box)
        best_txt, best_score = txt, score
        for dtxt, dscore, dbox in dev_items:
            # script evidence: only genuine Devanagari reads can replace a
            # Latin read (the dev model confabulates Latin-looking junk at
            # high confidence on cursive English).
            if not _has_devanagari(dtxt):
                continue
            dx, dy = _box_center(dbox)
            if abs(dx - cx) <= h and abs(dy - cy) <= h * 0.6 and dscore > best_score:
                best_txt, best_score = dtxt, dscore
        merged.append((best_txt, best_score, box))

    # Devanagari lines the default pass dropped entirely (sub-threshold rec)
    for dtxt, dscore, dbox in dev_items:
        if not _has_devanagari(dtxt) or dscore < 0.55:
            continue
        cx, cy = _box_center(dbox)
        near = any(abs(_box_center(b)[0] - cx) <= h and abs(_box_center(b)[1] - cy) <= h * 0.6
                   for _, _, b in items)
        if not near:
            merged.append((dtxt, dscore, dbox))

    return merged


def _has_devanagari(txt: str) -> bool:
    return sum("\u0900" <= ch <= "\u097F" for ch in txt) >= max(2, len(txt) * 0.3)


# ------------------------------------------------------------- fraction stacks
_MATH_FUNCS = {"sin", "cos", "tan", "sec", "cot", "log", "ln", "exp", "lim", "max", "min"}


def _math_dense(t: str) -> bool:
    """Short, word-free fragment — a fraction stack candidate."""
    t = t.strip()
    if not (1 <= len(t) <= 42):
        return False
    if "=" in t or re.match(r"^Q[\.\s]", t):
        return False
    if t.endswith((",", ";")):
        return False          # list items ("12,"), never fraction parts
    if any("\u0900" <= ch <= "\u097F" or "\u4e00" <= ch <= "\u9fff" for ch in t):
        return False          # Devanagari/CJK text is never a math fragment
    if not re.search(r"\d", t):
        # 'e' or 's' alone is math, and so is a differential fragment
        # (d, dt, dCA) — but a three-letter word is not
        return len(t) <= 2 or bool(re.match(r"^d[A-Za-z]{0,4}$", t))
    for m in re.finditer(r"[A-Za-z]+", t):
        if len(m.group(0)) >= 3 and m.group(0).lower() not in _MATH_FUNCS:
            return False
    return True


def _bbox(box):
    xs = [float(p[0]) for p in box]
    ys = [float(p[1]) for p in box]
    return min(xs), min(ys), max(xs), max(ys)


def _stacked(a_box, b_box, relaxed: bool = False) -> bool:
    """True if b sits tightly, centered-ish, below a — a fraction stack.

    relaxed mode allows extra vertical air (some layouts breathe around
    the fraction bar); callers must then also prove a drawn bar.
    """
    ax0, ay0, ax1, ay1 = _bbox(a_box)
    bx0, by0, bx1, by1 = _bbox(b_box)
    ah, bh = ay1 - ay0, by1 - by0
    if ah <= 0 or bh <= 0:
        return False
    if by0 <= ay0 + 0.5 * ah:            # b must start below a's midline
        return False
    gap = by0 - ay1
    air = 1.2 if relaxed else 0.6
    if gap > max(10.0, air * ah) or gap < -0.15 * ah:
        return False
    if bh > 2.2 * ah or ah > 2.2 * bh:   # similar heights
        return False
    overlap = min(ax1, bx1) - max(ax0, bx0)
    if overlap < 0.55 * min(ax1 - ax0, bx1 - bx0):
        return False
    return True


def _hmerge_math(items):
    """Merges math fragments the detector split on one visual line
    (classic case: a superscript read as its own box: 'e' + '-3s')."""
    n = len(items)
    used = [False] * n
    out = []
    for i in range(n):
        if used[i]:
            continue
        t, s, b = items[i]
        if not _math_dense(t):
            out.append((t, s, b))
            continue
        cur_t, cur_s, cur_b = t, s, np.asarray(b, dtype=float)
        for k in range(i + 1, n):
            if used[k]:
                continue
            tk, sk, bk = items[k]
            if not _math_dense(tk):
                break
            ax0, ay0, ax1, ay1 = _bbox(cur_b)
            bx0, by0, bx1, by1 = _bbox(bk)
            ov = min(ay1, by1) - max(ay0, by0)
            min_h = min(ay1 - ay0, by1 - by0)
            x_ov = min(ax1, bx1) - max(ax0, bx0)
            if ov < 0 or x_ov < -max(12.0, 0.6 * min_h):
                break   # vertical overlap = same visual line; none = different lines
            left_t, left_b, right_t, right_b = (
                (cur_t, cur_b, tk, np.asarray(bk, dtype=float)) if ax0 <= bx0
                else (tk, np.asarray(bk, dtype=float), cur_t, cur_b))
            # superscript/exponent continuations start with a sign, digit or
            # power glyph — a '(' starts a NEW term (stacked factor), not one
            if not re.match(r"^[-+\d\u00b0\u00b2\u00b3^]", right_t.strip()):
                break
            # ...and they sit RAISED above the line or are a tiny exponent
            # glyph. Siblings at the same height (side-by-side stacked
            # denominators like '(0.2s + 1)' '0.3s + 1') are separate terms.
            lx0, ly0, lx1, ly1 = _bbox(left_b)
            rx0, ry0, rx1, ry1 = _bbox(right_b)
            raised = (ry0 + ry1) / 2.0 <= (ly0 + ly1) / 2.0 - 2.0
            short = (ry1 - ry0) <= 0.8 * max(1.0, ly1 - ly0)
            if not (raised or short):
                break
            sep = "" if re.match(r"^[-+(\d]", right_t.strip()) else " "
            cur_t = left_t.rstrip() + sep + right_t.strip()
            cur_s = min(cur_s, sk)
            cur_b = np.vstack([cur_b, np.asarray(bk, dtype=float)])
            used[k] = True
        out.append((cur_t, cur_s, cur_b.tolist()))
    return out


def _dark_map(img):
    """Ink map of the page (dark text on light background).

    Threshold 200 — generous on purpose: fraction bars in print are thin
    and anti-aliased (gray ~120-180), and the rectangle guard below is
    what keeps block borders from masquerading as bars.
    """
    g = np.asarray(img.convert("L"))
    if float(g.mean()) < 127.0:          # dark mode: flip polarity
        g = 255 - g
    return g < 200


def _longest_run(row) -> int:
    run = best = 0
    for v in row:
        run = run + 1 if v else 0
        if run > best:
            best = run
    return best


def _bar_between(dark, a_box, b_box) -> bool:
    """True if a horizontal fraction bar is drawn between two boxes.

    This is the visual proof that a stack of fragments is a fraction.
    Block-diagram borders are rejected by the rectangle guard: a border is
    one side of a closed box, so a SECOND long horizontal line (the bottom
    edge) sits inside the denominator's row span; a fraction bar has text
    below it, and text never forms long unbroken runs.
    """
    ax0, ay0, ax1, ay1 = _bbox(a_box)
    bx0, by0, bx1, by1 = _bbox(b_box)
    x_lo, x_hi = int(max(ax0, bx0)), int(min(ax1, bx1))
    if x_hi - x_lo < 6:
        return False
    y_lo = int(max(0, ay1 - 3))
    y_hi = int(min(dark.shape[0] - 1, by0 + 3))
    need = 0.55 * (x_hi - x_lo)
    g_hi = int(min(dark.shape[0] - 1, by1 + max(8, (by1 - by0))))
    for y in range(y_lo, y_hi + 1):
        if _longest_run(dark[y, x_lo:x_hi]) < need:
            continue
        # the bar itself can be a few pixels thick — walk past it first
        y_b = y
        while y_b + 1 <= g_hi and _longest_run(dark[y_b + 1, x_lo:x_hi]) >= need:
            y_b += 1
        # rectangle guard: scan BELOW the bar — a block border is one side
        # of a closed box, so the bottom edge shows up as a second long
        # line inside the denominator's span; under a real bar there is only
        # text, and text never forms long unbroken runs.
        for y2 in range(y_b + 2, g_hi + 1):
            if _longest_run(dark[y2, x_lo:x_hi]) >= need:
                return False            # parallel line below = box border
        return True
    return False


def _fraction_join(items, dark):
    """Merges vertically stacked math fragments into fraction notation.

    numerator over denominator        -> "num / den"
    a further expression right below  -> implicit product factor (·)
    Proof: a real fraction has a drawn BAR between numerator and
    denominator — we look for it in the image, so stacked labels (K1/K2 in
    block diagrams) and margin marks never merge. Lines containing '=' are
    never merged either (equations, not fraction parts).
    """
    n = len(items)
    used = [False] * n
    out = []
    for i in range(n):
        if used[i]:
            continue
        t, s, b = items[i]
        if not _math_dense(t):
            out.append((t, s, b))
            continue
        # denominator: the closest stacked fragment below that has a bar
        j, j_gap = None, None
        for k in range(i + 1, n):
            if used[k]:
                continue
            tk = items[k][0]
            if "=" in tk or not _math_dense(tk):
                continue
            if not _stacked(b, items[k][2]):
                # extra air is acceptable only with a drawn bar as proof
                if not (_stacked(b, items[k][2], relaxed=True)
                        and _bar_between(dark, b, items[k][2])):
                    continue
            if not _bar_between(dark, b, items[k][2]):
                continue               # stacked but no bar: not a fraction
            _, ay0, _, ay1 = _bbox(b)
            _, by0, _, _ = _bbox(items[k][2])
            gap = abs(by0 - ay1)
            if j is None or gap < j_gap:
                j, j_gap = k, gap
        if j is None:
            out.append((t, s, b))
            continue
        tj, sj, bj = items[j]
        used[j] = True
        merged_t = f"{t} / {tj}"
        merged_b = np.vstack([np.asarray(b, dtype=float), np.asarray(bj, dtype=float)])
        # implicit product: an expression tightly below the denominator
        f, f_gap = None, None
        for k in range(n):
            if used[k]:
                continue
            tk, sk, bk = items[k]
            if "=" in tk or not _math_dense(tk):
                continue
            if not re.match(r"^[\(\d]", tk.strip()):
                continue
            if not _stacked(bj, bk):
                continue
            _, dy0, _, dy1 = _bbox(bj)
            _, fy0, _, _ = _bbox(bk)
            gap = abs(fy0 - dy1)
            if f is None or gap < f_gap:
                f, f_gap = k, gap
        if f is not None:
            tf, sf, bf = items[f]
            used[f] = True
            merged_t += "·" + tf.strip()
            merged_b = np.vstack([merged_b, np.asarray(bf, dtype=float)])
            sj = min(sj, sf)
        out.append((merged_t, min(s, sj), merged_b.tolist()))
    return out


def _is_stub(t: str) -> bool:
    """A short 'LHS =' line stub (the left side of an equation)."""
    t = t.strip()
    return len(t) <= 16 and t.endswith("=") and "=" not in t[:-1]


# ---------------------------------------------------------- page arrangement
_Q_MARK_RE = re.compile(
    r"^(?:Q\s*[\.\-]?\s*No\s*[\.\-]?\s*\d+|Q\s*\d{1,2}\b|\d{1,2}\s*[\.\)]\s)", re.I)
_OPT_MARK_RE = re.compile(r"^\(?[a-dA-D][\)\.]\s")
_BILL_RE = re.compile(
    r"\b(?:gst|invoice|receipt|subtotal|hsn|grand\s*total|amount\s*paid|net\s*payable)\b",
    re.I)


def _same_row(a_box, b_box, a_stub: bool, b_stub: bool) -> bool:
    """Two boxes sit on one visual text row."""
    ax0, ay0, ax1, ay1 = _bbox(a_box)
    bx0, by0, bx1, by1 = _bbox(b_box)
    min_h = max(1.0, min(ay1 - ay0, by1 - by0))
    ov = min(ay1, by1) - max(ay0, by0)
    if a_stub or b_stub:
        return ov > 0                     # an 'LHS =' stub reaches into its row
    if abs((ay0 + ay1) - (by0 + by1)) / 2 <= 0.6 * min_h:
        return True                       # same baseline
    return ov >= 0.5 * min_h              # strong overlap (tall stack + its RHS)


def _merge_row(parts):
    """Join one visual row's fragments; wide gaps stay wide (1-3 spaces)."""
    text = parts[0][0].strip()
    score = parts[0][1]
    box = np.asarray(parts[0][2], dtype=float)
    for p in parts[1:]:
        n_sp = p[3]
        text += " " * n_sp + p[0].strip()
        score = min(score, p[1])
        box = np.vstack([box, np.asarray(p[2], dtype=float)])
    return (text, score, box.tolist())


def _is_margin_mark(txt: str, box, page_w) -> bool:
    """Bare 1-2 digit number hugging a page edge (question number in the
    margin, page folio) — page decoration, never part of a text row."""
    t = txt.strip()
    if len(t) > 2 or not t.isdigit():
        return False
    x0 = _bbox(box)[0]
    return x0 <= 0.15 * page_w or x0 >= 0.85 * page_w


def _row_join(items, width, page_w=None):
    """One visual row -> one text line, gaps shown as gaps.

    Fragments further apart than a third of the block width stay separate
    elements; stacked labels (a tag above a question number) flush into
    their own lines; margin marks are page decoration and never join.
    """
    if not items:
        return []
    pw = page_w if page_w else width
    rows = []
    for it in items:
        b = it[2]
        if _is_margin_mark(it[0], b, pw):
            rows.append([it])              # decoration: always its own line
            continue
        stub = _is_stub(it[0])
        hit = None
        for row in rows:
            if row and _is_margin_mark(row[0][0], row[0][2], pw):
                continue
            # compare against the row member with the biggest vertical overlap
            best = max(row, key=lambda r: min(_bbox(r[2])[3], _bbox(b)[3])
                       - max(_bbox(r[2])[1], _bbox(b)[1]))
            if _same_row(best[2], b, _is_stub(best[0]), stub):
                hit = row
                break
        if hit is not None:
            hit.append(it)
        else:
            rows.append([it])
    rows.sort(key=lambda row: sum((_bbox(i[2])[1] + _bbox(i[2])[3]) / 2 for i in row) / len(row))
    out = []
    for row in rows:
        row.sort(key=lambda i: _bbox(i[2])[0])
        cur = []
        for t, s, b in row:
            if not cur:
                cur = [(t, s, b)]
                continue
            px1 = _bbox(cur[-1][2])[2]
            bx0 = _bbox(b)[0]
            min_h = max(1.0, min(_bbox(cur[-1][2])[3] - _bbox(cur[-1][2])[1],
                                 _bbox(b)[3] - _bbox(b)[1]))
            gap = bx0 - px1
            tol = min(8.0, 0.5 * min_h)
            if gap > 0.6 * width or gap < -tol:
                out.append(_merge_row(cur))
                cur = [(t, s, b)]
                continue
            cw = max(2.0, 0.55 * min_h)   # ~one character width
            n_sp = 1 if gap < 1.5 * cw else (2 if gap < 4.0 * cw else 3)
            cur.append((t, s, b, n_sp))
        if cur:
            out.append(_merge_row(cur))
    return out

def _find_gutter(items, page_w):
    """A whitespace band that splits the page into two text columns.

    The band may be crossed by LONG lines only (titles, headers) — those
    become section separators. Anything narrower crossing it (a margin
    mark, a stray label) disqualifies the candidate.
    """
    if len(items) < 12:
        return None
    boxes = [_bbox(b) for _, _, b in items]
    span = np.zeros(page_w)
    for x0, y0, x1, y1 in boxes:
        span[int(max(0, x0)):int(min(page_w, x1))] += 1
    lo, hi = int(0.12 * page_w), int(0.88 * page_w)
    n = len(items)
    best = None
    x = lo
    while x < hi:
        if span[x] <= 3:
            gx0 = x
            while x < hi and span[x] <= 3:
                x += 1
            gx1 = x
            # shrink away long column items that merely reach into the band:
            # a true separator (title) has its CENTER inside the gutter
            for x0, y0, x1, y1 in boxes:
                cx = (x0 + x1) / 2
                if x0 < gx1 and x1 > gx0 and (x1 - x0) >= 0.25 * page_w:
                    if cx < gx0:
                        gx0 = max(gx0, x1)
                    elif cx > gx1:
                        gx1 = min(gx1, x0)
            if gx1 - gx0 < max(2.0, 0.015 * page_w):
                continue
            # only long lines whose center sits inside the band may cross it
            ok = True
            for x0, y0, x1, y1 in boxes:
                if x0 < gx1 and x1 > gx0:
                    if (x1 - x0) < 0.25 * page_w or not (gx0 <= (x0 + x1) / 2 <= gx1):
                        ok = False
                        break
            if not ok:
                continue
            left = [i for i, bb in enumerate(boxes) if bb[2] <= gx0]
            right = [i for i, bb in enumerate(boxes) if bb[0] >= gx1]
            if min(len(left), len(right)) < 4:
                continue
            if len(left) + len(right) < 8:
                continue
            if min(len(left), len(right)) < 0.2 * n:
                continue                  # margin marks / a stray sidebar: no split
            score = min(len(left), len(right))
            if best is None or score > best[0]:
                best = (score, gx0, gx1, left, right)
        else:
            x += 1
    if best is None:
        return None
    return best[1], best[2], best[3], best[4]


def _arrange(items, page_w):
    """Column-aware reading order.

    Two-column pages (question worksheets, IDE screenshots, split bills)
    are read column by column — left column top-to-bottom, then right.
    Full-width lines (titles, headers) act as section separators and are
    emitted where they sit; short bands (a header row) stay row-joined.
    """
    gutter = _find_gutter(items, page_w)
    if gutter is None:
        return _row_join(items, page_w)
    gx0, gx1, left_ids, right_ids = gutter
    left_set, right_set = set(left_ids), set(right_ids)
    cross = [i for i in range(len(items)) if i not in left_set and i not in right_set]
    # cluster crossing items into separator rows
    sep_rows = []
    for i in cross:
        hit = None
        for row in sep_rows:
            if _same_row(items[row[0]][2], items[i][2], False, False):
                hit = row
                break
        if hit is not None:
            hit.append(i)
        else:
            sep_rows.append([i])
    sep_rows.sort(key=lambda row: sum((_bbox(items[i][2])[1] + _bbox(items[i][2])[3]) / 2
                                      for i in row) / len(row))
    sep_y = [sum((_bbox(items[i][2])[1] + _bbox(items[i][2])[3]) / 2 for i in row) / len(row)
             for row in sep_rows]

    def section_of(i):
        b = items[i][2]
        cy = (_bbox(b)[1] + _bbox(b)[3]) / 2
        h = max(1.0, _bbox(b)[3] - _bbox(b)[1])
        for k, sy in enumerate(sep_y):
            if abs(cy - sy) <= 0.7 * h:
                return ("sep", k)
            if cy < sy:
                return ("band", k)
        return ("band", len(sep_y))

    groups = {}
    for i in range(len(items)):
        groups.setdefault(section_of(i), []).append(i)
    out = []
    def group_y(key):
        ids = groups[key]
        return min((_bbox(items[i][2])[1] + _bbox(items[i][2])[3]) / 2 for i in ids)

    out = []
    for key in sorted(groups, key=lambda kk: (group_y(kk), 0 if kk[0] == "sep" else 1)):
        ids = groups[key]
        if key[0] == "sep":
            out += _row_join([items[i] for i in ids], page_w)
            continue
        L = [items[i] for i in ids if i in left_set]
        R = [items[i] for i in ids if i in right_set]
        if min(len(L), len(R)) >= 4 and len(L) + len(R) >= 8 \
                and min(len(L), len(R)) >= 0.2 * len(ids):
            lx = [_bbox(i[2]) for i in L]
            rx = [_bbox(i[2]) for i in R]
            lw = max(b[2] for b in lx) - min(b[0] for b in lx)
            rw = max(b[2] for b in rx) - min(b[0] for b in rx)
            out += _row_join(L, lw, page_w)
            out += _row_join(R, rw, page_w)
        else:
            out += _row_join([items[i] for i in ids], page_w, page_w)
    return out


def process_image(img, return_details=False):
    """OCR a PIL image, opened image path, or bytes."""
    if isinstance(img, (str, os.PathLike)):
        img = Image.open(img)
    elif isinstance(img, (bytes, bytearray)):
        img = Image.open(io.BytesIO(bytes(img)))
    elif not isinstance(img, Image.Image):
        raise TypeError(f"Unsupported image type: {type(img)}")

    text, details = _extract(img)
    if return_details:
        return text, details
    return text


def process_pdf(pdf_bytes, return_details=False):
    """OCR every page of a PDF (bytes or path)."""
    try:
        import pymupdf
    except ImportError:
        err = "pymupdf is not installed — PDF support unavailable."
        return (err, []) if return_details else err

    if isinstance(pdf_bytes, (str, os.PathLike)):
        with open(pdf_bytes, "rb") as f:
            pdf_bytes = f.read()

    doc = pymupdf.open(stream=bytes(pdf_bytes), filetype="pdf")
    pages, all_details = [], []
    for i, page in enumerate(doc, 1):
        pix = page.get_pixmap(dpi=200)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        t, d = _extract(img)
        pages.append(f"--- Page {i} ---\n{t}" if len(doc) > 1 else t)
        for item in d:
            item["page"] = i
        all_details.extend(d)

    combined = "\n".join(pages)
    return (combined, all_details) if return_details else combined


def process_any(path, return_details=False):
    """Convenience: image or PDF by extension."""
    if str(path).lower().endswith(".pdf"):
        return process_pdf(path, return_details=return_details)
    return process_image(path, return_details=return_details)
