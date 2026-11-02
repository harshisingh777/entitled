"""Adaptive interview: ask whichever attribute settles the most undecided schemes.

A question with `covers` is a screener: one "no" clears several rare attributes at
once, and only a "yes" leads to asking about them one by one.
"""
from .rules import UNDECIDED, evaluate_scheme, load_catalog, load_schemes, tri

_BOOL_SAMPLES = [True, False]


def answer_facts(attr: str, value) -> dict:
    """Every fact one answer establishes."""
    question = load_catalog()["questions"].get(attr, {})
    facts = {attr: value}
    if value is False:
        facts |= {name: False for name in question.get("covers", [])}
    return facts


def _samples(question: dict) -> list:
    return _BOOL_SAMPLES if question["type"] == "bool" else question["samples"]


def next_question(facts: dict, skipped: set | None = None) -> dict | None:
    skipped = skipped or set()
    questions = load_catalog()["questions"]
    undecided = [s for s in load_schemes().values() if evaluate_scheme(s, facts)["outcome"] == UNDECIDED]
    if not undecided:
        return None

    touching: dict[str, int] = {}
    for scheme in undecided:
        for name in evaluate_scheme(scheme, facts)["unknown_vars"]:
            touching[name] = touching.get(name, 0) + 1

    candidates: dict[str, int] = {}
    screened: set[str] = set()
    for name, question in questions.items():
        covers = [c for c in question.get("covers", []) if c in touching and c not in facts and c not in skipped]
        if len(covers) >= 2 and name not in facts and name not in skipped:
            candidates[name] = sum(touching[c] for c in covers)
            screened |= set(covers)
    for name, question in questions.items():
        if name not in touching or name in skipped or name in facts or name in screened:
            continue
        if "depends_on" not in question or tri(question["depends_on"], facts) is True:
            candidates[name] = touching[name]

    best, best_score = None, (-1.0, -1)
    for name, touches in candidates.items():
        samples = _samples(questions[name])
        resolved = sum(
            sum(evaluate_scheme(s, {**facts, **answer_facts(name, sample)})["outcome"] != UNDECIDED for s in undecided)
            for sample in samples
        ) / len(samples)
        score = (resolved, touches)
        if score > best_score:
            best, best_score = name, score
    if best is None:
        return None
    question = questions[best]
    return {
        "attr": best, "type": question["type"], "hi": question["hi"], "en": question["en"],
        "undecided": len(undecided), "expected_resolved": round(best_score[0], 2), "touches": best_score[1],
    }
