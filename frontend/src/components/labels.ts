/**
 * Fixed labels and the ONE function that decides how a record is presented.
 *
 * getDisplayState() is the only place in the app that reads processing_status
 * and status together. Badges, banners, filters and counts all call it, so
 * they can never disagree with each other.
 *
 * It decides nothing about the documents themselves: it reports the backend's
 * verdict in the team's words (PROJECT_RULES.md §14, "Processing-status
 * semantics" — `status` defaults to 'OK' in Postgres and must never be read
 * as a verdict before processing_status is 'completed').
 */
import { FIELD_KEYS, type Category, type EmailRecord, type FieldKey, type ReviewReason } from "../types";

export const FIELD_LABELS: Record<FieldKey, string> = {
  shipper: "Shipper",
  consignee: "Consignee",
  notify_party: "Notify Party",
  port_of_loading: "Port of Loading",
  port_of_discharge: "Port of Discharge",
  container_count: "Container Count",
  gross_weight_kg: "Gross Weight (kg)",
};

export const CATEGORY_LABELS: Record<Category, string> = {
  BL_COMPARISON: "Document check",
  SI_REQUEST: "New SI request",
  INVOICE_QUERY: "Invoice query",
  GENERAL: "General",
  SPAM: "Spam",
};

export const CATEGORY_ORDER: Category[] = [
  "BL_COMPARISON",
  "SI_REQUEST",
  "INVOICE_QUERY",
  "GENERAL",
  "SPAM",
];

export const REVIEW_REASON_TEXT: Record<ReviewReason, string> = {
  missing_attachment: "The SI or BL attachment is missing from this email.",
  unreadable: "An attachment could not be read.",
  wrong_doc_type: "An attachment is not an SI or a BL.",
  missing_value: "A required field is missing from one of the documents.",
};

/** Short explanation shown instead of a comparison table. */
export const CATEGORY_EXPLANATION: Record<Exclude<Category, "BL_COMPARISON">, string> = {
  SI_REQUEST: "This email asks for a new shipping instruction, so there are no documents to compare.",
  INVOICE_QUERY: "This email is an invoice query, so there are no documents to compare.",
  GENERAL: "This email is general correspondence, so there are no documents to compare.",
  SPAM: "This email was classified as spam, so there are no documents to compare.",
};

export type Tone = "neutral" | "info" | "danger" | "danger-outline" | "warning" | "success" | "muted";

export type DisplayKind =
  | "not-verified"
  | "processing"
  | "failed"
  | "needs-review"
  | "not-a-check"
  | "mismatch"
  | "ok";

export interface DisplayState {
  kind: DisplayKind;
  label: string;
  tone: Tone;
  /** Number of differing fields; only meaningful for kind === "mismatch". */
  defectCount: number;
}

/**
 * Decide by processing_status → category → status, in that order.
 * Nothing else in the app may branch on those three columns.
 */
export function getDisplayState(record: EmailRecord): DisplayState {
  const processing = record.processing_status;

  if (processing === null || processing === "pending") {
    return { kind: "not-verified", label: "Not yet verified", tone: "neutral", defectCount: 0 };
  }

  if (processing === "processing") {
    return { kind: "processing", label: "Processing…", tone: "info", defectCount: 0 };
  }

  if (processing === "failed") {
    return { kind: "failed", label: "Processing failed", tone: "danger-outline", defectCount: 0 };
  }

  // processing === "completed" from here down.
  if (record.status === "NEEDS_REVIEW") {
    return { kind: "needs-review", label: "Needs review", tone: "warning", defectCount: 0 };
  }

  if (record.category !== "BL_COMPARISON") {
    return { kind: "not-a-check", label: "Not a document check", tone: "muted", defectCount: 0 };
  }

  if (record.status === "MISMATCH") {
    const count = record.defect_fields?.length ?? 0;
    return {
      kind: "mismatch",
      label: `Mismatch in ${count} ${count === 1 ? "field" : "fields"}`,
      tone: "danger",
      defectCount: count,
    };
  }

  return { kind: "ok", label: "No mismatch detected.", tone: "success", defectCount: 0 };
}

/** Filter keys offered in the inbox toolbar, matching getDisplayState kinds. */
export const RESULT_FILTERS: Array<{ value: DisplayKind; label: string }> = [
  { value: "ok", label: "No mismatch detected" },
  { value: "mismatch", label: "Mismatch" },
  { value: "needs-review", label: "Needs review" },
  { value: "not-a-check", label: "Not a document check" },
  { value: "not-verified", label: "Not yet verified" },
  { value: "processing", label: "Processing" },
  { value: "failed", label: "Processing failed" },
];

export const PROCESSING_FILTERS: Array<{ value: NonNullable<EmailRecord["processing_status"]>; label: string }> = [
  { value: "pending", label: "Pending" },
  { value: "processing", label: "Processing" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
];

/* ------------------------------------------------------------------ *
 * Limits and constants — defined ONCE, here.
 * ------------------------------------------------------------------ */

/** Rows per page for the inbox and the review queue (server-side paging). */
export const PAGE_SIZE = 50;

/** Rows the dashboard's "Needs attention" list asks for. */
export const ATTENTION_LIMIT = 8;

/**
 * Client-side upload guards. These mirror backend/main.py @ 06e4ad4
 * (MAX_UPLOAD_FILES / MAX_UPLOAD_FILE_BYTES / MAX_UPLOAD_TOTAL_BYTES) so a
 * mistake is caught before a long round trip. The backend stays authoritative.
 */
export const UPLOAD_LIMITS = {
  maxFiles: 20,
  maxFileBytes: 25 * 1024 * 1024,
  maxTotalBytes: 100 * 1024 * 1024,
  maxFileMb: 25,
  maxTotalMb: 100,
  extensions: [".txt", ".pdf", ".docx", ".xlsx", ".zip", ".eml", ".json"],
} as const;

/** Plain-language text for the backend's upload rejections. */
export const UPLOAD_MISSING_FIELDS_MESSAGE =
  "Add a subject and body when uploading loose documents.";

/**
 * Column order of GET /api/emails/export?format=csv, mirroring
 * EXPORT_COLUMNS in backend/main.py: ten base columns, then si_<field> and
 * bl_<field> for each of the seven shipping fields.
 */
export const EXPORT_COLUMNS = {
  base: [
    "email_id",
    "sender",
    "subject",
    "category",
    "status",
    "review_reason",
    "has_defect",
    "defect_fields",
    "decided_by",
    "updated_at",
  ] as const,
  fields: FIELD_KEYS,
  get all(): string[] {
    return [
      ...EXPORT_COLUMNS.base,
      ...FIELD_KEYS.flatMap((key) => [`si_${key}`, `bl_${key}`]),
    ];
  },
};

export const EXPORT_OPTIONS: Array<{ format: "csv" | "json" | "submission"; label: string; hint: string }> = [
  { format: "csv", label: "Results as CSV", hint: "One row per email, all seven fields side by side" },
  { format: "json", label: "Results as JSON", hint: "The same rows as a JSON array" },
  {
    format: "submission",
    label: "Submission file (organizer format)",
    hint: "Keyed by email ID, built by the backend",
  },
];

/** True when this row came from a batch upload. */
export function isBatchEmail(record: EmailRecord): boolean {
  return Boolean(record.batch_id);
}

/** The ID a person recognises: the organizer's, when this is a batch row. */
export function displayEmailId(record: EmailRecord): string {
  return record.original_email_id || record.email_id;
}

/** Emails sampled for the discrepancy chart (GET /api/emails?status=MISMATCH). */
export const DISCREPANCY_SAMPLE_LIMIT = 500;

/**
 * Signed URLs expire after 300 s server-side
 * (database.DEFAULT_SIGNED_URL_EXPIRY_SECONDS). Never reuse one older than
 * four minutes — mint a fresh one instead.
 */
export const SIGNED_URL_MAX_AGE_MS = 4 * 60 * 1000;

/** Batch progress polls every 3 s; the expensive count endpoint every 10 s. */
export const BATCH_POLL_MS = 3_000;
export const BATCH_COUNTS_POLL_MS = 10_000;

/** Live batch speed/ETA are hidden until the run is long enough to be honest. */
export const ETA_MIN_DONE = 5;
export const ETA_MIN_ELAPSED_MS = 30_000;
