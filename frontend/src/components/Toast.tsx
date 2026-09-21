/** Small in-house toast system: confirmations and failures, no dependency. */
import { AlertOctagon, CheckCircle2, X } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

type ToastTone = "success" | "error";

interface Toast {
  id: number;
  tone: ToastTone;
  message: string;
}

interface ToastApi {
  success: (message: string) => void;
  error: (message: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const DISMISS_AFTER_MS = 5_000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback(
    (tone: ToastTone, message: string) => {
      const id = nextId.current++;
      setToasts((current) => [...current, { id, tone, message }]);
      window.setTimeout(() => dismiss(id), DISMISS_AFTER_MS);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      success: (message) => push("success", message),
      error: (message) => push("error", message),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="pointer-events-none fixed inset-x-4 bottom-4 z-50 flex flex-col items-end gap-2 sm:inset-x-auto sm:right-5 sm:bottom-5"
      >
        {toasts.map((toast) => {
          const Icon = toast.tone === "success" ? CheckCircle2 : AlertOctagon;
          const tone =
            toast.tone === "success"
              ? "border-success-line bg-success-tint text-success"
              : "border-danger-line bg-danger-tint text-danger";
          return (
            <div
              key={toast.id}
              role="status"
              className={`pointer-events-auto flex w-full max-w-sm items-start gap-2.5 rounded-panel border px-3.5 py-2.5 shadow-sm motion-safe:[animation:sdoc-slide-in_180ms_ease-out] ${tone}`}
            >
              <Icon aria-hidden className="mt-0.5 size-4 shrink-0" />
              <p className="min-w-0 flex-1 text-sm text-text">{toast.message}</p>
              <button
                type="button"
                onClick={() => dismiss(toast.id)}
                className="shrink-0 rounded p-0.5 text-muted hover:text-text"
                aria-label="Dismiss notification"
              >
                <X aria-hidden className="size-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const api = useContext(ToastContext);
  if (!api) throw new Error("useToast() must be used inside <ToastProvider>");
  return api;
}
