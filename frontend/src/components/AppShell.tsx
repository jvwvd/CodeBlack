/**
 * App shell: the CodeBlack sidebar (a drawer below 1024px), the backend
 * connection indicator, and the unreachable-backend banner.
 */
import {
  CircleAlert,
  Gauge,
  Inbox,
  Menu,
  Upload,
  UserCheck,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { USE_MOCK } from "../api";
import { Button } from "./ui";
import { useEmailCount, useHealth } from "./queries";

/* -------------------------------------------------------------- Wordmark */

function Wordmark() {
  return (
    <div className="flex items-start gap-2.5">
      {/* Cargo-block mark: a solid square with a square gap punched out. */}
      <svg viewBox="0 0 20 20" aria-hidden className="mt-0.5 size-5 shrink-0">
        <path
          d="M0 0h20v20H0z M9 9h2v2H9z"
          fill="currentColor"
          fillRule="evenodd"
          className="text-on-ink"
        />
      </svg>
      <div className="min-w-0">
        <p className="text-md leading-none text-on-ink">
          <span className="font-normal">Code</span>
          <span className="font-bold">Black</span>
        </p>
        <p className="mt-1.5 text-2xs leading-tight text-on-ink-muted">
          SDOC
          <br />
          Shipping document verification
        </p>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------- Connection */

type Connection = "mock" | "connected" | "unreachable" | "checking";

function useConnection(): Connection {
  const health = useHealth();
  if (USE_MOCK) return "mock";
  if (health.isPending) return "checking";
  return health.isError ? "unreachable" : "connected";
}

const CONNECTION_TEXT: Record<Connection, string> = {
  mock: "Demo data",
  connected: "Connected",
  unreachable: "Backend unreachable",
  checking: "Checking connection",
};

const CONNECTION_DOT: Record<Connection, string> = {
  mock: "bg-warning",
  connected: "bg-success",
  unreachable: "bg-danger",
  checking: "bg-muted",
};

function ConnectionIndicator({ connection }: { connection: Connection }) {
  return (
    <p className="flex items-center gap-2 text-2xs text-on-ink-muted">
      <span aria-hidden className={`size-2 shrink-0 rounded-full ${CONNECTION_DOT[connection]}`} />
      {CONNECTION_TEXT[connection]}
    </p>
  );
}

/* --------------------------------------------------------------- Nav */

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Dashboard", icon: Gauge, end: true },
  { to: "/inbox", label: "Inbox", icon: Inbox },
  { to: "/review", label: "Review queue", icon: UserCheck },
  { to: "/upload", label: "Upload", icon: Upload },
];

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const connection = useConnection();
  // GET /api/emails/count?status=NEEDS_REVIEW — the true total, not a page.
  const reviewQueue = useEmailCount({ status: "NEEDS_REVIEW" });
  const reviewCount = reviewQueue.data ?? null;

  return (
    <div className="flex h-full flex-col bg-ink">
      <div className="px-5 pt-5 pb-6">
        <Wordmark />
      </div>

      <nav aria-label="Main" className="flex-1 px-3">
        <ul className="flex flex-col gap-0.5">
          {NAV_ITEMS.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.end}
                onClick={onNavigate}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 rounded-control px-2.5 py-2 text-sm transition-colors ${
                    isActive
                      ? "bg-accent text-white font-medium"
                      : "text-on-ink-muted hover:bg-ink-soft hover:text-on-ink"
                  }`
                }
              >
                <item.icon aria-hidden className="size-4 shrink-0" />
                <span className="flex-1">{item.label}</span>
                {item.to === "/review" && reviewCount !== null && reviewCount > 0 ? (
                  <span className="rounded-full bg-warning px-1.5 py-px text-2xs font-semibold text-white tabular">
                    {reviewCount}
                  </span>
                ) : null}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <div className="border-t border-ink-line px-5 py-4">
        <p className="mb-1.5 text-2xs text-on-ink-muted">Built by CodeBlack</p>
        <ConnectionIndicator connection={connection} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- Shell */

export function AppShell({ children }: { children: React.ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const location = useLocation();
  const health = useHealth();
  const unreachable = !USE_MOCK && health.isError;

  // Route changes close the drawer so the content is visible after a tap.
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname, location.search]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDrawerOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen]);

  return (
    <div className="min-h-dvh lg:flex">
      {/* Desktop sidebar */}
      <aside className="hidden lg:block lg:h-dvh lg:w-64 lg:shrink-0 lg:sticky lg:top-0">
        <SidebarContent />
      </aside>

      {/* Mobile top bar */}
      <header className="sticky top-0 z-30 flex items-center gap-3 bg-ink px-4 py-3 lg:hidden">
        <button
          type="button"
          onClick={() => setDrawerOpen(true)}
          className="rounded-control p-1.5 text-on-ink hover:bg-ink-soft"
          aria-label="Open navigation menu"
          aria-expanded={drawerOpen}
        >
          <Menu aria-hidden className="size-5" />
        </button>
        <Wordmark />
      </header>

      {/* Mobile drawer */}
      {drawerOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-ink/55"
            onClick={() => setDrawerOpen(false)}
            aria-label="Close navigation menu"
          />
          <div className="absolute inset-y-0 left-0 w-72 max-w-[85vw] motion-safe:[animation:sdoc-slide-in_160ms_ease-out]">
            <button
              type="button"
              onClick={() => setDrawerOpen(false)}
              className="absolute top-3.5 right-3 z-10 rounded-control p-1.5 text-on-ink-muted hover:bg-ink-soft hover:text-on-ink"
              aria-label="Close navigation menu"
            >
              <X aria-hidden className="size-5" />
            </button>
            <SidebarContent onNavigate={() => setDrawerOpen(false)} />
          </div>
        </div>
      ) : null}

      <div className="min-w-0 flex-1">
        {unreachable ? (
          <div className="border-b border-danger-line bg-danger-tint">
            <div className="mx-auto flex max-w-[1200px] flex-wrap items-center gap-3 px-4 py-2.5 sm:px-6">
              <CircleAlert aria-hidden className="size-4 shrink-0 text-danger" />
              <p className="min-w-0 flex-1 text-xs text-text">
                The backend is not responding. Data on screen may be out of date, and actions will fail
                until the connection is restored.
              </p>
              <Button
                variant="secondary"
                onClick={() => void health.refetch()}
                busy={health.isFetching}
                className="text-xs"
              >
                Retry
              </Button>
            </div>
          </div>
        ) : null}

        <main className="mx-auto w-full max-w-[1200px] px-4 py-6 sm:px-6 sm:py-8">{children}</main>
      </div>
    </div>
  );
}

/** Shared page heading: title plus one line of explanation. */
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold">{title}</h1>
        <p className="mt-1 text-sm text-muted">{description}</p>
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </header>
  );
}
