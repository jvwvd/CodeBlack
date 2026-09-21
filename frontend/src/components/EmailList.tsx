/**
 * Inbox (/inbox). Filters and the page number live in the URL query string so
 * dashboard links work and the back button restores them.
 *
 * Category, processing state, batch and the backend status values are
 * SERVER-side filters, sent to GET /api/emails. Search is client-side and
 * narrows the current page only — the placeholder says so.
 *
 * Nothing here recomputes a verdict; sorting, filtering and search are
 * presentation only.
 */
import { Search, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";

import type { Category, EmailRecord, ProcessingStatus, Status } from "../types";
import { PageHeader } from "./AppShell";
import { ExportMenu } from "./ExportMenu";
import { formatAbsolute, formatNumber, formatRelative, setDocumentTitle } from "./format";
import {
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  PAGE_SIZE,
  PROCESSING_FILTERS,
  displayEmailId,
  getDisplayState,
  isBatchEmail,
} from "./labels";
import { Pagination } from "./Pagination";
import { useEmails } from "./queries";
import { Button, EmptyState, ErrorState, MonoId, SkeletonRows, StatusBadge, Tag } from "./ui";

const COLUMN_COUNT = 6;

/** Backend status values, filtered server-side (GET /api/emails?status=). */
const STATUS_FILTERS: Array<{ value: Status; label: string }> = [
  { value: "OK", label: "OK — no mismatch" },
  { value: "MISMATCH", label: "Mismatch" },
  { value: "NEEDS_REVIEW", label: "Needs review" },
];

function isCategory(value: string | null): value is Category {
  return value !== null && (CATEGORY_ORDER as string[]).includes(value);
}

function isStatus(value: string | null): value is Status {
  return value !== null && STATUS_FILTERS.some((filter) => filter.value === value);
}

function isProcessingStatus(value: string | null): value is ProcessingStatus {
  return value !== null && PROCESSING_FILTERS.some((filter) => filter.value === value);
}

function EmailIdCell({ record }: { record: EmailRecord }) {
  return (
    <span className="flex items-center gap-1.5">
      <MonoId>{displayEmailId(record)}</MonoId>
      {isBatchEmail(record) ? <Tag>Batch</Tag> : null}
    </span>
  );
}

export function EmailList() {
  const [params, setParams] = useSearchParams();

  useEffect(() => {
    setDocumentTitle("Inbox");
  }, []);

  const search = params.get("q") ?? "";
  const categoryParam = params.get("category");
  const statusParam = params.get("status");
  const processingParam = params.get("processing");
  const batchId = params.get("batch_id") ?? null;
  const pageParam = Number.parseInt(params.get("page") ?? "1", 10);
  const page = Number.isFinite(pageParam) && pageParam > 0 ? pageParam : 1;

  const category = isCategory(categoryParam) ? categoryParam : null;
  const status = isStatus(statusParam) ? statusParam : null;
  const processingStatus = isProcessingStatus(processingParam) ? processingParam : null;

  const serverFilters = useMemo(
    () => ({
      ...(status ? { status } : {}),
      ...(category ? { category } : {}),
      ...(processingStatus ? { processing_status: processingStatus } : {}),
      ...(batchId ? { batch_id: batchId } : {}),
    }),
    [status, category, processingStatus, batchId],
  );

  const emails = useEmails({
    ...serverFilters,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });

  /** Any filter change resets to page 1; only `page` itself keeps the page. */
  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value === null || value === "") next.delete(key);
    else next.set(key, value);
    if (key !== "page") next.delete("page");
    setParams(next, { replace: true });
  };

  const goToPage = (nextPage: number) => {
    const next = new URLSearchParams(params);
    if (nextPage <= 1) next.delete("page");
    else next.set("page", String(nextPage));
    setParams(next, { replace: false });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const pageItems = emails.data?.items ?? [];

  // Search narrows the page that is already on screen — it is not sent to the
  // server, so it can only ever match rows in this page.
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return pageItems;
    return pageItems.filter(
      (record) =>
        (record.subject ?? "").toLowerCase().includes(needle) ||
        (record.sender ?? "").toLowerCase().includes(needle),
    );
  }, [pageItems, search]);

  const hasFilters = Boolean(search || category || status || processingStatus || batchId);
  const detailState = { from: `/inbox?${params.toString()}` };

  return (
    <>
      <PageHeader
        title="Inbox"
        description="Every email the backend has imported, with the result of its document check."
        actions={<ExportMenu filters={serverFilters} />}
      />

      {batchId ? (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted">Filtered to batch</span>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-accent bg-accent-tint py-0.5 pr-1 pl-2.5 text-2xs font-medium text-accent">
            <span className="font-mono">{batchId}</span>
            <button
              type="button"
              onClick={() => setParam("batch_id", null)}
              className="rounded-full p-0.5 hover:bg-surface"
              aria-label="Remove batch filter"
            >
              <X aria-hidden className="size-3.5" />
            </button>
          </span>
          <Link to={`/batches/${encodeURIComponent(batchId)}`} className="text-xs text-accent hover:underline">
            View batch progress
          </Link>
        </div>
      ) : null}

      <div className="panel mb-4 p-3 sm:p-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className="field-label" htmlFor="inbox-search">
              Search this page
            </label>
            <div className="relative">
              <Search aria-hidden className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted" />
              <input
                id="inbox-search"
                type="search"
                className="control pl-8"
                placeholder="Search this page — subject or sender"
                value={search}
                onChange={(event) => setParam("q", event.target.value)}
              />
            </div>
          </div>

          <div>
            <label className="field-label" htmlFor="inbox-category">
              Category
            </label>
            <select
              id="inbox-category"
              className="control"
              value={category ?? ""}
              onChange={(event) => setParam("category", event.target.value || null)}
            >
              <option value="">All categories</option>
              {CATEGORY_ORDER.map((value) => (
                <option key={value} value={value}>
                  {CATEGORY_LABELS[value]}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="field-label" htmlFor="inbox-status">
              Result
            </label>
            <select
              id="inbox-status"
              className="control"
              value={status ?? ""}
              onChange={(event) => setParam("status", event.target.value || null)}
            >
              <option value="">All results</option>
              {STATUS_FILTERS.map((filter) => (
                <option key={filter.value} value={filter.value}>
                  {filter.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="field-label" htmlFor="inbox-processing">
              Processing state
            </label>
            <select
              id="inbox-processing"
              className="control"
              value={processingStatus ?? ""}
              onChange={(event) => setParam("processing", event.target.value || null)}
            >
              <option value="">Any state</option>
              {PROCESSING_FILTERS.map((filter) => (
                <option key={filter.value} value={filter.value}>
                  {filter.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
          <p className="text-xs text-muted">
            {search
              ? `${formatNumber(visible.length)} of ${formatNumber(pageItems.length)} on this page match “${search}”`
              : "Result, category, processing state and batch are applied by the backend."}
          </p>
          {hasFilters ? (
            <Button variant="quiet" icon={SlidersHorizontal} onClick={() => setParams({}, { replace: true })}>
              Clear filters
            </Button>
          ) : null}
        </div>
      </div>

      {emails.isError ? (
        <ErrorState
          title="Could not load the inbox"
          message={emails.error.message}
          onRetry={() => void emails.refetch()}
          retrying={emails.isFetching}
        />
      ) : (
        <div className="panel overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[50rem] border-collapse text-left">
              <thead>
                <tr className="bg-canvas text-xs text-muted">
                  <th scope="col" className="px-4 py-2.5 font-medium">Email ID</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Sender</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Subject</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Category</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Result</th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">Updated</th>
                </tr>
              </thead>
              <tbody>
                {emails.isPending ? <SkeletonRows rows={8} columns={COLUMN_COUNT} /> : null}

                {emails.isSuccess &&
                  visible.map((record) => {
                    const to = `/emails/${encodeURIComponent(record.email_id)}`;
                    return (
                      <tr key={record.email_id} className="border-t border-line hover:bg-canvas">
                        <td className="p-0">
                          <Link to={to} state={detailState} className="block px-4 py-3">
                            <EmailIdCell record={record} />
                          </Link>
                        </td>
                        <td className="p-0">
                          <Link
                            to={to}
                            state={detailState}
                            className="block max-w-[11rem] truncate px-4 py-3 text-sm text-muted"
                            title={record.sender ?? undefined}
                          >
                            {record.sender || "Unknown sender"}
                          </Link>
                        </td>
                        <td className="p-0">
                          <Link
                            to={to}
                            state={detailState}
                            className="block max-w-[18rem] truncate px-4 py-3 text-sm"
                            title={record.subject ?? undefined}
                          >
                            {record.subject || "No subject"}
                          </Link>
                        </td>
                        <td className="p-0">
                          <Link
                            to={to}
                            state={detailState}
                            className="block px-4 py-3 text-xs whitespace-nowrap text-muted"
                          >
                            {record.category ? CATEGORY_LABELS[record.category] : "Not classified"}
                          </Link>
                        </td>
                        <td className="p-0">
                          <Link to={to} state={detailState} className="block px-4 py-3">
                            <StatusBadge state={getDisplayState(record)} />
                          </Link>
                        </td>
                        <td className="p-0">
                          <Link
                            to={to}
                            state={detailState}
                            className="block px-4 py-3 text-right text-xs whitespace-nowrap text-muted"
                            title={formatAbsolute(record.updated_at)}
                          >
                            {formatRelative(record.updated_at)}
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>

          {emails.isSuccess && visible.length === 0 ? (
            <EmptyState
              icon={Search}
              title={hasFilters ? "No results match these filters" : "The inbox is empty"}
              message={
                search
                  ? "No email on this page matches your search. Search only covers the page you are on — try the next page, or a server-side filter."
                  : hasFilters
                    ? "Try a different filter, or clear them to see every email."
                    : "Emails appear here once the backend has imported them."
              }
              action={
                hasFilters ? (
                  <Button variant="secondary" onClick={() => setParams({}, { replace: true })}>
                    Clear filters
                  </Button>
                ) : null
              }
            />
          ) : null}

          {emails.isSuccess ? (
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              count={pageItems.length}
              total={emails.data.total}
              onPageChange={goToPage}
              busy={emails.isFetching}
            />
          ) : null}
        </div>
      )}
    </>
  );
}
