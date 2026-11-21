import { useMemo, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { accountsApi, cardsApi, plannedExpensesApi } from "../../api";
import { fmt, fmtDate } from "../../lib/utils";
import { useDebouncedValue } from "../../lib/useDebouncedValue";
import { splitEvenly } from "../../lib/splitEvenly";
import { maskIfHidden } from "../../store/balanceVisibility";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The checking account the Dashboard's Safety Margin is computed for. */
  accountId: number;
  hidden: boolean;
}

type Leg = { amount: string; expected_date: string };

const emptyLegs = (n: number): Leg[] => Array.from({ length: n }, () => ({ amount: "", expected_date: "" }));

const money = (hidden: boolean, v: string | number) => {
  const n = typeof v === "string" ? parseFloat(v) : v;
  return maskIfHidden(hidden, `${n < 0 ? "−" : ""}${fmt(Math.abs(n))}`);
};

/** Plan a one-off: preview its effect on the Safety Margin (figures come from
 *  the backend, the same calculation the Dashboard uses), then add it to the
 *  plan. A bottom sheet below lg, a centered dialog from lg up.
 *
 *  Can also split the one-off into 2-6 dated installments (outflow-only, no
 *  funding fields) via the "Split into separate payments" toggle -- either
 *  path shares the same name/account/card logic below. */
export default function PlanOneOffSheet({ open, onOpenChange, accountId, hidden }: Props) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState("");
  const [payWith, setPayWith] = useState("");

  const [split, setSplit] = useState(false);
  const [total, setTotal] = useState("");
  const [count, setCount] = useState(2);
  const [legs, setLegs] = useState<Leg[]>(emptyLegs(2));

  const { data: accounts = [] } = useQuery<any[]>({ queryKey: ["accounts"], queryFn: accountsApi.list, enabled: open });
  const { data: cards = [] } = useQuery<any[]>({ queryKey: ["credit-cards"], queryFn: cardsApi.list, enabled: open });
  const checking = useMemo(() => accounts.filter((a) => a.type === "checking" && a.is_active !== false), [accounts]);
  const activeCards = useMemo(() => cards.filter((c) => c.is_active !== false), [cards]);

  // Card first: bigger one-offs usually go on a card.
  const options = useMemo(
    () => [
      ...activeCards.map((c) => ({ value: `card:${c.id}`, label: c.name })),
      ...checking.map((a) => ({ value: `acct:${a.id}`, label: a.name })),
    ],
    [activeCards, checking],
  );
  // Until the user picks, follow the first option (a card when there is one),
  // which may still be loading.
  const effectivePay = payWith || options[0]?.value || "";

  const reset = () => {
    setName(""); setAmount(""); setDate(""); setPayWith("");
    setSplit(false); setTotal(""); setCount(2); setLegs(emptyLegs(2));
  };
  const close = () => { onOpenChange(false); reset(); };

  const [kind, id] = effectivePay.split(":");
  const draft = useMemo(
    () => ({
      name: name.trim() || "One-off",
      amount,
      expected_date: date,
      ...(kind === "card" ? { card_id: Number(id) } : kind === "acct" ? { account_id: Number(id) } : {}),
    }),
    [name, amount, date, kind, id],
  );
  const debounced = useDebouncedValue(draft, 300);
  const ready = parseFloat(debounced.amount) > 0 && !!debounced.expected_date && !!effectivePay;

  // The installments-mode analogue of `draft`/`debounced`/`ready` above.
  // `total`/`count` are local-only UI state for the "Split evenly" helper --
  // never sent to the backend, which only ever sees `legs`.
  const draftInstallments = useMemo(
    () => ({
      name: name.trim() || "One-off",
      legs: legs.map((l) => ({ amount: l.amount, expected_date: l.expected_date })),
      ...(kind === "card" ? { card_id: Number(id) } : kind === "acct" ? { account_id: Number(id) } : {}),
    }),
    [name, legs, kind, id],
  );
  const debouncedInstallments = useDebouncedValue(draftInstallments, 300);
  const legsReady = legs.length >= 2 && legs.every((l) => parseFloat(l.amount) > 0 && !!l.expected_date);
  const readyInstallments = legsReady && !!effectivePay;

  const activeReady = split ? readyInstallments : ready;

  const changeCount = (delta: number) => {
    const next = Math.min(6, Math.max(2, count + delta));
    setCount(next);
    setLegs((prev) => {
      const trimmed = prev.slice(0, next);
      return trimmed.length < next ? [...trimmed, ...emptyLegs(next - trimmed.length)] : trimmed;
    });
  };

  const updateLeg = (i: number, patch: Partial<Leg>) => {
    setLegs((prev) => prev.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));
  };

  const handleSplitEvenly = () => {
    const t = parseFloat(total);
    if (!(t > 0)) return;
    const amounts = splitEvenly(t, count);
    setLegs(amounts.map((a, i) => ({ amount: a.toFixed(2), expected_date: legs[i]?.expected_date ?? "" })));
  };

  // The Safety Margin that matters is the account the money leaves: the chosen
  // checking account, or (for a card) the primary checking the card is paid from.
  const previewAccountId = kind === "acct" ? Number(id) : accountId;

  const { data: preview, isFetching, isError, isPlaceholderData } = useQuery<any>({
    queryKey: split
      ? ["one-off-preview-installments", previewAccountId, debouncedInstallments]
      : ["one-off-preview", previewAccountId, debounced],
    queryFn: () =>
      split
        ? plannedExpensesApi.previewInstallments(previewAccountId, debouncedInstallments)
        : plannedExpensesApi.preview(previewAccountId, debounced),
    enabled: open && activeReady,
    staleTime: 0,
    gcTime: 0,
    placeholderData: keepPreviousData,
  });

  const invalidateAndClose = () => {
    for (const key of ["budget-snapshot", "planned-expenses", "weekly-digest", "cards-upcoming-due", "monthly-summary", "available-to-spend", "recurring-upcoming", "dashboard-balance-flow", "dashboard-balance-flow-prior", "accounts"]) {
      qc.invalidateQueries({ queryKey: [key] });
    }
    // Every forecast view (quarters, multi-year, risk, scenario, baseline, balance flow).
    qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).startsWith("forecast") });
    close();
  };

  const add = useMutation({
    // Exactly what was previewed, never the live (possibly newer) form values.
    mutationFn: (body: object) => plannedExpensesApi.create(body),
    onSuccess: invalidateAndClose,
  });

  const addInstallments = useMutation({
    mutationFn: (body: object) => plannedExpensesApi.createInstallments(body),
    onSuccess: invalidateAndClose,
  });
  const adding = split ? addInstallments.isPending : add.isPending;

  // Add only once the preview on screen is for exactly what the form holds now.
  const previewMatchesForm = split
    ? JSON.stringify(draftInstallments) === JSON.stringify(debouncedInstallments)
    : JSON.stringify(draft) === JSON.stringify(debounced);
  const canAdd = activeReady && previewMatchesForm && !!preview && !isFetching && !isPlaceholderData && !isError && !adding;
  const weekly = preview?.safety_margin_weekly;
  const tone = weekly && parseFloat(weekly.after) < 0 ? "text-red-600 dark:text-red-400" : "text-gray-900 dark:text-gray-100";

  return (
    <Dialog.Root open={open} onOpenChange={(o) => (o ? onOpenChange(true) : close())}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 z-50" />
        <Dialog.Content
          className="fixed z-50 inset-x-0 bottom-0 max-h-[90vh] overflow-y-auto rounded-t-2xl bg-white dark:bg-[#272c38] p-5 pb-[max(1.25rem,env(safe-area-inset-bottom))] shadow-xl focus:outline-none lg:inset-auto lg:left-1/2 lg:top-1/2 lg:w-full lg:max-w-md lg:-translate-x-1/2 lg:-translate-y-1/2 lg:rounded-2xl"
          onOpenAutoFocus={(e) => e.preventDefault()}
        >
          <Dialog.Title className="text-lg font-bold text-gray-900 dark:text-gray-100">Plan a one-off</Dialog.Title>
          <Dialog.Description className="text-sm text-gray-500 dark:text-gray-400 mb-4">
            See what it does to your Safety Margin before you add it.
          </Dialog.Description>

          <div className="space-y-3">
            <div>
              <label className="label" htmlFor="oneoff-name">What</label>
              <input id="oneoff-name" className="input min-h-[44px]" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Weekend trip" />
            </div>

            <div className="flex items-center gap-2">
              <input
                id="oneoff-split"
                type="checkbox"
                className="h-4 w-4"
                checked={split}
                onChange={(e) => {
                  setSplit(e.target.checked);
                  // A failed submit's error message must not linger once the
                  // user switches modes -- each mutation only ever runs in
                  // one mode, so the other's stale isError would otherwise
                  // show "Couldn't add it" for a submit that never happened
                  // in the newly-selected mode.
                  add.reset();
                  addInstallments.reset();
                }}
              />
              <label htmlFor="oneoff-split" className="text-sm text-gray-700 dark:text-gray-300">
                Split into separate payments
              </label>
            </div>

            {!split && (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label" htmlFor="oneoff-amount">Amount</label>
                  <input id="oneoff-amount" className="input min-h-[44px]" inputMode="decimal" type="number" min="0" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" />
                </div>
                <div>
                  <label className="label" htmlFor="oneoff-date">When</label>
                  <input id="oneoff-date" className="input min-h-[44px]" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
                </div>
              </div>
            )}

            {split && (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3 items-end">
                  <div>
                    <label className="label" htmlFor="oneoff-total">Total</label>
                    <input id="oneoff-total" className="input min-h-[44px]" inputMode="decimal" type="number" min="0" step="0.01" value={total} onChange={(e) => setTotal(e.target.value)} placeholder="0.00" />
                  </div>
                  <div>
                    <span className="label">Payments</span>
                    <div className="flex items-center gap-2 min-h-[44px]">
                      <button type="button" className="btn-secondary min-h-[44px] px-3" onClick={() => changeCount(-1)} disabled={count <= 2}>
                        −
                      </button>
                      <span className="w-6 text-center tabular-nums text-gray-900 dark:text-gray-100">{count}</span>
                      <button type="button" className="btn-secondary min-h-[44px] px-3" onClick={() => changeCount(1)} disabled={count >= 6}>
                        +
                      </button>
                    </div>
                  </div>
                </div>

                <button
                  type="button"
                  className="btn-secondary w-full min-h-[44px]"
                  onClick={handleSplitEvenly}
                  disabled={!(parseFloat(total) > 0)}
                >
                  Split evenly
                </button>

                <div className="space-y-2">
                  {legs.map((leg, i) => (
                    <div key={i} className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="label" htmlFor={`oneoff-leg-amount-${i}`}>{`Payment ${i + 1} amount`}</label>
                        <input
                          id={`oneoff-leg-amount-${i}`}
                          className="input min-h-[44px]"
                          inputMode="decimal"
                          type="number"
                          min="0"
                          step="0.01"
                          value={leg.amount}
                          onChange={(e) => updateLeg(i, { amount: e.target.value })}
                          placeholder="0.00"
                        />
                      </div>
                      <div>
                        <label className="label" htmlFor={`oneoff-leg-date-${i}`}>{`Payment ${i + 1} date`}</label>
                        <input
                          id={`oneoff-leg-date-${i}`}
                          className="input min-h-[44px]"
                          type="date"
                          value={leg.expected_date}
                          onChange={(e) => updateLeg(i, { expected_date: e.target.value })}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div>
              <label className="label" htmlFor="oneoff-pay">Pay with</label>
              <select id="oneoff-pay" className="input min-h-[44px]" value={effectivePay} onChange={(e) => setPayWith(e.target.value)}>
                {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
          </div>

          <div className="mt-4 rounded-xl bg-gray-50 dark:bg-[#333947] p-3 min-h-[92px]" aria-live="polite">
            {!activeReady && <p className="text-sm text-gray-500 dark:text-gray-400">Enter an amount and a date to see the effect.</p>}
            {activeReady && isError && <p className="text-sm text-red-600 dark:text-red-400">Couldn't work out the preview. Try again.</p>}
            {activeReady && !isError && !preview && <p className="text-sm text-gray-500 dark:text-gray-400">Working it out…</p>}
            {activeReady && preview && (
              <div className={isFetching ? "opacity-60" : ""}>
                <p className="text-xs font-medium text-gray-500 dark:text-gray-400">Safety Margin (this week)</p>
                <p className={`text-2xl font-bold tabular-nums ${tone}`}>
                  {money(hidden, weekly.before)} → {money(hidden, weekly.after)}
                </p>
                <p className="text-sm text-gray-600 dark:text-gray-300">
                  This month: {money(hidden, preview.safety_margin.before)} → {money(hidden, preview.safety_margin.after)}
                </p>
                {!split && preview.card_payment && (
                  <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">
                    Adds {maskIfHidden(hidden, fmt(preview.card_payment.amount))} to {activeCards.find((c) => c.id === preview.card_payment.card_id)?.name ?? "the card"} payment due {fmtDate(preview.card_payment.due)}
                  </p>
                )}
                {split && preview.card_payments?.map((cp: { card_id: number; due: string; amount: number | string }, i: number) => (
                  <p key={i} className="mt-1 text-sm text-gray-600 dark:text-gray-300">
                    Adds {maskIfHidden(hidden, fmt(cp.amount))} to {activeCards.find((c) => c.id === cp.card_id)?.name ?? "the card"} payment due {fmtDate(cp.due)}
                  </p>
                ))}
              </div>
            )}
          </div>

          {(add.isError || addInstallments.isError) && <p className="mt-2 text-sm text-red-600 dark:text-red-400">Couldn't add it. Try again.</p>}
          <div className="mt-4 flex gap-3">
            <button
              type="button"
              className="btn-primary flex-1 min-h-[44px]"
              disabled={!canAdd}
              onClick={() => (split ? addInstallments.mutate(debouncedInstallments) : add.mutate(debounced))}
            >
              {adding ? "Adding…" : "Add to plan"}
            </button>
            <button type="button" className="btn-secondary flex-1 min-h-[44px]" onClick={close}>Cancel</button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
