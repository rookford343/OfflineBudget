import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useUnreachable } from "../lib/connection";

export default function ConnectionBanner() {
  const unreachable = useUnreachable();
  const qc = useQueryClient();

  // When the Mac stops answering, drop what earlier loads put on screen so
  // old figures never sit under the banner. resetQueries restores each query
  // to its initial (no data) state; the refetch it triggers fails the same way.
  useEffect(() => {
    if (unreachable) void qc.resetQueries();
  }, [unreachable, qc]);

  if (!unreachable) return null;
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-2 bg-amber-100 px-4 py-2 text-sm text-amber-900 dark:bg-amber-900/40 dark:text-amber-100"
    >
      <span>Can't reach your Mac. It may be asleep or off this Wi-Fi.</span>
      <button
        type="button"
        onClick={() => void qc.refetchQueries()}
        className="rounded-md bg-amber-600 px-3 py-1 font-medium text-white hover:bg-amber-700"
      >
        Retry
      </button>
    </div>
  );
}
