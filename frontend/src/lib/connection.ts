import { useSyncExternalStore } from "react";

/** True when a request never got an HTTP response: a network failure, or an
 *  axios timeout (ECONNABORTED / ETIMEDOUT). Any status, even 5xx, means the
 *  server answered and is not unreachable. */
export function isUnreachable(error: unknown): boolean {
  const e = error as { isAxiosError?: boolean; response?: unknown } | null;
  return !!e && e.isAxiosError === true && !e.response;
}

let unreachable = false;
const listeners = new Set<() => void>();

export function setUnreachable(value: boolean): void {
  if (unreachable === value) return;
  unreachable = value;
  listeners.forEach((l) => l());
}

export function useUnreachable(): boolean {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => unreachable,
  );
}
