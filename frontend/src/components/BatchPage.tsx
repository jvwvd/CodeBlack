/**
 * Batch progress (/batches/:batchId).
 *
 * Polls GET /api/batches/{batch_id} every 3 s while the batch is still
 * processing and stops once it reports "completed" or "failed". The counts
 * shown are the backend's own done/failed/total — nothing is derived here.
 */
import { AlertOctagon, CheckCircle2, Inbox, Loader2, PackageSearch } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import type { Batch, EmailFilters } from "../types";
import { PageHeader } from "./AppShell";
import { ExportMenu } from "./ExportMenu";
import { formatAbsolute, formatNumber, formatRelative, setDocumentTitle } from "./format";
import { ETA_MIN_DONE, ETA_MIN_ELAPSED_MS } from "./labels";
import { useBatch, useBatchCounts } from "./queries";
import { Banner, Button, EmptyState, ErrorState, MonoId, Panel, SkeletonBlock } from "./ui";
import { Link as RouterLink } from "react-router-dom";


/* ------------------------------------------------------- Speed and ETA */

interface Rate {
  /** Emails per minute, or null while there is not enough evidence. */
  perMinute: number | null;
  /** Milliseconds remaining, or null. */
  remainingMs: number | null;
}

/**
 * Derives throughput from the backend's own done/total/created_at. Returns
 * nulls (rendered as "Estimating…") until at least ETA_MIN_DONE emails are
 * done AND ETA_MIN_ELAPSED_MS has passed, and whenever the arithmetic would
 * be nonsense — a created_at in the future, clock skew, or an absurd ETA.
 */
function computeRate(batch: Batch, now: number): Rate {
  const none: Rate = { perMinute: null, remainingMs: null };
  if (!batch.created_at) return none;

  const started = new Date(batch.created_at).getTime();
  if (!Number.isFinite(started)) return none;

  const elapsedMs = now - started;
  const handled = batch.done + batch.failed;

  if (elapsedMs < ETA_MIN_ELAPSED_MS || handled < ETA_MIN_DONE) return none;
  if (elapsedMs <= 0) return none;

  const perMinute = (handled / elapsedMs) * 60_000;
  if (!Number.isFinite(perMinute) || perMinute <= 0) return none;

  const remaining = batch.total - handled;
  if (remaining <= 0) return { perMinute, remainingMs: 0 };

  const remainingMs = (remaining / handled) * elapsedMs;
  // Anything over 24 h is clock skew or a stalled batch, not a useful estimate.
  if (!Number.isFinite(remainingMs) || remainingMs < 0 || remainingMs > 86_400_000) {
    return { perMinute, remainingMs: null };
  }
  return { perMinute, remainingMs };
}

function formatDuration(ms: number): string {
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours} h ${minutes} min`;
  if (minutes > 0) return `${minutes} min ${seconds} s`;
  return `${seconds} s`;
}

/** Counters shown for one batch, each linking to the inbox pre-filtered. */
const BATCH_COUNTERS: Array<{ label: string; filters: EmailFilters; query: string }> = [
  { label: "Document checks", filters: { category: "BL_COMPARISON" }, query: "category=BL_COMPARISON" },
  { label: "Mismatches", filters: { status: "MISMATCH" }, query: "status=MISMATCH" },
  { label: "Needs review", filters: { status: "NEEDS_REVIEW" }, query: "status=NEEDS_REVIEW" },
  { label: "No mismatch", filters: { status: "OK" }, query: "status=OK" },
];

function BatchCounters({ batchId, live }: { batchId: string; live: boolean }) {
  const counts = useBatchCounts(
    batchId,
    BATCH_COUNTERS.map((counter) => counter.filters),
    live,
  );

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {BATCH_COUNTERS.map((counter, index) => {
        const query = counts[index];
        return (
          <RouterLink
            key={counter.label}
            to={`/inbox?batch_id=${encodeURIComponent(batchId)}&${counter.query}`}
            className="rounded-control border border-line px-3 py-2.5 transition-colors hover:border-line-strong hover:bg-canvas"
          >
            {query?.isPending ? (
              <SkeletonBlock className="h-6 w-10" />
            ) : query?.isError ? (
              <p className="text-md font-semibold text-danger">—</p>
            ) : (
              <p className="text-lg font-semibold tabular">{formatNumber(query?.data ?? 0)}</p>
            )}
            <p className="mt-0.5 text-2xs text-muted">{counter.label}</p>
          </RouterLink>
        );
      })}
    </div>
  );
}

function ProgressBar({ batch, rate, runTimeMs }: { batch: Batch; rate: Rate; runTimeMs: number | null }) {
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

      {batch.status === "processing" ? (
        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-line pt-4 sm:grid-cols-4">
          <div>
            <dt className="text-2xs text-muted">Speed</dt>
            <dd className="text-sm tabular">
              {rate.perMinute === null ? (
                <span className="text-muted">Estimating…</span>
              ) : (
                `${rate.perMinute.toFixed(1)} emails/min`
              )}
            </dd>
          </div>
          <div>
            <dt className="text-2xs text-muted">Time remaining</dt>
            <dd className="text-sm tabular">
              {rate.remainingMs === null ? (
                <span className="text-muted">Estimating…</span>
              ) : (
                <>
                  about {formatDuration(rate.remainingMs)}{" "}
                  <span className="text-2xs text-muted">(estimate)</span>
                </>
              )}
            </dd>
          </div>
        </dl>
      ) : runTimeMs !== null ? (
        <dl className="mt-4 border-t border-line pt-4">
          <dt className="text-2xs text-muted">Total run time</dt>
          <dd className="text-sm tabular">{formatDuration(runTimeMs)}</dd>
        </dl>
      ) : null}
    </div>
  );
}

export function BatchPage() {
  const { batchId = "" } = useParams();
  const batch = useBatch(batchId);
  const processing = batch.data?.status === "processing";
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    setDocumentTitle("Batch progress");
  }, []);

  // Keeps speed/ETA moving between polls. Stops the moment the batch does.
  useEffect(() => {
    if (!processing) return;
    const id = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(id);
  }, [processing]);

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
  const rate = computeRate(data, now);
  const runTimeMs =
    data.created_at && data.finished_at
      ? Math.max(0, new Date(data.finished_at).getTime() - new Date(data.created_at).getTime())
      : null;
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
          <ProgressBar batch={data} rate={rate} runTimeMs={runTimeMs} />
        </Panel>

        <Panel
          title="Results so far"
          description={
            processing
              ? "Counted by the backend, refreshed every 10 seconds."
              : "Final counts for this batch."
          }
        >
          <BatchCounters batchId={data.batch_id} live={processing} />
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
