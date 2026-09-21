/**
 * Batch progress (/batches/:batchId).
 *
 * Polls GET /api/batches/{batch_id} every 3 s while the batch is still
 * processing and stops once it reports "completed" or "failed". The counts
 * shown are the backend's own done/failed/total — nothing is derived here.
 */
import { AlertOctagon, CheckCircle2, Inbox, Loader2, PackageSearch } from "lucide-react";
import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";

import type { Batch } from "../types";
import { PageHeader } from "./AppShell";
import { ExportMenu } from "./ExportMenu";
import { formatAbsolute, formatNumber, formatRelative, setDocumentTitle } from "./format";
import { useBatch } from "./queries";
import { Banner, Button, EmptyState, ErrorState, MonoId, Panel, SkeletonBlock } from "./ui";

function ProgressBar({ batch }: { batch: Batch }) {
  const handled = batch.done + batch.failed;
  const percent = batch.total === 0 ? 0 : Math.min(100, Math.round((handled / batch.total) * 100));

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-md font-semibold tabular">
          {formatNumber(batch.done)} of {formatNumber(batch.total)} checked
        </p>
        <p className="text-xs text-muted tabular">{percent}%</p>
      </div>

      <div
        className="mt-2 h-2.5 overflow-hidden rounded-full bg-canvas"
        role="progressbar"
        aria-valuenow={handled}
        aria-valuemin={0}
        aria-valuemax={batch.total}
        aria-label="Batch progress"
      >
        <div className="flex h-full">
          <span
            className="block h-full bg-accent transition-[width] duration-500"
            style={{ width: `${batch.total === 0 ? 0 : (batch.done / batch.total) * 100}%` }}
          />
          <span
            className="block h-full bg-danger transition-[width] duration-500"
            style={{ width: `${batch.total === 0 ? 0 : (batch.failed / batch.total) * 100}%` }}
          />
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
        <div>
          <dt className="text-2xs text-muted">Checked</dt>
          <dd className="text-md font-semibold tabular">{formatNumber(batch.done)}</dd>
        </div>
        <div>
          <dt className="text-2xs text-muted">Failed</dt>
          <dd className={`text-md font-semibold tabular ${batch.failed > 0 ? "text-danger" : ""}`}>
            {formatNumber(batch.failed)}
          </dd>
        </div>
        <div>
          <dt className="text-2xs text-muted">Started</dt>
          <dd className="text-sm" title={formatAbsolute(batch.created_at)}>
            {formatRelative(batch.created_at)}
          </dd>
        </div>
        <div>
          <dt className="text-2xs text-muted">Finished</dt>
          <dd className="text-sm" title={batch.finished_at ? formatAbsolute(batch.finished_at) : undefined}>
            {batch.finished_at ? formatRelative(batch.finished_at) : "Still running"}
          </dd>
        </div>
      </dl>
    </div>
  );
}

export function BatchPage() {
  const { batchId = "" } = useParams();
  const batch = useBatch(batchId);

  useEffect(() => {
    setDocumentTitle("Batch progress");
  }, []);

  if (batch.isPending) {
    return (
      <>
        <PageHeader title="Batch progress" description="Checking every email in this upload." />
        <Panel>
          <SkeletonBlock className="h-6 w-56" />
          <SkeletonBlock className="mt-3 h-2.5 w-full" />
          <SkeletonBlock className="mt-4 h-4 w-72" />
        </Panel>
      </>
    );
  }

  if (batch.isError && batch.error.status === 404) {
    return (
      <>
        <PageHeader title="Batch progress" description="Checking every email in this upload." />
        <Panel>
          <EmptyState
            icon={PackageSearch}
            title="Batch not found"
            message={`No batch with the ID “${batchId}” exists in the backend.`}
            action={
              <Link to="/inbox">
                <Button variant="primary" icon={Inbox}>
                  Back to inbox
                </Button>
              </Link>
            }
          />
        </Panel>
      </>
    );
  }

  if (batch.isError || !batch.data) {
    return (
      <>
        <PageHeader title="Batch progress" description="Checking every email in this upload." />
        <ErrorState
          title="Could not load this batch"
          message={batch.error?.message ?? "The batch could not be loaded."}
          onRetry={() => void batch.refetch()}
          retrying={batch.isFetching}
        />
      </>
    );
  }

  const data = batch.data;
  const processing = data.status === "processing";
  const inboxHref = `/inbox?batch_id=${encodeURIComponent(data.batch_id)}`;

  return (
    <>
      <PageHeader
        title="Batch progress"
        description="Checking every email in this upload."
        actions={
          !processing ? <ExportMenu filters={{ batch_id: data.batch_id }} label="Export this batch" /> : undefined
        }
      />

      <div className="mb-5 flex flex-wrap items-center gap-2">
        <MonoId>{data.batch_id}</MonoId>
      </div>

      <div className="flex flex-col gap-6">
        {processing ? (
          <Banner tone="info" icon={Loader2} title="Processing this batch">
            Emails are being checked a few at a time. This page updates every few seconds.
            <p className="mt-1.5 text-xs text-muted">
              Processing continues on the server if you close this page — you can come back to this
              link at any time.
            </p>
          </Banner>
        ) : data.failed > 0 ? (
          <Banner
            tone="warning"
            icon={AlertOctagon}
            title={`Finished with ${formatNumber(data.failed)} ${data.failed === 1 ? "failure" : "failures"}`}
            actions={
              <Link to={inboxHref}>
                <Button variant="primary" icon={Inbox}>
                  Open these emails in the inbox
                </Button>
              </Link>
            }
          >
            {formatNumber(data.done)} of {formatNumber(data.total)} emails were checked. The rest can be
            retried individually from their detail pages.
          </Banner>
        ) : (
          <Banner
            tone="success"
            icon={CheckCircle2}
            title="Batch complete"
            actions={
              <Link to={inboxHref}>
                <Button variant="primary" icon={Inbox}>
                  Open these emails in the inbox
                </Button>
              </Link>
            }
          >
            All {formatNumber(data.total)} emails in this upload have been checked.
          </Banner>
        )}

        <Panel title="Progress">
          <ProgressBar batch={data} />
        </Panel>

        <Panel title="What happens next">
          <ul className="flex list-disc flex-col gap-1.5 pl-5 text-sm text-text">
            <li>
              Each email is classified, its documents are read, and the SI is compared with the BL —
              the same check every imported email gets.
            </li>
            <li>
              Results appear in the inbox as they finish. You do not have to wait on this page.
            </li>
            <li>
              Anything the pipeline could not decide lands in the review queue with a reason.
            </li>
          </ul>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link to={inboxHref}>
              <Button icon={Inbox}>Open these emails in the inbox</Button>
            </Link>
            <Link to="/review">
              <Button variant="quiet">Go to review queue</Button>
            </Link>
          </div>
        </Panel>
      </div>
    </>
  );
}
