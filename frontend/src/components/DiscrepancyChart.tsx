/**
 * "Most common discrepancies" — how often each of the seven shipping fields
 * appears in the backend's `defect_fields`.
 *
 * This is counting, not deciding: every field named here was put in
 * defect_fields by pipeline/compare.py. Nothing is compared in the browser
 * (PROJECT_RULES.md §8).
 */
import { FIELD_KEYS, type FieldKey } from "../types";
import { formatNumber } from "./format";
import { DISCREPANCY_SCAN_LIMIT, FIELD_LABELS } from "./labels";
import { useEmails } from "./queries";
import { EmptyState, ErrorState, Panel, SkeletonBlock } from "./ui";

interface Row {
  key: FieldKey;
  count: number;
}

export function DiscrepancyChart() {
  const emails = useEmails({ status: "MISMATCH", limit: DISCREPANCY_SCAN_LIMIT });

  const records = emails.data?.items ?? [];

  // Every one of the seven fields is represented, zeros included.
  const tally = new Map<FieldKey, number>(FIELD_KEYS.map((key) => [key, 0]));
  for (const record of records) {
    for (const field of record.defect_fields ?? []) {
      if (tally.has(field as FieldKey)) {
        tally.set(field as FieldKey, (tally.get(field as FieldKey) ?? 0) + 1);
      }
    }
  }

  const rows: Row[] = [...tally.entries()]
    .map(([key, count]) => ({ key, count }))
    .sort((a, b) => (b.count - a.count) || FIELD_LABELS[a.key].localeCompare(FIELD_LABELS[b.key]));

  const max = rows[0]?.count ?? 0;

  const subtitle =
    emails.isSuccess
      ? `Across ${formatNumber(records.length)} ${records.length === 1 ? "email" : "emails"} with a mismatch`
      : "Across emails with a mismatch";

  return (
    <Panel title="Most common discrepancies" description={subtitle} bodyClassName="p-4 sm:p-5">
      {emails.isPending ? (
        <ul className="flex flex-col gap-3">
          {FIELD_KEYS.map((key) => (
            <li key={key} className="flex items-center gap-3">
              <SkeletonBlock className="h-3 w-32 shrink-0" />
              <SkeletonBlock className="h-2 flex-1" />
            </li>
          ))}
        </ul>
      ) : emails.isError ? (
        <ErrorState
          title="Could not load discrepancies"
          message={emails.error.message}
          onRetry={() => void emails.refetch()}
          retrying={emails.isFetching}
        />
      ) : records.length === 0 ? (
        <EmptyState
          title="No mismatches"
          message="No mismatches found yet. Fields appear here once the backend reports a difference between an SI and a BL."
        />
      ) : (
        <ul className="flex flex-col gap-1.5">
          {rows.map((row) => {
            const percent = max === 0 ? 0 : Math.round((row.count / max) * 100);
            return (
              <li key={row.key} className="flex items-center gap-3 py-1">
                <span className="w-36 shrink-0 text-sm sm:w-40">{FIELD_LABELS[row.key]}</span>
                <span className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-canvas">
                  <span
                    className={`block h-full rounded-full ${row.count === 0 ? "" : "bg-danger"}`}
                    style={{ width: `${percent}%` }}
                    aria-hidden
                  />
                </span>
                <span className="w-10 shrink-0 text-right text-sm tabular">
                  {formatNumber(row.count)}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
