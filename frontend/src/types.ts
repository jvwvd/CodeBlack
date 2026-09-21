/**
 * Mirror of backend/models.py and the public.emails / public.attachments
 * columns defined in backend/schema.sql (PROJECT_RULES.md §7, §14).
 *
 * There is deliberately NO `confidence` field and no other invented field:
 * PROJECT_RULES.md §7 freezes this shape. Do not add to it here — the
 * canonical contract changes in backend/models.py first.
 */

export type Category =
  | "BL_COMPARISON"
  | "SI_REQUEST"
  | "INVOICE_QUERY"
  | "GENERAL"
  | "SPAM";

export type Status = "OK" | "MISMATCH" | "NEEDS_REVIEW";

export type ReviewReason =
  | "wrong_doc_type"
  | "missing_attachment"
  | "unreadable"
  | "missing_value";

export type ProcessingStatus = "pending" | "processing" | "completed" | "failed";

export type DecidedBy = "rule" | "llm";

export type DocType = "SI" | "BL" | "OTHER" | "UNREADABLE";

/** The seven canonical shipping fields, in their fixed display order (§5). */
export const FIELD_KEYS = [
  "shipper",
  "consignee",
  "notify_party",
  "port_of_loading",
  "port_of_discharge",
  "container_count",
  "gross_weight_kg",
] as const;

export type FieldKey = (typeof FIELD_KEYS)[number];

export interface ShipmentFields {
  shipper: string | null;
  consignee: string | null;
  notify_party: string | null;
  port_of_loading: string | null;
  port_of_discharge: string | null;
  container_count: number | null;
  gross_weight_kg: number | null;
}

/** Canonical pipeline output. Returned by POST /process and POST /retry. */
export interface EmailResult {
  email_id: string;
  category: Category;
  status: Status;
  si: ShipmentFields | null;
  bl: ShipmentFields | null;
  defect_fields: string[];
  has_defect: boolean;
  review_reason: ReviewReason | null;
  decided_by: DecidedBy | null;
  notes: string | null;
}

/**
 * Full DB row from public.emails. Returned by GET /api/emails (items) and
 * GET /api/emails/{id}.
 *
 * `status` carries a database-level default of 'OK' (schema.sql line 37), so
 * it is NOT a verdict until `processing_status === "completed"`. Never read
 * it without gating on processing_status — see getDisplayState().
 */
export interface EmailRecord {
  email_id: string;
  sender: string | null;
  subject: string | null;
  body: string | null;
  source_attachments: string[] | null;
  category: Category | null;
  status: Status | null;
  si: ShipmentFields | null;
  bl: ShipmentFields | null;
  defect_fields: string[] | null;
  has_defect: boolean | null;
  review_reason: ReviewReason | null;
  decided_by: DecidedBy | null;
  notes: string | null;
  processing_status: ProcessingStatus | null;
  retry_count: number | null;
  last_error: string | null;
  reviewed_at: string | null;
  reviewer_notes: string | null;
  created_at: string | null;
  updated_at: string | null;
  /**
   * Batch columns. Present only once schema.sql's batch migration is applied
   * (it is still marked "MIGRATION (proposed, NOT YET DEPLOYED)"), and null on
   * every non-batch row, so both are optional here.
   *
   * A batch-processed email is stored under a synthetic, batch-namespaced
   * email_id such as "batch_3f9a1c2e7b10__email_004", with the organizer's
   * real id preserved verbatim in original_email_id.
   */
  batch_id?: string | null;
  original_email_id?: string | null;
}

export interface AttachmentRecord {
  id: string;
  email_id: string;
  doc_type: DocType | null;
  storage_bucket: string | null;
  storage_path: string;
  original_filename: string | null;
  content_type: string | null;
  size_bytes: number | null;
  created_at: string | null;
}

export interface ListResponse<T> {
  items: T[];
  count: number;
}

export interface SignedUrlResponse {
  url: string;
  expires_in: number;
}

export interface ReviewCorrectionRequest {
  si?: ShipmentFields;
  bl?: ShipmentFields;
  reviewer_notes?: string;
}

/** Server-side filters accepted by GET /api/emails and /api/emails/count. */
export interface EmailFilters {
  status?: Status;
  category?: Category;
  processing_status?: ProcessingStatus;
  batch_id?: string;
}

/** Server-side filters plus the pagination window. */
export interface EmailQuery extends EmailFilters {
  limit?: number;
  offset?: number;
}

/**
 * GET /api/emails. `count` is the number of rows in THIS page; `total` is the
 * full filtered row count, read from the X-Total-Count response header.
 * `total` is null when the header is absent or unparseable — a missing header
 * is never an error.
 */
export interface EmailListResult {
  items: EmailRecord[];
  count: number;
  total: number | null;
}

export type BatchStatus = "processing" | "completed" | "failed";

/** GET /api/batches/{batch_id}, and the row in public.batches. */
export interface Batch {
  batch_id: string;
  total: number;
  done: number;
  failed: number;
  status: BatchStatus;
  created_at: string | null;
  finished_at: string | null;
}

/** GET /api/emails/export?format= */
export type ExportFormat = "csv" | "json" | "submission";

export interface UploadInput {
  sender?: string;
  subject?: string;
  body?: string;
  files: File[];
}

/**
 * POST /api/emails/upload returns one of three shapes. This is the normalised
 * union the UI branches on.
 */
export type UploadResponse =
  | { kind: "single"; email: EmailRecord }
  | { kind: "multiple"; emails: EmailRecord[] }
  | { kind: "batch"; batch_id: string; total: number; status: string };

export interface CountResponse {
  total: number;
}

export interface HealthResponse {
  status: string;
}
