/**
 * The only module in this app that calls fetch().
 *
 * Every function has a real implementation and a demo implementation behind
 * one typed signature, selected by VITE_USE_MOCK. Components never import the
 * demo layer directly and never call fetch themselves — they go through the
 * React Query hooks in components/queries.ts, which call this module.
 *
 * Backend contract source: origin/feature/export-upload @ 06e4ad4
 * (backend/main.py, backend/models.py, backend/database.py,
 * docs/API_UPLOAD_EXPORT.md). Every endpoint below is confirmed against that
 * commit — there are no assumed shapes left.
 *
 * This layer performs no verification: it transports what the backend decided
 * (PROJECT_RULES.md §3, §8).
 */
import {
  MOCK_ATTACHMENTS,
  MOCK_BATCH,
  MOCK_DEFAULT_OUTCOME,
  MOCK_EMAILS,
  MOCK_PROCESS_OUTCOMES,
  makeMockBatchEmails,
} from "./mockData";
import { EXPORT_COLUMNS, UPLOAD_LIMITS } from "./components/labels";
import type {
  AttachmentRecord,
  Batch,
  CountResponse,
  EmailFilters,
  EmailListResult,
  EmailQuery,
  EmailRecord,
  EmailResult,
  ExportFormat,
  FieldKey,
  HealthResponse,
  ListResponse,
  ReviewCorrectionRequest,
  ShipmentFields,
  SignedUrlResponse,
  UploadInput,
  UploadResponse,
} from "./types";

const PROCESS_TIMEOUT_MS = 90_000;
const UPLOAD_TIMEOUT_MS = 180_000;
const DEFAULT_TIMEOUT_MS = 30_000;

/** Full filtered row count lives in this response header, not in the body. */
const TOTAL_COUNT_HEADER = "X-Total-Count";

export const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true";

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }

  /** status 0 means the request never reached the backend. */
  get isNetworkError(): boolean {
    return this.status === 0;
  }
}

export interface ExportedFile {
  blob: Blob;
  filename: string;
}

/* ------------------------------------------------------------------ *
 * Real transport
 * ------------------------------------------------------------------ */

type Params = Record<string, string | number | undefined>;

function url(path: string, params?: Params): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value === undefined || value === "") continue;
    query.set(key, String(value));
  }
  const suffix = query.toString();
  return `${BASE_URL}${path}${suffix ? `?${suffix}` : ""}`;
}

/** Server-side filters, with empty values omitted. */
function filterParams(filters: EmailFilters): Params {
  return {
    status: filters.status,
    category: filters.category,
    processing_status: filters.processing_status,
    batch_id: filters.batch_id,
  };
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  let message = `Request failed with status ${response.status}.`;
  try {
    const payload: unknown = await response.json();
    if (payload && typeof payload === "object" && "detail" in payload) {
      const detail = (payload as { detail: unknown }).detail;
      if (typeof detail === "string" && detail.trim()) message = detail;
      // FastAPI validation errors arrive as a list of {loc, msg, type}.
      else if (Array.isArray(detail)) {
        const first = detail[0] as { msg?: unknown } | undefined;
        if (first && typeof first.msg === "string") message = first.msg;
      }
    }
  } catch {
    // Body was empty or not JSON; the status-based message above stands.
  }
  return new ApiError(response.status, message);
}

async function request(
  path: string,
  options: RequestInit & { params?: Params; timeoutMs?: number } = {},
): Promise<Response> {
  const { params, timeoutMs = DEFAULT_TIMEOUT_MS, ...init } = options;

  if (!BASE_URL) {
    throw new ApiError(
      0,
      "No backend URL is configured. Set VITE_API_BASE_URL, or set VITE_USE_MOCK=true to use demo data.",
    );
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  let response: Response;
  try {
    response = await fetch(url(path, params), { ...init, signal: controller.signal });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") {
      throw new ApiError(0, `The backend did not respond within ${Math.round(timeoutMs / 1000)} seconds.`);
    }
    throw new ApiError(0, "Could not reach the backend. Check that it is running and that CORS allows this origin.");
  } finally {
    clearTimeout(timer);
  }

  if (!response.ok) throw await errorFromResponse(response);
  return response;
}

async function getJson<T>(path: string, params?: Params, timeoutMs?: number): Promise<T> {
  const response = await request(path, { params, ...(timeoutMs === undefined ? {} : { timeoutMs }) });
  return (await response.json()) as T;
}

/**
 * Reads X-Total-Count. Returns null when the header is missing (e.g. an older
 * backend, or CORS not exposing it) or not a number. Never throws.
 */
function readTotalHeader(response: Response): number | null {
  try {
    const raw = response.headers.get(TOTAL_COUNT_HEADER);
    if (raw === null) return null;
    const parsed = Number.parseInt(raw.trim(), 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
  } catch {
    return null;
  }
}

function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null;
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (utf8?.[1]) {
    try {
      return decodeURIComponent(utf8[1].trim());
    } catch {
      // Fall through to the plain filename form.
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain?.[1]?.trim() ?? null;
}

/* ------------------------------------------------------------------ *
 * Demo transport
 * ------------------------------------------------------------------ */

const mockEmails: EmailRecord[] = MOCK_EMAILS.map((email) => ({ ...email }));
const mockAttachments: AttachmentRecord[] = MOCK_ATTACHMENTS.map((a) => ({ ...a }));
const mockBatches = new Map<string, Batch>();
// The demo dataset already contains one completed batch, so /batches/<id> is
// reachable without uploading anything first.
if (USE_MOCK) mockBatches.set(MOCK_BATCH.batch_id, { ...MOCK_BATCH });
let mockUploadCounter = 520;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function readLatency(): Promise<void> {
  return sleep(200 + Math.random() * 400);
}

function nowIso(): string {
  return new Date().toISOString();
}

function findMock(emailId: string): EmailRecord | undefined {
  return mockEmails.find((email) => email.email_id === emailId);
}

function toResult(record: EmailRecord): EmailResult {
  return {
    email_id: record.email_id,
    category: record.category ?? "GENERAL",
    status: record.status ?? "OK",
    si: record.si,
    bl: record.bl,
    defect_fields: record.defect_fields ?? [],
    has_defect: record.has_defect ?? false,
    review_reason: record.review_reason,
    decided_by: record.decided_by,
    notes: record.notes,
  };
}

/** Applies a scripted outcome. Nothing here decides anything. */
function applyMockOutcome(record: EmailRecord): EmailRecord {
  const outcome = MOCK_PROCESS_OUTCOMES[record.email_id] ?? MOCK_DEFAULT_OUTCOME;
  return {
    ...record,
    ...outcome,
    processing_status: "completed",
    last_error: null,
    updated_at: nowIso(),
  };
}

function matchesFilters(record: EmailRecord, filters: EmailFilters): boolean {
  if (filters.status && record.status !== filters.status) return false;
  if (filters.category && record.category !== filters.category) return false;
  if (filters.processing_status && record.processing_status !== filters.processing_status) return false;
  if (filters.batch_id && (record.batch_id ?? null) !== filters.batch_id) return false;
  return true;
}

/** Same ordering the backend uses: created_at DESC, then email_id ASC. */
function mockSorted(records: EmailRecord[]): EmailRecord[] {
  return records.slice().sort((a, b) => {
    const byDate = (b.created_at ?? "").localeCompare(a.created_at ?? "");
    return byDate !== 0 ? byDate : a.email_id.localeCompare(b.email_id);
  });
}

function mockMatching(filters: EmailFilters): EmailRecord[] {
  return mockSorted(mockEmails.filter((record) => matchesFilters(record, filters)));
}

/* -- demo export ---------------------------------------------------- */

function exportRow(record: EmailRecord): Record<string, unknown> {
  const si = record.si;
  const bl = record.bl;
  const row: Record<string, unknown> = {
    email_id: record.email_id,
    sender: record.sender,
    subject: record.subject,
    category: record.category,
    status: record.status,
    review_reason: record.review_reason,
    has_defect: record.has_defect,
    defect_fields: record.defect_fields ?? [],
    decided_by: record.decided_by,
    updated_at: record.updated_at,
  };
  for (const key of EXPORT_COLUMNS.fields) {
    row[`si_${key}`] = si ? si[key as FieldKey] : null;
    row[`bl_${key}`] = bl ? bl[key as FieldKey] : null;
  }
  return row;
}

function mockCsv(records: EmailRecord[]): string {
  const cell = (value: unknown): string => {
    if (value === null || value === undefined) return "";
    const text = Array.isArray(value) ? value.join(";") : String(value);
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const columns = EXPORT_COLUMNS.all;
  const lines = [columns.join(",")];
  for (const record of records) {
    const row = exportRow(record);
    lines.push(columns.map((column) => cell(row[column])).join(","));
  }
  return lines.join("\r\n");
}

function mockSubmission(records: EmailRecord[]): Record<string, unknown> {
  const submission: Record<string, unknown> = {};
  for (const record of records) {
    const key = record.original_email_id || record.email_id;
    submission[key] = {
      category: record.category,
      status: record.status,
      review_reason: record.review_reason,
      defect_fields: record.defect_fields ?? [],
      has_defect: record.has_defect,
    };
  }
  return submission;
}

/** Mirrors the backend's codeblack_results_YYYYMMDD.<ext> convention. */
function mockExportFilename(format: ExportFormat): string {
  const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  return `codeblack_results_${stamp}.${format === "csv" ? "csv" : "json"}`;
}

/* -- demo upload / batch -------------------------------------------- */

function newMockEmail(overrides: Partial<EmailRecord> & { email_id: string }): EmailRecord {
  return {
    sender: null,
    subject: null,
    body: null,
    source_attachments: null,
    category: null,
    status: "OK",
    si: null,
    bl: null,
    defect_fields: [],
    has_defect: false,
    review_reason: null,
    decided_by: null,
    notes: null,
    processing_status: "pending",
    retry_count: 0,
    last_error: null,
    reviewed_at: null,
    reviewer_notes: null,
    created_at: nowIso(),
    updated_at: nowIso(),
    batch_id: null,
    original_email_id: null,
    ...overrides,
  };
}

function looksLikeBundle(file: File): boolean {
  return file.name.toLowerCase().endsWith(".zip");
}

function isStructuredEmailFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return name.endsWith(".eml") || name.endsWith(".json");
}

/* ------------------------------------------------------------------ *
 * Public API
 * ------------------------------------------------------------------ */

export async function getHealth(): Promise<HealthResponse> {
  if (USE_MOCK) {
    await sleep(120);
    return { status: "ok" };
  }
  return getJson<HealthResponse>("/api/health", undefined, 8_000);
}

/** GET /api/emails — paginated; total comes from the X-Total-Count header. */
export async function listEmails(query: EmailQuery = {}): Promise<EmailListResult> {
  const { limit, offset, ...filters } = query;

  if (USE_MOCK) {
    await readLatency();
    const matching = mockMatching(filters);
    const start = offset ?? 0;
    const end = limit === undefined ? undefined : start + limit;
    const items = matching.slice(start, end).map((record) => ({ ...record }));
    return { items, count: items.length, total: matching.length };
  }

  const response = await request("/api/emails", {
    params: { ...filterParams(filters), limit, offset },
  });
  const body = (await response.json()) as ListResponse<EmailRecord>;
  return {
    items: body.items,
    count: body.count,
    total: readTotalHeader(response),
  };
}

/** GET /api/emails/count — same filters as listEmails, no limit/offset. */
export async function countEmails(filters: EmailFilters = {}): Promise<number> {
  if (USE_MOCK) {
    await readLatency();
    return mockMatching(filters).length;
  }
  const body = await getJson<CountResponse>("/api/emails/count", filterParams(filters));
  return body.total;
}

export async function getEmail(emailId: string): Promise<EmailRecord> {
  if (USE_MOCK) {
    await readLatency();
    const record = findMock(emailId);
    if (!record) throw new ApiError(404, `email not found: ${emailId}`);
    return { ...record };
  }
  return getJson<EmailRecord>(`/api/emails/${encodeURIComponent(emailId)}`);
}

export async function listAttachments(emailId: string): Promise<ListResponse<AttachmentRecord>> {
  if (USE_MOCK) {
    await readLatency();
    const items = mockAttachments.filter((a) => a.email_id === emailId).map((a) => ({ ...a }));
    return { items, count: items.length };
  }
  return getJson<ListResponse<AttachmentRecord>>(`/api/emails/${encodeURIComponent(emailId)}/attachments`);
}

export async function getSignedUrl(path: string): Promise<SignedUrlResponse> {
  if (USE_MOCK) {
    await sleep(350);
    throw new ApiError(
      0,
      "Document preview is not available in demo mode. Connect a backend to open the original file.",
    );
  }
  return getJson<SignedUrlResponse>("/api/documents/signed-url", { path });
}

/**
 * Fetches a private document's text through a fresh signed URL.
 *
 * Used only for .txt previews. The response is returned as a plain string and
 * is rendered as text, never as HTML. The signed URL is minted per call, so
 * nothing cached or expired is reused.
 */
export async function fetchDocumentText(path: string): Promise<string> {
  const { url: signed } = await getSignedUrl(path);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS);
  try {
    const response = await fetch(signed, { signal: controller.signal });
    if (!response.ok) {
      throw new ApiError(response.status, `The file could not be read (status ${response.status}).`);
    }
    return await response.text();
  } catch (cause) {
    if (cause instanceof ApiError) throw cause;
    if (cause instanceof DOMException && cause.name === "AbortError") {
      throw new ApiError(0, "Reading the file timed out.");
    }
    throw new ApiError(0, "The file could not be read from storage in this browser.");
  } finally {
    clearTimeout(timer);
  }
}

export async function processEmail(emailId: string): Promise<EmailResult> {
  if (USE_MOCK) {
    const record = findMock(emailId);
    if (!record) throw new ApiError(404, `email not found: ${emailId}`);
    record.processing_status = "processing";
    record.last_error = null;
    record.updated_at = nowIso();
    await sleep(3_000);
    Object.assign(record, applyMockOutcome(record));
    return toResult(record);
  }

  const response = await request(`/api/emails/${encodeURIComponent(emailId)}/process`, {
    method: "POST",
    timeoutMs: PROCESS_TIMEOUT_MS,
  });
  return (await response.json()) as EmailResult;
}

export async function retryEmail(emailId: string): Promise<EmailResult> {
  if (USE_MOCK) {
    const record = findMock(emailId);
    if (!record) throw new ApiError(404, `email not found: ${emailId}`);
    record.retry_count = (record.retry_count ?? 0) + 1;
    record.processing_status = "processing";
    record.last_error = null;
    record.updated_at = nowIso();
    await sleep(3_000);
    Object.assign(record, applyMockOutcome(record));
    return toResult(record);
  }

  const response = await request(`/api/emails/${encodeURIComponent(emailId)}/retry`, {
    method: "POST",
    timeoutMs: PROCESS_TIMEOUT_MS,
  });
  return (await response.json()) as EmailResult;
}

export async function submitReview(
  emailId: string,
  body: ReviewCorrectionRequest,
): Promise<EmailRecord> {
  if (USE_MOCK) {
    const record = findMock(emailId);
    if (!record) throw new ApiError(404, `email not found: ${emailId}`);
    await sleep(1_400);
    // Store what the reviewer typed and stamp the review. Deliberately does
    // NOT recompute status/defect_fields — only the backend re-verifies.
    if (body.si !== undefined) record.si = { ...(body.si as ShipmentFields) };
    if (body.bl !== undefined) record.bl = { ...(body.bl as ShipmentFields) };
    if (body.reviewer_notes !== undefined) record.reviewer_notes = body.reviewer_notes;
    record.reviewed_at = nowIso();
    record.updated_at = nowIso();
    return { ...record };
  }

  const response = await request(`/api/emails/${encodeURIComponent(emailId)}/review`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return (await response.json()) as EmailRecord;
}

/** GET /api/emails/export?format=csv|json|submission */
export async function exportEmails(
  format: ExportFormat,
  filters: EmailFilters = {},
): Promise<ExportedFile> {
  if (USE_MOCK) {
    await sleep(900);
    const records = mockMatching(filters);
    const filename = mockExportFilename(format);
    if (format === "csv") {
      return { blob: new Blob([mockCsv(records)], { type: "text/csv;charset=utf-8" }), filename };
    }
    const payload =
      format === "submission" ? mockSubmission(records) : records.map((record) => exportRow(record));
    return {
      blob: new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }),
      filename,
    };
  }

  const response = await request("/api/emails/export", {
    params: { format, ...filterParams(filters) },
    timeoutMs: PROCESS_TIMEOUT_MS,
  });
  const fallback = `codeblack_results_${new Date().toISOString().slice(0, 10).replace(/-/g, "")}.${
    format === "csv" ? "csv" : "json"
  }`;
  return {
    blob: await response.blob(),
    filename: filenameFromDisposition(response.headers.get("Content-Disposition")) ?? fallback,
  };
}

/**
 * POST /api/emails/upload. Accepts any mix of files and normalises the
 * backend's three response shapes into one union.
 */
export async function uploadEmail(input: UploadInput): Promise<UploadResponse> {
  if (USE_MOCK) {
    await sleep(2_400);

    const bundle = input.files.find(looksLikeBundle);
    if (bundle) {
      const batchId = `batch_${Math.random().toString(16).slice(2, 14)}`;
      const total = 24;
      mockBatches.set(batchId, {
        batch_id: batchId,
        total,
        done: 0,
        failed: 0,
        status: "processing",
        created_at: nowIso(),
        finished_at: null,
      });
      mockEmails.unshift(...makeMockBatchEmails(batchId, total));
      return { kind: "batch", batch_id: batchId, total, status: "processing" };
    }

    const structured = input.files.filter(isStructuredEmailFile);
    const attachments = input.files.filter((file) => !isStructuredEmailFile(file));
    const created: EmailRecord[] = [];

    for (const file of structured) {
      mockUploadCounter += 1;
      const emailId = `upload_${Math.random().toString(16).slice(2, 14)}`;
      const record = newMockEmail({
        email_id: emailId,
        sender: `sender${mockUploadCounter}@example.com`,
        subject: file.name.replace(/\.(eml|json)$/i, ""),
        body: `Imported from ${file.name}.`,
        source_attachments: [],
      });
      mockEmails.unshift(record);
      created.push(record);
    }

    if (attachments.length > 0 || structured.length === 0) {
      if (!input.subject || !input.body) {
        throw new ApiError(
          422,
          "subject and body are required unless an .eml or organizer-format .json file is uploaded",
        );
      }
      const emailId = `upload_${Math.random().toString(16).slice(2, 14)}`;
      const record = newMockEmail({
        email_id: emailId,
        sender: input.sender || null,
        subject: input.subject,
        body: input.body,
        source_attachments: attachments.map((file) => file.name),
      });
      mockEmails.unshift(record);
      attachments.forEach((file, index) => {
        mockAttachments.push({
          id: `${emailId}-att-${index + 1}`,
          email_id: emailId,
          doc_type: null,
          storage_bucket: "documents",
          storage_path: `${emailId}/${file.name}`,
          original_filename: file.name,
          content_type: file.type || null,
          size_bytes: file.size,
          created_at: nowIso(),
        });
      });
      created.push(record);
    }

    return created.length === 1
      ? { kind: "single", email: created[0]! }
      : { kind: "multiple", emails: created };
  }

  const form = new FormData();
  // The backend reads these as optional Form fields; only send what we have.
  if (input.sender !== undefined) form.set("sender", input.sender);
  if (input.subject !== undefined) form.set("subject", input.subject);
  if (input.body !== undefined) form.set("body", input.body);
  for (const file of input.files) form.append("files", file, file.name);

  let response: Response;
  try {
    response = await request("/api/emails/upload", {
      method: "POST",
      body: form,
      timeoutMs: UPLOAD_TIMEOUT_MS,
    });
  } catch (cause) {
    throw cause instanceof ApiError ? readableUploadError(cause) : cause;
  }

  return normaliseUploadResponse(await response.json());
}

/** Turns the backend's 413/400/422 details into something a user can act on. */
function readableUploadError(error: ApiError): ApiError {
  const { maxFiles, maxFileMb, maxTotalMb } = UPLOAD_LIMITS;
  switch (error.status) {
    case 413:
      return new ApiError(
        413,
        `${error.message} Limits are ${maxFiles} files per upload, ${maxFileMb} MB per file and ${maxTotalMb} MB in total.`,
      );
    case 400:
      return new ApiError(400, `${error.message} Check that the archive is a valid .zip and try again.`);
    case 422:
      return new ApiError(422, "Add a subject and body when uploading loose documents.");
    default:
      return error;
  }
}

function normaliseUploadResponse(payload: unknown): UploadResponse {
  if (payload && typeof payload === "object") {
    const body = payload as {
      email_id?: unknown;
      emails?: unknown;
      batch_id?: unknown;
      total?: unknown;
      status?: unknown;
    };

    if (typeof body.batch_id === "string" && body.batch_id) {
      return {
        kind: "batch",
        batch_id: body.batch_id,
        total: typeof body.total === "number" ? body.total : 0,
        status: typeof body.status === "string" ? body.status : "processing",
      };
    }

    if (Array.isArray(body.emails)) {
      const emails = body.emails as EmailRecord[];
      return emails.length === 1 && emails[0]
        ? { kind: "single", email: emails[0] }
        : { kind: "multiple", emails };
    }

    if (typeof body.email_id === "string" && body.email_id) {
      return { kind: "single", email: payload as EmailRecord };
    }
  }

  throw new ApiError(200, "The upload succeeded but the backend returned an unexpected response.");
}

/** GET /api/batches/{batch_id} */
export async function getBatch(batchId: string): Promise<Batch> {
  if (USE_MOCK) {
    await sleep(320);
    const batch = mockBatches.get(batchId);
    if (!batch) throw new ApiError(404, `batch not found: ${batchId}`);

    // Advance on each poll until every email is accounted for.
    if (batch.status === "processing") {
      const remaining = batch.total - batch.done - batch.failed;
      if (remaining > 0) {
        const step = Math.min(remaining, 4);
        // Two of the batch fail, matching the mock batch emails.
        if (batch.failed < 2 && remaining <= 6) batch.failed += 1;
        else batch.done += step;
      }
      if (batch.done + batch.failed >= batch.total) {
        batch.done = batch.total - batch.failed;
        batch.status = "completed";
        batch.finished_at = nowIso();
      }
    }
    return { ...batch };
  }

  return getJson<Batch>(`/api/batches/${encodeURIComponent(batchId)}`);
}
