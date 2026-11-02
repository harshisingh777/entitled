"""Prints the numbers quoted in the README. Run from backend/: python scripts/eval.py"""
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

data_dir = tempfile.mkdtemp(prefix="entitled-eval-")
os.environ["ENTITLED_DATA_DIR"] = data_dir
os.environ["DATABASE_URL"] = f"sqlite:///{Path(data_dir, 'eval.db').as_posix()}"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.engine.planner import answer_facts, next_question  # noqa: E402
from app.engine.rules import evaluate_all, load_catalog  # noqa: E402
from app.main import app  # noqa: E402
from tests.data.households import HOUSEHOLDS  # noqa: E402


def accuracy() -> tuple[int, int]:
    right = total = 0
    for household in HOUSEHOLDS:
        for result in evaluate_all(household["facts"])["results"]:
            expected = "eligible" if result["id"] in household["eligible"] else "near_miss" if result["id"] in household["near_miss"] else "not_eligible"
            right += result["outcome"] == expected
            total += 1
    return right, total


def questions_needed(facts: dict) -> int:
    catalog = load_catalog()["questions"]
    known, asked = {}, 0
    while (question := next_question(known)) is not None:
        attr = question["attr"]
        covers = catalog[attr].get("covers")
        known |= answer_facts(attr, any(facts[c] for c in covers) if covers else facts[attr])
        asked += 1
    return asked


def agent_turn_times() -> list[float]:
    answers = {"has_lpg": "No", "has_pucca_house": "No", "formal_income_screen": "No", "rare_circumstances": "No", "has_bank_account": "Yes", "doc_income_certificate": "No"}
    timings = []
    with TestClient(app) as client:
        household = client.post("/api/households", json={}).json()["household"]["id"]
        text = "My name is Kamla Devi, I am a 58 year old widow, I live in a village in Raebareli. I have a BPL card. My son has 1.2 acres of land and my granddaughter is 6 years old. Our yearly income is 40 thousand."
        for _ in range(8):
            started = time.perf_counter()
            state = client.post(f"/api/households/{household}/chat", json={"text": text}).json()["state"]["household"]
            timings.append((time.perf_counter() - started) * 1000)
            if state["expected"] not in answers:
                break
            text = answers[state["expected"]]
    return timings


def main() -> None:
    right, total = accuracy()
    counts = [questions_needed(h["facts"]) for h in HOUSEHOLDS]
    timings = agent_turn_times()
    print(f"Eligibility accuracy: {right}/{total} decisions across {len(HOUSEHOLDS)} households ({right / total:.1%})")
    print(f"Questions to decide all schemes, answering one at a time: median {statistics.median(counts)}, max {max(counts)}")
    print(f"Agent turn, excluding speech: median {statistics.median(timings):.0f} ms")


if __name__ == "__main__":
    main()
