/**
 * Upload (/upload). Two modes: a whole dataset or loose files, and a single
 * typed email.
 *
 * The client-side limits here are usability guards so a mistake is caught
 * before a long round trip; they mirror backend/main.py @ 06e4ad4 and are
 * declared once in labels.ts. The backend remains authoritative.
 */
import { FileUp, FolderTree, Mail, Paperclip, Upload, X } from "lucide-react";
import { useEffect, useRef, useState, type DragEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import type { EmailRecord, UploadResponse } from "../types";
import { PageHeader } from "./AppShell";
import { formatBytes, setDocumentTitle } from "./format";
import { UPLOAD_LIMITS, UPLOAD_MISSING_FIELDS_MESSAGE, displayEmailId } from "./labels";
import { useUploadEmail } from "./queries";
import { useToast } from "./Toast";
import { Button, ErrorState, MonoId, Panel } from "./ui";

type Mode = "dataset" | "single";

const ACCEPT = UPLOAD_LIMITS.extensions.join(",");

function extensionOf(name: string): string {
  const index = name.lastIndexOf(".");
  return index === -1 ? "" : name.slice(index).toLowerCase();
}

/* ------------------------------------------------------- Bundle diagram */

function BundleDiagram() {
  return (
    <div className="rounded-control border border-line bg-surface p-3">
      <p className="mb-2 flex items-center gap-1.5 text-2xs font-medium text-muted">
        <FolderTree aria-hidden className="size-3.5" />
        Expected bundle layout
      </p>
      <pre className="overflow-x-auto font-mono text-2xs leading-relaxed text-text">
{`dataset.zip
├── inbox/
│   ├── email_001.json
│   ├── email_002.json
│   └── …
└── attachments/
    ├── email_001_SI.txt
    ├── email_001_BL.txt
    └── …`}
      </pre>
    </div>
  );
}

/* ------------------------------------------------------------ File list */

function FileRows({
  files,
  onRemove,
  disabled,
}: {
  files: File[];
  onRemove: (index: number) => void;
  disabled: boolean;
}) {
  if (files.length === 0) return null;
  const total = files.reduce((sum, file) => sum + file.size, 0);

  return (
    <>
      <ul className="mt-3 flex flex-col gap-1.5">
        {files.map((file, index) => (
          <li
            key={`${file.name}-${file.size}-${index}`}
            className="flex items-center gap-2.5 rounded-control border border-line px-3 py-2"
          >
            <Paperclip aria-hidden className="size-3.5 shrink-0 text-muted" />
            <span className="min-w-0 flex-1 truncate text-sm" title={file.name}>
              {file.name}
            </span>
            <span className="shrink-0 text-2xs text-muted tabular">{formatBytes(file.size)}</span>
            <button
              type="button"
              onClick={() => onRemove(index)}
              disabled={disabled}
              className="shrink-0 rounded p-0.5 text-muted hover:text-danger disabled:opacity-55"
              aria-label={`Remove ${file.name}`}
            >
              <X aria-hidden className="size-4" />
            </button>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-2xs text-muted tabular">
        {files.length} {files.length === 1 ? "file" : "files"} · {formatBytes(total)} total
      </p>
    </>
  );
}

/* --------------------------------------------------------- Result panel */

function CreatedEmails({ emails }: { emails: EmailRecord[] }) {
  return (
    <Panel
      title={`${emails.length} emails created`}
      description="Each one is being checked now."
      bodyClassName=""
    >
      <ul>
        {emails.map((email) => (
          <li key={email.email_id} className="border-t border-line first:border-t-0">
            <Link
              to={`/emails/${encodeURIComponent(email.email_id)}`}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 hover:bg-canvas sm:px-5"
            >
              <MonoId>{displayEmailId(email)}</MonoId>
              <span className="min-w-0 flex-1 truncate text-sm" title={email.subject ?? undefined}>
                {email.subject || "No subject"}
              </span>
              <span className="text-2xs text-accent">Open</span>
            </Link>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

/* ------------------------------------------------------------------ Page */

export function UploadPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const upload = useUploadEmail();
  const inputRef = useRef<HTMLInputElement>(null);

  const [mode, setMode] = useState<Mode>("dataset");
  const [sender, setSender] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [fileError, setFileError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [created, setCreated] = useState<EmailRecord[] | null>(null);

  useEffect(() => {
    setDocumentTitle("Upload");
  }, []);

  const switchMode = (next: Mode) => {
    setMode(next);
    setFiles([]);
    setFileError(null);
    setFormError(null);
    setCreated(null);
  };

  const addFiles = (incoming: FileList | null) => {
    if (!incoming || incoming.length === 0) return;
    const candidates = Array.from(incoming);

    const badType = candidates.filter(
      (file) => !(UPLOAD_LIMITS.extensions as readonly string[]).includes(extensionOf(file.name)),
    );
    if (badType.length > 0) {
      setFileError(
        `${badType.map((file) => file.name).join(", ")} — only ${UPLOAD_LIMITS.extensions.join(", ")} files can be uploaded.`,
      );
      return;
    }

    const tooBig = candidates.filter((file) => file.size > UPLOAD_LIMITS.maxFileBytes);
    if (tooBig.length > 0) {
      setFileError(
        `${tooBig.map((file) => file.name).join(", ")} — each file must be ${UPLOAD_LIMITS.maxFileMb} MB or smaller.`,
      );
      return;
    }

    const accepted = candidates.filter(
      (file) => !files.some((existing) => existing.name === file.name && existing.size === file.size),
    );

    if (files.length + accepted.length > UPLOAD_LIMITS.maxFiles) {
      setFileError(
        `Attach at most ${UPLOAD_LIMITS.maxFiles} files. Remove one before adding another.`,
      );
      return;
    }

    const next = [...files, ...accepted];
    const total = next.reduce((sum, file) => sum + file.size, 0);
    if (total > UPLOAD_LIMITS.maxTotalBytes) {
      setFileError(`The whole upload must be ${UPLOAD_LIMITS.maxTotalMb} MB or smaller.`);
      return;
    }

    setFileError(null);
    setFiles(next);
  };

  const removeFile = (index: number) => {
    setFiles((current) => current.filter((_, i) => i !== index));
    setFileError(null);
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    addFiles(event.dataTransfer.files);
  };

  const handleResult = (result: UploadResponse) => {
    if (result.kind === "batch") {
      toast.success("Dataset uploaded");
      navigate(`/batches/${encodeURIComponent(result.batch_id)}`);
      return;
    }
    if (result.kind === "single") {
      toast.success("Email uploaded");
      navigate(`/emails/${encodeURIComponent(result.email.email_id)}`);
      return;
    }
    toast.success(`${result.emails.length} emails uploaded`);
    setCreated(result.emails);
  };

  const submit = async () => {
    setFormError(null);
    setCreated(null);

    if (mode === "dataset") {
      if (files.length === 0) return setFormError("Choose a dataset bundle or at least one file.");
    } else {
      if (!sender.trim()) return setFormError("Enter the sender's email address.");
      if (!subject.trim()) return setFormError("Enter a subject.");
      if (!body.trim()) return setFormError("Enter the email body.");
    }

    try {
      const result = await upload.mutateAsync(
        mode === "dataset"
          ? { files }
          : { sender: sender.trim(), subject: subject.trim(), body, files },
      );
      handleResult(result);
    } catch (error) {
      // Form contents are deliberately left intact so nothing is retyped.
      const message = error instanceof Error ? error.message : "The upload could not be completed.";
      setFormError(
        message.includes("subject and body are required") ? UPLOAD_MISSING_FIELDS_MESSAGE : message,
      );
    }
  };

  const busy = upload.isPending;

  return (
    <>
      <PageHeader
        title="Upload"
        description="Add a whole dataset, a handful of documents, or one typed email, and run the same check over all of it."
      />

      {/* Segmented control */}
      <div
        role="tablist"
        aria-label="Upload mode"
        className="mb-5 inline-flex rounded-control border border-line bg-surface p-0.5"
      >
        {([
          { value: "dataset", label: "Dataset or files", icon: FolderTree },
          { value: "single", label: "Single email", icon: Mail },
        ] as const).map((option) => (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={mode === option.value}
            disabled={busy}
            onClick={() => switchMode(option.value)}
            className={`inline-flex items-center gap-2 rounded-[6px] px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-55 ${
              mode === option.value ? "bg-accent text-white" : "text-muted hover:text-text"
            }`}
          >
            <option.icon aria-hidden className="size-4" />
            {option.label}
          </button>
        ))}
      </div>

      {/* Stacks below 1100px so the info panel is never clipped. */}
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_19rem] xl:items-start">
        <div className="flex min-w-0 flex-col gap-6">
          {mode === "dataset" ? (
            <Panel title="Dataset or files">
              <div
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
                className={`flex flex-col items-center gap-2 rounded-panel border border-dashed px-4 py-10 text-center transition-colors ${
                  dragging ? "border-accent bg-accent-tint" : "border-line-strong bg-canvas"
                }`}
              >
                <FileUp aria-hidden className="size-6 text-muted" />
                <p className="text-md font-medium">Drop a dataset bundle here</p>
                <p className="max-w-md text-xs text-muted">
                  An organizer-style <span className="font-mono">.zip</span> bundle, individual{" "}
                  <span className="font-mono">.eml</span> files, organizer{" "}
                  <span className="font-mono">.json</span> email files, or a{" "}
                  <span className="font-mono">.zip</span> of those.
                </p>
                <p className="text-2xs text-muted">
                  Up to {UPLOAD_LIMITS.maxFiles} files · {UPLOAD_LIMITS.maxFileMb} MB per file ·{" "}
                  {UPLOAD_LIMITS.maxTotalMb} MB per upload
                </p>
                <Button variant="secondary" onClick={() => inputRef.current?.click()} disabled={busy}>
                  Choose files
                </Button>
              </div>

              <div className="mt-4">
                <BundleDiagram />
              </div>

              {fileError ? (
                <p className="mt-3 text-xs text-danger" role="alert">
                  {fileError}
                </p>
              ) : null}

              <FileRows files={files} onRemove={removeFile} disabled={busy} />
            </Panel>
          ) : (
            <Panel title="New email">
              <div className="flex flex-col gap-4">
                <div>
                  <label className="field-label" htmlFor="upload-sender">
                    Sender
                  </label>
                  <input
                    id="upload-sender"
                    type="email"
                    className="control"
                    placeholder="docs@example.com"
                    autoComplete="off"
                    value={sender}
                    disabled={busy}
                    onChange={(event) => setSender(event.target.value)}
                  />
                </div>

                <div>
                  <label className="field-label" htmlFor="upload-subject">
                    Subject
                  </label>
                  <input
                    id="upload-subject"
                    type="text"
                    className="control"
                    placeholder="Draft BL for checking — OC 0000-00000"
                    value={subject}
                    disabled={busy}
                    onChange={(event) => setSubject(event.target.value)}
                  />
                </div>

                <div>
                  <label className="field-label" htmlFor="upload-body">
                    Body
                  </label>
                  <textarea
                    id="upload-body"
                    className="control min-h-[9rem] resize-y"
                    placeholder="Paste the email text here."
                    value={body}
                    disabled={busy}
                    onChange={(event) => setBody(event.target.value)}
                  />
                </div>

                <div>
                  <span className="field-label">Attachments</span>
                  <div
                    onDragOver={(event) => {
                      event.preventDefault();
                      setDragging(true);
                    }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={onDrop}
                    className={`flex flex-col items-center gap-2 rounded-panel border border-dashed px-4 py-7 text-center transition-colors ${
                      dragging ? "border-accent bg-accent-tint" : "border-line-strong bg-canvas"
                    }`}
                  >
                    <FileUp aria-hidden className="size-5 text-muted" />
                    <p className="text-sm">Drop the SI and BL here</p>
                    <p className="text-2xs text-muted">
                      {UPLOAD_LIMITS.extensions.join(" · ")}
                    </p>
                    <Button variant="secondary" onClick={() => inputRef.current?.click()} disabled={busy}>
                      Choose files
                    </Button>
                  </div>

                  {fileError ? (
                    <p className="mt-2 text-xs text-danger" role="alert">
                      {fileError}
                    </p>
                  ) : null}

                  <FileRows files={files} onRemove={removeFile} disabled={busy} />
                </div>
              </div>
            </Panel>
          )}

          <input
            ref={inputRef}
            type="file"
            multiple
            accept={ACCEPT}
            className="sr-only"
            aria-label="Choose files to upload"
            onChange={(event) => {
              addFiles(event.target.files);
              event.target.value = "";
            }}
          />

          {formError ? <ErrorState title="Could not upload" message={formError} /> : null}

          {created ? <CreatedEmails emails={created} /> : null}

          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary" icon={Upload} onClick={() => void submit()} busy={busy}>
              {mode === "dataset" ? "Upload dataset" : "Upload and check"}
            </Button>
            {busy ? (
              <p className="text-xs text-muted">
                {mode === "dataset"
                  ? "Uploading — large bundles are queued on the server and checked in the background."
                  : "Uploading and checking documents — this can take up to 30 seconds."}
              </p>
            ) : null}
          </div>
        </div>

        <aside className="panel min-w-0 p-4 text-sm">
          <h2 className="text-md font-semibold">
            {mode === "dataset" ? "About dataset uploads" : "About single emails"}
          </h2>
          {mode === "dataset" ? (
            <>
              <p className="mt-2 text-muted">
                A bundle is unpacked on the server and every email inside it is queued. You get a
                batch link straight away and can watch progress there.
              </p>
              <p className="mt-3 text-muted">
                Processing continues even if you close the page. Hundreds or thousands of emails are
                expected — they are checked a few at a time so the pipeline stays stable.
              </p>
            </>
          ) : (
            <>
              <p className="mt-2 text-muted">
                This adds one email with its SI and BL documents and runs the same check as every
                imported email.
              </p>
              <p className="mt-3 text-muted">
                The shipping instruction is the reference; the draft bill of lading is checked
                against it. If a document is missing or cannot be read, the email lands in the
                review queue instead of getting a verdict.
              </p>
            </>
          )}
        </aside>
      </div>
    </>
  );
}
