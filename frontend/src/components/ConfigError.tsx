/**
 * Shown instead of the app when VITE_API_BASE_URL is missing or empty, so a
 * misconfigured deployment says so plainly rather than failing on every
 * request with a network error.
 */
import { PlugZap } from "lucide-react";

import { LogoMark } from "./Logo";

export function ConfigError() {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-canvas px-4 py-10">
      <div className="panel w-full max-w-lg p-6 sm:p-8">
        <LogoMark size={32} tone="light" />
        <h1 className="mt-4 text-xl font-semibold">The backend address is not configured.</h1>
        <p className="mt-2 text-sm text-muted">
          SDOC needs to know where the backend lives before it can load anything. Set{" "}
          <span className="font-mono text-xs">VITE_API_BASE_URL</span> and restart the app.
        </p>

        <div className="mt-5 rounded-control border border-line bg-canvas p-3">
          <p className="mb-1.5 flex items-center gap-1.5 text-2xs font-medium text-muted">
            <PlugZap aria-hidden className="size-3.5" />
            Create <span className="font-mono">frontend/.env.local</span>
          </p>
          <pre className="overflow-x-auto font-mono text-xs text-text">
VITE_API_BASE_URL=https://sdoc-backend.teamcodeblack9.workers.dev
          </pre>
        </div>

        <p className="mt-4 text-xs text-muted">
          This value is a public address, not a secret. The frontend never holds API keys or
          database credentials.
        </p>
      </div>
    </div>
  );
}
