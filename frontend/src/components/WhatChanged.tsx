import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { History, X, ChevronRight, ChevronDown } from "lucide-react";
import { historyApi, type MetricChange } from "../api";
import { fmt } from "../lib/utils";
import { maskMoneyText } from "../lib/maskMoney";
import { useBalancesHidden, maskIfHidden } from "../store/balanceVisibility";

const TRIGGER_WORDS: Record<string, string> = {
  sync: "bank sync", email: "email", manual: "refresh", calc_change: "app update",
};

// The API sends naive UTC ("2026-11-07T12:00:00"); without a zone the browser
// would read it as local time.
function localTime(iso: string): string {
  const utc = /(Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`;
  return new Date(utc).toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

// Display only: the backend's signed decimal string picks the sign, fmt()
// formats the magnitude. No arithmetic on the figure.
function signedMoney(hidden: boolean, v: string | null, plus: boolean): string {
  if (v == null) return "";
  const neg = v.startsWith("-");
  const body = maskIfHidden(hidden, fmt(neg ? v.slice(1) : v));
  return `${neg ? "−" : plus ? "+" : ""}${body}`;
}

function MetricList({ metricKey, title, showTitle }: { metricKey: string; title: string; showTitle: boolean }) {
  const hidden = useBalancesHidden();
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const { data, isLoading, isError } = useQuery({
    queryKey: ["history", metricKey],
    queryFn: () => historyApi.changes(metricKey).catch((e: any) => {
      if (e?.response?.status === 404) return null; // no readings yet
      throw e;
    }),
  });
  const changes: MetricChange[] = data?.changes ?? [];
  const toggle = (i: number) => setExpanded(s => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n; });

  return (
    <div>
      {showTitle && <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">{title}</p>}
      {isLoading && <p className="text-sm text-gray-400">Loading…</p>}
      {isError && <p className="text-sm text-red-500">Couldn't load the history.</p>}
      {!isLoading && !isError && changes.length === 0 && (
        <p className="text-sm text-gray-400">No changes recorded yet.</p>
      )}
      {changes.map((c, i) => {
        const hasCauses = c.causes.length > 0;
        const isOpen = hasCauses && expanded.has(i);
        return (
          <div key={`${c.taken_at}-${i}`} className="py-1.5 border-b border-gray-100 dark:border-gray-700 last:border-b-0">
            <button type="button" disabled={!hasCauses} onClick={() => toggle(i)}
              aria-expanded={hasCauses ? isOpen : undefined}
              className="w-full flex items-start gap-2 text-sm text-left disabled:cursor-default">
              <span className="flex-1 min-w-0">
                <span className="block text-xs text-gray-400">
                  {localTime(c.taken_at)} · {TRIGGER_WORDS[c.trigger] ?? c.trigger}
                </span>
                <span className="flex items-center gap-1 text-gray-800 dark:text-gray-200">
                  {hasCauses && (isOpen ? <ChevronDown size={12} className="shrink-0" /> : <ChevronRight size={12} className="shrink-0" />)}
                  <span className="break-words">{maskMoneyText(hidden, c.summary)}</span>
                </span>
              </span>
              <span className="tabular-nums whitespace-nowrap font-medium text-gray-900 dark:text-gray-100">
                {signedMoney(hidden, c.delta, true)}
              </span>
            </button>
            {isOpen && (
              <div className="ml-4 mt-1 space-y-0.5">
                {c.causes.map((k, ki) => (
                  <div key={ki} className="flex justify-between gap-2 text-xs text-gray-500 dark:text-gray-400">
                    <span className="break-words min-w-0">{maskMoneyText(hidden, k.text)}</span>
                    {k.amount != null && (
                      <span className="tabular-nums whitespace-nowrap">{signedMoney(hidden, k.amount, true)}</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/**
 * "What changed" beside a headline figure: a newest-first list of the
 * readings that moved it, each with a plain-language cause. Displays what the
 * backend's /history route explains; it computes nothing.
 */
export default function WhatChanged({ metrics }: { metrics: { key: string; title: string }[] }) {
  const [open, setOpen] = useState(false);
  if (metrics.length === 0) return null;
  const title = metrics[0].title;
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button type="button" aria-label={`What changed in ${title}?`} title="What changed?"
          className="text-gray-300 hover:text-indigo-500 dark:text-gray-400 dark:hover:text-indigo-400">
          <History size={12} />
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 z-50" />
        <Dialog.Content className="fixed inset-0 z-50 flex items-center justify-center p-4 focus:outline-none"
          onOpenAutoFocus={(e) => e.preventDefault()}>
          <div className="card w-full max-w-md max-h-[85vh] overflow-y-auto text-left">
            <div className="flex items-start justify-between mb-3">
              <Dialog.Title className="font-bold text-gray-900 dark:text-gray-100">What changed in {title}</Dialog.Title>
              <Dialog.Close asChild>
                <button aria-label="Close" className="btn-ghost p-1 text-gray-400"><X size={16} /></button>
              </Dialog.Close>
            </div>
            <Dialog.Description className="sr-only">Recent changes to this figure and what caused them</Dialog.Description>
            {open && metrics.map((m, i) => (
              <div key={m.key} className={i > 0 ? "mt-4 pt-4 border-t border-gray-100 dark:border-gray-700" : ""}>
                <MetricList metricKey={m.key} title={m.title} showTitle={metrics.length > 1} />
              </div>
            ))}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
