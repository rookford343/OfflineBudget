import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Gift, Plus, Trash2, GripVertical, ChevronDown, ChevronRight, X } from "lucide-react";
import { wishApi, accountsApi, cardsApi } from "../api";
import { fmt, errText } from "../lib/utils";
import { useBalancesHidden, maskIfHidden } from "../store/balanceVisibility";
import { ConfirmDialog } from "../components/ConfirmDialog";
import HowCalculated from "../components/HowCalculated";
import type { Explanation } from "../components/HowCalculated";
import ScenarioEditor from "../components/wish/ScenarioEditor";
import { primaryChecking } from "../lib/accounts";

// ── Shapes (mirrors backend/schemas.py WishPlan* -- every Decimal/date comes
// across as a JSON string, confirmed against the live /openapi.json schema). ──

interface PlanOption {
  option_id: number | null;
  label: string;
  method: string | null;
  monthly_payment: string | null;
  total_cost: string | null;
  error: string | null;
  safe_date: string | null;
  low: string | null;
  low_date: string | null;
  best_date: string | null;
  best_low: string | null;
  shortfall: string | null;
}

interface PlanItem {
  id: number;
  scenario_id: number;
  name: string;
  rank: number;
  status: string;
  price: string;
  trade_in_value: string;
  trade_in_on: string | null;
  target_date: string | null;
  target_ignored: boolean;
  target_low: string | null;
  target_shortfall: string | null;
  plan_option_id: number | null;
  placement_date: string | null;
  fits: boolean;
  options: PlanOption[];
  explain: Explanation | null;
}

interface PlanData {
  cushion: string;
  items: PlanItem[];
}

type CardRow = { id: number; name: string; is_active: boolean };

const METHOD_LABEL: Record<string, string> = {
  full_checking: "Full price · checking",
  full_card: "Full price · card",
  financed: "Financed",
};

function fmtMonD(iso: string): string {
  return new Date(iso + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function money(hidden: boolean, v: string | null | undefined): string {
  return v == null ? "—" : maskIfHidden(hidden, fmt(v));
}

// "Card 0% / 12" for an unpicked card -- the literal word "Card" stands in
// for a specific name until one is actually chosen, same way the method
// select itself reads before a choice is made.
function suggestLabel(method: string, cardId: string, cards: CardRow[], apr: string, months: string): string {
  const cardName = cards.find((c) => String(c.id) === cardId)?.name ?? "Card";
  if (method === "full_checking") return "Checking";
  if (method === "full_card") return cardName;
  const aprNum = apr.trim() === "" ? 0 : parseFloat(apr);
  return `${cardName} ${Number.isFinite(aprNum) ? aprNum : 0}% / ${months.trim()}`.trim();
}

// Names what committing will create, using the chosen option's own label
// (which already carries the card name, auto-suggested or typed) rather
// than re-deriving a card name from an id the plan response doesn't expose.
function commitConfirmText(item: PlanItem): string {
  const dateStr = item.placement_date ? fmtMonD(item.placement_date) : "today";
  const chosen = item.options.find((o) => o.option_id === item.plan_option_id);
  if (!chosen) return `Commit "${item.name}" for ${dateStr}?`;
  if (chosen.method === "full_checking") return `Adds a one-off on ${dateStr} from checking. Commit "${item.name}"?`;
  if (chosen.method === "full_card") return `Adds a one-off on ${dateStr} charged to ${chosen.label}. Commit "${item.name}"?`;
  if (chosen.method === "financed") return `Adds a down payment and monthly payments starting ${dateStr} via ${chosen.label}. Commit "${item.name}"?`;
  return `Commit "${item.name}" for ${dateStr}?`;
}

// Same family TripDetail's invalidateForecast predicate watches, with
// "recurring" added -- a financed wish with no card routes its payments
// through a RecurringItem (wish_lifecycle.commit_wish), and that item's own
// queries weren't in TripDetail's original set.
function invalidateForecastFamily(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({
    predicate: (q) => typeof q.queryKey[0] === "string" && /forecast|planned|snapshot|budget|recurring/i.test(q.queryKey[0] as string),
  });
}

export default function WishList() {
  const qc = useQueryClient();
  const hidden = useBalancesHidden();

  const { data: accounts = [], isLoading: accountsLoading } = useQuery<any[]>({
    queryKey: ["accounts"],
    queryFn: accountsApi.list,
  });
  const accountId: number | undefined = primaryChecking(accounts)?.id;

  const { data: cards = [] } = useQuery<CardRow[]>({ queryKey: ["cards"], queryFn: cardsApi.list });
  // Same filter Forecast.tsx and Recurring.tsx apply before any card select --
  // a closed/inactive card shouldn't be choosable as a new option's funding source.
  const activeCards = cards.filter((c) => c.is_active);

  const { data: plan } = useQuery<PlanData>({
    queryKey: ["wish-plan", accountId],
    queryFn: () => wishApi.plan(accountId),
    enabled: accountId !== undefined,
  });

  const items = plan?.items ?? [];
  const invalidatePlan = () => qc.invalidateQueries({ queryKey: ["wish-plan"] });

  // Cushion input -- fed by the plan's own `cushion` (the already-resolved
  // effective value) rather than a second GET /wish-list/cushion call the
  // page doesn't otherwise need.
  const [cushionInput, setCushionInput] = useState("");
  useEffect(() => { setCushionInput(plan?.cushion ?? ""); }, [plan?.cushion]);
  const setCushionMut = useMutation({
    mutationFn: (cushion: string | null) => wishApi.setCushion(cushion),
    onSuccess: invalidatePlan,
  });
  const saveCushion = () => {
    const trimmed = cushionInput.trim();
    setCushionMut.mutate(trimmed === "" ? null : trimmed);
  };

  // Add wish
  const [wishForm, setWishForm] = useState({ name: "", price: "" });
  const createItemMut = useMutation({
    mutationFn: (data: object) => wishApi.createItem(data),
    onSuccess: () => { invalidatePlan(); setWishForm({ name: "", price: "" }); },
  });
  const submitWish = (e: React.FormEvent) => {
    e.preventDefault();
    const name = wishForm.name.trim();
    if (!name) return;
    createItemMut.mutate({
      name,
      price: wishForm.price.trim() === "" ? 0 : parseFloat(wishForm.price) || 0,
    });
  };

  // Reorder (native HTML5 drag-and-drop, started from each card's handle)
  const [draggingId, setDraggingId] = useState<number | null>(null);
  const reorderMut = useMutation({
    mutationFn: (ids: number[]) => wishApi.reorder(ids),
    onSuccess: invalidatePlan,
  });
  const handleDropOn = (targetId: number) => {
    const fromId = draggingId;
    setDraggingId(null);
    if (fromId == null || fromId === targetId) return;
    const ids = items.map((i) => i.id);
    const from = ids.indexOf(fromId);
    const to = ids.indexOf(targetId);
    if (from === -1 || to === -1) return;
    ids.splice(from, 1);
    ids.splice(to, 0, fromId);
    reorderMut.mutate(ids);
  };

  // Delete (shared confirm dialog, same pattern as Goals.tsx)
  const [deleteItem, setDeleteItem] = useState<PlanItem | null>(null);
  const removeItemMut = useMutation({
    mutationFn: (id: number) => wishApi.removeItem(id),
    onSuccess: () => { invalidatePlan(); setDeleteItem(null); },
  });

  if (!accountsLoading && accountId === undefined) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-2">
          <Gift className="w-5 h-5 text-indigo-500" />
          <h1 className="text-xl font-semibold text-gray-900 dark:text-white">Wish List</h1>
        </div>
        <p className="text-sm text-gray-500 dark:text-gray-400">No checking account found yet.</p>
      </div>
    );
  }

  const stripText = items
    .map((i) => i.status === "committed"
      ? `${i.name} · committed`
      : `${i.name} · ${i.placement_date ? fmtMonD(i.placement_date) : "doesn't fit"}`)
    .join(" → ");

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div className="flex items-center gap-2">
          <Gift className="w-5 h-5 text-indigo-500" />
          <h1 className="text-xl font-semibold text-gray-900 dark:text-white">Wish List</h1>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="label">Cushion</label>
            <input
              type="number" step="0.01" min="0" className="input w-28" placeholder="1000"
              value={cushionInput}
              onChange={(e) => setCushionInput(e.target.value)}
              onBlur={saveCushion}
            />
            {setCushionMut.isError && <p className="text-sm text-red-600 mt-1">{errText(setCushionMut.error)}</p>}
          </div>
          <form onSubmit={submitWish} className="flex items-end gap-2">
            <div>
              <label className="label">New wish</label>
              <input
                className="input w-36" placeholder="Name"
                value={wishForm.name}
                onChange={(e) => setWishForm((f) => ({ ...f, name: e.target.value }))}
                required
              />
            </div>
            <div>
              <label className="label">Price</label>
              <input
                type="number" step="0.01" min="0" className="input w-24" placeholder="0.00"
                value={wishForm.price}
                onChange={(e) => setWishForm((f) => ({ ...f, price: e.target.value }))}
              />
            </div>
            <button type="submit" className="btn-primary">
              <Plus size={16} /> Add wish
            </button>
          </form>
        </div>
      </div>
      {createItemMut.isError && <p className="text-sm text-red-600">{errText(createItemMut.error)}</p>}

      {items.length > 0 && (
        <div className="card text-sm text-gray-600 dark:text-gray-300">{stripText}</div>
      )}
      {reorderMut.isError && <p className="text-sm text-red-600">{errText(reorderMut.error)}</p>}

      <div className="space-y-4">
        {items.map((item) => (
          <ItemCard
            key={item.id}
            item={item}
            cards={activeCards}
            accountId={accountId}
            hidden={hidden}
            isDragging={draggingId === item.id}
            onDragStart={() => setDraggingId(item.id)}
            onDragEnd={() => setDraggingId(null)}
            onDragOverCard={(e) => e.preventDefault()}
            onDropCard={() => handleDropOn(item.id)}
            onDeleteRequest={() => setDeleteItem(item)}
          />
        ))}
        {items.length === 0 && (
          <p className="text-sm text-gray-500 dark:text-gray-400">No wishes yet. Add one above.</p>
        )}
      </div>

      {removeItemMut.isError && <p className="text-sm text-red-600">{errText(removeItemMut.error)}</p>}
      <ConfirmDialog
        open={!!deleteItem}
        onOpenChange={(open) => !open && setDeleteItem(null)}
        icon={Trash2}
        title="Delete this wish?"
        description={`"${deleteItem?.name}" and its options will be permanently removed.`}
        confirmLabel="Delete"
        confirmingLabel="Deleting…"
        isPending={removeItemMut.isPending}
        onConfirm={() => deleteItem && removeItemMut.mutate(deleteItem.id)}
      />
    </div>
  );
}

function ItemCard({
  item, cards, accountId, hidden, isDragging, onDragStart, onDragEnd, onDragOverCard, onDropCard, onDeleteRequest,
}: {
  item: PlanItem;
  cards: CardRow[];
  accountId: number | undefined;
  hidden: boolean;
  isDragging: boolean;
  onDragStart: () => void;
  onDragEnd: () => void;
  onDragOverCard: (e: React.DragEvent) => void;
  onDropCard: () => void;
  onDeleteRequest: () => void;
}) {
  const qc = useQueryClient();
  const committed = item.status === "committed";
  const invalidatePlan = () => qc.invalidateQueries({ queryKey: ["wish-plan"] });

  const [name, setName] = useState(item.name);
  const [price, setPrice] = useState(item.price);
  const [tradeInValue, setTradeInValue] = useState(item.trade_in_value);
  const [tradeInOn, setTradeInOn] = useState(item.trade_in_on ?? "");
  const [targetDate, setTargetDate] = useState(item.target_date ?? "");
  const [expanded, setExpanded] = useState(false);
  const [showAddOption, setShowAddOption] = useState(false);

  const updateItem = useMutation({
    mutationFn: (data: object) => wishApi.updateItem(item.id, data),
    onSuccess: invalidatePlan,
  });
  const createOption = useMutation({
    mutationFn: (data: object) => wishApi.createOption(item.id, data),
    onSuccess: () => { invalidatePlan(); setShowAddOption(false); },
  });
  const removeOption = useMutation({
    mutationFn: (optionId: number) => wishApi.removeOption(item.id, optionId),
    onSuccess: invalidatePlan,
  });
  const commit = useMutation({
    mutationFn: () => wishApi.commit(item.id, accountId),
    onSuccess: () => { invalidatePlan(); invalidateForecastFamily(qc); },
  });
  const uncommit = useMutation({
    mutationFn: () => wishApi.uncommit(item.id),
    onSuccess: () => { invalidatePlan(); invalidateForecastFamily(qc); },
  });

  const saveName = () => {
    const trimmed = name.trim();
    if (!trimmed) { setName(item.name); return; }
    if (trimmed !== item.name) updateItem.mutate({ name: trimmed });
  };
  const savePrice = () => {
    const n = price.trim() === "" ? 0 : parseFloat(price);
    const value = Number.isFinite(n) ? n : 0;
    if (Math.abs(value - parseFloat(item.price)) >= 0.005) updateItem.mutate({ price: value });
    else setPrice(item.price);
  };
  const saveTradeInValue = () => {
    const n = tradeInValue.trim() === "" ? 0 : parseFloat(tradeInValue);
    const value = Number.isFinite(n) ? n : 0;
    if (Math.abs(value - parseFloat(item.trade_in_value)) >= 0.005) updateItem.mutate({ trade_in_value: value });
    else setTradeInValue(item.trade_in_value);
  };
  const saveTradeInOn = () => {
    const value = tradeInOn || null;
    if (value !== (item.trade_in_on ?? null)) updateItem.mutate({ trade_in_on: value });
  };
  const saveTargetDate = () => {
    const value = targetDate || null;
    if (value !== (item.target_date ?? null)) updateItem.mutate({ target_date: value });
  };

  // Add-option form
  const [optForm, setOptForm] = useState({
    method: "full_checking", card_id: "", months: "12", apr: "0", down_payment: "0", label: "", labelTouched: false,
  });
  const suggestedLabel = suggestLabel(optForm.method, optForm.card_id, cards, optForm.apr, optForm.months);
  useEffect(() => {
    if (!optForm.labelTouched) setOptForm((f) => ({ ...f, label: suggestedLabel }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [optForm.method, optForm.card_id, optForm.apr, optForm.months, optForm.labelTouched]);
  const optionReady = optForm.method !== "full_card" || !!optForm.card_id;
  const submitOption = (e: React.FormEvent) => {
    e.preventDefault();
    if (!optionReady) return;
    const data: Record<string, unknown> = {
      label: optForm.label.trim() || suggestedLabel,
      method: optForm.method,
    };
    if (optForm.method === "full_card" || (optForm.method === "financed" && optForm.card_id)) {
      data.card_id = optForm.card_id ? parseInt(optForm.card_id, 10) : null;
    }
    if (optForm.method === "financed") {
      data.months = optForm.months.trim() ? parseInt(optForm.months, 10) : null;
      data.apr = optForm.apr.trim() === "" ? 0 : parseFloat(optForm.apr) || 0;
      data.down_payment = optForm.down_payment.trim() === "" ? 0 : parseFloat(optForm.down_payment) || 0;
    }
    createOption.mutate(data);
  };

  return (
    <div
      className={`card ${isDragging ? "opacity-50" : ""}`}
      onDragOver={onDragOverCard}
      onDrop={onDropCard}
    >
      <div className="flex items-start gap-3">
        <button
          type="button"
          aria-label="Drag to reorder"
          className="cursor-grab text-gray-400 hover:text-gray-600 mt-1.5 shrink-0"
          draggable
          onDragStart={(e) => { e.dataTransfer.effectAllowed = "move"; onDragStart(); }}
          onDragEnd={onDragEnd}
        >
          <GripVertical size={16} />
        </button>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <input
              className="input font-medium flex-1 min-w-[140px]" value={name} disabled={committed}
              onChange={(e) => setName(e.target.value)} onBlur={saveName}
            />
            {committed && <span className="badge-blue">committed</span>}
          </div>

          <div className="flex flex-wrap gap-3 mt-2">
            <div>
              <label className="label">Price</label>
              <input
                type="number" step="0.01" min="0" className="input w-28" disabled={committed}
                value={price} onChange={(e) => setPrice(e.target.value)} onBlur={savePrice}
              />
            </div>
            <div>
              <label className="label">Trade-in value</label>
              <input
                type="number" step="0.01" min="0" className="input w-28" disabled={committed}
                value={tradeInValue} onChange={(e) => setTradeInValue(e.target.value)} onBlur={saveTradeInValue}
              />
            </div>
            <div>
              <label className="label">Trade-in {tradeInOn ? "date" : "(at purchase)"}</label>
              <input
                type="date" className="input w-auto" disabled={committed}
                value={tradeInOn} onChange={(e) => setTradeInOn(e.target.value)} onBlur={saveTradeInOn}
              />
            </div>
            <div>
              <label className="label">I want it on</label>
              <input
                type="date" className="input w-auto" disabled={committed}
                value={targetDate} onChange={(e) => setTargetDate(e.target.value)} onBlur={saveTargetDate}
              />
            </div>
          </div>

          {item.target_date && (
            <div className="mt-1.5 text-xs text-gray-600 dark:text-gray-400 space-y-0.5">
              <p>Your date: {fmtMonD(item.target_date)}</p>
              {item.target_ignored && (
                <p className="text-gray-400">Your date is in the past, so it's ignored</p>
              )}
              {!item.target_ignored && item.target_shortfall != null && parseFloat(item.target_shortfall) > 0 && (
                <p className="text-amber-600">below cushion by {money(hidden, item.target_shortfall)}</p>
              )}
            </div>
          )}

          {updateItem.isError && <p className="text-sm text-red-600 mt-1">{errText(updateItem.error)}</p>}
        </div>

        <div className="flex flex-col items-end gap-2 shrink-0">
          <button
            type="button" className="btn-ghost p-1" aria-label={expanded ? "Collapse" : "Expand"}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </button>
          {committed ? (
            <button
              type="button" className="btn-secondary text-xs" disabled={uncommit.isPending}
              onClick={() => uncommit.mutate()}
            >
              {uncommit.isPending ? "Uncommitting…" : "Uncommit"}
            </button>
          ) : (
            <button
              type="button" className="btn-primary text-xs" disabled={!item.fits || commit.isPending}
              onClick={() => { if (window.confirm(commitConfirmText(item))) commit.mutate(); }}
            >
              {commit.isPending ? "Committing…" : "Commit"}
            </button>
          )}
          <button
            type="button" className="btn-ghost p-1 text-gray-400 hover:text-red-500" disabled={committed}
            aria-label="Delete wish" onClick={onDeleteRequest}
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {commit.isError && <p className="text-sm text-red-600 mt-2">{errText(commit.error)}</p>}
      {uncommit.isError && <p className="text-sm text-red-600 mt-2">{errText(uncommit.error)}</p>}

      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3 mt-3">
        {item.options.map((opt) => {
          const isPlan = item.plan_option_id === opt.option_id;
          return (
            <div
              key={opt.option_id ?? "none"}
              className={`rounded-lg border p-3 text-sm ${isPlan ? "border-indigo-400 bg-indigo-50/50 dark:bg-indigo-950/20" : "border-gray-200 dark:border-gray-700"}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="font-medium truncate">{opt.label}</p>
                  {opt.method && <p className="text-xs text-gray-400">{METHOD_LABEL[opt.method] ?? opt.method}</p>}
                </div>
                {opt.option_id != null && !committed && (
                  <button
                    type="button" aria-label="Remove option" className="text-gray-400 hover:text-red-500 shrink-0"
                    onClick={() => removeOption.mutate(opt.option_id!)}
                  >
                    <X size={14} />
                  </button>
                )}
              </div>

              {opt.error ? (
                <p className="text-red-600 text-xs mt-1.5">{opt.error}</p>
              ) : (
                <>
                  <p className="mt-1.5">
                    {opt.safe_date
                      ? fmtMonD(opt.safe_date)
                      : opt.best_date
                        ? `Doesn't fit — short ${money(hidden, opt.shortfall)}; best day ${fmtMonD(opt.best_date)}`
                        : "Doesn't fit"}
                  </p>
                  {opt.method === "financed" && opt.monthly_payment != null && (
                    <p className="text-xs text-gray-500 mt-0.5">{money(hidden, opt.monthly_payment)}/mo</p>
                  )}
                  {opt.total_cost != null && (
                    <p className="text-xs text-gray-500 mt-0.5">Total {money(hidden, opt.total_cost)}</p>
                  )}
                  {opt.low != null && opt.low_date && (
                    <p className="text-xs text-gray-400 mt-0.5">low {money(hidden, opt.low)} on {fmtMonD(opt.low_date)}</p>
                  )}
                </>
              )}

              <label className="inline-flex items-center gap-1 text-xs mt-2">
                <input
                  type="radio" name={`plan-${item.id}`} disabled={!!opt.error || committed}
                  checked={isPlan}
                  onChange={() => updateItem.mutate({ plan_option_id: opt.option_id })}
                />
                Plan
                {isPlan && item.explain && <HowCalculated title="Safe date" explanations={[item.explain]} />}
              </label>
            </div>
          );
        })}
      </div>

      {!committed && (
        <div className="border-t border-gray-100 dark:border-gray-700 pt-3 mt-3">
          {!showAddOption ? (
            <button type="button" className="btn-ghost text-xs" onClick={() => setShowAddOption(true)}>
              <Plus size={14} /> Add option
            </button>
          ) : (
            <form onSubmit={submitOption} className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-sm items-end">
              <select
                className="input" value={optForm.method}
                onChange={(e) => setOptForm((f) => ({ ...f, method: e.target.value, card_id: "" }))}
              >
                <option value="full_checking">Full amount · checking</option>
                <option value="full_card">Full amount · card</option>
                <option value="financed">Financed</option>
              </select>
              {(optForm.method === "full_card" || optForm.method === "financed") && (
                <select
                  className="input" value={optForm.card_id}
                  onChange={(e) => setOptForm((f) => ({ ...f, card_id: e.target.value }))}
                >
                  <option value="">{optForm.method === "full_card" ? "Card…" : "No card"}</option>
                  {cards.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              )}
              {optForm.method === "financed" && (
                <>
                  <input
                    type="number" min="1" max="84" className="input" placeholder="Months"
                    value={optForm.months} onChange={(e) => setOptForm((f) => ({ ...f, months: e.target.value }))}
                  />
                  <input
                    type="number" min="0" step="0.01" className="input" placeholder="APR %"
                    value={optForm.apr} onChange={(e) => setOptForm((f) => ({ ...f, apr: e.target.value }))}
                  />
                  <input
                    type="number" min="0" step="0.01" className="input" placeholder="Down payment"
                    value={optForm.down_payment} onChange={(e) => setOptForm((f) => ({ ...f, down_payment: e.target.value }))}
                  />
                </>
              )}
              <input
                className="input" placeholder="Label" value={optForm.label}
                onChange={(e) => setOptForm((f) => ({ ...f, label: e.target.value, labelTouched: true }))}
              />
              <div className="flex gap-2 col-span-full">
                <button type="submit" className="btn-primary text-xs" disabled={!optionReady || createOption.isPending}>
                  {createOption.isPending ? "Adding…" : "Add"}
                </button>
                <button type="button" className="btn-secondary text-xs" onClick={() => setShowAddOption(false)}>
                  Cancel
                </button>
              </div>
            </form>
          )}
          {createOption.isError && <p className="text-sm text-red-600 mt-2">{errText(createOption.error)}</p>}
          {removeOption.isError && <p className="text-sm text-red-600 mt-2">{errText(removeOption.error)}</p>}
        </div>
      )}

      {expanded && (
        <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-700 space-y-4">
          <ScenarioEditor scenarioId={item.scenario_id} accountId={accountId} />
        </div>
      )}
    </div>
  );
}
