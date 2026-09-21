/**
 * Email detail (/emails/:emailId). Order: result, then evidence, then details.
 *
 * Every verdict on this page comes from getDisplayState(), which reads the
 * backend's processing_status/category/status. Nothing here recomputes one.
 */
import { ChevronDown, ChevronRight, FileQuestion, Inbox } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import type { EmailRecord } from "../types";
import { PageHeader } from "./AppShell";
import { AttachmentList } from "./AttachmentList";
import { ComparisonView } from "./ComparisonView";
import { DocumentPreview } from "./DocumentPreview";
import { formatAbsolute, setDocumentTitle } from "./format";
import {
  CATEGORY_EXPLANATION,
  CATEGORY_LABELS,
  REVIEW_REASON_TEXT,
  displayEmailId,
  getDisplayState,
  isBatchEmail,
} from "./labels";
import { useAttachments, useEmail, useProcessEmail, useRetryEmail } from "./queries";
import { ReviewPanel } from "./ReviewPanel";
import { Timeline } from "./Timeline";
import { useToast } from "./Toast";
import {
  Banner,
  Button,
  DISPLAY_ICON,
  EmptyState,
  ErrorState,
  MonoId,
  Panel,
  SkeletonBlock,
  Tag,
} from "./ui";

const DECIDED_BY_LABEL = { rule: "Decided by rule", llm: "Decided by AI" } as const;

/* ------------------------------------------------------------- Result */

function ResultBanner({
  record,
  onOpenReview,
}: {
  record: EmailRecord;
  onOpenReview: () => void;
}) {
  const toast = useToast();
  const state = getDisplayState(record);
  const Icon = DISPLAY_ICON[state.kind];
  const process = useProcessEmail(record.email_id);
  const retry = useRetryEmail(record.email_id);
  const busy = process.isPending || retry.isPending;

  const run = async (which: "process" | "retry") => {
    const mutation = which === "process" ? process : retry;
    try {
      await mutation.mutateAsync();
      toast.success("Email processed");
    } catch {
      toast.error("Processing failed");
    }
  };

  if (busy || state.kind === "processing") {
    return (
      <Banner tone="info" icon={Icon} title="Processing…">
        Checking documents — this can take up to 20 seconds.
      </Banner>
    );
  }

  switch (state.kind) {
    case "not-verified":
      return (
        <Banner
          tone="neutral"
          icon={Icon}
          title={state.label}
          actions={
            <Button variant="primary" onClick={() => void run("process")}>
              Process email
            </Button>
          }
        >
          This email has not been through the pipeline yet, so there is no result to show.
        </Banner>
      );

    case "failed":
      return (
        <Banner
          tone="danger-outline"
          icon={Icon}
          title={state.label}
          actions={
            <Button variant="primary" onClick={() => void run("retry")}>
              Retry processing
            </Button>
          }
        >
          <p>The pipeline did not finish. Retrying runs it again from the start.</p>
          {record.last_error ? (
            <p className="mt-1.5 font-mono text-xs break-words text-muted">{record.last_error}</p>
          ) : null}
        </Banner>
      );

    case "needs-review":
      return (
        <Banner
          tone="warning"
          icon={Icon}
          title={state.label}
          actions={
            <Button variant="primary" onClick={onOpenReview}>
              Open review form
            </Button>
          }
        >
          {record.review_reason ? REVIEW_REASON_TEXT[record.review_reason] : "This email needs a person to look at it."}
        </Banner>
      );

    case "not-a-check":
      return (
        <Banner tone="muted" icon={Icon} title={state.label}>
          {record.category && record.category !== "BL_COMPARISON"
            ? CATEGORY_EXPLANATION[record.category]
            : "There are no documents to compare on this email."}
        </Banner>
      );

    case "mismatch":
      return (
        <Banner tone="danger" icon={Icon} title={state.label}>
          The draft bill of lading does not match the shipping instruction. The differing fields are
          marked in the table below.
        </Banner>
      );

    case "ok":
    default:
      return (
        <Banner tone="success" icon={Icon} title={state.label}>
          Every compared field on the draft bill of lading matches the shipping instruction.
        </Banner>
      );
  }
}

/* --------------------------------------------------------------- Body */

function EmailBody({ body }: { body: string | null }) {
  const [open, setOpen] = useState(false);
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <section className="panel overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-canvas sm:px-5"
      >
        <span className="text-md font-semibold">Email body</span>
        <Chevron aria-hidden className="size-4 shrink-0 text-muted" />
      </button>
      {open ? (
        <div className="border-t border-line px-4 py-4 sm:px-5">
          {body ? (
            // Plain text only: never dangerouslySetInnerHTML.
            <p className="text-sm whitespace-pre-wrap text-text">{body}</p>
          ) : (
            <p className="text-sm text-muted italic">This email has no body text.</p>
          )}
        </div>
      ) : null}
    </section>
  );
}

/* --------------------------------------------------------------- Page */

export function EmailDetailPage() {
  const { emailId = "" } = useParams();
  const location = useLocation();
  const email = useEmail(emailId);
  const attachments = useAttachments(emailId);
  const [reviewOpen, setReviewOpen] = useState(false);

  const record = email.data;
  const state = record ? getDisplayState(record) : null;

  useEffect(() => {
    setDocumentTitle(record ? displayEmailId(record) : "Email");
  }, [record]);

  // Coming back from the inbox should restore the filters that were active.
  const back = useMemo(() => {
    const from = (location.state as { from?: string } | null)?.from;
    if (from === "/review") return { to: from, label: "Back to review queue" };
    if (from === "/") return { to: from, label: "Back to dashboard" };
    return { to: from ?? "/inbox", label: "Back to inbox" };
  }, [location.state]);

  if (email.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <SkeletonBlock className="h-3 w-24" />
        <SkeletonBlock className="h-7 w-2/3" />
        <SkeletonBlock className="h-20 w-full" />
        <SkeletonBlock className="h-64 w-full" />
      </div>
    );
  }

  if (email.isError && email.error.status === 404) {
    return (
      <Panel>
        <EmptyState
          icon={FileQuestion}
          title="Email not found"
          message={`No email with the ID “${emailId}” exists in the backend.`}
          action={
            <Link to="/inbox">
              <Button variant="primary" icon={Inbox}>
                Back to inbox
              </Button>
            </Link>
          }
        />
      </Panel>
    );
  }

  if (email.isError || !record || !state) {
    return (
      <ErrorState
        title="Could not load this email"
        message={email.error?.message ?? "The email could not be loaded."}
        onRetry={() => void email.refetch()}
        retrying={email.isFetching}
      />
    );
  }

  const showComparison =
    record.category === "BL_COMPARISON" && (record.si !== null || record.bl !== null);
  const showCategoryExplanation =
    record.processing_status === "completed" &&
    record.category !== null &&
    record.category !== "BL_COMPARISON";

  return (
    <>
      <Link
        to={back.to}
        className="mb-4 inline-flex items-center gap-1.5 text-xs font-medium text-accent hover:underline"
      >
        <ChevronRight aria-hidden className="size-3.5 rotate-180" />
        {back.label}
      </Link>

      <PageHeader
        title={record.subject || "No subject"}
        description={record.sender || "Unknown sender"}
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <MonoId>{displayEmailId(record)}</MonoId>
        {isBatchEmail(record) && record.batch_id ? (
          <Link to={`/batches/${encodeURIComponent(record.batch_id)}`} className="hover:underline">
            <Tag>Batch</Tag>
          </Link>
        ) : null}
        {record.category ? <Tag>{CATEGORY_LABELS[record.category]}</Tag> : <Tag>Not classified</Tag>}
        {record.decided_by ? (
          <span className="text-2xs text-muted">{DECIDED_BY_LABEL[record.decided_by]}</span>
        ) : null}
        {record.reviewed_at ? (
          <span className="text-2xs text-muted">Reviewed {formatAbsolute(record.reviewed_at)}</span>
        ) : null}
      </div>

      <div className="mb-6 rounded-panel border border-line bg-surface px-4 py-3.5 sm:px-5">
        <Timeline record={record} />
      </div>

      <div className="flex flex-col gap-6">
        <ResultBanner record={record} onOpenReview={() => setReviewOpen(true)} />

        {showComparison ? (
          // The comparison table stays dominant: it takes the wider column and
          // the preview sits beside it only when there is room (>=1280px).
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] xl:items-start">
            <ComparisonView record={record} />
            <DocumentPreview
              attachments={attachments.data?.items ?? []}
              isPending={attachments.isPending}
              error={attachments.isError ? attachments.error.message : null}
              onRetry={() => void attachments.refetch()}
            />
          </div>
        ) : null}

        {showCategoryExplanation && !showComparison ? (
          <Panel title="No documents to compare">
            <p className="text-sm text-text">
              {record.category && record.category !== "BL_COMPARISON"
                ? CATEGORY_EXPLANATION[record.category]
                : null}
            </p>
          </Panel>
        ) : null}

        {record.notes ? (
          <Panel title="Notes from the backend">
            <p className="text-sm whitespace-pre-wrap text-text">{record.notes}</p>
          </Panel>
        ) : null}

        {record.reviewer_notes ? (
          <Panel title="Reviewer notes">
            <p className="text-sm whitespace-pre-wrap text-text">{record.reviewer_notes}</p>
          </Panel>
        ) : null}

        {state.kind === "needs-review" && reviewOpen ? <ReviewPanel record={record} /> : null}

        {state.kind === "needs-review" && !reviewOpen ? (
          <Panel title="Review">
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="primary" onClick={() => setReviewOpen(true)}>
                Open review form
              </Button>
              <p className="text-xs text-muted">
                Correct the extracted SI and BL values, then ask the backend to check them again.
              </p>
            </div>
          </Panel>
        ) : null}

        {showComparison ? (
          <AttachmentList
            attachments={attachments.data?.items ?? []}
            isPending={attachments.isPending}
            error={attachments.isError ? attachments.error.message : null}
            onRetry={() => void attachments.refetch()}
          />
        ) : (
          <DocumentPreview
            attachments={attachments.data?.items ?? []}
            isPending={attachments.isPending}
            error={attachments.isError ? attachments.error.message : null}
            onRetry={() => void attachments.refetch()}
          />
        )}

        <EmailBody body={record.body} />
      </div>
    </>
  );
}
