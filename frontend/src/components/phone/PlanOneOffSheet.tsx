import { useMemo, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { accountsApi, cardsApi, plannedExpensesApi } from "../../api";
import { fmt, fmtDate } from "../../lib/utils";
import { useDebouncedValue } from "../../lib/useDebouncedValue";
import { maskIfHidden } from "../../store/balanceVisibility";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The checking account the Dashboard's Safety Margin is computed for. */
  accountId: number;
  hidden: boolean;
}

const money = (hidden: boolean, v: string | number) => {
  const n = typeof v === "string" ? parseFloat(v) : v;
  return maskIfHidden(hidden, `${n < 0 ? "−" : ""}${fmt(Math.abs(n))}`);
};

/** Plan a one-off: preview its effect on the Safety Margin (figures come from
 *  the backend, the same calculation the Dashboard uses), then add it to the
 *  plan. A bottom sheet below lg, a centered dialog from lg up. */
export default function PlanOneOffSheet({ open, onOpenChange, accountId, hidden }: Props) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState("");
  const [payWith, setPayWith] = useState("");

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

  const reset = () => { setName(""); setAmount(""); setDate(""); setPayWith(""); };
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

  // The Safety Margin that matters is the account the money leaves: the chosen
  // checking account, or (for a card) the primary checking the card is paid from.
  const previewAccountId = kind === "acct" ? Number(id) : accountId;

  const { data: preview, isFetching, isError, isPlaceholderData } = useQuery<any>({
    queryKey: ["one-off-preview", previewAccountId, debounced],
    queryFn: () => plannedExpensesApi.preview(previewAccountId, debounced),
    enabled: open && ready,
    staleTime: 0,
    gcTime: 0,
    placeholderData: keepPreviousData,
  });

  const add = useMutation({
    // Exactly what was previewed, never the live (possibly newer) form values.
    mutationFn: (body: object) => plannedExpensesApi.create(body),
    onSuccess: () => {
      for (const key of ["budget-snapshot", "planned-expenses", "weekly-digest", "cards-upcoming-due", "monthly-summary", "available-to-spend", "recurring-upcoming", "dashboard-balance-flow", "dashboard-balance-flow-prior", "accounts"]) {
        qc.invalidateQueries({ queryKey: [key] });
      }
      // Every forecast view (quarters, multi-year, risk, scenario, baseline, balance flow).
      qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).startsWith("forecast") });
      close();
    },
  });

  // Add only once the preview on screen is for exactly what the form holds now.
  const previewMatchesForm = JSON.stringify(draft) === JSON.stringify(debounced);
  const canAdd = ready && previewMatchesForm && !!preview && !isFetching && !isPlaceholderData && !isError && !add.isPending;
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
            <div>
              <label className="label" htmlFor="oneoff-pay">Pay with</label>
              <select id="oneoff-pay" className="input min-h-[44px]" value={effectivePay} onChange={(e) => setPayWith(e.target.value)}>
                {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
          </div>

          <div className="mt-4 rounded-xl bg-gray-50 dark:bg-[#333947] p-3 min-h-[92px]" aria-live="polite">
            {!ready && <p className="text-sm text-gray-500 dark:text-gray-400">Enter an amount and a date to see the effect.</p>}
            {ready && isError && <p className="text-sm text-red-600 dark:text-red-400">Couldn't work out the preview. Try again.</p>}
            {ready && !isError && !preview && <p className="text-sm text-gray-500 dark:text-gray-400">Working it out…</p>}
            {ready && preview && (
              <div className={isFetching ? "opacity-60" : ""}>
                <p className="text-xs font-medium text-gray-500 dark:text-gray-400">Safety Margin (this week)</p>
                <p className={`text-2xl font-bold tabular-nums ${tone}`}>
                  {money(hidden, weekly.before)} → {money(hidden, weekly.after)}
                </p>
                <p className="text-sm text-gray-600 dark:text-gray-300">
                  This month: {money(hidden, preview.safety_margin.before)} → {money(hidden, preview.safety_margin.after)}
                </p>
                {preview.card_payment && (
                  <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">
                    Adds {maskIfHidden(hidden, fmt(preview.card_payment.amount))} to {activeCards.find((c) => c.id === preview.card_payment.card_id)?.name ?? "the card"} payment due {fmtDate(preview.card_payment.due)}
                  </p>
                )}
              </div>
            )}
          </div>

          {add.isError && <p className="mt-2 text-sm text-red-600 dark:text-red-400">Couldn't add it. Try again.</p>}
          <div className="mt-4 flex gap-3">
            <button type="button" className="btn-primary flex-1 min-h-[44px]" disabled={!canAdd} onClick={() => add.mutate(debounced)}>
              {add.isPending ? "Adding…" : "Add to plan"}
            </button>
            <button type="button" className="btn-secondary flex-1 min-h-[44px]" onClick={close}>Cancel</button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
