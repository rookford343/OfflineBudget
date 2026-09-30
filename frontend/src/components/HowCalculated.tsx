import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Info, X, ChevronRight, ChevronDown } from "lucide-react";
import { fmt } from "../lib/utils";
import { useBalancesHidden, maskIfHidden } from "../store/balanceVisibility";

export interface ExplainChild { label: string; amount: string; note?: string | null }
export interface ExplainRow {
  op: "start" | "add" | "subtract" | "divide" | "result";
  label: string; amount: string; note?: string | null; children?: ExplainChild[];
}
export interface Explanation { title: string; result: string; rows: ExplainRow[] }

const SYMBOL: Record<ExplainRow["op"], string> = { start: "", add: "+", subtract: "−", divide: "÷", result: "=" };

/**
 * The receipt behind a calculated number. Each explanation is built by the
 * backend from the same variables as the number and replays to it exactly,
 * so this never re-derives any math, it only displays the steps.
 */
export default function HowCalculated(
  { title, explanations, helpText }:
  { title: string; explanations: (Explanation | null | undefined)[]; helpText?: string },
) {
  const hidden = useBalancesHidden();
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [showHelp, setShowHelp] = useState(false);
  const list = explanations.filter((e): e is Explanation => !!e);
  if (list.length === 0) return null;

  const money = (v: string) => maskIfHidden(hidden, fmt(Math.abs(parseFloat(v))));
  const signed = (v: string) => `${parseFloat(v) < 0 ? "−" : ""}${money(v)}`;
  const toggle = (k: string) => setExpanded(s => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; });

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button type="button" aria-label={`How is ${title} calculated?`} title="How is this calculated?"
          className="text-gray-300 hover:text-indigo-500 dark:text-gray-400 dark:hover:text-indigo-400">
          <Info size={12} />
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 z-50" />
        <Dialog.Content className="fixed inset-0 z-50 flex items-center justify-center p-4 focus:outline-none"
          onOpenAutoFocus={(e) => e.preventDefault()}>
          <div className="card w-full max-w-md max-h-[85vh] overflow-y-auto text-left">
            <div className="flex items-start justify-between mb-3">
              <Dialog.Title className="font-bold text-gray-900 dark:text-gray-100">How {title} is calculated</Dialog.Title>
              <Dialog.Close asChild>
                <button aria-label="Close" className="btn-ghost p-1 text-gray-400"><X size={16} /></button>
              </Dialog.Close>
            </div>
            <Dialog.Description className="sr-only">Step-by-step calculation with your current numbers</Dialog.Description>
            {list.map((ex, ei) => (
              <div key={ei} className={ei > 0 ? "mt-4 pt-4 border-t border-gray-100 dark:border-gray-700" : ""}>
                {list.length > 1 && <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">{ex.title}</p>}
                {ex.rows.map((r, ri) => {
                  const key = `${ei}-${ri}`;
                  const hasKids = (r.children?.length ?? 0) > 0;
                  const isResult = r.op === "result";
                  return (
                    <div key={key} className={`py-1 ${isResult ? "border-t border-gray-200 dark:border-gray-600 mt-1 pt-2" : ""}`}>
                      <button type="button" disabled={!hasKids} onClick={() => hasKids && toggle(key)}
                        aria-expanded={hasKids ? expanded.has(key) : undefined}
                        className="w-full flex items-center gap-2 text-sm text-left disabled:cursor-default">
                        <span className="w-4 text-gray-400 tabular-nums">{SYMBOL[r.op]}</span>
                        <span className={`flex-1 flex items-center gap-1 ${isResult ? "font-bold" : ""}`}>
                          {r.label}
                          {hasKids && (expanded.has(key) ? <ChevronDown size={12} /> : <ChevronRight size={12} />)}
                        </span>
                        <span className={`tabular-nums ${isResult ? "font-bold" : ""}`}>
                          {r.op === "divide" ? parseFloat(r.amount).toFixed(2) : isResult || r.op === "start" ? signed(r.amount) : money(r.amount)}
                        </span>
                      </button>
                      {r.note && <p className="ml-6 text-xs text-gray-400">{r.note}</p>}
                      {hasKids && expanded.has(key) && (
                        <div className="ml-6 mt-1 space-y-0.5">
                          {r.children!.map((c, ci) => (
                            <div key={ci} className="flex justify-between text-xs text-gray-500">
                              <span>{c.label}{c.note ? <span className="text-gray-400"> · {c.note}</span> : null}</span>
                              <span className="tabular-nums">{signed(c.amount)}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ))}
            {helpText && (
              <div className="mt-4 pt-3 border-t border-gray-100 dark:border-gray-700">
                <button type="button" className="text-xs text-indigo-500 hover:underline" aria-expanded={showHelp}
                  onClick={() => setShowHelp(v => !v)}>What does this mean?</button>
                {showHelp && <p className="mt-2 text-xs text-gray-500 whitespace-pre-line">{helpText}</p>}
              </div>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
