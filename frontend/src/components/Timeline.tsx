/**
 * What happened to one email, built ONLY from columns that exist on the row.
 *
 * Deliberately conservative: `updated_at` is labelled "Last updated", never
 * "Processed at", because a reviewer correction also bumps it. Nothing is
 * inferred and no timestamp is invented.
 */
import { CircleCheck, CircleDashed, Clock, Loader2, RotateCcw, UserCheck, XCircle } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { EmailRecord } from "../types";
import { formatAbsolute, formatRelative } from "./format";

interface Entry {
  icon: LucideIcon;
  label: string;
  timestamp: string | null;
  detail?: string | null;
  tone?: "muted" | "danger" | "success";
  spin?: boolean;
}

function processingEntry(record: EmailRecord): Entry {
  switch (record.processing_status) {
    case "processing":
      return { icon: Loader2, label: "Processing…", timestamp: record.updated_at, spin: true };
    case "failed":
      return {
        icon: XCircle,
        label: "Processing failed",
        timestamp: record.updated_at,
        detail: record.last_error,
        tone: "danger",
      };
    case "completed":
      return { icon: CircleCheck, label: "Checked", timestamp: record.updated_at, tone: "success" };
    default:
      return { icon: CircleDashed, label: "Not yet verified", timestamp: record.updated_at };
  }
}

export function Timeline({ record }: { record: EmailRecord }) {
  const entries: Entry[] = [];

  if (record.created_at) {
    entries.push({ icon: Clock, label: "Received", timestamp: record.created_at });
  }

  entries.push(processingEntry(record));

  if ((record.retry_count ?? 0) > 0) {
    const n = record.retry_count ?? 0;
    entries.push({
      icon: RotateCcw,
      label: `Retried ${n} ${n === 1 ? "time" : "times"}`,
      timestamp: null,
    });
  }

  if (record.reviewed_at) {
    entries.push({
      icon: UserCheck,
      label: "Reviewed",
      timestamp: record.reviewed_at,
      detail: record.reviewer_notes,
    });
  }

  const toneClass = { muted: "text-muted", danger: "text-danger", success: "text-success" };

  return (
    <ol className="flex flex-col">
      {entries.map((entry, index) => {
        const last = index === entries.length - 1;
        return (
          <li key={`${entry.label}-${index}`} className="flex gap-3">
            {/* Rail: icon plus the connector down to the next entry. */}
            <div className="flex flex-col items-center">
              <entry.icon
                aria-hidden
                className={`size-4 shrink-0 ${entry.tone ? toneClass[entry.tone] : "text-muted"} ${
                  entry.spin ? "motion-safe:animate-spin" : ""
                }`}
              />
              {!last ? <span aria-hidden className="w-px flex-1 bg-line" /> : null}
            </div>

            <div className={`min-w-0 ${last ? "" : "pb-3"}`}>
              <p className="text-sm leading-tight">
                <span className="font-medium">{entry.label}</span>
                {entry.timestamp ? (
                  <span className="ml-2 text-2xs text-muted" title={formatAbsolute(entry.timestamp)}>
                    {entry.label === "Checked" ||
                    entry.label === "Processing…" ||
                    entry.label === "Not yet verified" ||
                    entry.label === "Processing failed"
                      ? `Last updated ${formatRelative(entry.timestamp).toLowerCase()}`
                      : formatRelative(entry.timestamp)}
                  </span>
                ) : null}
              </p>
              {entry.detail ? (
                <p
                  className={`mt-0.5 text-xs break-words ${
                    entry.tone === "danger" ? "font-mono text-muted" : "text-muted"
                  }`}
                >
                  {entry.detail}
                </p>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
