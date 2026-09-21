/**
 * Dashboard. Every summary figure is its own GET /api/emails/count call with
 * the matching server-side filter, run in parallel, each with its own loading
 * and error state. Nothing is counted in the browser.
 */
import { Upload } from "lucide-react";
import { useEffect, useMemo } from "react";
import { Link } from "react-router-dom";

import type { Category, EmailFilters, EmailRecord } from "../types";
import { PageHeader } from "./AppShell";
import { formatNumber, formatRelative, setDocumentTitle } from "./format";
import {
  ATTENTION_LIMIT,
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  displayEmailId,
  getDisplayState,
  isBatchEmail,
} from "./labels";
import { useEmailCounts, useEmails } from "./queries";
import { EmptyState, ErrorState, MonoId, Panel, SkeletonBlock, StatusBadge, Tag } from "./ui";

interface Figure {
  label: string;
  filters: EmailFilters;
  /** Inbox query string this figure links to. */
  href: string;
}

const FIGURES: Figure[] = [
  { label: "Total emails", filters: {}, href: "/inbox" },
  {
    label: "Document checks",
    filters: { category: "BL_COMPARISON" },
    href: "/inbox?category=BL_COMPARISON",
  },
  { label: "Mismatches", filters: { status: "MISMATCH" }, href: "/inbox?status=MISMATCH" },
  { label: "Needs review", filters: { status: "NEEDS_REVIEW" }, href: "/inbox?status=NEEDS_REVIEW" },
  {
    label: "Not yet verified",
    filters: { processing_status: "pending" },
    href: "/inbox?processing=pending",
  },
  { label: "Failed", filters: { processing_status: "failed" }, href: "/inbox?processing=failed" },
];

const CATEGORY_FILTERS: EmailFilters[] = CATEGORY_ORDER.map((category) => ({ category }));

function FigureCard({
  figure,
  value,
  isPending,
  isError,
}: {
  figure: Figure;
  value: number | undefined;
  isPending: boolean;
  isError: boolean;
}) {
  return (
    <Link
      to={figure.href}
      className="panel px-4 py-3.5 transition-colors hover:border-line-strong hover:bg-surface"
    >
      {isPending ? (
        <SkeletonBlock className="h-7 w-14" />
      ) : isError ? (
        <p className="text-md font-semibold text-danger">—</p>
      ) : (
        <p className="text-xl font-semibold tabular">{formatNumber(value ?? 0)}</p>
      )}
      <p className="mt-0.5 text-xs text-muted">{figure.label}</p>
      {isError ? <p className="text-2xs text-danger">Count unavailable</p> : null}
    </Link>
  );
}

function CategoryBar({
  category,
  count,
  total,
  isPending,
  isError,
}: {
  category: Category;
  count: number | undefined;
  total: number;
  isPending: boolean;
  isError: boolean;
}) {
  const value = count ?? 0;
  const percent = total === 0 ? 0 : Math.round((value / total) * 100);
  return (
    <li className="flex items-center gap-3 py-1.5">
      <Link
        to={`/inbox?category=${category}`}
        className="w-36 shrink-0 text-sm hover:text-accent hover:underline sm:w-40"
      >
        {CATEGORY_LABELS[category]}
      </Link>
      <span className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-canvas">
        {!isPending && !isError ? (
          <span className="block h-full rounded-full bg-accent" style={{ width: `${percent}%` }} aria-hidden />
        ) : null}
      </span>
      <span className="w-16 shrink-0 text-right text-sm tabular">
        {isPending ? (
          <SkeletonBlock className="ml-auto h-3 w-10" />
        ) : isError ? (
          <span className="text-danger">—</span>
        ) : (
          <>
            {formatNumber(value)}
            <span className="ml-1 text-2xs text-muted">{percent}%</span>
          </>
        )}
      </span>
    </li>
  );
}

function AttentionRow({ record }: { record: EmailRecord }) {
  return (
    <li className="border-t border-line first:border-t-0">
      <Link
        to={`/emails/${encodeURIComponent(record.email_id)}`}
        state={{ from: "/" }}
        className="block px-4 py-3 hover:bg-canvas sm:px-5"
      >
        <div className="flex items-center gap-2">
          <MonoId>{displayEmailId(record)}</MonoId>
          {isBatchEmail(record) ? <Tag>Batch</Tag> : null}
          <StatusBadge state={getDisplayState(record)} />
          <span
            className="ml-auto shrink-0 text-2xs whitespace-nowrap text-muted"
            title={record.updated_at ?? undefined}
          >
            {formatRelative(record.updated_at)}
          </span>
        </div>
        <p className="mt-1 truncate text-sm" title={record.subject ?? undefined}>
          {record.subject || "No subject"}
        </p>
      </Link>
    </li>
  );
}

export function DashboardPage() {
  useEffect(() => {
    setDocumentTitle("Dashboard");
  }, []);

  const figureCounts = useEmailCounts(FIGURES.map((figure) => figure.filters));
  const categoryCounts = useEmailCounts(CATEGORY_FILTERS);

  // Mismatches and review cases, newest first, straight from the server.
  const mismatches = useEmails({ status: "MISMATCH", limit: ATTENTION_LIMIT });
  const reviews = useEmails({ status: "NEEDS_REVIEW", limit: ATTENTION_LIMIT });

  const totalQuery = figureCounts[0];
  const totalEmails = totalQuery?.data ?? 0;

  const classified = useMemo(
    () => categoryCounts.reduce((sum, query) => sum + (query.data ?? 0), 0),
    [categoryCounts],
  );

  const attention = useMemo(() => {
    const combined = [...(mismatches.data?.items ?? []), ...(reviews.data?.items ?? [])];
    return combined
      .slice()
      .sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? ""))
      .slice(0, ATTENTION_LIMIT);
  }, [mismatches.data, reviews.data]);

  const attentionPending = mismatches.isPending || reviews.isPending;
  const attentionError = mismatches.isError ? mismatches.error : reviews.isError ? reviews.error : null;
  const isEmptyDataset = totalQuery?.isSuccess === true && totalEmails === 0;

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Where the inbox stands right now: how many emails have been checked, and what still needs a person."
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {FIGURES.map((figure, index) => {
          const query = figureCounts[index];
          return (
            <FigureCard
              key={figure.label}
              figure={figure}
              value={query?.data}
              isPending={query?.isPending ?? true}
              isError={query?.isError ?? false}
            />
          );
        })}
      </div>

      {isEmptyDataset ? (
        <div className="mt-6">
          <Panel>
            <EmptyState
              title="No emails yet"
              message="Emails appear here once the organizer inbox has been imported into the backend, or as soon as you upload a dataset yourself."
              action={
                <Link to="/upload">
                  <span className="inline-flex items-center gap-2 rounded-control border border-accent bg-accent px-3 py-1.5 text-sm font-medium text-white">
                    <Upload aria-hidden className="size-4" />
                    Upload
                  </span>
                </Link>
              }
            />
          </Panel>
        </div>
      ) : (
        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <Panel
            title="Category breakdown"
            description={`${formatNumber(classified)} of ${formatNumber(totalEmails)} emails classified`}
          >
            <ul>
              {CATEGORY_ORDER.map((category, index) => {
                const query = categoryCounts[index];
                return (
                  <CategoryBar
                    key={category}
                    category={category}
                    count={query?.data}
                    total={classified}
                    isPending={query?.isPending ?? true}
                    isError={query?.isError ?? false}
                  />
                );
              })}
            </ul>
          </Panel>

          <Panel
            title="Needs attention"
            description="Mismatches and review cases, most recently updated first"
            bodyClassName=""
          >
            {attentionPending ? (
              <div className="flex flex-col gap-3 p-5">
                <SkeletonBlock className="h-3.5 w-2/3" />
                <SkeletonBlock className="h-3.5 w-1/2" />
                <SkeletonBlock className="h-3.5 w-3/5" />
              </div>
            ) : attentionError ? (
              <div className="p-4 sm:p-5">
                <ErrorState
                  title="Could not load this list"
                  message={attentionError.message}
                  onRetry={() => {
                    void mismatches.refetch();
                    void reviews.refetch();
                  }}
                />
              </div>
            ) : attention.length === 0 ? (
              <EmptyState
                title="Nothing waiting"
                message="No mismatches and no review cases right now."
              />
            ) : (
              <ul>
                {attention.map((record) => (
                  <AttentionRow key={record.email_id} record={record} />
                ))}
              </ul>
            )}
          </Panel>
        </div>
      )}
    </>
  );
}
