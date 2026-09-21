/**
 * The only module in this app that calls fetch().
 *
 * Every function here makes exactly one real HTTP call to the SDOC backend.
 * Components never call fetch themselves — they go through the React Query
 * hooks in components/queries.ts, which call this module.
 *
 * Backend contract source: origin/feature/export-upload @ 06e4ad4
 * (backend/main.py, backend/models.py, backend/database.py,
 * docs/API_UPLOAD_EXPORT.md).
 *
 * This layer performs no verification: it transports what the backend decided
 * (PROJECT_RULES.md §3, §8).
 */
import { UPLOAD_LIMITS } from "./components/labels";
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
  HealthResponse,
  ListResponse,
  ReviewCorrectionRequest,
  SignedUrlResponse,
  UploadInput,
  UploadResponse,
} from "./types";

const PROCESS_TIMEOUT_MS = 90_000;
const UPLOAD_TIMEOUT_MS = 180_000;
const DEFAULT_TIMEOUT_MS = 30_000;

/** Full filtered row count lives in this response header, not in the body. */
const TOTAL_COUNT_HEADER = "X-Total-Count";

/**
 * The single piece of configuration this app needs. It holds no secrets: the
 * backend URL is public, and the frontend never sees a Supabase or provider
 * key (PROJECT_RULES.md §14, §18).
 */
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");

/** False when VITE_API_BASE_URL is missing or empty; the app then shows a
 * configuration screen instead of failing on every request. */
export const IS_CONFIGURED = API_BASE_URL.length > 0;

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
 * Transport
 * ------------------------------------------------------------------ */

type Params = Record<string, string | number | undefined>;

function url(path: string, params?: Params): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value === undefined || value === "") continue;
    query.set(key, String(value));
  }
  const suffix = query.toString();
  return `${API_BASE_URL}${path}${suffix ? `?${suffix}` : ""}`;
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

  if (!IS_CONFIGURED) {
    throw new ApiError(0, "The backend address is not configured.");
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
 * Reads X-Total-Count. Returns null when the header is missing (for example
 * CORS not exposing it) or not a number. Never throws.
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
 * Endpoints
 * ------------------------------------------------------------------ */

export async function getHealth(): Promise<HealthResponse> {
  return getJson<HealthResponse>("/api/health", undefined, 20_000);
}

/** GET /api/emails — paginated; total comes from the X-Total-Count header. */
export async function listEmails(query: EmailQuery = {}): Promise<EmailListResult> {
  const { limit, offset, ...filters } = query;
  const response = await request("/api/emails", {
    params: { ...filterParams(filters), limit, offset },
  });
  const body = (await response.json()) as ListResponse<EmailRecord>;
  return {
    items: body.items ?? [],
    count: body.count ?? (body.items?.length ?? 0),
    total: readTotalHeader(response),
  };
}

/** GET /api/emails/count — same filters as listEmails, no limit/offset. */
export async function countEmails(filters: EmailFilters = {}): Promise<number> {
  const body = await getJson<CountResponse>("/api/emails/count", filterParams(filters));
  return body.total ?? 0;
}

export async function getEmail(emailId: string): Promise<EmailRecord> {
  return getJson<EmailRecord>(`/api/emails/${encodeURIComponent(emailId)}`);
}

export async function listAttachments(emailId: string): Promise<ListResponse<AttachmentRecord>> {
  return getJson<ListResponse<AttachmentRecord>>(`/api/emails/${encodeURIComponent(emailId)}/attachments`);
}

export async function getSignedUrl(path: string): Promise<SignedUrlResponse> {
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
  const response = await request(`/api/emails/${encodeURIComponent(emailId)}/process`, {
    method: "POST",
    timeoutMs: PROCESS_TIMEOUT_MS,
  });
  return (await response.json()) as EmailResult;
}

export async function retryEmail(emailId: string): Promise<EmailResult> {
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
  return getJson<Batch>(`/api/batches/${encodeURIComponent(batchId)}`);
}
