/**
 * Document preview panel on the email detail page.
 *
 * One tab per attachment. Opening a tab mints a FRESH signed URL: the backend
 * issues them with a 300 s expiry (database.DEFAULT_SIGNED_URL_EXPIRY_SECONDS),
 * so a URL older than SIGNED_URL_MAX_AGE_MS is discarded rather than reused.
 *
 * `storage_path` is never shown or linked — the documents bucket is private
 * and only a signed URL may reach it (PROJECT_RULES.md §14).
 */
import { ExternalLink, FileText, Paperclip } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, fetchDocumentText, getSignedUrl } from "../api";
import type { AttachmentRecord } from "../types";
import { FILE_KIND_LABEL, fileKind, formatBytes } from "./format";
import { SIGNED_URL_MAX_AGE_MS } from "./labels";
import { Button, EmptyState, ErrorState, Panel, SkeletonBlock } from "./ui";

type PreviewKind = "pdf" | "text" | "unsupported";

function previewKindFor(attachment: AttachmentRecord): PreviewKind {
  const kind = fileKind(attachment.original_filename);
  if (kind === "pdf") return "pdf";
  if (kind === "text") return "text";
  return "unsupported";
}

function tabLabel(attachment: AttachmentRecord): string {
  if (attachment.doc_type === "SI") return "SI";
  if (attachment.doc_type === "BL") return "BL";
  if (attachment.doc_type === "OTHER") return "Other";
  if (attachment.doc_type === "UNREADABLE") return "Unreadable";
  return attachment.original_filename || "File";
}

interface Loaded {
  url: string;
  mintedAt: number;
  text: string | null;
}

export function DocumentPreview({
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
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [frameFailed, setFrameFailed] = useState(false);

  // Guards against a stale response overwriting a newer tab's result.
  const requestSeq = useRef(0);

  const active = attachments.find((a) => a.id === activeId) ?? null;

  useEffect(() => {
    if (activeId === null && attachments.length > 0 && attachments[0]) {
      setActiveId(attachments[0].id);
    }
  }, [attachments, activeId]);

  const open = useCallback(async (attachment: AttachmentRecord) => {
    const seq = ++requestSeq.current;
    setLoading(true);
    setLoadError(null);
    setFrameFailed(false);
    setLoaded(null);

    try {
      const kind = previewKindFor(attachment);
      if (kind === "text") {
        const text = await fetchDocumentText(attachment.storage_path);
        if (seq !== requestSeq.current) return;
        setLoaded({ url: "", mintedAt: Date.now(), text });
      } else {
        const { url } = await getSignedUrl(attachment.storage_path);
        if (seq !== requestSeq.current) return;
        setLoaded({ url, mintedAt: Date.now(), text: null });
      }
    } catch (cause) {
      if (seq !== requestSeq.current) return;
      // Shown once, with the open-in-new-tab fallback. Never retried in a loop.
      setLoadError(cause instanceof ApiError ? cause.message : "The file could not be opened.");
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, []);

  // Load whenever the active attachment changes.
  useEffect(() => {
    if (!active) return;
    void open(active);
  }, [active, open]);

  /** Always mints a new URL if the held one is near its 300 s expiry. */
  const openInNewTab = async (attachment: AttachmentRecord) => {
    try {
      const fresh =
        loaded && loaded.url && Date.now() - loaded.mintedAt < SIGNED_URL_MAX_AGE_MS
          ? loaded.url
          : (await getSignedUrl(attachment.storage_path)).url;
      window.open(fresh, "_blank", "noopener,noreferrer");
    } catch (cause) {
      setLoadError(cause instanceof ApiError ? cause.message : "The file could not be opened.");
    }
  };

  const body = () => {
    if (!active) return null;
    if (loading) return <SkeletonBlock className="h-64 w-full" />;

    if (loadError) {
      return (
        <ErrorState
          title="Could not open this document"
          message={loadError}
          onRetry={() => void open(active)}
        />
      );
    }

    const kind = previewKindFor(active);

    if (kind === "text" && loaded?.text !== null && loaded?.text !== undefined) {
      return (
        // Plain text only: never dangerouslySetInnerHTML.
        <pre className="max-h-[28rem] overflow-auto rounded-control border border-line bg-canvas p-3 font-mono text-xs whitespace-pre-wrap text-text">
          {loaded.text || "This file is empty."}
        </pre>
      );
    }

    if (kind === "pdf" && loaded?.url) {
      if (frameFailed) {
        return (
          <ErrorState
            title="This PDF cannot be shown here"
            message="The storage server refused to embed it. Open it in a new tab instead."
          />
        );
      }
      return (
        <iframe
          key={loaded.url}
          src={loaded.url}
          title={`Preview of ${active.original_filename ?? "document"}`}
          className="h-[28rem] w-full rounded-control border border-line bg-canvas"
          onError={() => setFrameFailed(true)}
        />
      );
    }

    return (
      <div className="rounded-control border border-line bg-canvas px-4 py-8 text-center">
        <FileText aria-hidden className="mx-auto size-6 text-muted" />
        <p className="mt-2 text-sm font-medium">Preview isn't available for this file type</p>
        <p className="mt-0.5 text-xs text-muted">
          {FILE_KIND_LABEL[fileKind(active.original_filename)]} · {formatBytes(active.size_bytes)}
        </p>
        <Button
          variant="secondary"
          icon={ExternalLink}
          className="mt-3"
          onClick={() => void openInNewTab(active)}
        >
          Open file
        </Button>
      </div>
    );
  };

  return (
    <Panel
      title="Documents"
      description="Opened through a short-lived signed link."
      actions={
        active ? (
          <Button icon={ExternalLink} onClick={() => void openInNewTab(active)}>
            Open in new tab
          </Button>
        ) : undefined
      }
    >
      {isPending ? (
        <SkeletonBlock className="h-64 w-full" />
      ) : error ? (
        <ErrorState title="Could not load attachments" message={error} onRetry={onRetry} />
      ) : attachments.length === 0 ? (
        <EmptyState
          icon={Paperclip}
          title="No documents"
          message="This email arrived without any files attached."
        />
      ) : (
        <>
          <div
            role="tablist"
            aria-label="Attachments"
            className="mb-3 flex flex-wrap gap-1 border-b border-line pb-2"
          >
            {attachments.map((attachment) => {
              const selected = attachment.id === activeId;
              return (
                <button
                  key={attachment.id}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  onClick={() => setActiveId(attachment.id)}
                  title={attachment.original_filename ?? undefined}
                  className={`max-w-[12rem] truncate rounded-control px-2.5 py-1 text-xs font-medium transition-colors ${
                    selected ? "bg-accent text-white" : "text-muted hover:bg-canvas hover:text-text"
                  }`}
                >
                  {tabLabel(attachment)}
                </button>
              );
            })}
          </div>

          {active ? (
            <p className="mb-2 truncate text-2xs text-muted" title={active.original_filename ?? undefined}>
              {active.original_filename || "Unnamed file"} · {formatBytes(active.size_bytes)}
            </p>
          ) : null}

          {body()}
        </>
      )}
    </Panel>
  );
}
