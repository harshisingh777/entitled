# हक़दार · Haqdaar
### *"Jo tumhara haq hai, woh tum tak pahunche."*

**Problem statement:** PS-01 · Scheme Saathi — welfare scheme agent
**One-liner:** A Hindi-first voice agent that finds every government scheme a family is entitled to, proves *why* with a rule trace, turns missing documents into a to-do list, pre-fills the application, and chases it until the money lands.

> **Haqdaar** (हक़दार) = "the one who is rightfully entitled." The framing is deliberate: schemes are not charity, they are the citizen's *haq*. The agent's job is to close the gap between being entitled and actually receiving.

---

## 1. Why this PS

| Criterion (weight) | Why PS-01 scores here |
|---|---|
| Problem fit & impact (25%) | Massive, measurable, India-specific. myScheme lists 4000+ schemes (550+ central, 3440+ state/UT), yet uptake depends on literacy, language and knowing which office to visit. |
| Agent design (25%) | Naturally multi-step: interview → eligibility tools → document planning → form filling → human gate → follow-up scheduling. Real memory across sessions (a family's profile and pending applications). |
| Demo (20%) | Fully demo-able in 3 min with a Hindi voice conversation and a visible form being filled. |
| Innovation (15%) | Deterministic + explainable eligibility, "near-miss" detection, scheme conflict detection, operator (CSC/ASHA) mode. |
| Presentation (15%) | Emotional, relatable story (a farmer's widowed mother in Raebareli), easy to pitch. |

Other PSes (placement co-pilot, bug-fix agent, trading bot) will be crowded with near-identical builds. PS-01 rewards domain depth, which most teams will skip.

---

## 2. Who the user is

**Primary:** a rural / semi-urban citizen with a smartphone, comfortable speaking Hindi (or Awadhi/Bhojpuri-mixed Hindi), not comfortable reading English government portals.

**Secondary (force multiplier):** a **Gram Saathi operator** — CSC VLE, ASHA worker, panchayat volunteer, NGO field worker — who helps 20–50 families a week. Operator mode lets one person run Haqdaar for many households, with each family's profile and follow-ups kept separately.

**Persona for the demo:** *Kamla Devi, 58, Raebareli. Widowed, BPL ration card, son is a small farmer with 1.2 acres, granddaughter aged 6.* She has heard of "pension" but has never applied for anything.

---

## 3. Why an agent, not a chatbot

A chatbot can *tell* Kamla about PM-KISAN. Haqdaar *does the job*:

1. **Plans** — decides which questions to ask next based on which schemes are still undecided (no 40-question form).
2. **Calls tools** — eligibility engine, document planner, OCR, form filler, reminder scheduler, status tracker.
3. **Remembers** — the household profile, uploaded documents, applications in flight, next follow-up date.
4. **Acts** — produces a filled application and schedules follow-ups.
5. **Stops for a human** — nothing is submitted without explicit spoken/typed confirmation of a read-back summary.

---

## 4. Core features

### 4.1 Hindi voice/text conversation
- Speech-to-text: **Sarvam Saaras v3** (handles Hindi–English code-mixing, auto language detection).
- Text-to-speech: **Sarvam Bulbul v3** — every agent reply is spoken back.
- Fallback: **Bhashini** (govt. Dhruva pipeline) for STT/TTS/translation.
- Text mode via web chat (and WhatsApp stretch goal).

### 4.2 Adaptive interview (information-gain questioning)
The planner keeps a set of *undecided* schemes. Each next question is the attribute that resolves the most undecided schemes (age? land owned? BPL card? girl child under 10? widow?). Typical household resolved in **~8–12 questions** instead of a long form.

### 4.3 Deterministic, explainable eligibility engine *(key differentiator)*
- Scheme rules encoded as **JSON-Logic** files, one per scheme, with source link to the myScheme / official page.
- **The LLM never decides eligibility.** It only extracts facts; the rules engine decides. No hallucinated "you qualify".
- Every result returns a **rule trace**, spoken in Hindi:
  > "Aap Vridhavastha Pension ke liye *paatra* hain — umar 60+ ✅, BPL card ✅. Lekin abhi aapki umar 58 hai, isliye 2 saal baad."
- Three outcomes: ✅ Eligible · ❌ Not eligible (with reason) · 🟡 **Near-miss** (eligible if one gap is fixed, e.g. "income certificate banwa lo, phir Kanya Sumangala mil sakti hai").
- **Conflict detection:** flags mutually exclusive benefits (e.g. two pensions that cannot be drawn together) and recommends the higher-value one.

### 4.4 Document checklist planner
- Union of documents across all chosen schemes, **deduplicated** (Aadhaar once, not five times).
- Marks what the family already has (from conversation or upload) vs. what is missing.
- Missing documents become **actions**: where to get it (tehsil/CSC/online), typical time, and which schemes it unlocks — sorted by "most schemes unlocked per document".

### 4.5 Document reading (OCR)
- User sends photos of ration card / Aadhaar / bank passbook.
- **Sarvam Vision** (or Tesseract + layout rules as fallback) extracts name, DOB, address, IFSC, account no.
- Privacy: Aadhaar masked to last 4 digits in storage and UI; raw images deleted after extraction; demo uses synthetic documents only.

### 4.6 Form pre-fill
- Mock state-portal application forms (built by us, realistic field layout).
- **Playwright** agent fills the form from the household profile, screenshot shown to user.
- Also generates a **printable pre-filled PDF** for schemes applied offline at the block office.

### 4.7 Human confirmation gate (mandatory)
- Before submission: agent reads back a short summary in Hindi — scheme, name, bank account last 4, documents attached.
- Requires explicit "haan, bhej do" / button tap. Any field change resets confirmation.
- Gate is enforced in code (submit tool refuses without a signed confirmation token), not just in the prompt.

### 4.8 Follow-up tracking
- Each submitted application gets a tracker: submitted → under verification → approved → first instalment.
- Mock status API polled on a schedule; reminders via SMS/WhatsApp sandbox (Twilio) or in-app notification.
- Agent resumes context next session: *"Kamla ji, aapki pension application 12 din se verification mein hai. Block office jaane ka samay aa gaya hai — yeh rahi zaroori cheezein."*

### 4.9 Memory
- **Household profile** (structured facts with source + confidence: said / from document / inferred-and-confirmed).
- **Application ledger** (status history, next action, due date).
- **Conversation summary** per session for continuity.

---

## 5. Architecture

```
          Voice / Text (Web PWA, WhatsApp stretch)
                         │
                Sarvam STT  ←→  Sarvam TTS
                         │
                 ┌───────▼────────┐
                 │ Orchestrator   │  LLM planner (tool-calling, ReAct-style)
                 │ (LangGraph)    │  state machine: INTERVIEW → ELIGIBILITY
                 └───┬───┬───┬────┘  → DOCS → FORM → CONFIRM → TRACK
                     │   │   │
   ┌─────────────────┘   │   └───────────────────┐
   ▼                     ▼                       ▼
Tools                 Memory                 Guardrails
- next_question()     - Postgres:            - confirm-token gate
- check_eligibility()   households,          - PII masking
- explain_rule()        applications,        - rules-only eligibility
- plan_documents()      reminders            - action audit log
- ocr_document()      - session summaries
- fill_form()
- submit_application()  ← requires confirmation token
- schedule_reminder()
- check_status()
                     │
          Rule store: /schemes/*.json (JSON-Logic + metadata + source URL)
          Mock portals: FastAPI forms + status API
```

**Stack:** Python, FastAPI, LangGraph, json-logic-py, Playwright, PostgreSQL (or SQLite for demo), Next.js PWA, Sarvam APIs, Bhashini fallback, APScheduler for follow-ups, Twilio sandbox for SMS/WhatsApp.

**LLM:** any tool-calling model; Sarvam-30B as the Indic-native option, a frontier model as fallback for planning reliability.

---

## 6. Scheme coverage for the MVP (~12–15 schemes)

Mix of central + Uttar Pradesh schemes so the demo persona hits several outcomes. Candidates (rules to be encoded from official / myScheme pages, each verified before demo):

- **Central:** PM-KISAN, PM Ujjwala Yojana, Ayushman Bharat PM-JAY, PMAY-Gramin, PM Matru Vandana Yojana, Sukanya Samriddhi Yojana, PM Vishwakarma, PM Jeevan Jyoti / Suraksha Bima, Atal Pension Yojana, NSAP old-age / widow pension.
- **Uttar Pradesh:** Mukhyamantri Kanya Sumangala Yojana, UP Vridhavastha Pension, UP Nirashrit Mahila (widow) Pension, UP scholarship.

Scheme data source for descriptions: myScheme pages + the public myScheme dataset on Hugging Face (descriptions only; eligibility rules hand-encoded and cited).

---

## 7. Action log & safety

- Every tool call logged: timestamp, tool, inputs (PII-masked), output, who confirmed.
- Agent cannot submit, send messages to third parties, or delete data without the confirmation gate.
- Explicit disclaimer: Haqdaar assists; final eligibility is decided by the department.
- Demo runs only on mock portals and synthetic identity documents.

---

## 8. 3-minute demo script

| Time | Scene |
|---|---|
| 0:00–0:20 | Hook: "Kamla Devi is entitled to ₹X/year in benefits. She receives ₹0." |
| 0:20–1:10 | Kamla speaks in Hindi. Agent asks ~6 adaptive questions; eligibility panel updates live with ✅ ❌ 🟡 and spoken rule trace. |
| 1:10–1:40 | Photo of ration card → fields auto-extracted. Document checklist shows 2 missing items and which schemes they unlock. |
| 1:40–2:15 | Playwright fills the mock pension form on screen. Agent reads back the summary. User says "haan, bhej do" → submitted. Show refusal when confirmation is missing. |
| 2:15–2:45 | Time-skip: status API changes, reminder SMS arrives, agent resumes from memory with next step. |
| 2:45–3:00 | Operator mode: one ASHA worker, 30 households, pending actions dashboard. Close on impact. |

---

## 9. Idea deck (6 slides)

1. **Problem** — Kamla Devi's story + scale (4000+ schemes, scattered, English-heavy portals, uptake gap).
2. **User & why an agent** — citizen + Gram Saathi operator; chatbot vs agent comparison.
3. **Solution flow** — Talk → Find (explainable) → Prepare docs → Fill → Confirm → Track.
4. **Agent design** — architecture diagram, tools list, memory, confirmation gate.
5. **What's new** — deterministic rule engine with Hindi rule trace, near-miss + conflict detection, doc-unlock ranking, operator mode.
6. **Plan & impact** — 10-day build plan, metrics (questions to decision, eligibility accuracy vs hand-checked cases, time-to-filled-form), team.

---

## 10. Build plan (2 Nov → 12 Nov 10:00 AM)

| Days | Work |
|---|---|
| 2 Nov | Idea deck submitted. Repo scaffold. |
| 3–4 Nov | Encode 12–15 scheme rules (JSON-Logic) + 25 hand-labelled test households for eligibility accuracy. Rule engine + explain_rule. |
| 4–5 Nov | Orchestrator (LangGraph) with tool calls; adaptive question selection; Postgres memory. |
| 6 Nov | Sarvam STT/TTS voice loop; Bhashini fallback. |
| 7 Nov | Mock portals + status API; Playwright form filler; PDF generator; confirmation gate. |
| 8 Nov | OCR pipeline on synthetic documents; document planner. |
| 9 Nov | Follow-up scheduler + SMS/WhatsApp sandbox; operator dashboard. |
| 10 Nov | End-to-end reliability: run all 25 test households, fix failures, record eval numbers for README. |
| 11 Nov | Demo video, README, final 6-slide deck. Buffer. |
| 12 Nov, before 10:00 | Submit. |

---

## 11. Success metrics (shown in README)

- Eligibility accuracy on 25 hand-labelled households (target: 100% — it's deterministic, so any miss is a rule bug).
- Median questions to resolve all schemes (target ≤ 12).
- Voice turn latency (target < 3 s).
- Form pre-fill field accuracy from OCR + conversation.
- Zero submissions without a valid confirmation token (tested).

---

## 12. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Eligibility rules change / are ambiguous | Each rule file stores source URL + "last verified" date; ambiguous criteria become a clarifying question, never a guess. |
| STT errors on names/numbers | Read-back confirmation of critical fields; digits confirmed one by one. |
| No real government submission API | Mock portals that mirror real form fields; architecture keeps `submit_application()` swappable. |
| PII exposure | Synthetic data only in demo; masking; images deleted post-OCR. |
| Live demo failure | Recorded fallback run; text mode as backup for voice. |

---

## 13. Future scope

- More languages (Sarvam Saaras covers 22 Indian languages).
- DigiLocker document pull (with consent) instead of photo uploads.
- Real integration with state portals / CSC backend.
- IVR / feature-phone access via missed-call callback.
