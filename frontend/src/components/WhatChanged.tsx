import { useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { History, X, ChevronRight, ChevronDown } from "lucide-react";
import { historyApi, type HistoryStatementRow } from "../api";
import { dayLabel, displayHeadline, itemMoney, mathFigures, periodLine, sameFigure, signedMoney } from "../lib/historyMoney";
import { maskMoneyText } from "../lib/maskMoney";
import { useBalancesHidden } from "../store/balanceVisibility";

// The API sends naive UTC ("2026-11-07T12:00:00"); without a zone the browser
// would read it as local time.
function asDate(iso: string): Date {
  const utc = /(Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`;
  return new Date(utc);
}

const clock = (iso: string) => asDate(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
const shortDate = (iso: string) => asDate(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });

const capFirst = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

const riseFall = (delta: string) => delta.startsWith("-")
  ? "text-red-600 dark:text-red-400"
  : "text-emerald-600 dark:text-emerald-400";

function SectionTitle({ children }: { children: string }) {
  return <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-1">{children}</p>;
}

// What opening a row shows: the events behind it and the math lines that moved.
function RowDetail({ row, title, hidden }: { row: HistoryStatementRow; title: string; hidden: boolean }) {
  return (
    <div className="ml-4 mt-1 mb-1 space-y-2 text-xs text-gray-500 dark:text-gray-400">
      {row.events.length > 0 && (
        <div>
          <SectionTitle>What came in</SectionTitle>
          <ul className="space-y-1 list-disc pl-3">
            {row.events.map((k, ki) => (
              <li key={ki}>
                {k.head ? (
                  <>
                    {/* events[0]'s head is what the row's own collapsed headline is built from
                        (see statement_headline in metric_diff.py), so repeating it here says
                        nothing new — only events[1:] ("+ N more") are new information. */}
                    {ki > 0 && <span className="break-words">{maskMoneyText(hidden, capFirst(k.head))}</span>}
                    <ul className="mt-0.5 space-y-0.5 list-none">
                      {k.items.map((it, ii) => (
                        <li key={ii} className="flex justify-between gap-2">
                          <span className="min-w-0 break-words">{maskMoneyText(hidden, it.name)}</span>
                          {it.amount != null && (
                            <span className="tabular-nums whitespace-nowrap">{itemMoney(hidden, it.amount)}</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </>
                ) : (
                  <span className="flex justify-between gap-2">
                    <span className="break-words min-w-0">{maskMoneyText(hidden, capFirst(k.text))}</span>
                    {k.amount != null && (
                      <span className="tabular-nums whitespace-nowrap">{signedMoney(hidden, k.amount, true)}</span>
                    )}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {row.math.length > 0 && (
        <div>
          <SectionTitle>How the number moved</SectionTitle>
          <ul className="space-y-1">
            {row.math.map((m, mi) => (
              <li key={mi}>
                <span className="flex justify-between gap-2">
                  <span className="break-words min-w-0">{maskMoneyText(hidden, m.label)}</span>
                  <span className="tabular-nums text-right">{mathFigures(hidden, m.old, m.new)}</span>
                </span>
                {m.parts.map((p, pi) => (
                  <span key={pi} className="flex justify-between gap-2 pl-4">
                    <span className="break-words min-w-0">{maskMoneyText(hidden, p.label)}</span>
                    <span className="tabular-nums whitespace-nowrap">{signedMoney(hidden, p.delta, true)}</span>
                  </span>
                ))}
              </li>
            ))}
            <li className="flex justify-between gap-2 font-semibold text-gray-800 dark:text-gray-200">
              <span className="break-words min-w-0">{title}</span>
              <span className="tabular-nums text-right">{mathFigures(hidden, row.old_value, row.new_value)}</span>
            </li>
          </ul>
        </div>
      )}
    </div>
  );
}

function Statement({ metricKey, title }: { metricKey: string; title: string }) {
  const hidden = useBalancesHidden();
  const [days, setDays] = useState(7);
  // Open rows are tracked by reading time: the list grows as days load.
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const { data: fetched, isLoading, isError, isFetching } = useQuery({
    queryKey: ["history", metricKey, days],
    queryFn: () => historyApi.statement(metricKey, days).catch((e: any) => {
      if (e?.response?.status === 404) return null; // no readings yet
      throw e;
    }),
    placeholderData: keepPreviousData, // keep the list on screen while more loads
  });
  // A failed load of earlier days drops the query's data; keep the last good list.
  const lastGood = useRef(fetched);
  if (fetched) lastGood.current = fetched;
  const data = fetched ?? lastGood.current;
  const toggle = (k: string) => setExpanded(s => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; });
  const hasDays = (data?.days.length ?? 0) > 0;

  return (
    <div>
      {isLoading && <p className="text-sm text-gray-400">Loading…</p>}
      {isError && !data && <p className="text-sm text-red-500">Couldn't load the history.</p>}
      {!isLoading && !isError && !hasDays && (
        <p className="text-sm text-gray-400">No changes recorded yet.</p>
      )}
      {data && (
        <div className="mb-3">
          <p className="text-2xl font-bold tabular-nums text-gray-900 dark:text-gray-100">
            {signedMoney(hidden, data.current_value, false)}
          </p>
          <p className="text-xs text-gray-400">
            as of {shortDate(data.current_taken_at)}, {clock(data.current_taken_at)}
          </p>
          {data.period_delta != null && data.period_from != null && data.period_since != null && (
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {periodLine(hidden, data.period_delta, data.period_from, shortDate(data.period_since))}
            </p>
          )}
        </div>
      )}
      {data?.days.map(d => (
        <div key={d.day} className="mb-3">
          <div className="flex justify-between gap-2 border-b border-gray-200 dark:border-gray-600 pb-1 text-xs font-semibold text-gray-500 dark:text-gray-400">
            <span>{dayLabel(d.day, new Date())}</span>
            <span className={`tabular-nums ${sameFigure(d.delta, "0") ? "" : riseFall(d.delta)}`}>{signedMoney(hidden, d.delta, true)}</span>
          </div>
          {d.rows.map(r => {
            // Expandable only when opening shows more than the row already says.
            const expandable = r.events.length > 0 || r.math.length > 0;
            const isOpen = expandable && expanded.has(r.taken_at);
            return (
              <div key={r.taken_at} className="py-1.5 border-b border-gray-100 dark:border-gray-700 last:border-b-0">
                <button type="button" disabled={!expandable} onClick={() => toggle(r.taken_at)}
                  aria-expanded={expandable ? isOpen : undefined}
                  className="w-full flex items-start gap-2 text-sm text-left disabled:cursor-default">
                  <span className="flex-1 min-w-0">
                    <span className="block text-xs text-gray-400">{clock(r.taken_at)}</span>
                    <span className="flex items-center gap-1 text-gray-800 dark:text-gray-200">
                      {expandable && (isOpen ? <ChevronDown size={12} className="shrink-0" /> : <ChevronRight size={12} className="shrink-0" />)}
                      <span className="break-words min-w-0">{maskMoneyText(hidden, displayHeadline(r.headline, r.events))}</span>
                    </span>
                  </span>
                  <span className="text-right">
                    <span className={`block tabular-nums whitespace-nowrap font-medium ${riseFall(r.delta)}`}>
                      {signedMoney(hidden, r.delta, true)}
                    </span>
                    <span className="block text-xs tabular-nums whitespace-nowrap text-gray-400">
                      → {signedMoney(hidden, r.new_value, false)}
                    </span>
                  </span>
                </button>
                {isOpen && <RowDetail row={r} title={title} hidden={hidden} />}
              </div>
            );
          })}
        </div>
      ))}
      {isError && data && <p className="text-xs text-red-500 mb-1">Couldn't load earlier days.</p>}
      {data?.has_more && (
        <button type="button" disabled={isFetching} onClick={() => setDays(n => n + 7)} className="btn-ghost text-sm w-full">
          {isFetching ? "Loading…" : "Show earlier days"}
        </button>
      )}
      {hasDays && (
        <p className="mt-3 text-xs text-gray-400">
          Times are when the app noticed the change, not when the charge happened.
        </p>
      )}
    </div>
  );
}

/**
 * "What changed" beside a headline figure: a statement of the figure, newest
 * day first, with a running balance on each reading and the math behind it.
 * Displays what the backend's /history statement route works out; it computes
 * nothing.
 */
export default function WhatChanged({ metric }: { metric: { key: string; title: string } }) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button type="button" aria-label={`What changed in ${metric.title}?`} title="What changed?"
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
              <Dialog.Title className="font-bold text-gray-900 dark:text-gray-100">{metric.title} history</Dialog.Title>
              <Dialog.Close asChild>
                <button aria-label="Close" className="btn-ghost p-1 text-gray-400"><X size={16} /></button>
              </Dialog.Close>
            </div>
            <Dialog.Description className="sr-only">Recent changes to this figure and what caused them</Dialog.Description>
            {open && <Statement metricKey={metric.key} title={metric.title} />}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
