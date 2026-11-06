# Entitled

*What is rightfully yours should reach you.*

A voice agent that finds every government scheme a family is entitled to, proves why with a rule trace, turns missing documents into a to-do list, pre-fills the application, and follows it until the money lands.

Schemes are not charity. They are a citizen's right, and Entitled closes the gap between being entitled and actually receiving. Built for PS-01, Scheme Saathi. The full brief is in [detail.md](detail.md).

The website and the agent's replies and speech are in English. The agent can still understand Hindi and romanised Hindi if someone types them, but it always answers in English.

## Run it

You need Python 3.10+ and Node 20+.

```powershell
.\run.ps1
```

```bash
./run.sh
```

Then open <http://localhost:3000>. The first run installs dependencies and a headless Chromium. No API keys are needed.

Press **Walk through Kamla Devi's case** for the demo, or **Open operator mode** for the 30-household dashboard.

Microphones only work on `localhost` or HTTPS, so to try voice on a phone over your network you need an HTTPS tunnel. Everything else works over plain LAN at `http://<your-ip>:3000`.

To run it in Docker or put it on a server, see [DEPLOYMENT.md](DEPLOYMENT.md).

## What it does

| Step | What happens |
|---|---|
| **Talk** | Speak or type. One sentence can answer many questions. Otherwise an adaptive interview asks whichever question settles the most undecided schemes. |
| **Find out why** | A deterministic rules engine decides. Every result carries a spoken rule trace, with near-miss and conflict detection. |
| **Prepare papers** | Documents are deduplicated across schemes and ranked by how many schemes each one unlocks. Photos are read on the phone itself by our own OCR model, UniOCR, and never stored. Aadhaar is reduced to its last 4 digits before anything leaves the phone. |
| **Fill** | A Playwright agent fills the mock portal form on screen. A printable pre-filled PDF is also available. |
| **Your yes** | Nothing is sent until the person hears a read-back and confirms. This is enforced in code by a signed token bound to the exact field values. Any edit cancels it. |
| **Track** | Status polling, reminders, and an agent that resumes from memory with the next step. |

Operator mode lets one ASHA or CSC worker run many households, with pending tasks and overdue follow-ups. The action log records every tool call with personal numbers masked.

## Document reading with UniOCR

Documents are read by **UniOCR**, our own offline OCR engine (PP-OCRv6 detection and recognition, packaged with its sha256 manifest as [`uniocr_mobile.bin`](frontend/public/models/uniocr_mobile.bin)).

| Where | When | What leaves the phone |
|---|---|---|
| **On the phone**, in the browser with ONNX Runtime Web | By default, on a modern browser with a 4G or better connection, or once the model is cached | Only the text, with any Aadhaar number already cut to `XXXX XXXX 1234`. The photo never leaves. |
| **On the server**, the same bundle plus a Devanagari reader | Old browsers, data saver, slow connections, PDFs, and documents the phone could not make sense of, usually Hindi ones | The photo, which is read in memory and never stored |

The phone downloads about 41 MB once (the model and the runtime), and keeps it for later visits and offline use. Each model file is checked against the bundle's manifest before it runs, on the phone and on the server.

Measured on the three demo documents, every field came out correct in both places. On the phone, in Chromium, each read takes 3 to 4 s. On a server limited to Render's free plan (512 MB, 0.1 CPU), a read takes 24 to 30 s, or about 40 s for the Hindi card.

Two things learned while fitting UniOCR to identity documents:

- **Its dictionary repair is off.** It is built for notes, and on a card it changed names: Kamla to Kamala, Sunita Kumari to Sunita Kumar, Shyam to Sham.
- **Its 180° classifier is off.** It flips Devanagari lines, whose top stroke looks upside down to it. With it off, a synthetic Hindi ration card reads in full, and with it on, the name and address lines are lost. Photos are turned upright from their EXIF data instead.

Details read from a Hindi document are written out in Latin letters (सुनीता देवी becomes Sunita Devi) because the site and the forms are in English. The spelling is a reading aid, and every field can be corrected under Profile.

## Measured results

Run `python scripts/eval.py` from `backend/` to reproduce these.

| Metric | Target | Result |
|---|---|---|
| Eligibility accuracy on 25 hand-labelled households | 100% | **400 of 400 decisions (100%)** |
| Median questions to decide all schemes, one answer at a time | at most 12 | **11** (max 17) |
| Form pre-fill field accuracy in the end-to-end run | not set | **100%**, read back from the page by the browser agent |
| Submissions without a valid confirmation token | 0 | **0**, tested for missing, forged, foreign and stale tokens |
| Voice turn latency | under 3 s | **Not measured.** Needs a Sarvam key. The agent's own share is a median of 29 ms per turn. |

The labels were written by hand from the rule definitions, so they catch encoding bugs. They do not independently prove the rules match each department's current policy.

## Tests

```bash
cd backend
python -m pytest tests            # 114 tests, including a real browser and real OCR run
python scripts/ui_check.py        # with both servers running, or --base https://your-site
```

`ui_check.py` drives the whole journey by tapping on a phone-sized screen, then checks every screen at 320, 390, 768, 844, 1024, 1366 and 1920 px for sideways scrolling, clipped elements, small tap targets, console errors and any Hindi text on screen. It also checks that the demo documents are read on the device without the full Aadhaar number ever being sent, that a Hindi card falls back to the server and is read, and that a household lost in a server restart shows a way back.

Set `TEST_DATABASE_URL` to run the tests against PostgreSQL instead of SQLite.

## How it is built

```
Next.js PWA  ──  /api, /portal proxied to FastAPI
                     │
               LangGraph orchestrator
     INTERVIEW → ELIGIBILITY → DOCS → FORM → CONFIRM → TRACK
                     │
   Tools                 Memory                Guardrails
   next_question         households, facts     signed confirmation token
   check_eligibility     (source + confidence) PII masking
   explain_rule          applications, status  rules-only eligibility
   plan_documents        session summaries     action log
   ocr_document
   fill_form             Rules: schemes/*.json (JSON-Logic, source URL, last verified)
   submit_application    Mock portal: forms, submission and status API
   schedule_reminder
   check_status
```

**The LLM never decides eligibility.** Rules are JSON-Logic files in [schemes/](schemes). An unknown fact stays undecided rather than being guessed.

### Works with no keys

| Capability | With a key | Without a key |
|---|---|---|
| Speech to text, text to speech | Sarvam Saaras and Bulbul, then Bhashini | The browser's own speech |
| Document reading | Sarvam Vision on the server | UniOCR, on the phone or on the server |
| Understanding speech | Pattern extractor, then an LLM for what it misses | Pattern extractor alone |
| SMS reminders | Twilio | Shown in the app, labelled as simulated |

Copy `.env.example` to `.env` to add keys. **The Sarvam, Bhashini, Twilio and LLM integrations are written against their documentation but have not been run against the live services**, because no keys were available during the build.

### Where this differs from the brief

- **`panzi-json-logic` instead of `json-logic-py`.** The latter crashes on Python 3.
- **`sarvam-105b` as the default model.** Sarvam's current docs do not list `sarvam-30b`. Change it with `LLM_MODEL`.
- **English instead of Hindi-first.** The site, replies and speech are English only, at the project owner's request. Hindi text is still in the backend's rule files and replies, and the extractor still reads Hindi, but the website shows none of it.
- **UniOCR instead of Tesseract** as the reader that needs no key. It runs on the phone, so the photo stays there. On the server it adds a Devanagari reader for Hindi documents.
- **SQLite by default.** Set `DATABASE_URL` to a PostgreSQL URL to keep data across restarts. The whole test suite passes on PostgreSQL 16.

## Scheme coverage

16 schemes. Central: PM-KISAN, PM Ujjwala, Ayushman Bharat PM-JAY, PMAY-Gramin, PM Matru Vandana, Sukanya Samriddhi, PM Vishwakarma, PM Jeevan Jyoti, PM Suraksha, Atal Pension, NSAP Old-Age, NSAP Widow. Uttar Pradesh: Kanya Sumangala, Old-Age Pension, Widow Pension, Scholarship.

**Rules were cross-checked against web sources on 2 November 2026, mostly secondary ones, and need checking against official notifications before real use.** Where sources disagree, the rule file records it under `verification` and the app shows a warning. That applies to the UP pensions, Kanya Sumangala, PMAY-G and the UP Scholarship.

Some rules use stated assumptions that are not official policy, each recorded in its file:

- A BPL card stands in for an income certificate when screening UP pensions.
- A BPL card stands in for the SECC list for PM-JAY, and for the deprivation declaration for Ujjwala.
- Age 50 is a screening limit for PM Matru Vandana, so older women are not asked about pregnancy.

## Limits

- Runs only on mock portals and synthetic documents. Everyone in the seed data is invented.
- **There is no login.** Anyone who can reach the server can see every household, so keep it local. Real use needs authentication before any real data goes in.
- The time-skip buttons move one clock shared by all households.
- Entitled assists. The department makes the final eligibility decision.
