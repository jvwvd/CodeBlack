/**
 * Small shared presentation primitives.
 *
 * Every state carries a text label AND an icon, so nothing depends on colour
 * alone and the whole interface stays readable in greyscale.
 */
import {
  AlertOctagon,
  CheckCircle2,
  CircleDashed,
  Inbox,
  Loader2,
  UserCheck,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import type { DisplayKind, DisplayState, Tone } from "./labels";

/* ---------------------------------------------------------------- Tones */

const TONE_BADGE: Record<Tone, string> = {
  neutral: "bg-canvas text-muted border-line",
  info: "bg-info-tint text-info border-info-line",
  danger: "bg-danger-tint text-danger border-danger-line",
  "danger-outline": "bg-surface text-danger border-danger",
  warning: "bg-warning-tint text-warning border-warning-line",
  success: "bg-success-tint text-success border-success-line",
  muted: "bg-canvas text-muted border-line",
};

const TONE_BANNER: Record<Tone, string> = {
  neutral: "bg-canvas border-line",
  info: "bg-info-tint border-info-line",
  danger: "bg-danger-tint border-danger-line",
  "danger-outline": "bg-surface border-danger",
  warning: "bg-warning-tint border-warning-line",
  success: "bg-success-tint border-success-line",
  muted: "bg-canvas border-line",
};

const TONE_TEXT: Record<Tone, string> = {
  neutral: "text-text",
  info: "text-info",
  danger: "text-danger",
  "danger-outline": "text-danger",
  warning: "text-warning",
  success: "text-success",
  muted: "text-muted",
};

export const DISPLAY_ICON: Record<DisplayKind, LucideIcon> = {
  "not-verified": CircleDashed,
  processing: Loader2,
  failed: AlertOctagon,
  "needs-review": UserCheck,
  "not-a-check": Inbox,
  mismatch: XCircle,
  ok: CheckCircle2,
};

/* --------------------------------------------------------------- Badges */

export function StatusBadge({ state, size = "sm" }: { state: DisplayState; size?: "sm" | "md" }) {
  const Icon = DISPLAY_ICON[state.kind];
  const spin = state.kind === "processing" ? "motion-safe:animate-spin" : "";
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-medium whitespace-nowrap ${
        size === "md" ? "text-sm" : "text-2xs"
      } ${TONE_BADGE[state.tone]}`}
    >
      <Icon aria-hidden className={`size-3.5 ${spin}`} />
      {state.label}
    </span>
  );
}

export function Tag({ children, tone = "neutral" }: { children: ReactNode; tone?: Tone }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-2xs font-medium whitespace-nowrap ${TONE_BADGE[tone]}`}
    >
      {children}
    </span>
  );
}

export function MonoId({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`font-mono text-xs text-muted ${className}`}>{children}</span>;
}

/* -------------------------------------------------------------- Banners */

export function Banner({
  tone,
  icon: Icon,
  title,
  children,
  actions,
}: {
  tone: Tone;
  icon: LucideIcon;
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className={`rounded-panel border p-4 sm:p-5 ${TONE_BANNER[tone]}`}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <Icon
            aria-hidden
            className={`mt-0.5 size-5 shrink-0 ${TONE_TEXT[tone]} ${
              Icon === Loader2 ? "motion-safe:animate-spin" : ""
            }`}
          />
          <div className="min-w-0">
            <p className={`text-md font-semibold ${TONE_TEXT[tone]}`}>{title}</p>
            {children ? <div className="mt-1 text-sm text-text">{children}</div> : null}
          </div>
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap gap-2 sm:pl-4">{actions}</div> : null}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------- Buttons */

type ButtonVariant = "primary" | "secondary" | "quiet" | "danger";

const BUTTON_VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-accent text-white border-accent hover:bg-accent-strong hover:border-accent-strong",
  secondary: "bg-surface text-text border-line-strong hover:bg-canvas",
  quiet: "bg-transparent text-accent border-transparent hover:bg-accent-tint",
  danger: "bg-danger text-white border-danger hover:opacity-90",
};

export function Button({
  variant = "secondary",
  icon: Icon,
  busy = false,
  children,
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  icon?: LucideIcon;
  busy?: boolean;
}) {
  return (
    <button
      type="button"
      {...props}
      disabled={props.disabled || busy}
      className={`inline-flex items-center justify-center gap-2 rounded-control border px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-55 ${BUTTON_VARIANT[variant]} ${className}`}
    >
      {busy ? <Loader2 aria-hidden className="size-4 motion-safe:animate-spin" /> : Icon ? <Icon aria-hidden className="size-4" /> : null}
      {children}
    </button>
  );
}

/* --------------------------------------------------------------- States */

export function Panel({
  title,
  description,
  actions,
  children,
  bodyClassName = "p-4 sm:p-5",
}: {
  title?: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  bodyClassName?: string;
}) {
  return (
    <section className="panel overflow-hidden">
      {title ? (
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3 sm:px-5">
          <div>
            <h2 className="text-md font-semibold">{title}</h2>
            {description ? <p className="text-xs text-muted">{description}</p> : null}
          </div>
          {actions}
        </header>
      ) : null}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <p className="flex items-center gap-2 text-sm text-muted">
      <Loader2 aria-hidden className="size-4 motion-safe:animate-spin" />
      {label}
    </p>
  );
}

export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
  retrying = false,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
  retrying?: boolean;
}) {
  return (
    <div className="rounded-panel border border-danger-line bg-danger-tint p-4">
      <div className="flex items-start gap-3">
        <AlertOctagon aria-hidden className="mt-0.5 size-5 shrink-0 text-danger" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-danger">{title}</p>
          <p className="mt-0.5 text-sm text-text">{message}</p>
          {onRetry ? (
            <Button variant="secondary" className="mt-3" onClick={onRetry} busy={retrying}>
              Retry
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function EmptyState({
  icon: Icon = Inbox,
  title,
  message,
  action,
}: {
  icon?: LucideIcon;
  title: string;
  message: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
      <Icon aria-hidden className="size-7 text-muted" />
      <p className="text-md font-semibold">{title}</p>
      <p className="max-w-md text-sm text-muted">{message}</p>
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function SkeletonRows({ rows = 6, columns = 6 }: { rows?: number; columns?: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <tr key={rowIndex} className="border-t border-line">
          {Array.from({ length: columns }).map((__, columnIndex) => (
            <td key={columnIndex} className="px-4 py-3.5">
              <span
                className="block h-3 rounded-full bg-line motion-safe:animate-pulse"
                style={{ width: `${45 + ((rowIndex * 7 + columnIndex * 13) % 45)}%` }}
              />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

export function SkeletonBlock({ className = "h-4 w-40" }: { className?: string }) {
  return <span className={`block rounded bg-line motion-safe:animate-pulse ${className}`} aria-hidden />;
}
