"""The orchestrator: INTERVIEW → ELIGIBILITY → DOCS → FORM → CONFIRM → TRACK, as a LangGraph.

Nodes decide what to do next and call tools. Eligibility always comes from the rules
engine and submission always goes through the gate, so a reply can never promise
something the engine or the gate would refuse.
"""
import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from . import clock, gate, jobs, llm, nlu, tools
from .db import Application, Household, Message, SessionSummary
from .engine import documents as doc_engine
from .engine.planner import answer_facts
from .engine.rules import ELIGIBLE, NEAR_MISS, explain, inr, load_catalog, load_schemes


class AgentState(TypedDict, total=False):
    db: Session
    household: Household
    text: str
    actor: str
    hi: list
    en: list
    route: str
    scheme: str | None
    understood: bool


def _say(state: AgentState, hi: str, en: str) -> None:
    state["hi"].append(hi)
    state["en"].append(en)


def _set(household: Household, **values) -> None:
    household.agent_state = {**household.agent_state, **values}


def _ask(state: AgentState, hi: str, en: str, **pending) -> None:
    household = state["household"]
    _say(state, hi, en)
    _set(household, last_prompt={"hi": hi, "en": en}, expected=None, pending_field=None, pending_digit=None)
    _set(household, **pending)


def _scheme_from_text(text: str, results: list[dict]) -> str | None:
    found = nlu.matches_scheme(text, load_schemes())
    if found:
        return found
    if re.search(r"पेंशन|pension", nlu.normalize(text)):
        pensions = [r for r in results if load_schemes()[r["id"]].get("conflict_group") == "pension"]
        usable = [r for r in pensions if r["outcome"] == ELIGIBLE and not r.get("suppressed_by")]
        return (usable or pensions)[0]["id"] if pensions else None
    return None


def _announce_changes(state: AgentState, result: dict) -> None:
    """Speak the rule trace for whatever just became decided. Two at most, so a voice turn stays short."""
    household = state["household"]
    before = household.agent_state.get("outcomes", {})
    current = {r["id"]: r["outcome"] for r in result["results"]}
    fresh = [r for r in result["results"]
             if r["outcome"] in (ELIGIBLE, NEAR_MISS) and before.get(r["id"]) != r["outcome"] and not r.get("suppressed_by")]
    for item in fresh[:2]:
        _say(state, explain(item, "hi"), explain(item, "en"))
    if len(fresh) > 2:
        extra = len(fresh) - 2
        _say(state, f"{extra} और योजनाओं का फ़ैसला भी हो गया, सूची में देखिए।", f"{extra} more schemes were decided, see the list.")
    _set(household, outcomes=current)


def _pick_scheme(result: dict, household: Household) -> str | None:
    started = {a.scheme_id for a in household.applications if a.status in tools.SUBMITTED_STATES}
    usable = [r for r in result["results"] if r["outcome"] == ELIGIBLE and not r.get("suppressed_by") and r["id"] not in started]
    usable.sort(key=lambda r: (-r["annual_inr"], -r["one_time_inr"], -r["cover_inr"]))
    return usable[0]["id"] if usable else None


# ---- graph nodes ---------------------------------------------------------------------------

def ingest(state: AgentState) -> dict:
    db, household, text = state["db"], state["household"], state["text"]
    agent = household.agent_state
    digit, field, expected = agent.get("pending_digit"), agent.get("pending_field"), agent.get("expected")

    if digit:
        answer = nlu.yes_no(text)
        again = nlu.extract_profile_field(digit["field"], text)
        if answer is True:
            tools.set_fact(db, household, digit["field"], digit["value"], "confirmed")
            _set(household, pending_digit=None)
            return {"route": "form"}
        if again and answer is not False:
            return _read_digits(state, digit["field"], again)
        ask = load_catalog()["profile_fields"][digit["field"]]
        _ask(state, f"ठीक है, दोबारा बताइए। {ask['ask_hi']}", f"All right, once more. {ask['ask_en']}", pending_field=digit["field"])
        return {"route": "end"}

    if field:
        value = nlu.extract_profile_field(field, text)
        spec = load_catalog()["profile_fields"][field]
        if value is None:
            _say(state, f"यह समझ नहीं आया। {spec['ask_hi']}", f"I did not catch that. {spec['ask_en']}")
            return {"route": "end"}
        if spec.get("digits"):
            return _read_digits(state, field, value)
        tools.set_fact(db, household, field, value, "said")
        _set(household, pending_field=None)
        return {"route": "form"}

    if household.stage == "CONFIRM":
        return {"route": "confirm"}

    understood = False
    if expected == "start_form":
        answer = nlu.yes_no(text)
        if answer is True:
            _set(household, expected=None)
            return {"route": "form"}
        if answer is False:
            _ask(state, "ठीक है, अभी नहीं। जब मन हो तब बोलिए: फॉर्म भरो।", "All right, not now. Say: fill the form, whenever you are ready.")
            return {"route": "end"}
    elif expected and expected.startswith("doc_"):
        answer = nlu.yes_no(text)
        if answer is not None:
            tools.set_fact(db, household, expected, answer, "said")
            _set(household, expected=None)
            understood = True

    extracted = nlu.extract_facts(text, expected if expected != "start_form" else None)
    if not extracted and not understood and not nlu.is_dont_know(text) and llm.available() and not nlu.detect_intent(text):
        extracted = llm.extract(text, expected)
        if extracted:
            tools.audit(db, household.id, "llm_extract", {"text": text}, {"keys": list(extracted)})
    for key, (value, source) in extracted.items():
        for fact, fact_value in answer_facts(key, value).items():
            tools.set_fact(db, household, fact, fact_value, source)
        understood = True

    if expected and expected != "start_form" and nlu.is_dont_know(text):
        _set(household, skipped=sorted({*agent.get("skipped", []), expected}), expected=None)
        understood = True

    result = tools.check_eligibility(db, household)
    if household.stage != "INTERVIEW" or understood:
        _announce_changes(state, result)

    intent = nlu.detect_intent(text)
    scheme = _scheme_from_text(text, result["results"])
    if intent == "why":
        return {"route": "explain", "scheme": scheme, "understood": True}
    if intent == "status" and household.applications:
        return {"route": "track", "understood": True}
    if intent == "apply":
        if scheme:
            _set(household, active_scheme=scheme)
        return {"route": "form", "understood": True}
    if intent == "documents" and household.stage != "INTERVIEW":
        _set(household, docs_intro=False)
        return {"route": "docs", "understood": True}

    route = {"INTERVIEW": "interview", "DOCS": "docs", "FORM": "form", "TRACK": "track"}.get(household.stage, "interview")
    return {"route": route, "understood": understood}


def _read_digits(state: AgentState, field: str, value: str) -> dict:
    spec = load_catalog()["profile_fields"][field]
    spaced = " ".join(value)
    _ask(state, f"{spec['hi']}: {spaced}। क्या यह सही है?", f"{spec['en']}: {spaced}. Is that right?",
         pending_digit={"field": field, "value": value})
    return {"route": "end"}


def interview(state: AgentState) -> dict:
    db, household = state["db"], state["household"]
    question = tools.next_question(db, household)
    if question is None:
        return {"route": "eligibility"}
    agent = household.agent_state
    if agent.get("expected") == question["attr"] and not state.get("understood"):
        _say(state, "यह समझ नहीं आया, फिर से बताइए।", "I did not catch that, please say it again.")
    household.questions_asked += 1
    _ask(state, question["hi"], question["en"], expected=question["attr"])
    return {"route": "end"}


def eligibility(state: AgentState) -> dict:
    db, household = state["db"], state["household"]
    result = tools.check_eligibility(db, household)
    counts, totals = result["counts"], result["totals"]
    usable = [r for r in result["results"] if r["outcome"] == ELIGIBLE and not r.get("suppressed_by")]
    money_hi = f"हर साल ₹{inr(totals['annual_inr'])}" if totals["annual_inr"] else "नियमित राशि नहीं"
    money_en = f"₹{totals['annual_inr']:,} every year" if totals["annual_inr"] else "no regular payment"
    _say(state, f"जानकारी पूरी हुई। आपके परिवार का हक़ {len(usable)} योजनाओं पर बनता है: {money_hi}।",
         f"That is everything I need. Your family is entitled to {len(usable)} schemes: {money_en}.")
    for conflict in result["conflicts"]:
        _say(state, conflict["hi"], conflict["en"])
    if counts[NEAR_MISS]:
        _say(state, f"{counts[NEAR_MISS]} योजनाएँ बस एक क़दम दूर हैं।", f"{counts[NEAR_MISS]} schemes are one step away.")
    if counts["undecided"]:
        _say(state, f"{counts['undecided']} योजनाओं का फ़ैसला बाकी है, क्योंकि कुछ जानकारी नहीं मिली।",
             f"{counts['undecided']} schemes stay undecided because some answers are missing.")
    _say(state, "आख़िरी फ़ैसला विभाग करता है।", "The department makes the final decision.")
    household.stage = "DOCS"
    audit_summary = {"counts": counts, "annual_inr": totals["annual_inr"], "questions": household.questions_asked}
    tools.audit(db, household.id, "eligibility_summary", {}, audit_summary)
    return {"route": "docs"}


def docs(state: AgentState) -> dict:
    db, household = state["db"], state["household"]
    result = tools.check_eligibility(db, household, log=False)
    plan = tools.plan_documents(db, household, result["results"])
    catalog = load_catalog()["documents"]
    household.stage = "DOCS"

    if not household.agent_state.get("docs_intro"):
        _set(household, docs_intro=True)
        if plan["total"]:
            _say(state, f"सब योजनाओं के लिए कुल {plan['total']} दस्तावेज़ लगेंगे। हर एक सिर्फ़ एक बार देना है।",
                 f"All these schemes need {plan['total']} documents in total. Each one is needed only once.")

    if plan["missing"]:
        top = next(d for d in plan["items"] if d["id"] == plan["missing"][0])
        if household.agent_state.get("announced_missing") != plan["missing"]:
            _set(household, announced_missing=plan["missing"])
            _say(state, f"{top['name']['hi']} बनवाने से {len(top['unlocks'])} योजनाएँ खुलेंगी। {top['where']['hi']} से, {top['time']['hi']} में।",
                 f"Getting the {top['name']['en']} opens {len(top['unlocks'])} schemes. From {top['where']['en']}, in {top['time']['en']}.")

    if plan["unknown"]:
        doc = catalog[plan["unknown"][0]]
        _ask(state, f"क्या आपके पास {doc['hi']} है? फ़ोटो भी भेज सकते हैं।", f"Do you have the {doc['en']}? You can also send a photo.",
             expected=f"doc_{plan['unknown'][0]}")
        return {"route": "end"}

    scheme_id = _pick_scheme(result, household)
    if not scheme_id:
        _ask(state, "अभी कोई नया फॉर्म भरने को नहीं है। जो बाकी है वह ऊपर की सूची में है।", "There is no new form to fill right now. What is pending is in the list.")
        return {"route": "end"}
    name = load_schemes()[scheme_id]["name"]
    _set(household, active_scheme=scheme_id)
    _ask(state, f"अब {name['hi']} का फॉर्म भर दूँ?", f"Shall I fill the {name['en']} form now?", expected="start_form", active_scheme=scheme_id)
    return {"route": "end"}


def form(state: AgentState) -> dict:
    db, household = state["db"], state["household"]
    result = tools.check_eligibility(db, household, log=False)
    scheme_id = household.agent_state.get("active_scheme") or _pick_scheme(result, household)
    if not scheme_id:
        _say(state, "अभी कोई योजना फॉर्म के लिए तैयार नहीं है।", "No scheme is ready for a form yet.")
        return {"route": "end"}

    outcome = next(r for r in result["results"] if r["id"] == scheme_id)
    if outcome["outcome"] != ELIGIBLE:
        _say(state, explain(outcome, "hi"), explain(outcome, "en"))
        _set(household, active_scheme=None)
        return {"route": "end"}
    if outcome.get("suppressed_by"):
        better = load_schemes()[outcome["suppressed_by"]]["name"]
        _say(state, f"ध्यान दीजिए: यह और {better['hi']} एक साथ नहीं मिल सकतीं, और {better['hi']} में ज़्यादा राशि है।",
             f"Note: this and {better['en']} cannot be drawn together, and {better['en']} pays more.")

    household.stage = "FORM"
    _set(household, active_scheme=scheme_id)
    app = tools.open_application(db, household, scheme_id)
    if app.status in tools.SUBMITTED_STATES:
        return {"route": "track"}

    facts = tools.facts_of(household)
    required = doc_engine.documents_for_scheme(scheme_id, facts)
    catalog = load_catalog()
    missing_doc = next((d for d in required if facts.get(f"doc_{d}") is False), None)
    if missing_doc:
        doc = catalog["documents"][missing_doc]
        _say(state, f"इस फॉर्म के लिए {doc['hi']} चाहिए। {doc['where']['hi']} से {doc['time']['hi']} में बनेगा। बन जाए तो बताइए।",
             f"This form needs the {doc['en']}. {doc['where']['en']} issues it in {doc['time']['en']}. Tell me when you have it.")
        household.stage = "DOCS"
        return {"route": "end"}
    unknown_doc = next((d for d in required if f"doc_{d}" not in facts), None)
    if unknown_doc:
        doc = catalog["documents"][unknown_doc]
        _ask(state, f"क्या आपके पास {doc['hi']} है?", f"Do you have the {doc['en']}?", expected=f"doc_{unknown_doc}")
        return {"route": "end"}

    _, missing = tools.form_fields(scheme_id, facts)
    if missing:
        spec = catalog["profile_fields"][missing[0]]
        _ask(state, spec["ask_hi"], spec["ask_en"], pending_field=missing[0])
        return {"route": "end"}

    name = load_schemes()[scheme_id]["name"]
    try:
        tools.fill_form(db, household, app)
    except jobs.Busy:
        tools.audit(db, household.id, "fill_form", {"scheme": scheme_id}, {"error": "busy"}, outcome="failed")
        _say(state, "सर्वर अभी दूसरा काम कर रहा है। एक मिनट बाद बोलिए: फॉर्म भरो।",
             "The server is busy with another document or form. Please say: fill the form, again in a minute.")
        return {"route": "end"}
    except Exception as exc:  # The browser agent runs apart from us, and any failure there must reach the person as words.
        tools.audit(db, household.id, "fill_form", {"scheme": scheme_id}, {"error": str(exc)[:300]}, outcome="failed")
        _say(state, "फॉर्म भरने में दिक़्क़त आई। फिर से बोलिए: फॉर्म भरो।", "Filling the form failed. Please say: fill the form, to try again.")
        return {"route": "end"}
    _say(state, f"{name['hi']} का फॉर्म भर दिया है। अभी भेजा नहीं है।", f"The {name['en']} form is filled. It has not been sent.")
    return {"route": "readback"}


def readback(state: AgentState) -> dict:
    db, household = state["db"], state["household"]
    app = _active_app(household)
    summary = tools.read_back(db, household, app)
    household.stage = "CONFIRM"
    _ask(state, summary["hi"], summary["en"])
    return {"route": "end"}


def _active_app(household: Household) -> Application:
    scheme_id = household.agent_state.get("active_scheme")
    return next(a for a in household.applications if a.scheme_id == scheme_id)


def confirm(state: AgentState) -> dict:
    db, household, text = state["db"], state["household"], state["text"]
    app = _active_app(household)

    for key, (value, source) in nlu.extract_facts(text).items():
        if key in load_schemes()[app.scheme_id]["form"]:
            tools.set_fact(db, household, key, value, source)
    if tools._sync_fields(app, household):
        _say(state, "जानकारी बदली है, इसलिए पहले वाली पुष्टि रद्द हो गई।", "The details changed, so the earlier confirmation is cancelled.")
        return {"route": "form"}

    if nlu.refuses_send(text):
        _ask(state, "ठीक है, नहीं भेजा। जो बदलना है बताइए, या जब तैयार हों तो बोलिए: हाँ, भेज दो।",
             "All right, nothing was sent. Tell me what to change, or say: yes, send it, when you are ready.")
        return {"route": "end"}
    if nlu.confirms_send(text):
        return _submit(state, app, "voice")
    _say(state, "भेजने के लिए पूरा बोलिए: हाँ, भेज दो। या बताइए क्या बदलना है।", "To send it, please say in full: yes, send it. Or tell me what to change.")
    return {"route": "end"}


def _submit(state: AgentState, app: Application, method: str) -> dict:
    db, household = state["db"], state["household"]
    try:
        token = tools.confirm_application(db, household, app, method, state.get("actor", "applicant"))
        outcome = tools.submit_application(db, household, app, token)
    except gate.GateRefused as refused:
        _say(state, refused.hi, refused.en)
        return {"route": "end"}
    name = load_schemes()[app.scheme_id]["name"]
    _say(state, f"{name['hi']} का आवेदन भेज दिया। संदर्भ संख्या: {outcome['reference']}। 10 दिन बाद याद दिलाऊँगी।",
         f"The {name['en']} application is sent. Reference: {outcome['reference']}. I will remind you in 10 days.")
    household.stage = "TRACK"
    _set(household, active_scheme=None)
    return {"route": "track"}


def track(state: AgentState) -> dict:
    db, household = state["db"], state["household"]
    household.stage = "TRACK"
    if state.get("text") and nlu.detect_intent(state["text"]) == "status":
        for app in household.applications:
            if app.submitted_at:
                _say(state, *_status_line(db, household, app))
    result = tools.check_eligibility(db, household, log=False)
    next_id = _pick_scheme(result, household)
    if next_id:
        name = load_schemes()[next_id]["name"]
        _ask(state, f"अब {name['hi']} का फॉर्म भर दूँ?", f"Shall I fill the {name['en']} form next?", expected="start_form", active_scheme=next_id)
    return {"route": "end"}


def _status_line(db: Session, household: Household, app: Application) -> tuple[str, str]:
    state = tools.check_status(db, household, app)
    name = load_schemes()[app.scheme_id]["name"]
    label = tools.STATUS_LABELS[state["status"]]
    action = app.next_action or {"hi": "", "en": ""}
    return (f"{name['hi']}: {label['hi']}, {state['days']} दिन से। {action['hi']}".strip(),
            f"{name['en']}: {label['en']}, {state['days']} days. {action['en']}".strip())


def explain_node(state: AgentState) -> dict:
    db, household = state["db"], state["household"]
    scheme = state.get("scheme")
    if scheme:
        answer = tools.explain_rule(db, household, scheme)
        _say(state, answer["hi"], answer["en"])
    else:
        _say(state, "किस योजना के बारे में पूछ रहे हैं? उसका नाम बताइए।", "Which scheme are you asking about? Tell me its name.")
    prompt = household.agent_state.get("last_prompt")
    if prompt:
        _say(state, prompt["hi"], prompt["en"])
    return {"route": "end"}


def _after(state: AgentState) -> str:
    return state["route"]


def _build_graph():
    graph = StateGraph(AgentState)
    nodes = {"ingest": ingest, "interview": interview, "eligibility": eligibility, "docs": docs, "form": form,
             "readback": readback, "confirm": confirm, "track": track, "explain": explain_node}
    for name, fn in nodes.items():
        graph.add_node(name, fn)
    graph.add_edge(START, "ingest")
    targets = {"end": END, **{n: n for n in nodes if n != "ingest"}}
    for name in nodes:
        graph.add_conditional_edges(name, _after, targets)
    return graph.compile()


_graph = _build_graph()


# ---- entry points --------------------------------------------------------------------------

def _record(db: Session, household: Household, role: str, hi: str, en: str, kind: str = "text") -> None:
    db.add(Message(household_id=household.id, role=role, hi=hi, en=en, kind=kind,
                   session_no=household.session_no, created_at=clock.now(db)))


def handle_turn(db: Session, household: Household, text: str, actor: str = "applicant") -> dict:
    _record(db, household, "user", text, text)
    state: AgentState = {"db": db, "household": household, "text": text, "actor": actor, "hi": [], "en": []}
    _graph.invoke(state, {"recursion_limit": 25})
    reply = {"hi": " ".join(state["hi"]), "en": " ".join(state["en"])}
    _record(db, household, "agent", reply["hi"], reply["en"])
    db.commit()
    return reply


def confirm_by_tap(db: Session, household: Household, app: Application, actor: str = "applicant") -> dict:
    state: AgentState = {"db": db, "household": household, "text": "", "actor": actor, "hi": [], "en": [], "route": "end"}
    _set(household, active_scheme=app.scheme_id)
    _record(db, household, "user", "हाँ, भेज दो (बटन)", "Yes, send it (button)")
    if _submit(state, app, "tap")["route"] == "track":
        track(state)
    reply = {"hi": " ".join(state["hi"]), "en": " ".join(state["en"])}
    _record(db, household, "agent", reply["hi"], reply["en"])
    db.commit()
    return reply


def begin_form(db: Session, household: Household, scheme_id: str) -> dict:
    """Tapping 'apply' on a scheme enters the same graph step as saying it."""
    state: AgentState = {"db": db, "household": household, "text": "", "actor": "applicant", "hi": [], "en": []}
    _set(household, active_scheme=scheme_id, expected=None, pending_field=None, pending_digit=None)
    route = form(state)["route"]
    if route == "readback":
        readback(state)
    elif route == "track":
        track(state)
    reply = {"hi": " ".join(state["hi"]), "en": " ".join(state["en"])}
    _record(db, household, "agent", reply["hi"], reply["en"])
    db.commit()
    return reply


def welcome(db: Session, household: Household, actor_is_operator: bool = False) -> dict:
    state: AgentState = {"db": db, "household": household, "text": "", "actor": "agent", "hi": [], "en": []}
    _say(state, "नमस्ते! मैं Entitled हूँ। जो आपका हक़ है, उसे आप तक पहुँचाना मेरा काम है। पूरे परिवार के बारे में एक साथ बता सकते हैं, या मेरे सवालों के जवाब दीजिए।",
         "Hello! I am Entitled. My job is to get you what is rightfully yours. Tell me about your whole family at once, or just answer my questions.")
    question = tools.next_question(db, household)
    if question:
        household.questions_asked += 1
        _ask(state, question["hi"], question["en"], expected=question["attr"])
    reply = {"hi": " ".join(state["hi"]), "en": " ".join(state["en"])}
    _record(db, household, "agent", reply["hi"], reply["en"])
    db.commit()
    return reply


def resume_session(db: Session, household: Household) -> dict:
    """New session: remember where things stood and pick up from the next step."""
    facts = tools.facts_of(household)
    tools.poll_statuses(db)
    live = [a for a in household.applications if a.submitted_at]
    db.add(SessionSummary(
        household_id=household.id, session_no=household.session_no,
        summary={"stage": household.stage, "applications": {a.scheme_id: a.status for a in household.applications}, "facts": len(facts)},
        created_at=clock.now(db),
    ))
    household.session_no += 1
    person = facts.get("name", "").split(" ")[0] if facts.get("name") else ""
    hi_name = f"{person} जी, " if person else ""
    en_name = f"{person} ji, " if person else ""
    hi, en = [f"{hi_name}आपका फिर से स्वागत है।"], [f"{en_name}welcome back."]
    for app in live:
        name = load_schemes()[app.scheme_id]["name"]
        days = (clock.now(db) - app.submitted_at).days
        label = tools.STATUS_LABELS[app.status]
        if app.status == "under_verification" and days >= tools.BLOCK_OFFICE_REMINDER_DAYS:
            docs = ", ".join(load_catalog()["documents"][d]["hi"] for d in app.documents) or "संदर्भ संख्या"
            docs_en = ", ".join(load_catalog()["documents"][d]["en"] for d in app.documents) or "the reference number"
            hi.append(f"आपका {name['hi']} का आवेदन {days} दिन से जाँच में है। ब्लॉक कार्यालय जाने का समय आ गया है। ये साथ ले जाइए: {docs}। संदर्भ संख्या: {app.reference}।")
            en.append(f"Your {name['en']} application has been in verification for {days} days. It is time to visit the block office. Take: {docs_en}. Reference: {app.reference}.")
        else:
            hi.append(f"{name['hi']} की स्थिति: {label['hi']}।")
            en.append(f"{name['en']} status: {label['en']}.")
    if not live:
        prompt = household.agent_state.get("last_prompt")
        if prompt:
            hi.append(prompt["hi"])
            en.append(prompt["en"])
    reply = {"hi": " ".join(hi), "en": " ".join(en)}
    _record(db, household, "agent", reply["hi"], reply["en"])
    tools.audit(db, household.id, "resume_session", {"session": household.session_no}, {"applications": len(live)})
    db.commit()
    return reply
