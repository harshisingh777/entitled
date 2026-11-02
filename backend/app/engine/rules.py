"""Deterministic eligibility engine. The LLM never reaches this module's decisions.

Rules are JSON-Logic. Facts can be unknown, so and/or/! are evaluated with
three-valued logic here and every leaf is handed to the JSON-Logic library once
all its variables are known.
"""
import json
from functools import lru_cache

from json_logic import jsonLogic

from ..config import SCHEMES_DIR

ELIGIBLE, NOT_ELIGIBLE, NEAR_MISS, UNDECIDED = "eligible", "not_eligible", "near_miss", "undecided"


@lru_cache
def load_schemes() -> dict:
    schemes = {}
    for path in sorted(SCHEMES_DIR.glob("*.json")):
        if not path.name.startswith("_"):
            scheme = json.loads(path.read_text(encoding="utf-8"))
            schemes[scheme["id"]] = scheme
    return schemes


@lru_cache
def load_catalog() -> dict:
    return json.loads((SCHEMES_DIR / "_catalog.json").read_text(encoding="utf-8"))


def vars_in(expr) -> set:
    if isinstance(expr, dict):
        if "var" in expr:
            return {expr["var"]}
        return set().union(*(vars_in(v) for v in expr.values())) if expr else set()
    if isinstance(expr, list):
        return set().union(*(vars_in(v) for v in expr)) if expr else set()
    return set()


def tri(expr, facts: dict):
    """True, False, or None when the facts do not settle it yet."""
    op = next(iter(expr))
    if op == "and":
        values = [tri(e, facts) for e in expr[op]]
        return False if False in values else (None if None in values else True)
    if op == "or":
        values = [tri(e, facts) for e in expr[op]]
        return True if True in values else (None if None in values else False)
    if op == "!":
        value = tri(expr[op] if isinstance(expr[op], dict) else expr[op][0], facts)
        return None if value is None else not value
    if any(name not in facts for name in vars_in(expr)):
        return None
    return bool(jsonLogic(expr, facts))


def inr(amount: int) -> str:
    """Indian digit grouping: 200000 becomes 2,00,000."""
    digits = str(int(amount))
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join(([head] if head else []) + groups + [tail])


class _Blank(dict):
    def __missing__(self, key):
        return "?"


def _fmt(template: str, facts: dict, **extra) -> str:
    values = {**facts, **extra}
    if "annual_income" in values:
        values["annual_income"] = inr(values["annual_income"])
    return template.format_map(_Blank(values))


def _gap_applies(gap: dict | None, facts: dict) -> bool:
    if not gap:
        return False
    if gap["kind"] == "wait":
        return gap["var"] in facts and 0 < gap["threshold"] - facts[gap["var"]] <= gap["max_years"]
    return True


def _describe_gap(gap: dict, scheme: dict, facts: dict) -> dict:
    if gap["kind"] == "wait":
        years = gap["threshold"] - facts[gap["var"]]
        return {
            "kind": "wait", "years": years,
            "hi": f"अभी उम्र {facts[gap['var']]} है, {years} साल बाद {scheme['name']['hi']} मिल सकती है",
            "en": f"Age is {facts[gap['var']]} now, {scheme['name']['en']} is possible in {years} years",
        }
    return {
        "kind": gap["kind"], "doc": gap.get("doc"),
        "hi": _fmt(gap["hi"], facts, scheme=scheme["name"]["hi"]),
        "en": _fmt(gap["en"], facts, scheme=scheme["name"]["en"]),
    }


def annual_value(scheme: dict, facts: dict) -> int:
    benefit = scheme["benefit"]
    for tier in benefit.get("tiers", []):
        if tri(tier["when"], facts) is True:
            return tier["annual_inr"]
    return benefit.get("annual_inr", 0)


def evaluate_scheme(scheme: dict, facts: dict) -> dict:
    trace, unknown_vars, gaps, hard_fail = [], set(), [], False
    for criterion in scheme["criteria"]:
        value = tri(criterion["logic"], facts)
        status = "unknown" if value is None else ("pass" if value else "fail")
        entry = {
            "id": criterion["id"], "status": status, "label": criterion["label"],
            "vars": sorted(vars_in(criterion["logic"])),
            "values": {k: facts[k] for k in vars_in(criterion["logic"]) if k in facts},
        }
        if status == "unknown":
            unknown_vars |= {k for k in vars_in(criterion["logic"]) if k not in facts}
        elif status == "fail":
            entry["reason"] = {lang: _fmt(criterion["fail"][lang], facts) for lang in ("hi", "en")}
            if _gap_applies(criterion.get("gap"), facts):
                gaps.append(_describe_gap(criterion["gap"], scheme, facts))
            else:
                hard_fail = True
        trace.append(entry)

    if hard_fail or len(gaps) > 1:
        outcome = NOT_ELIGIBLE
    elif unknown_vars:
        outcome = UNDECIDED
    elif gaps:
        outcome = NEAR_MISS
    else:
        outcome = ELIGIBLE

    return {
        "id": scheme["id"], "name": scheme["name"], "level": scheme["level"], "outcome": outcome,
        "trace": trace, "gaps": gaps if outcome == NEAR_MISS else [], "unknown_vars": sorted(unknown_vars),
        "benefit": scheme["benefit"], "annual_inr": annual_value(scheme, facts),
        "one_time_inr": scheme["benefit"].get("one_time_inr", 0), "cover_inr": scheme["benefit"].get("cover_inr", 0),
        "beneficiary": scheme["beneficiary"], "source_url": scheme["source_url"],
        "last_verified": scheme["last_verified"], "verification": scheme["verification"],
    }


def _detect_conflicts(results: list[dict]) -> list[dict]:
    schemes = load_schemes()
    groups: dict[str, list[dict]] = {}
    for result in results:
        group = schemes[result["id"]].get("conflict_group")
        if group and result["outcome"] == ELIGIBLE:
            groups.setdefault(group, []).append(result)

    conflicts = []
    for group, members in groups.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda r: (-r["annual_inr"], r["level"] != "up"))
        best = members[0]
        for other in members[1:]:
            other["suppressed_by"] = best["id"]
        best_hi, best_en = best["name"]["hi"], best["name"]["en"]
        conflicts.append({
            "group": group, "schemes": [m["id"] for m in members], "recommended": best["id"],
            "hi": f"ये पेंशन एक साथ नहीं मिल सकतीं। {best_hi} सबसे ज़्यादा है: ₹{inr(best['annual_inr'])} सालाना।",
            "en": f"These pensions cannot be drawn together. {best_en} pays the most: ₹{inr(best['annual_inr'])} a year.",
        })
    return conflicts


def evaluate_all(facts: dict) -> dict:
    results = [evaluate_scheme(s, facts) for s in load_schemes().values()]
    conflicts = _detect_conflicts(results)
    counted = [r for r in results if r["outcome"] == ELIGIBLE and not r.get("suppressed_by")]
    results.sort(key=lambda r: (
        {ELIGIBLE: 0, NEAR_MISS: 1, UNDECIDED: 2, NOT_ELIGIBLE: 3}[r["outcome"]],
        bool(r.get("suppressed_by")), -(r["annual_inr"] + r["one_time_inr"]),
    ))
    counts = {k: 0 for k in (ELIGIBLE, NOT_ELIGIBLE, NEAR_MISS, UNDECIDED)}
    for result in results:
        counts[result["outcome"]] += 1
    return {
        "results": results, "conflicts": conflicts, "counts": counts,
        "totals": {
            "annual_inr": sum(r["annual_inr"] for r in counted),
            "one_time_inr": sum(r["one_time_inr"] for r in counted),
            "cover_inr": max((r["cover_inr"] for r in counted), default=0),
        },
    }


def explain(result: dict, lang: str = "hi") -> str:
    """The rule trace as one spoken sentence."""
    name = result["name"][lang]
    passed = [t["label"][lang] for t in result["trace"] if t["status"] == "pass"]
    failed = [t["reason"][lang] for t in result["trace"] if t["status"] == "fail"]
    tick = ", ".join(passed)
    hi = lang == "hi"
    if result["outcome"] == ELIGIBLE:
        return f"{name} का हक़ बनता है: {tick}।" if hi else f"You are entitled to {name}: {tick}."
    if result["outcome"] == NEAR_MISS:
        gap = result["gaps"][0][lang]
        prefix = f"{name}: {tick} ठीक हैं। " if hi and tick else (f"{name}: {tick} are fine. " if tick else f"{name}: ")
        return f"{prefix}{gap}{'।' if hi else '.'}"
    if result["outcome"] == NOT_ELIGIBLE:
        reason = "; ".join(failed)
        return f"{name} नहीं मिल सकती: {reason}।" if hi else f"{name} is not available: {reason}."
    return f"{name} के लिए अभी और जानकारी चाहिए।" if hi else f"{name} needs more information."
