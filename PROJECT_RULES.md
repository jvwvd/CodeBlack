# PROJECT_RULES.md

**This file is the single canonical contract for the Shipping Document Verification (SDOC) hackathon project.**

It applies equally to all four human team members, Claude CLI / Claude Code, ChatGPT coding sessions, and any other coding agent working in this repository. Its purpose is to prevent architecture drift, schema drift, duplicated business logic, accidental secret exposure, and conflicting implementations across people and tools working in parallel.

If any instruction given to a coding agent conflicts with this document, the agent must stop and report the conflict instead of silently choosing a side (see §22).

---

## 1. Project Goal

The system verifies shipping documents referenced in an inbox of emails. The pipeline is:

```
Inbox
  → Classification
  → Attachments
  → Parsing/OCR
  → Extraction
  → Normalization
  → SI vs BL Comparison
  → Reliability Check
  → Human Review
  → Dashboard
```

- **SI (Shipping Instruction) is the reference document.**
- **Only `BL_COMPARISON` emails proceed to SI-vs-BL verification.** Every other category is classified and recorded, but never enters the comparison stage.

---

## 2. Frozen Technology Architecture

| Layer | Technology | Deployment |
|---|---|---|
| Frontend | React + Vite + Tailwind | Vercel |
| Backend | Python + FastAPI + Pydantic, Docker | Google Cloud Run |
| Persistence | Supabase PostgreSQL + Supabase Storage | Supabase |
| AI | Gemini, or another team-approved multimodal LLM | — |
| Documents | PyMuPDF, python-docx, openpyxl; OCR/vision only when native parsing is insufficient | — |

**AI provider note:** this document does not lock in a specific AI provider beyond what the repository has already established. `backend/config.py` currently provisions a `GEMINI_API_KEY` setting — if the team adopts a different or additional provider, that is a `config.py` change owned by Member 2, not something to duplicate elsewhere.

**Request flow:**
```
User → React → FastAPI → Pipeline → DB/Storage + Parser/OCR + AI + Comparator → Results/Human Review
```

**Core principle:** AI is for understanding (reading messy, unstructured, or ambiguous content). Deterministic Python code is for decisions (classification thresholds, field comparison, status, routing to review). AI must never be the sole basis for a `MISMATCH`/`OK`/`NEEDS_REVIEW` verdict without a deterministic rule backing it.

---

## 3. Frozen Repository Structure

```
sdoc/
├── README.md
├── ARCHITECTURE.md
├── PROJECT_RULES.md
├── .gitignore
├── .env.example
├── data/
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   ├── config.py
│   ├── models.py
│   ├── prompts.py
│   ├── llm.py
│   ├── database.py
│   ├── loader.py
│   └── pipeline/
│       ├── __init__.py
│       ├── classify.py
│       ├── documents.py
│       ├── extract.py
│       ├── normalize.py
│       ├── compare.py
│       ├── reliability.py
│       └── run.py
├── evaluation/
│   ├── run_all.py
│   ├── build_submission.py
│   └── submit.py
└── frontend/
    ├── package.json
    ├── index.html
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── api.ts
        ├── types.ts
        └── components/
            ├── EmailList.tsx
            ├── ComparisonView.tsx
            └── ReviewQueue.tsx
```

Rules:
- **Do not invent `backend/app/`.**
- **Do not invent `repositories/`, `adapters/`, `services/`, `infrastructure/`, `data_sources/`, or any alternative architecture** without explicit team agreement recorded by updating this file first.
- Keep the structure shallow — no nested layering beyond what's shown above.
- `pipeline/run.py` is the **only** shared pipeline orchestrator; nothing else calls `classify`/`extract`/`normalize`/`compare`/`reliability` directly.
- The frontend never performs verification or business calculations — it renders what the backend returns.

Not every file above exists yet at any given point in the project's life; this tree describes the target frozen shape everyone builds toward, not a claim that all files are already present.

---

## 4. Canonical Classification Contract

```
BL_COMPARISON
SI_REQUEST
INVOICE_QUERY
GENERAL
SPAM
```

Only `BL_COMPARISON` continues to document verification. The other four categories are terminal outcomes for that email.

---

## 5. Canonical Seven Shipping Fields

```
shipper
consignee
notify_party
port_of_loading
port_of_discharge
container_count
gross_weight_kg
```

Never rename these fields without explicit team agreement (which means: update this file first, then code).

- **SI is the reference.** BL is compared against SI, not the other way around.
- If all seven comparable values match: **"No mismatch detected."**

---

## 6. Canonical Status / Review Contracts

**Status**
```
OK
MISMATCH
NEEDS_REVIEW
```

**Review reasons**
```
wrong_doc_type
missing_attachment
unreadable
missing_value
```

**Document types**
```
SI
BL
OTHER
UNREADABLE
```

**decided_by**
```
rule
llm
```

Never invent alternative spellings, casings, or synonyms for any of the above.

---

## 7. Canonical Internal Pydantic Contract

```python
class ShipmentFields(BaseModel):
    shipper: Optional[str] = None
    consignee: Optional[str] = None
    notify_party: Optional[str] = None
    port_of_loading: Optional[str] = None
    port_of_discharge: Optional[str] = None
    container_count: Optional[int] = None
    gross_weight_kg: Optional[float] = None

class EmailResult(BaseModel):
    email_id: str
    category: Category
    status: Status = "OK"
    si: Optional[ShipmentFields] = None
    bl: Optional[ShipmentFields] = None
    defect_fields: list[str] = []
    has_defect: bool = False
    review_reason: Optional[ReviewReason] = None
    decided_by: Optional[Literal["rule", "llm"]] = None
    notes: Optional[str] = None
```

`backend/models.py` is the eventual single source of truth for these models. **Do not duplicate these Pydantic schemas anywhere else** — other files may filter/project a subset of columns (see §13, §14) but must not redefine the shape.

**Do not add a `confidence` float or any other field to this canonical contract** unless the team explicitly agrees to change the frozen contract and this document is updated first.

---

## 8. Frozen Pipeline Responsibilities

| File | Responsibility |
|---|---|
| `classify.py` | Rules first; AI only when rules are insufficient |
| `documents.py` | Native parsing first; vision/OCR fallback only when needed |
| `reliability.py` | Deterministic `NEEDS_REVIEW` checks |
| `extract.py` | Deterministic extraction where reliable; AI for semantic/messy/missing fields |
| `normalize.py` | Pure deterministic Python |
| `compare.py` | Pure deterministic Python |
| `run.py` | The only shared orchestration path |

**Do not put classification, extraction, or comparison logic in `main.py`, `database.py`, the frontend, or evaluation scripts.** Those layers consume pipeline output; they do not reimplement it.

---

## 9. Frozen Function Contracts

```python
classify_email(email: dict) -> tuple[Category, str]

read_attachment(path: str) -> str | None
identify_doc_type(text: str) -> str

extract_fields(text: str) -> ShipmentFields

norm_company(v: str) -> str
norm_port(v: str) -> str
norm_weight(v: str) -> float
norm_count(v: str) -> int

compare(si: ShipmentFields, bl: ShipmentFields) -> list[str]

check(
    email: dict,
    si_text: str | None,
    bl_text: str | None,
) -> ReviewReason | None
```

Do not silently change these signatures. If a signature must change, update this document first and flag it to the team.

---

## 10. Organizer Data Contract

Verified from the organizer's public participant materials only.

Email JSON contains exactly:
```
email_id
from
subject
body
attachments
```

- `email_id` pattern: `email_NNN` (e.g. `email_004`).
- Current participant dataset: **520 emails**.
- `attachments` is a list of relative path strings, e.g. `attachments/email_004_SI.txt`.
- Observed public participant attachment extensions: `.txt`, `.pdf`, `.xlsx`, `.docx`.

**Do not infer email fields that are not in this list** (no `to`, `date`, pre-assigned `category`, etc. — the organizer inbox is unlabeled).

---

## 11. Organizer `loader.py` Rule

**`backend/loader.py` is an EXACT copy of the organizer-provided participant `loader.py`. It MUST remain unmodified.**

Verified SHA256 at the time it was vendored:
```
87fb59fa42aed417c4c7e877e51e1d6c9d097e7ac369b7fb653c1ee479a1c123
```

It already provides source-independent access for:
- the local static participant bundle
- the organizer HTTP/Docker source

**Do not add Supabase/cloud helpers to the organizer's `loader.py`. Do not refactor it.** If cloud-sourced email access is ever needed, it belongs in a separate function, not a modification of this file (see §3, §16 for ownership).

---

## 12. Organizer Public HTTP Contract

Verified public endpoints:
```
GET  /health
GET  /
GET  /emails
GET  /emails/{email_id}
GET  /attachments/{path:path}
GET  /sample_submission
POST /submit
```

**The correct sample route is `/sample_submission`, NOT `/sample`.**

**Do not document or use private/judge-only evaluation endpoints** (e.g. `/ground_truth`) as part of the application — they are organizer-only and gated for a reason.

---

## 13. Submission Contract

The organizer submission is a JSON object keyed by `email_id`. Each value contains **exactly**:
```
category
status
review_reason
defect_fields
has_defect
```

The internal `EmailResult` (§7) carries richer information. Projection from `EmailResult` to the organizer submission must:

| Action | Field(s) |
|---|---|
| Move to outer dict key | `email_id` |
| Keep | `category`, `status`, `review_reason`, `defect_fields`, `has_defect` |
| Strip | `si`, `bl`, `decided_by`, `notes` |

`evaluation/build_submission.py` owns this projection — it must not be re-implemented elsewhere. Output must cover **every** organizer email, not a subset.

---

## 14. Supabase Persistence Contract

**`public.emails`**
```
email_id            TEXT primary key
category
status
si                  JSONB
bl                  JSONB
defect_fields       TEXT[]
has_defect          BOOLEAN
review_reason
decided_by
notes
processing_status
retry_count
last_error
reviewed_at
reviewer_notes
created_at
updated_at
```

**`public.attachments`**
```
id                  UUID primary key
email_id            FK -> emails.email_id
doc_type
storage_bucket
storage_path
original_filename
content_type
size_bytes
created_at
```

**Storage:** one private bucket named `documents`.

Rules:
- No separate verification table — `EmailResult` fields live directly on `emails`.
- No separate `review_cases` table — review state is columns on `emails`.
- No separate SI/BL tables — stored as JSONB on `emails`.
- Cross-field business rules (e.g. "`review_reason` implies `status = NEEDS_REVIEW`") belong in Python, never as database constraints/triggers.
- The frontend must never receive or use backend Supabase secret credentials — it only talks to FastAPI.
- `database.py` is persistence only: no classification, extraction, comparison, or pipeline orchestration.

---

## 15. Human Review Rules

**Never guess when evidence is insufficient.** `NEEDS_REVIEW` exists precisely so the system can say "I don't know" instead of fabricating a verdict.

Canonical review cases:
- wrong document type
- missing attachment
- unreadable input
- missing required value

The reviewer workflow may correct or confirm a result. When surfacing a case for review, keep the evidence and useful internal context (extracted values, defect fields, notes) — but **never invent extracted values** that weren't actually read from a document.

---

## 16. Member Ownership

**Member 1 — AI/Documents**
- `models.py` (coordination / single-source contract)
- `prompts.py`, `llm.py`
- `pipeline/` — classification, document identification/parsing/OCR, extraction, normalization/comparison implementation, reliability logic

**Member 2 — Backend/Cloud/Integration**
- `main.py`, `config.py`, `database.py`, `Dockerfile`
- `backend/loader.py` integration responsibility (the organizer file itself remains unmodified, per §11)
- FastAPI, Supabase PostgreSQL/Storage, Cloud Run, backend integration/deployment

**Member 3 — Frontend**
- `frontend/` — dashboard, inbox, comparison UI, review UI, processing/error UI
- Consumes backend results; must not recompute verification logic

**Member 4 — QA/Evaluation**
- `evaluation/` — full dataset runs, `build_submission.py`, `submit.py`, Docker evaluator usage, regression testing, error analysis

Ownership prevents duplicate implementations, but integration points (§7's `EmailResult`, §9's function contracts, §13's projection) are shared and must not be silently changed by one member without updating this document.

---

## 17. Git Workflow

Branches:
```
feature/ai-extraction
feature/backend
feature/frontend
feature/evaluation
```

Rules:
- Pull/fetch before integration work.
- Keep `main` stable.
- Commit after verified working steps.
- Integrate frequently rather than in one large merge.
- Use PRs when merging shared work.
- Do not silently overwrite another member's contract or files.
- Report conflicts rather than redesigning around them.

---

## 18. Secrets / Security

Never commit:
- `.env` files
- API keys
- database passwords
- authenticated database URLs
- Supabase service/secret keys
- cloud secret keys
- OAuth client secrets
- JWT secrets
- private certificates
- passwords/tokens
- private organizer evaluation data

Use environment variables. Keep `.env` gitignored. Use `.env.example` with placeholders only.

**Rule of thumb:** if a credential can grant access, spend money, or unlock private data, it does not belong in Git.

---

## 19. Ground Truth / Evaluation Integrity

This section is explicit and non-negotiable.

**Never:**
- open `ground_truth.json`
- read it
- parse it
- print it
- copy it into the repository
- write code that accesses it
- use hidden/private organizer answers
- hard-code evaluation answers

Use only legitimate organizer evaluation interfaces (`POST /submit`, or the organizer's own `score_cli.py` if they run it for you).

**Evaluation loop:**
```
Bundle/Docker → Pipeline → Output → Submit/Evaluate → Diagnose earliest failure → Fix → Regression test
```

**When debugging, diagnose in this order:**
```
Classification → Attachments → Parsing/OCR → Extraction → Normalization → Comparison → Output format
```

---

## 20. Testing Priorities

1. Unit tests
2. One real email end-to-end
3. Match / mismatch / missing / unreadable / low-confidence / failure cases
4. Full dataset
5. Organizer evaluation
6. Every bug becomes a regression test
7. Deployed frontend → backend → DB/storage → AI → review

**First milestone**, before any UI polish:
```
One real email → classify → attachments → extract SI/BL → normalize → compare seven fields → correct result
```

---

## 21. Agent Rules

Every coding agent (human-directed or autonomous) working in this repository must, **before making changes**:

1. Read `PROJECT_RULES.md`.
2. Inspect the existing repository.
3. Preserve frozen architecture and contracts.
4. Modify only files required for the assigned task.
5. Not duplicate another member's logic.
6. Not invent alternative folders or schemas.
7. Not rename shared fields/contracts.
8. Not modify the organizer's `loader.py`.
9. Never access `ground_truth.json`.
10. Never expose or commit secrets.
11. Run relevant tests.
12. Not commit/push unless explicitly instructed.
13. If the task conflicts with `PROJECT_RULES.md`, stop and report the conflict.

**After a coding task, report:**
- files changed
- implementation
- commands/tests run
- results
- integration dependencies
- unresolved issues
- git status
- whether anything was committed/pushed

---

## 22. Change-Control Rule

`PROJECT_RULES.md` is the canonical contract. **No single coding agent may silently change frozen architecture or contracts.**

If a genuine organizer requirement conflicts with this document:
1. The organizer requirement wins.
2. Report the conflict.
3. The team agrees on the change.
4. Update `PROJECT_RULES.md`.
5. Only then update the implementation.

Do not maintain multiple conflicting copies of the project contract — this file is the only one.
