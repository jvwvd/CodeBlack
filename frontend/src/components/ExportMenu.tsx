/**
 * Export menu, shared by the inbox and the batch page.
 *
 * All three formats are produced by the backend
 * (GET /api/emails/export?format=csv|json|submission). The frontend only
 * forwards the active server-side filters and saves the file it gets back —
 * it never builds the organizer submission projection itself, which remains
 * evaluation/build_submission.py's job (PROJECT_RULES.md §13).
 */
import { Check, ChevronDown, Download } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { EmailFilters, ExportFormat } from "../types";
import { downloadBlob } from "./format";
import { EXPORT_OPTIONS } from "./labels";
import { useExportEmails } from "./queries";
import { useToast } from "./Toast";
import { Button } from "./ui";

export function ExportMenu({
  filters,
  label = "Export",
  disabled = false,
}: {
  filters: EmailFilters;
  label?: string;
  disabled?: boolean;
}) {
  const toast = useToast();
  const exportMutation = useExportEmails();
  const [open, setOpen] = useState(false);
  const [running, setRunning] = useState<ExportFormat | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const run = async (format: ExportFormat) => {
    setRunning(format);
    try {
      const file = await exportMutation.mutateAsync({ format, filters });
      downloadBlob(file.blob, file.filename);
      toast.success("Export downloaded");
      setOpen(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "The export could not be downloaded.");
    } finally {
      setRunning(null);
    }
  };

  return (
    <div className="relative" ref={containerRef}>
      <Button
        icon={Download}
        onClick={() => setOpen((current) => !current)}
        busy={running !== null}
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        {label}
        <ChevronDown aria-hidden className="size-3.5" />
      </Button>

      {open ? (
        // Anchored to the button's LEFT edge on small screens, where the header
        // wraps the actions onto their own line at the left gutter: right-
        // anchoring there pushes the panel off the left of the screen. From sm
        // upwards the button sits on the right, so keep right-0. max-w keeps
        // the panel inside the viewport whatever the width.
        <div
          role="menu"
          className="panel absolute left-0 z-20 mt-1.5 w-72 max-w-[calc(100vw-2rem)] overflow-hidden p-1 shadow-md sm:right-0 sm:left-auto"
        >
          {EXPORT_OPTIONS.map((option) => (
            <button
              key={option.format}
              type="button"
              role="menuitem"
              disabled={running !== null}
              onClick={() => void run(option.format)}
              className="flex w-full items-start gap-2 rounded-control px-2.5 py-2 text-left hover:bg-canvas disabled:opacity-55"
            >
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium break-words">{option.label}</span>
                <span className="block text-2xs break-words text-muted">{option.hint}</span>
              </span>
              {running === option.format ? (
                <Check aria-hidden className="mt-0.5 size-4 shrink-0 text-accent" />
              ) : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
