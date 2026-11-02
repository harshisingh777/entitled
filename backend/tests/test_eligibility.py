import statistics

import pytest

from app.engine.documents import plan_documents
from app.engine.planner import answer_facts, next_question
from app.engine.rules import ELIGIBLE, NEAR_MISS, NOT_ELIGIBLE, UNDECIDED, evaluate_all, evaluate_scheme, explain, load_catalog, load_schemes, tri
from tests.data.households import HOUSEHOLDS


@pytest.mark.parametrize("household", HOUSEHOLDS, ids=[h["label"] for h in HOUSEHOLDS])
def test_labelled_household(household):
    results = {r["id"]: r["outcome"] for r in evaluate_all(household["facts"])["results"]}
    for scheme_id, outcome in results.items():
        expected = ELIGIBLE if scheme_id in household["eligible"] else NEAR_MISS if scheme_id in household["near_miss"] else NOT_ELIGIBLE
        assert outcome == expected, f"{scheme_id}: expected {expected}, got {outcome}"


def _truthful_answer(attr: str, facts: dict):
    covers = load_catalog()["questions"][attr].get("covers")
    return any(facts[c] for c in covers) if covers else facts[attr]


def _interview(facts: dict) -> tuple[dict, int]:
    known, asked = {}, 0
    while (question := next_question(known)) is not None:
        attr = question["attr"]
        known |= answer_facts(attr, _truthful_answer(attr, facts))
        asked += 1
        assert asked < 25
    return known, asked


def test_median_questions_meets_target():
    counts = [_interview(h["facts"])[1] for h in HOUSEHOLDS]
    assert statistics.median(counts) <= 12, counts


def test_older_women_are_not_asked_about_pregnancy():
    known, _ = _interview(HOUSEHOLDS[0]["facts"])
    questions_never_needed = next_question({"age": 58, "gender": "female"})["attr"]
    assert questions_never_needed != "pregnant_or_lactating"
    assert "pregnant_or_lactating" not in known or known["pregnant_or_lactating"] is False


def test_screener_yes_leads_to_follow_up_questions():
    facts = next(h for h in HOUSEHOLDS if h["label"].startswith("Urban blacksmith"))["facts"]
    known, _ = _interview(facts)
    assert known["rare_circumstances"] is True
    assert known["traditional_artisan"] is True


def test_interview_resolves_every_scheme_and_matches_full_knowledge():
    for household in HOUSEHOLDS:
        known, _ = _interview(household["facts"])
        partial = {r["id"]: r["outcome"] for r in evaluate_all(known)["results"]}
        full = {r["id"]: r["outcome"] for r in evaluate_all(household["facts"])["results"]}
        assert UNDECIDED not in partial.values()
        assert partial == full, household["label"]


def test_every_rule_file_cites_a_source_and_verification_date():
    schemes = load_schemes()
    assert len(schemes) == 16
    for scheme in schemes.values():
        assert scheme["source_url"].startswith("https://")
        assert scheme["last_verified"]
        assert scheme["verification"]["status"] in ("cross_checked", "conflicting")


def test_unknown_facts_stay_undecided_rather_than_guessed():
    result = evaluate_scheme(load_schemes()["up_vridhavastha"], {})
    assert result["outcome"] == UNDECIDED


def test_three_valued_or_settles_when_one_side_is_true():
    expr = {"or": [{"==": [{"var": "bpl_card"}, True]}, {">=": [{"var": "age"}, 70]}]}
    assert tri(expr, {"age": 75}) is True
    assert tri(expr, {"age": 40}) is None
    assert tri(expr, {"age": 40, "bpl_card": False}) is False


def test_conflict_recommends_the_higher_pension_and_counts_it_once():
    kamla = HOUSEHOLDS[0]["facts"]
    evaluation = evaluate_all(kamla)
    conflict = evaluation["conflicts"][0]
    assert conflict["recommended"] == "up_nirashrit_mahila"
    assert "nsap_widow" in conflict["schemes"]
    assert evaluation["totals"]["annual_inr"] == 18000


def test_rule_trace_for_near_miss_says_when():
    kamla = HOUSEHOLDS[0]["facts"]
    result = evaluate_scheme(load_schemes()["up_vridhavastha"], kamla)
    assert result["outcome"] == NEAR_MISS
    assert "2 साल बाद" in explain(result, "hi")
    assert "in 2 years" in explain(result, "en")


def test_document_gap_names_the_document():
    kamla = HOUSEHOLDS[0]["facts"]
    result = evaluate_scheme(load_schemes()["up_kanya_sumangala"], kamla)
    assert result["gaps"][0]["doc"] == "income_certificate"
    assert "आय प्रमाण पत्र" in explain(result, "hi")


def test_documents_are_deduplicated_and_ranked_by_what_they_unlock():
    kamla = HOUSEHOLDS[0]["facts"] | {"doc_aadhaar": True}
    plan = plan_documents(evaluate_all(kamla)["results"], kamla)
    ids = [d["id"] for d in plan["items"]]
    assert len(ids) == len(set(ids))
    assert plan["requested_across_schemes"] > plan["total"]
    assert "income_certificate" in plan["missing"]
    open_items = [d for d in plan["items"] if d["have"] is not True]
    assert [len(d["unlocks"]) for d in open_items] == sorted((len(d["unlocks"]) for d in open_items), reverse=True)


def test_bpl_card_removes_income_certificate_from_pension_documents():
    kamla = HOUSEHOLDS[0]["facts"]
    plan = plan_documents(evaluate_all(kamla)["results"], kamla)
    certificate = next(d for d in plan["items"] if d["id"] == "income_certificate")
    assert "up_nirashrit_mahila" not in [u["id"] for u in certificate["unlocks"]]
