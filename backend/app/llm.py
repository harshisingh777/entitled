"""Optional fact extraction through any OpenAI-compatible model.

The model only reads facts out of messy speech. Every value is validated against the
question catalog, and the rules engine still makes every eligibility decision.
"""
import json
import re

import httpx

from . import config
from .engine.rules import load_catalog

_PROMPT = """You extract facts from what an Indian citizen said, usually in Hindi or Hinglish.
Return only a JSON object. Use only these keys, and only when the speaker clearly stated the fact:
{keys}
Never guess. Never say whether anyone qualifies for anything. The question just asked was: {question}"""


def _providers() -> list[tuple[str, str, str]]:
    chain = []
    if config.LLM_API_KEY:
        chain.append((config.LLM_BASE_URL, config.LLM_API_KEY, config.LLM_MODEL))
    if config.LLM_FALLBACK_API_KEY and config.LLM_FALLBACK_BASE_URL:
        chain.append((config.LLM_FALLBACK_BASE_URL, config.LLM_FALLBACK_API_KEY, config.LLM_FALLBACK_MODEL))
    return chain


def available() -> bool:
    return bool(_providers())


def _valid(question: dict, value) -> bool:
    kind = question["type"]
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100_000_000
    return value in question["samples"]


def extract(text: str, expected: str | None) -> dict:
    questions = load_catalog()["questions"]
    keys = "\n".join(
        f"- {name} ({q['type']}{': ' + '/'.join(q['samples']) if q['type'] == 'choice' else ''}): {q['en']}"
        for name, q in questions.items()
    )
    asked = questions[expected]["en"] if expected in questions else "none"
    for base_url, api_key, model in _providers():
        try:
            response = httpx.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "temperature": 0, "messages": [
                    {"role": "system", "content": _PROMPT.format(keys=keys, question=asked)},
                    {"role": "user", "content": text},
                ]},
                timeout=10,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            match = re.search(r"\{.*\}", content, re.DOTALL)
            parsed = json.loads(match.group()) if match else {}
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            continue
        return {k: (v, "inferred") for k, v in parsed.items() if k in questions and _valid(questions[k], v)}
    return {}
