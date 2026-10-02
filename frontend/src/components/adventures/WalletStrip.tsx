import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import { ArrowRightLeft, ChevronDown, ChevronUp, X } from "lucide-react";
import { adventuresApi } from "../../api";
import { maskIfHidden, useBalancesHidden } from "../../store/balanceVisibility";
import { type PartnerRow, type WalletRow, pts } from "./types";

function ProgramChip({ p }: { p: WalletRow }) {
  const qc = useQueryClient();
  const hidden = useBalancesHidden();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(String(p.balance));
  const save = useMutation({
    mutationFn: () => adventuresApi.updateProgram(p.id, { balance: Math.max(0, parseInt(value || "0", 10)) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["adventures"] }); setEditing(false); },
  });
  const stale = p.age_days !== null && p.age_days > 30;
  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-2 min-w-[180px]">
      <p className="text-xs text-gray-500 dark:text-gray-400 truncate">{p.name}</p>
      {editing ? (
        <div className="flex items-center gap-1 mt-1">
          <input className="input py-0.5 w-28 text-sm" type="number" min={0} value={value} autoFocus
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") save.mutate(); if (e.key === "Escape") setEditing(false); }} />
          <button className="btn-primary text-xs px-2 py-0.5" onClick={() => save.mutate()}>Save</button>
        </div>
      ) : (
        <button className="text-lg font-bold tabular-nums text-gray-900 dark:text-gray-100 hover:text-indigo-600"
          title="Edit balance" onClick={() => { setValue(String(p.balance)); setEditing(true); }}>
          {maskIfHidden(hidden, pts(p.balance))}
        </button>
      )}
      <p className="text-xs text-gray-500 dark:text-gray-400">
        {p.reserved > 0 && <>{maskIfHidden(hidden, pts(p.available))} available · </>}
        <span className={stale ? "text-amber-600 dark:text-amber-400" : ""}>
          {p.age_days === null ? "never updated" : p.age_days === 0 ? "updated today" : `updated ${p.age_days}d ago`}
        </span>
      </p>
    </div>
  );
}

function PartnersDialog({ programs }: { programs: WalletRow[] }) {
  const qc = useQueryClient();
  const { data: partners = [] } = useQuery<PartnerRow[]>({ queryKey: ["adventures", "partners"], queryFn: adventuresApi.partners });
  const update = useMutation({
    mutationFn: ({ id, data }: { id: number; data: object }) => adventuresApi.updatePartner(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["adventures"] }),
  });
  const remove = useMutation({
    mutationFn: (id: number) => adventuresApi.removePartner(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["adventures"] }),
  });
  const [from, setFrom] = useState(""); const [to, setTo] = useState(""); const [ratio, setRatio] = useState("1");
  const add = useMutation({
    mutationFn: () => adventuresApi.createPartner({ from_program_id: Number(from), to_program_id: Number(to), ratio }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["adventures"] }); setTo(""); },
  });
  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>
        <button className="btn-secondary text-xs flex items-center gap-1"><ArrowRightLeft size={14} /> Partners & bonuses</button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 z-50" />
        <Dialog.Content className="fixed inset-0 z-50 flex items-center justify-center p-4 focus:outline-none">
          <div className="card w-full max-w-2xl max-h-[85vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-3">
              <Dialog.Title className="font-bold text-gray-900 dark:text-gray-100">Transfer partners & bonuses</Dialog.Title>
              <Dialog.Close aria-label="Close" className="text-gray-400 hover:text-gray-600"><X size={18} /></Dialog.Close>
            </div>
            <Dialog.Description className="text-xs text-gray-500 mb-3">
              Ratio is partner points per source point. A bonus applies through its end date; leave the end blank for an open-ended bonus.
            </Dialog.Description>
            <table className="w-full text-sm">
              <thead><tr className="text-left text-gray-500 border-b border-gray-100 dark:border-gray-700">
                <th className="py-1">From → To</th><th>Ratio</th><th>Bonus %</th><th>Ends</th><th /></tr></thead>
              <tbody>
                {partners.map((p) => (
                  <tr key={p.id} className="border-b border-gray-50 dark:border-gray-800">
                    <td className="py-1 pr-2">{p.from_program_name} → {p.to_program_name}</td>
                    <td><input className="input py-0.5 w-16 text-xs" defaultValue={p.ratio}
                      onBlur={(e) => e.target.value !== p.ratio && update.mutate({ id: p.id, data: { ratio: e.target.value } })} /></td>
                    <td><input className={`input py-0.5 w-16 text-xs ${p.bonus_pct && !p.bonus_active ? "line-through text-gray-400" : ""}`}
                      defaultValue={p.bonus_pct ?? ""} placeholder="—"
                      onBlur={(e) => update.mutate({ id: p.id, data: { bonus_pct: e.target.value === "" ? null : e.target.value } })} /></td>
                    <td><input className="input py-0.5 text-xs" type="date" defaultValue={p.bonus_ends_on ?? ""}
                      onBlur={(e) => update.mutate({ id: p.id, data: { bonus_ends_on: e.target.value || null } })} /></td>
                    <td><button aria-label="Remove partner" className="text-gray-400 hover:text-red-500 px-1" onClick={() => remove.mutate(p.id)}><X size={14} /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex flex-wrap items-center gap-2 mt-3 text-sm">
              <select className="input py-1 text-sm" value={from} onChange={(e) => setFrom(e.target.value)}>
                <option value="">From…</option>{programs.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              <select className="input py-1 text-sm" value={to} onChange={(e) => setTo(e.target.value)}>
                <option value="">To…</option>{programs.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              <input className="input py-1 w-20 text-sm" value={ratio} onChange={(e) => setRatio(e.target.value)} />
              <button className="btn-primary text-xs" disabled={!from || !to || from === to} onClick={() => add.mutate()}>Add partner</button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default function WalletStrip() {
  const { data: programs = [] } = useQuery<WalletRow[]>({ queryKey: ["adventures", "wallet"], queryFn: adventuresApi.wallet });
  const [showOthers, setShowOthers] = useState(false);
  const inUse = programs.filter((p) => p.is_active && (p.balance > 0 || p.reserved > 0 || p.kind === "bank"));
  const others = programs.filter((p) => !inUse.includes(p));
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-gray-900 dark:text-gray-100">Points wallet</h3>
        <PartnersDialog programs={programs} />
      </div>
      <div className="flex flex-wrap gap-2">{inUse.map((p) => <ProgramChip key={p.id} p={p} />)}</div>
      {others.length > 0 && (
        <div className="mt-3">
          <button className="text-xs text-indigo-600 flex items-center gap-1" onClick={() => setShowOthers(!showOthers)}>
            {showOthers ? <ChevronUp size={14} /> : <ChevronDown size={14} />} Other programs ({others.length})
          </button>
          {showOthers && <div className="flex flex-wrap gap-2 mt-2">{others.map((p) => <ProgramChip key={p.id} p={p} />)}</div>}
        </div>
      )}
    </div>
  );
}
