"""Union of documents across schemes, deduplicated and ranked by what each one unlocks."""
from .rules import ELIGIBLE, NEAR_MISS, load_catalog, load_schemes, tri


def _required(entry, facts: dict) -> str | None:
    if isinstance(entry, str):
        return entry
    return None if tri(entry["unless"], facts) is True else entry["id"]


def plan_documents(results: list[dict], facts: dict) -> dict:
    schemes, catalog = load_schemes(), load_catalog()["documents"]
    items: dict[str, dict] = {}
    for result in results:
        if result["outcome"] not in (ELIGIBLE, NEAR_MISS) or result.get("suppressed_by"):
            continue
        for entry in schemes[result["id"]]["documents"]:
            doc_id = _required(entry, facts)
            if doc_id is None:
                continue
            doc = catalog[doc_id]
            item = items.setdefault(doc_id, {
                "id": doc_id, "name": {"hi": doc["hi"], "en": doc["en"]}, "where": doc["where"], "time": doc["time"],
                "unlocks": [], "unlock_value_inr": 0,
                "have": facts.get(f"doc_{doc_id}"),
            })
            item["unlocks"].append({"id": result["id"], "name": result["name"]})
            item["unlock_value_inr"] += result["annual_inr"] + result["one_time_inr"]

    ordered = sorted(items.values(), key=lambda d: (d["have"] is True, -len(d["unlocks"]), -d["unlock_value_inr"]))
    return {
        "items": ordered,
        "total": len(ordered),
        "have": sum(d["have"] is True for d in ordered),
        "missing": [d["id"] for d in ordered if d["have"] is False],
        "unknown": [d["id"] for d in ordered if d["have"] is None],
        "requested_across_schemes": sum(len(d["unlocks"]) for d in ordered),
    }


def documents_for_scheme(scheme_id: str, facts: dict) -> list[str]:
    ids = [_required(e, facts) for e in load_schemes()[scheme_id]["documents"]]
    return [d for d in ids if d]
