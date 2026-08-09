import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { plannedTransfersApi, accountsApi } from "../api";
import { fmt } from "../lib/utils";
import { Landmark, Check, Trash2, Pencil, X } from "lucide-react";

function formatDate(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "long", day: "numeric" });
}

export function PlannedTransferReminder() {
  const qc = useQueryClient();
  const { data: transfers = [] } = useQuery<any[]>({ queryKey: ["planned-transfers"], queryFn: plannedTransfersApi.list });
  const { data: accounts = [] } = useQuery<any[]>({ queryKey: ["accounts"], queryFn: accountsApi.list });
  const accountName = (id: number | null) => accounts.find((a: any) => a.id === id)?.name ?? "Savings";

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editAmount, setEditAmount] = useState("");
  const [editDate, setEditDate] = useState("");

  const markScheduledMut = useMutation({
    mutationFn: plannedTransfersApi.markScheduled,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["planned-transfers"] }),
  });
  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: object }) => plannedTransfersApi.update(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["planned-transfers"] });
      qc.invalidateQueries({ queryKey: ["forecast-risk"] });
      setEditingId(null);
    },
  });
  const removeMut = useMutation({
    mutationFn: plannedTransfersApi.remove,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["planned-transfers"] });
      qc.invalidateQueries({ queryKey: ["forecast-risk"] });
    },
  });

  function startEdit(t: any) {
    setEditingId(t.id);
    setEditAmount(t.amount);
    setEditDate(t.target_date);
  }
  function saveEdit(id: number) {
    updateMut.mutate({ id, data: { amount: parseFloat(editAmount), target_date: editDate } });
  }

  const active = transfers.filter((t: any) => t.status === "pending" || t.status === "scheduled");
  if (active.length === 0) return null;

  return (
    <div className="card border-amber-200 dark:border-amber-700 bg-amber-50/60 dark:bg-amber-900/20 space-y-2">
      {active.map((t: any) => (
        <div key={t.id} className="flex items-center justify-between gap-3">
          {editingId === t.id ? (
            <div className="flex items-center gap-2 flex-1">
              <input type="number" step="1" className="input w-28 text-sm" value={editAmount} onChange={(e) => setEditAmount(e.target.value)} autoFocus />
              <input type="date" className="input text-sm" value={editDate} onChange={(e) => setEditDate(e.target.value)} />
              <button onClick={() => saveEdit(t.id)} disabled={updateMut.isPending} className="text-green-600"><Check size={16} /></button>
              <button onClick={() => setEditingId(null)} className="text-gray-400"><X size={16} /></button>
            </div>
          ) : (
            <div className="flex items-center gap-2 min-w-0">
              <Landmark size={16} className="text-amber-500 shrink-0" />
              <p className="text-sm text-amber-900 dark:text-amber-200 truncate">
                {t.status === "scheduled" ? "Scheduled — waiting to verify: " : "Move "}
                <strong>{fmt(parseFloat(t.amount))}</strong> {accountName(t.from_account_id)} → {accountName(t.to_account_id)} by {formatDate(t.target_date)}
              </p>
            </div>
          )}
          {editingId !== t.id && (
            <div className="flex items-center gap-1 shrink-0">
              {t.status === "pending" && (
                <button
                  onClick={() => markScheduledMut.mutate(t.id)}
                  disabled={markScheduledMut.isPending}
                  className="btn-secondary text-xs px-2 py-1 flex items-center gap-1"
                >
                  <Check size={12} /> Mark Scheduled
                </button>
              )}
              <button onClick={() => startEdit(t)} className="btn-ghost p-1.5"><Pencil size={14} /></button>
              <button onClick={() => removeMut.mutate(t.id)} className="btn-ghost p-1.5 text-red-400 hover:bg-red-50">
                <Trash2 size={14} />
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
