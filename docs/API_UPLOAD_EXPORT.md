# Upload / Batch / Export API

Reference for the frontend. Covers `POST /api/emails/upload`, `GET /api/batches/{batch_id}`,
and `GET /api/emails/export`. All limits and status codes below are read directly from
`backend/main.py` on branch `feature/export-upload`.

## Limits

| Limit | Value |
|---|---|
| Max files per upload request | 20 |
| Max size per file | 25 MB |
| Max total request size | 100 MB |
| Zip (plain): max inner files | 50 |
| Zip (plain): max uncompressed size | 50 MB |
| Zip (plain): nesting | 1 level (a zip inside a zip is not expanded further) |
| Bundle zip (`inbox/*.json` + `attachments/`): max files | 5000 |
| Bundle zip: max uncompressed size | 200 MB |
| Bundle zip: max upload size | 100 MB (same as the general request ceiling) |

Type detection is magic-bytes first, file extension as fallback.

---

## `POST /api/emails/upload`

`multipart/form-data`. Fields:

| Field | Required | Notes |
|---|---|---|
| `files` | at least implicitly, see below | one or more files, repeated `files` parts |
| `subject` | conditional | required unless every file resolves to a self-describing email (`.eml` or organizer-format `.json`) |
| `body` | conditional | same rule as `subject` |
| `sender` | no | only used for the attachment-only path |

If the upload contains only `.eml` and/or organizer-format `.json` files, `subject`/`body` are not
required — sender/subject/body come from those files instead. If any file needs to be attached to
a form-described email (txt/pdf/docx/xlsx/zip-passthrough/unrecognized), `subject` and `body` are
required.

### Response shape

- Exactly one email created → the `EmailResult` object directly.
- More than one email created (e.g. a zip containing two `.eml` files) → `{"emails": [EmailResult, ...]}`.
- A bundle-shaped zip → routed to batch handling instead (see below), not an `EmailResult`.

`EmailResult`:
```json
{
  "email_id": "upload_ab12cd34ef56",
  "category": "SI_REQUEST",
  "status": "OK",
  "si": { "shipper": "...", "consignee": "...", "...": "..." },
  "bl": null,
  "defect_fields": [],
  "has_defect": false,
  "review_reason": null,
  "decided_by": "rule",
  "notes": null
}
```

### File-type handling

| Type (detected) | Behavior |
|---|---|
| `.txt` `.pdf` `.docx` `.xlsx` | Parsed as before; attached to the form-described email. |
| `.zip` (plain, not bundle-shaped) | Extracted in memory (zip-slip and zip-bomb protected, `__MACOSX/` and `.DS_Store` skipped); each inner file re-enters classification and becomes an attachment or its own email. |
| `.zip` (bundle-shaped: `inbox/*.json` + `attachments/`) | Not an email upload — creates a **batch** instead. See `_handle_bundle_upload` below. |
| `.eml` | Parsed with Python's stdlib `email` package; sender/subject/body/attachments extracted from the message itself. Becomes its own email. |
| `.json` (organizer inbox format: `email_id`, `from`, `subject`, `body`, `attachments`) | Imported as its own email. |
| Anything else (image, `.csv`, `.doc`, `.xls`, `.rtf`, unknown extension, empty, corrupt) | Stored and attached to the form-described email — **not an error**. The pipeline marks the resulting email `NEEDS_REVIEW` (unreadable), which is the expected outcome. |

### Examples

**Single file**
```
POST /api/emails/upload
Content-Type: multipart/form-data

files=si_request.pdf
subject="SI request - booking 4471"
body="Please see attached SI."
```
```json
200 OK
{ "email_id": "upload_ab12cd34ef56", "category": "SI_REQUEST", "status": "OK",
  "si": { "...": "..." }, "bl": null, "defect_fields": [], "has_defect": false,
  "review_reason": null, "decided_by": "rule", "notes": null }
```

**Plain zip (two attachments, one email)**
```
POST /api/emails/upload
files=docs.zip   (contains si.txt, bl.txt)
subject="BL comparison"
body="See attached SI and BL."
```
```json
200 OK
{ "email_id": "upload_9f3a1b2c4d5e", "category": "BL_COMPARISON", "status": "MISMATCH",
  "si": { "...": "..." }, "bl": { "...": "..." },
  "defect_fields": ["shipper"], "has_defect": true,
  "review_reason": null, "decided_by": "rule", "notes": null }
```

**`.eml` upload (subject/body omitted)**
```
POST /api/emails/upload
files=incoming.eml
```
```json
200 OK
{ "email_id": "upload_1122aabb3344", "category": "SI_REQUEST", "status": "OK",
  "si": { "...": "..." }, "bl": null, "defect_fields": [], "has_defect": false,
  "review_reason": null, "decided_by": "rule", "notes": null }
```

**Bundle zip (organizer dataset shape)**
```
POST /api/emails/upload
files=full_dataset.zip   (inbox/*.json + attachments/, e.g. ~520 emails / ~770 files)
```
```json
200 OK
{ "batch_id": "batch_3f9a0c1d2b4e", "total": 520, "status": "processing" }
```
Returns immediately. Processing happens in the background with 3 workers, calling
`orchestration.process_and_persist_email` per email. Poll `GET /api/batches/{batch_id}` for progress.

### Error responses

| Status | Trigger | Example detail |
|---|---|---|
| `413` | more than 20 files in the request | `"too many files: at most 20 allowed, got 23"` |
| `413` | running total across files exceeds 100 MB | `"upload exceeds total request size limit of 104857600 bytes"` |
| `413` | a single file exceeds 25 MB | `"file 'scan.pdf' exceeds max size of 26214400 bytes"` |
| `413` | plain zip has more than 50 inner files or >50 MB uncompressed | (from `_extract_zip_entries`) |
| `413` | bundle zip has more than 5000 files | `"bundle contains too many files: 5200 > 5000 allowed"` |
| `413` | bundle zip uncompressed exceeds 200 MB | `"bundle uncompressed size too large: ... bytes > 209715200 allowed"` |
| `400` | uploaded `.zip` fails to open (corrupt zip container itself) | `"'docs.zip' is not a valid zip file"` |
| `422` | attachment-only upload with no `subject`/`body` given | `"subject and body are required unless an .eml or organizer-format .json file is uploaded"` |

Note: a corrupt or unreadable *inner* file (not the zip container itself) is not an error — it is
stored and the resulting email is marked `NEEDS_REVIEW` by the pipeline.

---

## `GET /api/batches/{batch_id}`

Poll this after a bundle upload returns a `batch_id`.

```json
200 OK
{
  "batch_id": "batch_3f9a0c1d2b4e",
  "total": 520,
  "done": 340,
  "failed": 2,
  "status": "processing",
  "created_at": "2026-09-22T00:00:00+00:00",
  "finished_at": null
}
```

`status` is one of `"processing"`, `"completed"`, `"failed"`. `finished_at` is `null` until the
batch stops running. Per-email failures increment `failed` but never stop the rest of the batch.

```json
404 Not Found
{ "detail": "batch not found: batch_xyz" }
```

---

## `GET /api/emails/export`

`?format=json|csv|submission` (default `json`), plus optional filters:
`status`, `category`, `processing_status`, `batch_id`.

Declared before `GET /api/emails/{email_id}` so `/api/emails/export` is never matched as an
`email_id` path parameter.

### `format=json` / `format=csv`

Unchanged flat row shape (one row per email), now filterable by `batch_id`. Columns:
`email_id, sender, subject, category, status, review_reason, has_defect, defect_fields,
decided_by, updated_at`, plus `si_<field>` / `bl_<field>` for each of the seven shipment fields
(`shipper`, `consignee`, `notify_party`, `port_of_loading`, `port_of_discharge`,
`container_count`, `gross_weight_kg`).

Response is a file download (`Content-Disposition: attachment`), `application/json` or
`text/csv; charset=utf-8` respectively.

### `format=submission` (new)

Exactly the organizer's expected submission shape, keyed by each email's **original** organizer
`email_id` — batch-processed rows resolve back to their original id automatically; non-batch rows
use their own `email_id`.

```
GET /api/emails/export?format=submission&batch_id=batch_xyz
```
```json
200 OK
{
  "email_001": {
    "category": "BL_COMPARISON",
    "status": "MISMATCH",
    "review_reason": null,
    "defect_fields": ["shipper"],
    "has_defect": true
  },
  "email_010": {
    "category": "SI_REQUEST",
    "status": "OK",
    "review_reason": null,
    "defect_fields": [],
    "has_defect": false
  }
}
```
Omit `batch_id` to export every email regardless of batch.

---

## Notes on batch email ids (backend-internal, informational for the frontend)

`emails.email_id` is a frozen primary key, so two batches that both contain an organizer id like
`email_004` cannot both write a row keyed `email_004` without colliding. Batch-processed rows are
persisted under a synthetic, batch-namespaced id (`batch_<batch_id>__email_004`); the real
organizer id is preserved in a separate `original_email_id` column and is what `format=submission`
keys its output by. `GET /api/emails/{email_id}` and `GET /api/emails/{email_id}/attachments` for a
batch-created email must be called with the **namespaced** id (as returned by
`GET /api/emails?batch_id=...`), not the original organizer id.
