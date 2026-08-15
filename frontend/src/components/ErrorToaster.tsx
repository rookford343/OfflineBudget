import { useEffect, useState } from "react";
import { AlertTriangle, X } from "lucide-react";
import { onAppError } from "../lib/errorBus";

interface Toast {
  id: number;
  message: string;
}

const AUTO_DISMISS_MS = 8000;

/**
 * Renders errors published on the app error bus.
 *
 * Mounted once at the app root and fed by the QueryClient's global caches
 * (see main.tsx), so it covers every mutation and query without each of the
 * ~99 useMutation call sites needing its own onError. Before this, a failed
 * save did nothing visible at all -- the row simply didn't change and the
 * user had no way to tell a no-op from a network failure.
 */
export default function ErrorToaster() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => {
    return onAppError((message) => {
      const id = Date.now() + Math.random();
      setToasts((prev) => {
        // Collapse an identical message already on screen rather than
        // stacking duplicates -- a failed refetch can retry and republish
        // the same error several times in a row.
        if (prev.some((t) => t.message === message)) return prev;
        return [...prev, { id, message }];
      });
      setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), AUTO_DISMISS_MS);
    });
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 max-w-sm" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div
          key={t.id}
          className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 shadow-lg dark:border-red-900/60 dark:bg-red-950/80"
        >
          <AlertTriangle size={15} className="mt-0.5 shrink-0 text-red-600 dark:text-red-400" />
          <p className="flex-1 text-sm text-red-800 dark:text-red-200">{t.message}</p>
          <button
            onClick={() => setToasts((prev) => prev.filter((x) => x.id !== t.id))}
            className="shrink-0 text-red-400 hover:text-red-600 dark:hover:text-red-200"
            aria-label="Dismiss"
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
