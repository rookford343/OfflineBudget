import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plane, Plus } from "lucide-react";
import { adventuresApi, cardsApi } from "../api";
import { errText, fmt } from "../lib/utils";
import { maskIfHidden, useBalancesHidden } from "../store/balanceVisibility";
import WalletStrip from "../components/adventures/WalletStrip";
import TripDetail from "../components/adventures/TripDetail";
import { type TripSummary, type WalletRow, pts, shortDate } from "../components/adventures/types";

const STATUS_PILL: Record<string, string> = {
  planning: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300",
  committed: "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300",
  done: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
};

function NewTripForm({ onCreated }: { onCreated: (id: number) => void }) {
  const qc = useQueryClient();
  const { data: cards = [] } = useQuery<any[]>({ queryKey: ["credit-cards"], queryFn: cardsApi.list });
  const [f, setF] = useState({ name: "", destination: "", start_date: "", end_date: "", travelers: "2", default_card_id: "" });
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => adventuresApi.createTrip({
      name: f.name, destination: f.destination || null, start_date: f.start_date, end_date: f.end_date,
      travelers: parseInt(f.travelers || "1", 10), default_card_id: f.default_card_id ? Number(f.default_card_id) : null,
    }),
    onSuccess: (trip) => { qc.invalidateQueries({ queryKey: ["adventures"] }); setError(null); onCreated(trip.id); },
    onError: (e: any) => setError(errText(e)),
  });
  const ok = f.name && f.start_date && f.end_date && f.end_date >= f.start_date;
  return (
    <div className="card grid grid-cols-1 md:grid-cols-6 gap-2 items-end text-sm">
      <label className="md:col-span-2">Name<input className="input w-full" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
      <label>Destination<input className="input w-full" value={f.destination} onChange={(e) => setF({ ...f, destination: e.target.value })} /></label>
      <label>Start<input type="date" className="input w-full" value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value })} /></label>
      <label>End<input type="date" className="input w-full" value={f.end_date} onChange={(e) => setF({ ...f, end_date: e.target.value })} /></label>
      <label>Travelers<input type="number" min={1} className="input w-full" value={f.travelers} onChange={(e) => setF({ ...f, travelers: e.target.value })} /></label>
      <label className="md:col-span-2">Charge to
        <select className="input w-full" value={f.default_card_id} onChange={(e) => setF({ ...f, default_card_id: e.target.value })}>
          <option value="">Checking</option>{cards.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </label>
      <button className="btn-primary md:col-span-1" disabled={!ok || create.isPending} onClick={() => create.mutate()}>Create</button>
      {error && <p className="text-xs text-red-500 md:col-span-6">{error}</p>}
    </div>
  );
}

export default function Adventures() {
  const hidden = useBalancesHidden();
  const { data: trips = [] } = useQuery<TripSummary[]>({ queryKey: ["adventures", "trips"], queryFn: adventuresApi.trips });
  const { data: programs = [] } = useQuery<WalletRow[]>({ queryKey: ["adventures", "wallet"], queryFn: adventuresApi.wallet });
  const [selected, setSelected] = useState<number | null>(null);
  const [showNew, setShowNew] = useState(false);
  const progName = (id: string) => programs.find((p) => String(p.id) === id)?.name ?? "points";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100 flex items-center gap-2"><Plane size={20} /> Adventures</h2>
        <button className="btn-primary text-sm flex items-center gap-1" onClick={() => setShowNew(!showNew)}><Plus size={14} /> New adventure</button>
      </div>
      <WalletStrip />
      {showNew && <NewTripForm onCreated={(id) => { setShowNew(false); setSelected(id); }} />}
      {trips.length === 0 && !showNew && (
        <div className="card text-center text-sm text-gray-400 py-8">No adventures yet. Plan one to see what it really costs in cash and points.</div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {trips.map((t) => (
          <button key={t.id} onClick={() => setSelected(selected === t.id ? null : t.id)}
            className={`card text-left ${selected === t.id ? "ring-2 ring-indigo-500" : ""}`}>
            <div className="flex items-center justify-between">
              <span className="font-semibold text-gray-900 dark:text-gray-100">{t.name}</span>
              <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_PILL[t.status]}`}>{t.status}</span>
            </div>
            <p className="text-xs text-gray-500">{t.destination ? `${t.destination} · ` : ""}{shortDate(t.start_date)} – {shortDate(t.end_date)} · {t.travelers} traveler{t.travelers === 1 ? "" : "s"}</p>
            <p className="text-sm mt-2">Cash remaining <strong className="tabular-nums">{maskIfHidden(hidden, fmt(t.cash_remaining))}</strong></p>
            {Object.entries(t.points_by_program).map(([pid, n]) => (
              <p key={pid} className="text-xs text-gray-500">{maskIfHidden(hidden, pts(n))} {progName(pid)}</p>
            ))}
            {t.fund_goal_id && t.fund_target && (
              <p className="text-xs text-gray-500 mt-1">Fund {maskIfHidden(hidden, fmt(t.fund_current ?? "0"))} / {maskIfHidden(hidden, fmt(t.fund_target))}</p>
            )}
          </button>
        ))}
      </div>
      {selected !== null && <TripDetail tripId={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
