/**
 * Review queue (/review). Server-side status=NEEDS_REVIEW with the same
 * pagination as the inbox.
 */
import { UserCheck } from "lucide-react";
import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";

import type { EmailRecord } from "../types";
import { PageHeader } from "./AppShell";
import { formatAbsolute, formatRelative, setDocumentTitle } from "./format";
import {
  CATEGORY_LABELS,
  PAGE_SIZE,
  REVIEW_REASON_TEXT,
  displayEmailId,
  getDisplayState,
  isBatchEmail,
} from "./labels";
import { Pagination } from "./Pagination";
import { useEmails } from "./queries";
import { EmptyState, ErrorState, MonoId, Panel, SkeletonBlock, StatusBadge, Tag } from "./ui";

function QueueRow({ record, from }: { record: EmailRecord; from: string }) {
  return (
    <li className="border-t border-line first:border-t-0">
      <Link
        to={`/emails/${encodeURIComponent(record.email_id)}`}
        state={{ from }}
        className="block px-4 py-4 hover:bg-canvas sm:px-5"
      >
        <div className="flex flex-wrap items-center gap-2">
          <MonoId>{displayEmailId(record)}</MonoId>
          {isBatchEmail(record) ? <Tag>Batch</Tag> : null}
          <StatusBadge state={getDisplayState(record)} />
          {record.reviewed_at ? <Tag tone="success">Reviewed</Tag> : null}
          <span className="ml-auto text-2xs text-muted" title={formatAbsolute(record.updated_at)}>
            {formatRelative(record.updated_at)}
          </span>
        </div>

        <p className="mt-2 text-sm font-medium">{record.subject || "No subject"}</p>
        <p className="text-xs text-muted">{record.sender || "Unknown sender"}</p>

        <p className="mt-2 text-sm text-text">
          {record.review_reason
            ? REVIEW_REASON_TEXT[record.review_reason]
            : "This email needs a person to look at it."}
        </p>

        {record.category ? (
          <p className="mt-1 text-2xs text-muted">{CATEGORY_LABELS[record.category]}</p>
        ) : null}
      </Link>
    </li>
  );
}

export function ReviewQueue() {
  const [params, setParams] = useSearchParams();

  useEffect(() => {
    setDocumentTitle("Review queue");
  }, []);

  const pageParam = Number.parseInt(params.get("page") ?? "1", 10);
  const page = Number.isFinite(pageParam) && pageParam > 0 ? pageParam : 1;

  const emails = useEmails({
    status: "NEEDS_REVIEW",
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });

  const goToPage = (nextPage: number) => {
    const next = new URLSearchParams(params);
    if (nextPage <= 1) next.delete("page");
    else next.set("page", String(nextPage));
    setParams(next, { replace: false });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const records = emails.data?.items ?? [];
  const from = `/review?${params.toString()}`;

  return (
    <>
      <PageHeader
        title="Review queue"
        description="Emails the pipeline could not decide on its own. Open one to correct the values and re-check it."
      />

      {emails.isError ? (
        <ErrorState
          title="Could not load the review queue"
          message={emails.error.message}
          onRetry={() => void emails.refetch()}
          retrying={emails.isFetching}
        />
      ) : (
        <Panel bodyClassName="">
          {emails.isPending ? (
            <div className="flex flex-col gap-3 p-5">
              <SkeletonBlock className="h-3.5 w-1/3" />
              <SkeletonBlock className="h-3.5 w-2/3" />
              <SkeletonBlock className="h-3.5 w-1/2" />
            </div>
          ) : null}

          {emails.isSuccess && records.length === 0 ? (
            <EmptyState
              icon={UserCheck}
              title="Nothing to review"
              message="No email is currently waiting for a person. Cases appear here when the pipeline cannot decide on its own."
            />
          ) : null}

          {emails.isSuccess && records.length > 0 ? (
            <ul>
              {records.map((record) => (
                <QueueRow key={record.email_id} record={record} from={from} />
              ))}
            </ul>
          ) : null}

          {emails.isSuccess ? (
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              count={records.length}
              total={emails.data.total}
              onPageChange={goToPage}
              busy={emails.isFetching}
            />
          ) : null}
        </Panel>
      )}
    </>
  );
}
