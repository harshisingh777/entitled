"""
Evidence-gated repair layer for OCR output.

Design rule (from the project owner): guessing must have proof.
  * A token that is already a valid English / Hinglish / tech / math word is
    NEVER touched — this is what stops "pike" -> "bike".
  * An invalid token is only replaced when exactly one dictionary candidate is
    clearly closer than every other candidate (margin gate), using
    visual-confusion-weighted edit distance.
  * Math normalizations fire only inside "math mode" lines and only under
    numeric-context proof (e.g. 'V' -> '√' only when followed by a perfect
    square).
  * Splits/completions need every resulting part to be a valid word.

Everything here is pure Python, offline, and runs in a few ms per line.
"""
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_LAYER = os.path.join(_HERE, "layer")


def _load(name):
    with open(os.path.join(_LAYER, name), encoding="utf-8") as f:
        return [w.strip() for w in f if w.strip()]


_ENGLISH = _load("english_freq.txt")
_TECH = _load("tech.txt")
_HINGLISH = _load("hinglish.txt")
_MATH = _load("math.txt")

ENGLISH_RANK = {w: i for i, w in enumerate(_ENGLISH)}          # frequency rank
ALL_WORDS = set(_ENGLISH) | set(_TECH) | set(_HINGLISH) | set(_MATH)

# curated display casing for well-known tech terms (proof: it's a brand list)
_CANONICAL_CASE = {
    "fastapi": "FastAPI", "nextjs": "Next.js", "nodejs": "Node.js",
    "javascript": "JavaScript", "typescript": "TypeScript", "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL", "mongodb": "MongoDB", "django": "Django",
    "react": "React", "angular": "Angular", "vue": "Vue", "prisma": "Prisma",
    "docker": "Docker", "kubernetes": "Kubernetes", "graphql": "GraphQL",
    "pytorch": "PyTorch", "tensorflow": "TensorFlow", "scikit-learn": "scikit-learn",
    "github": "GitHub", "gitlab": "GitLab", "linkedin": "LinkedIn",
    "sqlite": "SQLite", "mysql": "MySQL", "redis": "Redis", "kafka": "Kafka",
    "oauth": "OAuth", "jwt": "JWT", "api": "API", "crud": "CRUD",
    "orm": "ORM", "rbac": "RBAC", "http": "HTTP", "https": "HTTPS",
    "json": "JSON", "yaml": "YAML", "sql": "SQL", "css": "CSS", "html": "HTML",
    "cpu": "CPU", "gpu": "GPU", "docker": "Docker", "jwt": "JWT",
}

# words that are valid on their own even though tiny
_VALID_SHORT = {"a", "i", "ok", "no", "vs", "x", "y", "z", "n", "h", "b", "c", "p", "q"}

# common contractions kept as valid words (apostrophe stripped when matching)
_CONTRACTIONS = {"im", "dont", "its", "isnt", "cant", "youre", "ive", "id",
                 "youll", "wasnt", "arent", "didnt", "doesnt", "wouldnt",
                 "couldnt", "shouldnt", "thats", "whats", "lets", "hes", "shes"}
_CONTRACTION_DISPLAY = {"im": "I'm", "dont": "don't", "its": "it's",
                         "isnt": "isn't", "cant": "can't", "youre": "you're",
                         "ive": "I've", "youll": "you'll", "wasnt": "wasn't",
                         "didnt": "didn't", "doesnt": "doesn't", "thats": "that's",
                         "whats": "what's", "lets": "let's", "hes": "he's",
                         "shes": "she's", "arent": "aren't", "wouldnt": "wouldn't",
                         "couldnt": "couldn't", "shouldnt": "shouldn't"}

# visual confusion costs for OCR (lower = more easily confused)
_CONFUSION = {
    ("r", "n"): 0.4, ("n", "r"): 0.4, ("m", "n"): 0.45, ("n", "m"): 0.45,
    ("c", "l"): 1.3, ("l", "c"): 1.3, ("i", "l"): 0.35, ("l", "i"): 0.35,
    ("i", "t"): 0.5, ("t", "i"): 0.5, ("i", "j"): 0.5, ("j", "i"): 0.5,
    ("v", "w"): 0.5, ("w", "v"): 0.5, ("u", "v"): 0.55, ("v", "u"): 0.55,
    ("a", "o"): 0.5, ("o", "a"): 0.5, ("e", "o"): 0.5, ("o", "e"): 0.5,
    ("e", "c"): 0.5, ("c", "e"): 0.5, ("e", "a"): 0.55, ("a", "e"): 0.55,
    ("i", "e"): 0.7, ("e", "i"): 0.7,
    ("b", "h"): 0.6, ("h", "b"): 0.6, ("k", "h"): 0.6, ("h", "k"): 0.6,
    ("t", "k"): 0.6, ("k", "t"): 0.6, ("l", "t"): 0.6, ("t", "l"): 0.6,
    ("s", "f"): 0.6, ("f", "s"): 0.6, ("c", "s"): 0.6, ("s", "c"): 0.6,
    ("g", "q"): 0.6, ("q", "g"): 0.6, ("u", "o"): 0.6, ("o", "u"): 0.6,
    ("r", "v"): 0.6, ("v", "r"): 0.6, ("e", "u"): 0.6, ("u", "e"): 0.6,
    ("n", "a"): 0.6, ("a", "n"): 0.6, ("p", "s"): 0.7, ("s", "p"): 0.7,
    ("x", "k"): 0.7, ("k", "x"): 0.7, ("z", "s"): 0.7, ("s", "z"): 0.7,
}

# Hinglish line-end completion: (previous word) -> (partial -> full)
_END_TABLE = {
    "karna": {"h": "hai", "ha": "hai", "hai": "hai"},
    "raha": {"h": "hai"}, "rahi": {"h": "hai"}, "hota": {"h": "hai"},
    "kya": {"karna": "karna", "kar": "kar"},
    "pehle": {"kar": "karo", "k": "karo"},
    "waste": {"mat": "mat", "m": "mat"},
    "kaam": {"kar": "karo", "k": "karo"},
    "time": {"w": "waste"},
}

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'’]*")

# code-ish lines: identifiers are not English typos — never dictionary-repaired
_CODEY_RE = re.compile(r"[;{}\[\]#]|<\w+\.h>|\w+\s*\(")


def _is_codey(line: str) -> bool:
    return bool(_CODEY_RE.search(line))


def is_valid_word(tok: str) -> bool:
    t = tok.lower().replace("’", "'")
    bare = t.replace("'", "")
    if bare in ALL_WORDS:
        return True
    if t in _CONTRACTIONS or bare in _CONTRACTIONS:
        return True
    if t in _VALID_SHORT:
        return True
    return False


def _weighted_dist(s1: str, s2: str) -> float:
    m, n = len(s1), len(s2)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0.0] * n
        for j in range(1, n + 1):
            if s1[i - 1] == s2[j - 1]:
                cost = 0.0
            else:
                # visually implausible substitutions cost MORE than a
                # dropped/inserted letter — OCR loses letters, it rarely
                # hallucinates unrelated ones.
                cost = _CONFUSION.get((s1[i - 1], s2[j - 1]), 1.3)
            cur[j] = min(prev[j] + 1.0, cur[j - 1] + 1.0, prev[j - 1] + cost)
        prev = cur
    return float(prev[n])


def _unit_edits(s1: str, s2: str) -> int:
    """Plain Levenshtein: how many letters the rewrite actually changes."""
    m, n = len(s1), len(s2)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        for j in range(1, n + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                         prev[j - 1] + (s1[i - 1] != s2[j - 1]))
        prev = cur
    return prev[n]


def _candidates(token: str):
    """Return ranked (score, word) candidates for an invalid token."""
    t = token.lower().replace("'", "")
    n = len(t)
    if n < 3:
        return []
    # an accepted fix may change at most ONE letter on short tokens, at most
    # a quarter of the letters on long ones (the pike rule: a candidate that
    # rewrites most of what was read is a guess, not a repair). This blocks
    # "amethi" -> "meth" (two letters dropped) and "ctm" -> "lim" (two of
    # three letters replaced) even though both look cost-cheap.
    max_d = 1.0 if n <= 9 else 2.0
    max_edits = 1 if n <= 7 else max(2, n // 4)
    # long tokens: >2 edits produce too many phantom candidates; leave them.
    out = []
    for w in ALL_WORDS:
        if abs(len(w) - n) > 2:
            continue
        rank = ENGLISH_RANK.get(w, 15000)          # non-English lists: mid rank
        if rank >= 28000:                          # cut corpus-tail junk
            continue
        if _unit_edits(t, w) > max_edits:          # rewrite-extent proof
            continue
        d = _weighted_dist(t, w)
        if d <= max_d:
            out.append((d, rank, w))
    out.sort(key=lambda x: (x[0], x[1]))
    return out


def _keep_case(candidate: str, original: str) -> str:
    if candidate in _CANONICAL_CASE:
        c = _CANONICAL_CASE[candidate]
        if original.isupper():
            return c.upper()
        return c
    if original.isupper():
        return candidate.upper()
    if original[:1].isupper():
        return candidate.capitalize()
    return candidate


def _is_math_line(line: str) -> bool:
    digits = sum(c.isdigit() for c in line)
    ops = any(c in "=+-×÷√π≤≥≠^%∞" for c in line)
    return digits >= 2 and ops


# ---- ordinals & temperature (evidence-gated) --------------------------------
_SUPS = {"2": "²", "3": "³"}

_ORDINAL_CTX = (r"year|yr|semester|sem|class|standard|floor|rank|row|edition|"
                r"chapter|page|quarter|qtr|century|grade|attempt|phase|position|"
                r"time|day|month|week|born")
_ORDINAL_RE = re.compile(
    rf"(\d{{1,3}})\s*[\u00b0\u00ba](?=\s*(?:{_ORDINAL_CTX})\b)", re.I)

_TEMP_CTX_RE = re.compile(
    r"temperature|thermometer|bath|fever|heat|weather|climate|boil|freez", re.I)
_TEMP_FIX_RE = re.compile(r"(\d)\s*([FC])(?![A-Za-z0-9])")


def _ord_suffix(n: int) -> str:
    """1st 2nd 3rd 4th ... fully determined by the number itself."""
    if n % 100 in (11, 12, 13):
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _fix_ordinals(line: str, is_math: bool) -> str:
    """'3º year' -> '3rd year'. Never fires on real angles (math or no ctx word)."""
    if is_math:
        return line
    return _ORDINAL_RE.sub(
        lambda m: f"{m.group(1)}{_ord_suffix(int(m.group(1)))}", line)


def _fix_temperature(line: str) -> str:
    """'100F' -> '100°F' but only with temperature words on the line
    (in a chem-eng paper F is also flow and C is concentration)."""
    if not _TEMP_CTX_RE.search(line):
        return line
    line = re.sub(r"\u00b0\s+([FC])\b", r"°\1", line)   # "120° F" -> "120°F"
    return _TEMP_FIX_RE.sub(r"\1°\2", line)


def _is_perfect_square(s: str) -> bool:
    if not s.isdigit():
        return False
    v = int(s)
    if v > 10**8:
        return False
    r = int(round(v ** 0.5))
    return r * r == v


def math_normalize(line: str) -> str:
    """Applies proof-gated math fixes. Only inside math-mode lines."""
    if not _is_math_line(line):
        return line
    # typographic dashes that mean minus -> ASCII '-'
    line = re.sub(r"(?<=[\d\s=])[\u2013\u2014\u2212](?=\s?\d)", "-", line)
    # 'V' + perfect square -> radical  (V is the classic OCR read of √)
    line = re.sub(r"(?<![A-Za-z])V(\d+)", lambda m: "√" + m.group(1)
                  if _is_perfect_square(m.group(1)) else m.group(0), line)
    # digit x digit -> digit × digit (x between numbers is multiplication)
    line = re.sub(r"(?<=\d)\s*[xX]\s*(?=\d)", " × ", line)
    # standalone 'pi' in a numeric line -> π
    if re.search(r"\d", line):
        line = re.sub(r"(?<![A-Za-z])pi(?![A-Za-z])", "π", line)

    # --- OCR slips inside math expressions (all still gated by math mode) ---
    # decimal-coefficient 'o' is the Laplace 's': 0.1o + 1 -> 0.1s + 1
    line = re.sub(r"(\d\.\d+)o", r"\1s", line)
    # digit-s-digit is a power of s: 4s2 -> 4s²
    line = re.sub(r"(\d)s([2-9])(?![\d.])",
                  lambda m: f"{m.group(1)}s{_SUPS.get(m.group(2), '^' + m.group(2))}",
                  line)
    # superscript on a parenthesized group: (0.1s + 1)2 -> (0.1s + 1)²
    line = re.sub(r"\)([2-9])(?![\d.])",
                  lambda m: ")" + _SUPS.get(m.group(1), "^" + m.group(1)), line)
    # standalone exponential/delay term: e-3s, e - 3s -> e^(-3s)
    line = re.sub(r"(?<![\w.])e\s*([+-])\s*(\d+)([A-Za-z]?)",
                  lambda m: f"e^({m.group(1)}{m.group(2)}{m.group(3)})", line)
    return re.sub(r" {2,}", " ", line).strip()


def _is_subseq(small: str, big: str) -> bool:
    """True if every letter of `small` appears in `big` in order."""
    it = iter(big)
    return all(ch in it for ch in small)


def repair_token(token: str, prev_word: str | None = None, is_last: bool = False,
                 codey: bool = False):
    """Repair a single invalid token with evidence gates. Returns fixed or original."""
    low = token.lower()

    # 0. line-end completion (Hinglish) — checked first; needs a unique table
    #    hit with the previous word, which is proof even for tiny tokens.
    if is_last and prev_word and len(low) <= 4:
        table = _END_TABLE.get(prev_word.lower())
        if table and low in table:
            fixed = table[low]
            if fixed != low:
                return _keep_case(fixed, token)

    if is_valid_word(token):
        return token

    # tokens containing digits, slashes or @ are never dictionary-repaired
    # (IDs, version numbers, URLs, code fragments, prices)
    if re.search(r"[\d/\\@]", token):
        return token
    # acronyms (CSTR, DPP, MSQ) are unguessable by a frequency dictionary
    if token.isupper() and len(token) >= 2:
        return token
    # code lines: 'printf' is an identifier, not a typo of 'prints'
    if codey:
        # one exception with proof: C keywords are a closed set, and the
        # m/n confusion is the single most common slip on them
        if low == "retum":
            return _keep_case("return", token)
        return token

    # 2a. statement-label split: 'Ponly' -> 'P only' (P/Q glued to their
    #     word — the label set is closed, so this is provable, not a guess)
    low_flat = low.replace("'", "").replace("\u2019", "")
    if len(low_flat) >= 4 and low_flat[0] in ("p", "q") and not low_flat[1:2].isdigit():
        for cut in (1, 2):
            a, b = low_flat[:cut], low_flat[cut:]
            if a in ("p", "q") and len(b) >= 3 and b in ALL_WORDS \
                    and ENGLISH_RANK.get(b, 28000) < 28000:
                return f"{_keep_case(a, token)} {b}"

    # 2. split repair: two valid words glued together (proof: both halves
    #    valid AND the split point is unique)
    if len(low) >= 6:
        low_flat = low.replace("'", "").replace("’", "")
        splits = []
        for i in range(3, len(low_flat) - 1):
            a, b = low_flat[:i], low_flat[i:]
            a_ok = a in ALL_WORDS and ENGLISH_RANK.get(a, 15000) <= 15000
            b_ok = b in _CONTRACTIONS or (
                len(b) >= 3 and b in ALL_WORDS and ENGLISH_RANK.get(b, 15000) <= 15000)
            if a_ok and b_ok:
                splits.append((a, b))
        if len(splits) == 1:
            a, b = splits[0]
            a_disp = _keep_case(a, token)
            b_disp = _CONTRACTION_DISPLAY.get(b, _keep_case(b, token))
            return f"{a_disp} {b_disp}"

    # 3. dictionary repair with margin gate
    cands = _candidates(token)
    if not cands:
        return token
    best_d, best_rank, best_w = cands[0]
    # proof 1: unique near-candidate, clear of the runner-up
    if len(cands) == 1 or cands[1][0] - best_d >= 0.3:
        return _keep_case(best_w, token)
    # tied set: everything at essentially the same distance
    tied = [c for c in cands if c[0] <= best_d + 0.05]
    t = token.lower().replace("'", "")
    # proof 2: prefer candidates that keep every read letter (subsequence)
    pool = [c for c in tied if _is_subseq(t, c[2])] or tied
    if len(pool) == 1:
        return _keep_case(pool[0][2], token)
    # proof 3: within the pool, accept the most frequent only on a 5x gap
    pool.sort(key=lambda c: c[1])
    if len(pool) == 1 or pool[0][1] * 5 <= pool[1][1]:
        return _keep_case(pool[0][2], token)
    return token


def repair_line(line: str) -> str:
    """Full pipeline for one OCR line."""
    if not line.strip():
        return line
    is_math = _is_math_line(line)
    line = _fix_ordinals(line, is_math)
    line = _fix_temperature(line)
    line = math_normalize(line)
    # unconditional: typographic dash before a digit is always a minus sign
    line = re.sub(r"[\u2013\u2014\u2212](?=\s?\d)", "-", line)
    out, last_end = [], 0
    prev_word = None
    codey = _is_codey(line)
    if codey:
        # code uses straight quotes only; curly ones are typesetting bleed
        line = re.sub("[\u201c\u201d]", '"', line)
        line = re.sub("[\u2018\u2019]", "'", line)
    matches = list(_TOKEN_RE.finditer(line))
    for idx, m in enumerate(matches):
        tok = m.group(0)
        fixed = repair_token(tok, prev_word, is_last=(idx == len(matches) - 1), codey=codey)
        out.append(line[last_end:m.start()])
        out.append(fixed)
        last_end = m.end()
        prev_word = fixed.split()[-1] if fixed.split() else None
    out.append(line[last_end:])
    return re.sub(r" {2,}", " ", "".join(out)).strip()


def repair_text(text: str) -> str:
    return "\n".join(repair_line(l) for l in text.split("\n"))
