type Listener = (message: string) => void;

const listeners = new Set<Listener>();

/** Subscribe to app errors. Returns an unsubscribe function. */
export function onAppError(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function publishAppError(message: string): void {
  listeners.forEach((fn) => fn(message));
}

/**
 * Turn whatever a failed request threw into something worth showing a user.
 *
 * Prefers FastAPI's `detail` (the app's own message, e.g. "Transaction not
 * found") over axios's generic "Request failed with status code 404". A 422
 * carries `detail` as an array of per-field validation objects rather than a
 * string, which would otherwise render as "[object Object]".
 */
export function describeError(error: unknown): string {
  const err = error as {
    response?: { status?: number; data?: { detail?: unknown } };
    message?: string;
    code?: string;
  };

  const detail = err?.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const first = detail[0] as { loc?: unknown[]; msg?: string } | undefined;
    if (first?.msg) {
      const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : undefined;
      return field ? `${field}: ${first.msg}` : first.msg;
    }
  }

  // No response at all means the request never landed -- the backend being
  // down is by far the most common cause in this self-hosted setup, and it
  // deserves a clearer message than axios's "Network Error".
  if (!err?.response) return "Can't reach the server. Is the backend running?";

  const status = err.response.status;
  if (status === 401) return "Your session expired. Please sign in again.";
  if (status === 403) return "You don't have permission to do that.";
  if (status && status >= 500) return `Server error (${status}). Check the backend logs.`;
  return err.message || "Something went wrong.";
}
