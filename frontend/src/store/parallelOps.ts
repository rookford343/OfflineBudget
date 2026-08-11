import { useEffect, useState } from "react";

const KEY = "parallelOpsEnabled";

export function isParallelOpsEnabled(): boolean {
  return localStorage.getItem(KEY) === "1";
}

export function setParallelOpsEnabled(enabled: boolean): void {
  localStorage.setItem(KEY, enabled ? "1" : "0");
  window.dispatchEvent(new Event("parallel-ops-changed"));
}

export function useParallelOpsEnabled(): boolean {
  const [enabled, setEnabled] = useState(isParallelOpsEnabled());
  useEffect(() => {
    const handler = () => setEnabled(isParallelOpsEnabled());
    window.addEventListener("parallel-ops-changed", handler);
    return () => window.removeEventListener("parallel-ops-changed", handler);
  }, []);
  return enabled;
}
