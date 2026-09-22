/** Presentation-only helpers: formatting, never decisions. */
import type { FieldKey } from "../types";

const NOT_FOUND = "— not found";

export const NOT_FOUND_TEXT = NOT_FOUND;

/** Renders one of the seven shipping values, or the subtle not-found marker. */
export function formatFieldValue(key: FieldKey, value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return NOT_FOUND;
  if (key === "gross_weight_kg" || key === "container_count") {
    const numeric = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(numeric)) return String(value);
    return numeric.toLocaleString("en-GB", { maximumFractionDigits: 3 });
  }
  return String(value);
}

export function formatNumber(value: number): string {
  return value.toLocaleString("en-GB");
}

export function formatBytes(bytes: number | null): string {
  if (bytes === null || !Number.isFinite(bytes)) return "Unknown size";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatAbsolute(iso: string | null): string {
  if (!iso) return "Unknown";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return date.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const RELATIVE_STEPS: Array<[limitSeconds: number, divisor: number, unit: Intl.RelativeTimeFormatUnit]> = [
  [60, 1, "second"],
  [3600, 60, "minute"],
  [86400, 3600, "hour"],
  [2592000, 86400, "day"],
  [31536000, 2592000, "month"],
  [Number.POSITIVE_INFINITY, 31536000, "year"],
];

export function formatRelative(iso: string | null): string {
  if (!iso) return "Unknown";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Unknown";

  const deltaSeconds = (date.getTime() - Date.now()) / 1000;
  const magnitude = Math.abs(deltaSeconds);
  if (magnitude < 45) return "Just now";

  const formatter = new Intl.RelativeTimeFormat("en-GB", { numeric: "auto" });
  for (const [limit, divisor, unit] of RELATIVE_STEPS) {
    if (magnitude < limit) return formatter.format(Math.round(deltaSeconds / divisor), unit);
  }
  return formatAbsolute(iso);
}

/** File-type word used for the attachment icon and its text label. */
export function fileKind(filename: string | null): "pdf" | "word" | "sheet" | "text" | "file" {
  const ext = (filename ?? "").toLowerCase().split(".").pop() ?? "";
  if (ext === "pdf") return "pdf";
  if (ext === "docx" || ext === "doc") return "word";
  if (ext === "xlsx" || ext === "xls" || ext === "csv") return "sheet";
  if (ext === "txt") return "text";
  return "file";
}

export const FILE_KIND_LABEL: Record<ReturnType<typeof fileKind>, string> = {
  pdf: "PDF document",
  word: "Word document",
  sheet: "Spreadsheet",
  text: "Text file",
  file: "File",
};

/** Triggers a browser download for a blob the API layer produced. */
export function downloadBlob(blob: Blob, filename: string): void {
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Safari cancels an in-flight download if the object URL is revoked right
  // after click(), so release it well after the browser has taken the blob.
  window.setTimeout(() => URL.revokeObjectURL(href), 60_000);
}

export function setDocumentTitle(page: string): void {
  document.title = `${page} — SDOC by CodeBlack`;
}
