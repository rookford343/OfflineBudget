import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, X } from "lucide-react";
import { adventuresApi, cardsApi } from "../../api";
import { errText, fmt } from "../../lib/utils";
import { maskIfHidden, useBalancesHidden } from "../../store/balanceVisibility";
import HowCalculated, { type Explanation } from "../HowCalculated";
import {
  CATEGORY_LABEL, type Category, PRICING_HINT, type Payment, type TripDetailData, type TripItem, type WalletRow, pts, shortDate,
} from "./types";

const CATEGORIES: Category[] = ["getting_there", "staying", "daily", "before", "while_there"];

function ItemRow({ trip, item, programs, onChange }: {
  trip: TripDetailData; item: TripItem; programs: WalletRow[]; onChange: (d: TripDetailData) => void;
}) {
  const hidden = useBalancesHidden();
  const [err, setErr] = useState<string | null>(null);
  const done = trip.status === "done";
  const save = useMutation({
    mutationFn: (data: object) => adventuresApi.updateItem(trip.id, item.id, data),
    onSuccess: (d) => { setErr(null); onChange(d); },
    onError: (e: any) => setErr(errText(e)),
  });
  const remove = useMutation({
    mutationFn: (fromTemplate: boolean) => adventuresApi.removeItem(trip.id, item.id, fromTemplate),
    onSuccess: onChange,
  });
  const setPayment = (payment: Payment) => {
    if (payment === "cash") return save.mutate({ payment });
    if (!item.points_program_id || !item.points_price) {
      // Need a program and price first: switch locally by sending both with a sensible default.
      const first = programs.find((p) => p.kind !== "bank") ?? programs[0];
      return save.mutate({ payment, points_program_id: item.points_program_id ?? first?.id, points_price: item.points_price || 1 });
    }
    save.mutate({ payment });
  };
  const blurNum = (field: string, current: string | number | null) => (e: React.FocusEvent<HTMLInputElement>) => {
    const v = e.target.value.trim();
    if (v === String(current ?? "")) return;
    if (v !== "") {
      const n = Number(v);
      if (!Number.isFinite(n)) { setErr("Enter a number"); return; }
      if ((field === "points_price" || field === "transfer_points") && !Number.isInteger(n)) { setErr("Enter a number"); return; }
    }
    save.mutate({ [field]: v === "" ? null : v });
  };
  return (
    <div className={`py-2 border-b border-gray-50 dark:border-gray-800 ${item.is_paid ? "opacity-60" : ""}`}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium text-gray-900 dark:text-gray-100 w-44 truncate" title={item.name}>{item.name}</span>
        <div className="inline-flex rounded-md border border-gray-200 dark:border-gray-700 overflow-hidden text-xs" role="group" aria-label={`${item.name} payment`}>
          {(["cash", "points", "mix"] as Payment[]).map((p) => (
            <button key={p} disabled={done || item.is_auto_buffer} onClick={() => setPayment(p)}
              className={`px-2 py-0.5 ${item.payment === p ? "bg-indigo-600 text-white" : "text-gray-600 dark:text-gray-300"}`}>{p}</button>
          ))}
        </div>
        <label className="text-xs text-gray-500 flex items-center gap-1">$
          <input key={`unit-${item.unit_cash}`} className="input py-0.5 w-24 text-xs" disabled={done} defaultValue={item.unit_cash ?? ""}
            placeholder={item.is_auto_buffer ? "10% auto" : "0"} onBlur={blurNum("unit_cash", item.unit_cash)} />
          {PRICING_HINT[item.pricing] && <span>{PRICING_HINT[item.pricing]} ×{item.multiplier}</span>}
        </label>
        {item.payment !== "cash" && (
          <>
            <select className="input py-0.5 text-xs" disabled={done} value={item.points_program_id ?? ""}
              onChange={(e) => save.mutate({ points_program_id: Number(e.target.value) })}>
              {programs.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <label className="text-xs text-gray-500 flex items-center gap-1">pts
              <input key={`points-${item.points_price}`} className="input py-0.5 w-24 text-xs" disabled={done} defaultValue={item.points_price ?? ""}
                onBlur={blurNum("points_price", item.points_price)} /></label>
            <label className="text-xs text-gray-500 flex items-center gap-1">taxes $
              <input key={`copay-${item.cash_copay}`} className="input py-0.5 w-20 text-xs" disabled={done} defaultValue={item.cash_copay}
                onBlur={blurNum("cash_copay", item.cash_copay)} /></label>
            {item.payment === "mix" && (
              <label className="text-xs text-gray-500 flex items-center gap-1">+ cash $
                <input key={`mix-${item.mix_cash}`} className="input py-0.5 w-20 text-xs" disabled={done} defaultValue={item.mix_cash ?? ""}
                  onBlur={blurNum("mix_cash", item.mix_cash)} /></label>
            )}
            {(item.points_price ?? 0) > 1 ? (
              item.value_cpp && <span className="badge-blue">{item.value_cpp}¢/pt</span>
            ) : (
              <span className="text-xs text-gray-400">enter points price</span>
            )}
          </>
        )}
        <span className="ml-auto font-semibold tabular-nums">{maskIfHidden(hidden, fmt(item.cash_owed))}</span>
        {trip.status === "committed" && (
          <label className="text-xs flex items-center gap-1"><input type="checkbox" checked={item.is_paid}
            onChange={(e) => save.mutate({ is_paid: e.target.checked })} /> paid</label>
        )}
        {!done && (
          <button aria-label={`Remove ${item.name}`} className="text-gray-400 hover:text-red-500"
            onClick={() => remove.mutate(window.confirm(`Also remove "${item.name}" from your checklist template for future trips?`))}>
            <X size={14} />
          </button>
        )}
      </div>
      {item.transfer_from_program_id && item.transfer_points ? (
        <p className="text-xs text-indigo-600 dark:text-indigo-300 mt-1">
          Transfer {maskIfHidden(hidden, pts(item.transfer_points))} from {programs.find((p) => p.id === item.transfer_from_program_id)?.name}
          {!done && <button className="ml-2 underline" onClick={() => save.mutate({ transfer_from_program_id: null, transfer_points: null })}>detach</button>}
        </p>
      ) : item.suggestion && !done ? (
        <p className="text-xs text-amber-700 dark:text-amber-300 mt-1">
          Short on points: transfer {maskIfHidden(hidden, pts(item.suggestion.source_points))} {item.suggestion.from_program_name} →{" "}
          {maskIfHidden(hidden, pts(item.suggestion.partner_points))}{item.suggestion.bonus_pct ? ` (+${parseFloat(item.suggestion.bonus_pct)}% bonus)` : ""}
          <button className="ml-2 underline" onClick={() => save.mutate({
            transfer_from_program_id: item.suggestion!.from_program_id, transfer_points: item.suggestion!.source_points,
          })}>attach</button>
        </p>
      ) : null}
      {err && <p className="text-xs text-red-500 mt-1">{err}</p>}
    </div>
  );
}

function AddItem({ trip, category, onChange }: { trip: TripDetailData; category: Category; onChange: (d: TripDetailData) => void }) {
  const [name, setName] = useState("");
  const add = useMutation({
    mutationFn: () => adventuresApi.addItem(trip.id, { category, name }),
    onSuccess: (d) => { setName(""); onChange(d); },
  });
  if (trip.status === "done") return null;
  return (
    <div className="flex gap-2 mt-2">
      <input className="input py-0.5 text-xs flex-1" placeholder="Add an item…" value={name} onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && name.trim() && add.mutate()} />
      <button className="btn-secondary text-xs" disabled={!name.trim()} onClick={() => add.mutate()}>Add</button>
    </div>
  );
}

export default function TripDetail({ tripId, onClose }: { tripId: number; onClose: () => void }) {
  const qc = useQueryClient();
  const hidden = useBalancesHidden();
  const key = ["adventures", "trip", tripId];
  const { data: trip } = useQuery<TripDetailData>({ queryKey: key, queryFn: () => adventuresApi.trip(tripId) });
  const { data: programs = [] } = useQuery<WalletRow[]>({ queryKey: ["adventures", "wallet"], queryFn: adventuresApi.wallet });
  const { data: cards = [] } = useQuery<any[]>({ queryKey: ["credit-cards"], queryFn: cardsApi.list });
  const [err, setErr] = useState<string | null>(null);
  // The real query keys that cover anything Adventures can move -- Forecast
  // (forecast-quarters, forecast-multi-year, forecast-risk, ...), the
  // Planned One-Offs list (planned-expenses, planned-transfers), and the
  // Dashboard budget snapshot (budget-snapshot, budget-overview, ...).
  // A literal ["forecast"] key never matched any of those and invalidated
  // nothing; this predicate catches the family by name instead.
  const invalidateForecast = () =>
    qc.invalidateQueries({
      predicate: (q) => typeof q.queryKey[0] === "string" && /forecast|planned|snapshot|budget/i.test(q.queryKey[0] as string),
    });
  const onChange = (d: TripDetailData) => {
    qc.setQueryData(key, d);
    qc.invalidateQueries({ queryKey: ["adventures", "trips"] });
    qc.invalidateQueries({ queryKey: ["adventures", "wallet"] });
    invalidateForecast();
    qc.invalidateQueries({ queryKey: ["goals"] });
  };
  const act = useMutation({
    mutationFn: (fn: () => Promise<TripDetailData>) => fn(),
    onSuccess: (d) => { setErr(null); onChange(d); },
    onError: (e: any) => setErr(errText(e, "Something went wrong")),
  });
  const del = useMutation({
    mutationFn: () => adventuresApi.removeTrip(tripId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["adventures"] }); invalidateForecast(); onClose(); },
  });
  if (!trip) return <div className="card text-sm text-gray-400">Loading…</div>;

  const owing = trip.items.filter((i) => parseFloat(i.cash_owed) > 0 && !i.is_paid).length;
  const finish = async () => {
    setErr(null);
    let plan: Record<string, number>;
    try {
      plan = await adventuresApi.finishPlan(trip.id);
    } catch (e: any) {
      setErr(errText(e, "Couldn't finish"));
      return;
    }
    const lines = Object.entries(plan).map(([pid, d]) =>
      `${programs.find((p) => String(p.id) === pid)?.name}: ${maskIfHidden(hidden, `${d > 0 ? "+" : ""}${pts(d)}`)}`);
    let msg = `Finish this trip and update balances?\n\n${lines.join("\n") || "No points change."}`;
    if (owing > 0) {
      msg += `\n\n${owing} unpaid one-off${owing === 1 ? "" : "s"} stay on the Forecast. Settle them on the Planned page when they're charged.`;
    }
    if (!window.confirm(msg)) return;
    try {
      onChange(await adventuresApi.finish(trip.id, {}));
    } catch (e: any) {
      const msg = errText(e, "Couldn't finish");
      if (window.confirm(`${msg}\n\nFinish anyway and allow a negative balance?`)) {
        try {
          onChange(await adventuresApi.finish(trip.id, { force: true }));
        } catch (e2: any) {
          setErr(errText(e2, "Couldn't finish"));
        }
      }
    }
  };
  const cashExplain: Explanation = {
    title: "Trip cash", result: trip.cash_total,
    rows: [
      ...trip.items.filter((i) => parseFloat(i.cash_owed) > 0).map((i, idx) => ({
        op: (idx === 0 ? "start" : "add") as "start" | "add", label: i.name, amount: i.cash_owed,
      })),
      { op: "result" as const, label: "Trip cash", amount: trip.cash_total },
    ],
  };

  return (
    <div className="card space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-bold text-gray-900 dark:text-gray-100">{trip.name}</h3>
          <p className="text-xs text-gray-500">{trip.destination ? `${trip.destination} · ` : ""}{shortDate(trip.start_date)} – {shortDate(trip.end_date)}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <label>Start <input type="date" className="input py-0.5 text-xs" disabled={trip.status === "done"} defaultValue={trip.start_date}
            onBlur={(e) => e.target.value !== trip.start_date && act.mutate(() => adventuresApi.updateTrip(trip.id, { start_date: e.target.value }))} /></label>
          <label>End <input type="date" className="input py-0.5 text-xs" disabled={trip.status === "done"} defaultValue={trip.end_date}
            onBlur={(e) => e.target.value !== trip.end_date && act.mutate(() => adventuresApi.updateTrip(trip.id, { end_date: e.target.value }))} /></label>
          <label>Travelers <input type="number" min={1} className="input py-0.5 w-14 text-xs" disabled={trip.status === "done"} defaultValue={trip.travelers}
            onBlur={(e) => Number(e.target.value) !== trip.travelers && act.mutate(() => adventuresApi.updateTrip(trip.id, { travelers: Number(e.target.value) }))} /></label>
          <label>Charge to <select className="input py-0.5 text-xs" disabled={trip.status === "done"} value={trip.default_card_id ?? ""}
            onChange={(e) => act.mutate(() => adventuresApi.updateTrip(trip.id, { default_card_id: e.target.value ? Number(e.target.value) : null }))}>
            <option value="">Checking</option>{cards.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
          {trip.status === "planning" && (
            <button className="btn-primary text-xs" title={`Adds ${owing} one-off${owing === 1 ? "" : "s"} to the Forecast`}
              onClick={() => window.confirm(`Commit to forecast? This adds ${owing} planned one-off${owing === 1 ? "" : "s"} to the Forecast.`) && act.mutate(() => adventuresApi.commit(trip.id))}>
              Commit to forecast</button>
          )}
          {trip.status === "committed" && (
            <>
              <button className="btn-secondary text-xs" onClick={() => act.mutate(() => adventuresApi.uncommit(trip.id))}>Back to planning</button>
              <button className="btn-primary text-xs" onClick={finish}>Done</button>
            </>
          )}
          <button aria-label="Delete trip" className="text-gray-400 hover:text-red-500"
            onClick={() => window.confirm(`Delete "${trip.name}"? Its unpaid one-offs leave the Forecast too.`) && del.mutate()}><Trash2 size={16} /></button>
          <button aria-label="Close trip" className="text-gray-400 hover:text-gray-600" onClick={onClose}><X size={18} /></button>
        </div>
      </div>
      {err && <p className="text-sm text-red-500">{err}</p>}

      <div className="flex flex-wrap items-center gap-4 text-sm rounded-lg bg-gray-50 dark:bg-gray-800/60 px-3 py-2 sticky top-0 z-10">
        <span className="flex items-center gap-1">Cash <strong className="tabular-nums">{maskIfHidden(hidden, fmt(trip.cash_total))}</strong>
          <HowCalculated title="Trip cash" explanations={[cashExplain]} /></span>
        <span>Remaining <strong className="tabular-nums">{maskIfHidden(hidden, fmt(trip.cash_remaining))}</strong></span>
        {trip.points_summary.map((s) => (
          <span key={s.program_id} className={s.shortfall > 0 ? "text-red-600" : ""}>
            {s.name}: {maskIfHidden(hidden, pts(s.needed))}{s.shortfall > 0 && <> · short {maskIfHidden(hidden, pts(s.shortfall))}</>}
          </span>
        ))}
        <span className="ml-auto text-xs">
          {trip.fund_goal_id ? (
            <>Fund {maskIfHidden(hidden, fmt(trip.fund_current ?? "0"))} / {maskIfHidden(hidden, fmt(trip.fund_target ?? "0"))}
              {trip.status !== "done" && <>
                <button className="ml-2 underline" onClick={() => act.mutate(() => adventuresApi.updateFund(trip.id))}>Update fund target</button>
                <button className="ml-2 underline" onClick={() => act.mutate(() => adventuresApi.removeFund(trip.id, window.confirm("Also delete the savings goal?")))}>Remove fund</button>
              </>}</>
          ) : trip.status !== "done" ? (
            <button className="underline" onClick={() => act.mutate(() => adventuresApi.createFund(trip.id))}>Set up a trip fund</button>
          ) : null}
        </span>
      </div>

      {CATEGORIES.map((cat) => {
        const items = trip.items.filter((i) => i.category === cat);
        return (
          <div key={cat}>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">{CATEGORY_LABEL[cat]}</p>
            {items.map((i) => <ItemRow key={i.id} trip={trip} item={i} programs={programs} onChange={onChange} />)}
            <AddItem trip={trip} category={cat} onChange={onChange} />
          </div>
        );
      })}
    </div>
  );
}
