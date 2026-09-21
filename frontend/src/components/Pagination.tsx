/**
 * Server-side pagination control, shared by the inbox and the review queue.
 * Renders the window as "51–100 of 1,240" using the total from the
 * X-Total-Count header. When the total is unknown it falls back to a plain
 * range and only disables Next once a short page comes back.
 */
import { ChevronLeft, ChevronRight } from "lucide-react";

import { formatNumber } from "./format";
import { Button } from "./ui";

export function Pagination({
  page,
  pageSize,
  count,
  total,
  onPageChange,
  busy = false,
}: {
  /** 1-based. */
  page: number;
  pageSize: number;
  /** Rows on this page. */
  count: number;
  total: number | null;
  onPageChange: (page: number) => void;
  busy?: boolean;
}) {
  const first = count === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = (page - 1) * pageSize + count;

  const lastPage = total === null ? null : Math.max(1, Math.ceil(total / pageSize));
  const hasNext = total === null ? count === pageSize : page < lastPage!;
  const hasPrevious = page > 1;

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 sm:px-5">
      <p className="text-xs text-muted tabular">
        {count === 0 ? (
          "No results"
        ) : total === null ? (
          <>
            {formatNumber(first)}–{formatNumber(last)}
          </>
        ) : (
          <>
            {formatNumber(first)}–{formatNumber(last)} of {formatNumber(total)}
          </>
        )}
        {lastPage !== null && lastPage > 1 ? (
          <span className="ml-2 text-muted">
            · page {formatNumber(page)} of {formatNumber(lastPage)}
          </span>
        ) : null}
      </p>

      <div className="flex items-center gap-2">
        <Button
          icon={ChevronLeft}
          onClick={() => onPageChange(page - 1)}
          disabled={!hasPrevious || busy}
        >
          Previous
        </Button>
        <Button onClick={() => onPageChange(page + 1)} disabled={!hasNext || busy}>
          Next
          <ChevronRight aria-hidden className="size-4" />
        </Button>
      </div>
    </div>
  );
}
