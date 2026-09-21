/**
 * Attachments for one email. Files open only through a short-lived signed
 * URL fetched on click — `storage_path` is never shown or linked, because the
 * documents bucket is private (PROJECT_RULES.md §14).
 */
import { ExternalLink, FileSpreadsheet, FileText, FileType2, Paperclip } from "lucide-react";
import { useState } from "react";

import { getSignedUrl } from "../api";
import type { AttachmentRecord } from "../types";
import { FILE_KIND_LABEL, fileKind, formatBytes } from "./format";
import { EmptyState, ErrorState, Panel, SkeletonBlock, Tag } from "./ui";

const KIND_ICON = {
  pdf: FileType2,
  word: FileText,
  sheet: FileSpreadsheet,
  text: FileText,
  file: Paperclip,
} as const;

function AttachmentRow({ attachment }: { attachment: AttachmentRecord }) {
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const kind = fileKind(attachment.original_filename);
  const Icon = KIND_ICON[kind];

  const open = async () => {
    setOpening(true);
    setError(null);
    try {
      const { url } = await getSignedUrl(attachment.storage_path);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The document could not be opened.");
    } finally {
      setOpening(false);
    }
  };

  return (
    <li className="border-t border-line first:border-t-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 sm:px-5">
        <Icon aria-hidden className="size-4 shrink-0 text-muted" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm" title={attachment.original_filename ?? undefined}>
            {attachment.original_filename || "Unnamed file"}
          </p>
          <p className="text-2xs text-muted">
            {FILE_KIND_LABEL[kind]} · {formatBytes(attachment.size_bytes)}
          </p>
        </div>
        {attachment.doc_type ? <Tag>{attachment.doc_type}</Tag> : null}
        <button
          type="button"
          onClick={() => void open()}
          disabled={opening}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-control border border-line-strong px-2.5 py-1 text-xs font-medium hover:bg-canvas disabled:opacity-55"
        >
          <ExternalLink aria-hidden className="size-3.5" />
          {opening ? "Opening…" : "Open"}
        </button>
      </div>
      {error ? (
        <p className="px-4 pb-3 text-xs text-danger sm:px-5" role="alert">
          {error}
        </p>
      ) : null}
    </li>
  );
}

export function AttachmentList({
  attachments,
  isPending,
  error,
  onRetry,
}: {
  attachments: AttachmentRecord[];
  isPending: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  return (
    <Panel title="Attachments" description="Files open in a new tab through a short-lived signed link." bodyClassName="">
      {isPending ? (
        <div className="flex flex-col gap-2 px-4 py-4 sm:px-5">
          <SkeletonBlock className="h-3.5 w-56" />
          <SkeletonBlock className="h-3.5 w-44" />
        </div>
      ) : null}

      {error ? (
        <div className="p-4 sm:p-5">
          <ErrorState title="Could not load attachments" message={error} onRetry={onRetry} />
        </div>
      ) : null}

      {!isPending && !error && attachments.length === 0 ? (
        <EmptyState
          icon={Paperclip}
          title="No attachments"
          message="This email arrived without any files attached."
        />
      ) : null}

      {!isPending && !error && attachments.length > 0 ? (
        <ul>
          {attachments.map((attachment) => (
            <AttachmentRow key={attachment.id} attachment={attachment} />
          ))}
        </ul>
      ) : null}
    </Panel>
  );
}
