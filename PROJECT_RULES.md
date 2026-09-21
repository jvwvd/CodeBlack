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
| Backend | Python + FastAPI + Pydantic, Docker | Cloudflare Containers |
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
│   ├── import_organizer_data.py
│   ├── orchestration.py
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
- `backend/import_organizer_data.py` is a controlled, on-demand organizer-bundle → Supabase import utility (Member 2-owned). It is **not** part of FastAPI startup, not a request handler, not pipeline logic, and not a background service. See §14 ("Cloud Import") for the import flow and §16 for ownership.
- `backend/orchestration.py` is the controlled bridge between Supabase persistence/storage and the Member-1 pipeline (Member 2-owned). It is the **one** place allowed to import both `database.py` and `pipeline.run`/`models` in the same process. `process_stored_email()` itself does not persist results or add API routes; `process_and_persist_email()` is the explicit persistence wrapper around it. Neither implements any classification/extraction/comparison/reliability logic itself. See §16 for both frozen signatures.

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

**Development/evaluation vs. deployment data source.** `backend/loader.py` (and the organizer bundle/Docker server it reads from) is a **development and evaluation dependency only** — used for local pipeline development and for `evaluation/`'s full-dataset runs and `/submit` scoring. The **deployed** Cloudflare Containers application never calls `loader.py` and must never depend on the organizer Docker server being reachable at runtime. Instead, the organizer's participant data is imported once into our own Supabase PostgreSQL + private Storage (see §14, "Cloud Import"), and the deployed API and pipeline read exclusively from there. `backend/import_organizer_data.py` (§3, §16) is the one deliberate bridge allowed to call both `loader.py` and `database.py` in the same process — nothing else should.

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

**`public.emails` — current deployed schema (21 columns, verified via `information_schema`)**
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
sender              TEXT
subject             TEXT
body                TEXT
source_attachments  TEXT[]
```

`sender`/`subject`/`body`/`source_attachments` are live columns on `public.emails`, all nullable, no defaults, added via an additive `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migration that touched no other column, table, index, trigger, RLS policy, or Storage configuration.

| Column | Meaning |
|---|---|
| `sender` | Verbatim value of the organizer email's `from` field |
| `subject` | Verbatim value of the organizer email's `subject` field |
| `body` | Verbatim value of the organizer email's `body` field |
| `source_attachments` | Verbatim copy of the organizer email's `attachments` list |

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

No column changes are proposed for this table.

**Storage:** one private bucket named `documents`.

Rules:
- No separate verification table — `EmailResult` fields live directly on `emails`.
- No separate `review_cases` table — review state is columns on `emails`.
- No separate SI/BL tables — stored as JSONB on `emails`.
- **No separate raw/source email table** (`raw_emails`, `source_emails`, `inbox_emails`, or similar) — `public.emails` holds both raw/source organizer information and processing/result/review information in the same row, for the same 1:1-relationship reason the other "no separate table" rules above already exist. Do not create one of these unless a future organizer requirement forces the change.
- Cross-field business rules (e.g. "`review_reason` implies `status = NEEDS_REVIEW`") belong in Python, never as database constraints/triggers.
- The frontend must never receive or use backend Supabase secret credentials — it only talks to FastAPI.
- `database.py` is persistence only: no classification, extraction, comparison, or pipeline orchestration.

### Source + result coexistence

`sender`/`subject`/`body`/`source_attachments` (raw, written once at import) and `category`/`status`/`si`/`bl`/`defect_fields`/`has_defect`/`review_reason`/`decided_by`/`notes`/`processing_status`/`retry_count`/`last_error`/`reviewed_at`/`reviewer_notes` (processing/result/review, written by the pipeline and by reviewers) live on the same row, but are written by different, non-overlapping code paths:

- The importer (`backend/import_organizer_data.py`) may only write the 4 raw columns (+ timestamps). It must never write `category`, `status`, `si`, `bl`, `defect_fields`, `has_defect`, `review_reason`, `decided_by`, `notes`, or any retry/review-state column.
- `database.py`'s existing `upsert_email()` may only write the processing/result columns (it already filters to exactly the `EmailResult` field set) and must never write the 4 raw columns.

Because these two write paths never touch each other's columns, re-running the importer can never reset or overwrite processing/result/review state, and the pipeline writing a result can never disturb the raw source record — **unless a future explicit reset/reprocessing operation is intentionally implemented and documented here first.**

### Processing-status semantics

`status` and `processing_status` mean different things and **must not be conflated**:

| `processing_status` | Meaning |
|---|---|
| `pending` | Email/attachments imported, but processing has not started. |
| `processing` | Pipeline processing is currently underway. |
| `completed` | Processing finished successfully; `status` now represents the final verification result. |
| `failed` | Processing failed; `last_error` may contain internal diagnostic context. |

**`public.emails.status` defaults to `OK` at the database level.** This default **must not** be interpreted as "verified, no mismatch" for a row that has not completed processing — it is simply the column's default value, not a verdict. Consumers (the frontend above all) must check `processing_status` before trusting `status`:

| State | Interpretation |
|---|---|
| `processing_status = pending` | **NOT YET VERIFIED** |
| `processing_status = processing` | **PROCESSING** |
| `processing_status = completed` + `status = OK` | **VERIFIED / NO MISMATCH** |
| `processing_status = completed` + `status = MISMATCH` | **VERIFIED / MISMATCH** |
| `status = NEEDS_REVIEW` | **HUMAN REVIEW** path, per the pipeline/review state |

This is a documentation clarification only — **the actual database default is not changed by this document.**

### Cloud Import (Organizer Bundle → Supabase)

```
Organizer bundle/Docker
  → backend/loader.py (unmodified organizer code)
  → backend/import_organizer_data.py (Member 2, controlled/on-demand utility)
  → backend/database.py (persistence helpers)
  → Supabase PostgreSQL (public.emails, public.attachments) + private Storage bucket "documents"
```

**`backend/import_organizer_data.py` has not been implemented yet.** It is frozen as a target file in §3's repository structure and owned by Member 2 per §16, but no code exists for it yet — the schema it will write into (above) is live; the importer itself is not. The rules below describe constraints its future implementation must satisfy. Once built, it must be: **not** part of FastAPI startup, not a request handler, not pipeline logic, not an evaluation script, and not a background service — it is run manually/on-demand.

**Reconstructed dict.** When code (the importer, or later the pipeline reading imported data) needs the organizer-shaped email dict back, it is reconstructed as:
```json
{ "email_id": "...", "from": "...", "subject": "...", "body": "...", "attachments": [...] }
```
`sender` → `"from"`. **The organizer's `"from"` key is never renamed to `"sender"` in this dict — only the PostgreSQL column is called `sender`.**

**Storage path convention.** Canonical path for an imported organizer attachment:
```
{email_id}/{original_filename}
```
Example: `email_004/email_004_SI.txt`. Bucket remains the existing private `documents` bucket. This convention is deterministic, easy to debug, collision-free across emails, preserves the original filename, and supports idempotent re-import. Do not introduce UUID-based filenames unless a future requirement makes them necessary.

**Import idempotency.** The importer must be safe to rerun at any time:
- **Email source import** — upsert the 4 raw columns for the same `email_id`; must never overwrite processing/result/review fields (see "Source + result coexistence" above).
- **Attachment Storage upload** — deterministic path (above) + upload with upsert behavior, so a rerun overwrites the same object rather than erroring or duplicating.
- **Attachment metadata** — relies on the existing `UNIQUE(email_id, storage_path)` constraint on `public.attachments`; upsert rather than insert-and-fail.

**`doc_type` at import time.** `public.attachments.doc_type` is set to `NULL` by the importer. **The importer must never infer `SI`/`BL`/`OTHER` from filenames**, even though organizer filenames often contain `_SI`/`_BL`. Document identification is exclusively Member 1's `pipeline/documents.py` responsibility (§8, §16).

**Import completeness.** A `public.emails` row existing is not sufficient evidence that an email is safely ready for pipeline processing. Before treating an email as fully imported, the source email and all of its referenced attachments must actually be persisted. No new database field is added for this yet; completeness should eventually be checked deterministically by comparing `source_attachments` (what the organizer claims) against the persisted `public.attachments` rows and Storage upload success for that `email_id`. If an import fails partway through, rerunning the importer must safely repair the incomplete state (idempotency above makes this safe by construction).

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
- `backend/import_organizer_data.py` — organizer bundle → Supabase cloud dataset import (see §14, "Cloud Import")
- `backend/orchestration.py` — Supabase → Member-1 pipeline bridge (see below)
- FastAPI, Supabase PostgreSQL/Storage, Cloudflare Containers, backend integration/deployment

**Member 3 — Frontend**
- `frontend/` — dashboard, inbox, comparison UI, review UI, processing/error UI
- Consumes backend results; must not recompute verification logic

**Member 4 — QA/Evaluation**
- `evaluation/` — full dataset runs, `build_submission.py`, `submit.py`, Docker evaluator usage, regression testing, error analysis

Ownership prevents duplicate implementations, but integration points (§7's `EmailResult`, §9's function contracts, §13's projection) are shared and must not be silently changed by one member without updating this document.

**Pipeline integration boundary (Member 2 → Member 1).** For an imported email, Member 2 must eventually make available to Member 1's `pipeline/run.py`:
1. A plain email dict reconstructed in the organizer shape — see §14, "Cloud Import."
2. Access to the corresponding raw attachment bytes from private Storage.

Member 2 must **not** perform classification, SI/BL identification, extraction, normalization, comparison, or reliability decisions — those remain exclusively Member 1's, per §8.

**This boundary is implemented by `backend/orchestration.py`**, frozen as:
```python
def process_stored_email(email_id: str) -> EmailResult | None:
```
It reads the stored email row via `database.get_email()`, reconstructs the organizer-shaped dict, downloads attachment bytes via `database.list_attachments()` + `database.download_document()` (keyed by the *original organizer attachment reference*, matched to stored rows by basename — never guessed when ambiguous or absent), and calls `pipeline.run.process_email()` unmodified, returning its `EmailResult` as-is. **It does not persist the result** — persistence remains a separate, explicit step for whatever caller invokes it.

**`process_and_persist_email(email_id: str) -> EmailResult | None`** is that explicit persistence wrapper. It marks `processing_status = 'processing'` (clearing any stale `last_error`), calls `process_stored_email()`, and — on a successful `EmailResult` — persists it via `database.upsert_email()` and marks `processing_status = 'completed'` (clearing `last_error`) before returning the result unchanged. On `None` (email not found) it returns `None` without persisting anything or calling `upsert_email()`. On any unexpected exception during processing or persistence, it marks `processing_status = 'failed'` with a bounded, redacted error summary (URLs and key=value-style secrets/tokens stripped; unusually long messages replaced with a generic note rather than stored raw) and re-raises. It adds no retry/concurrency/idempotency guards. It is exposed via `POST /api/emails/{email_id}/process` — `200` with the `EmailResult` body on success, `404` if the email does not exist, `500` via the existing generic exception handler on any other failure.

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
