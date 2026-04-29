import { useState, useRef } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { importApi, accountsApi, cardsApi, categoriesApi } from "../api";
import { fmt } from "../lib/utils";
import { Upload, CheckCircle, AlertCircle, X } from "lucide-react";
import { useNavigate } from "react-router-dom";

type SourceTab = "checking" | "card";

interface PreviewRow {
  date: string;
  description: string;
  amount: number;
  category_id: number | null;
  category_name: string | null;
  needs_review: boolean;
}

export default function Import() {
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);

  const [tab, setTab] = useState<SourceTab>("checking");
  const [sourceId, setSourceId] = useState<number | null>(null);
  const [preview, setPreview] = useState<{ format: string; rows: PreviewRow[]; stats: any } | null>(null);
  const [editedRows, setEditedRows] = useState<PreviewRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<{ imported: number; skipped_duplicates: number } | null>(null);

  const { data: accounts = [] } = useQuery({ queryKey: ["accounts"], queryFn: accountsApi.list });
  const { data: cards = [] } = useQuery({ queryKey: ["cards"], queryFn: cardsApi.list });
  const { data: categories = [] } = useQuery({ queryKey: ["categories"], queryFn: categoriesApi.list });

  const checkingAccounts = accounts.filter((a: any) => a.type === "checking");
  const allCats = categories.flatMap((c: any) => [c, ...(c.children ?? [])]).filter((c: any) => c.type === "expense");

  const previewMut = useMutation({
    mutationFn: importApi.preview,
    onSuccess: (data) => {
      setPreview(data);
      setEditedRows(data.rows.map((r: PreviewRow) => ({ ...r })));
      setError(null);
    },
    onError: (e: any) => setError(e?.response?.data?.detail ?? "Preview failed"),
  });

  const confirmMut = useMutation({
    mutationFn: importApi.confirm,
    onSuccess: (data) => {
      setSuccess(data);
      setPreview(null);
    },
    onError: (e: any) => setError(e?.response?.data?.detail ?? "Import failed"),
  });

  function handleFile(file: File) {
    if (!sourceId) { setError("Select an account or card first"); return; }
    setError(null);
    setPreview(null);
    setSuccess(null);
    const fd = new FormData();
    fd.append("file", file);
    if (tab === "checking") fd.append("account_id", String(sourceId));
    else fd.append("card_id", String(sourceId));
    previewMut.mutate(fd);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }

  function handleFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  }

  function setCategoryForRow(idx: number, catId: number) {
    const cat = allCats.find((c: any) => c.id === catId);
    setEditedRows(rows => rows.map((r, i) => i === idx ? { ...r, category_id: catId, category_name: cat?.name ?? null, needs_review: false } : r));
  }

  function confirmImport() {
    if (!sourceId) return;
    const payload: any = { rows: editedRows.map(r => ({ date: r.date, description: r.description, amount: r.amount, category_id: r.category_id })) };
    if (tab === "checking") payload.account_id = sourceId;
    else payload.card_id = sourceId;
    confirmMut.mutate(payload);
  }

  const needsReviewCount = editedRows.filter(r => r.needs_review).length;
  const sources = tab === "checking" ? checkingAccounts : cards;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">Import Transactions</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">Upload a CSV file to import transactions with auto-categorization</p>
      </div>

      {success && (
        <div className="card border-green-200 bg-green-50 dark:bg-green-900/20 dark:border-green-800">
          <div className="flex items-center gap-3">
            <CheckCircle size={20} className="text-green-600 shrink-0" />
            <div>
              <p className="font-semibold text-green-800 dark:text-green-300">Import complete</p>
              <p className="text-sm text-green-700 dark:text-green-400">
                {success.imported} transactions imported · {success.skipped_duplicates} duplicates skipped
              </p>
            </div>
            <button onClick={() => navigate("/transactions")} className="btn-primary ml-auto text-xs">View Transactions →</button>
          </div>
        </div>
      )}

      {/* Source selector */}
      <div className="card space-y-4">
        <div>
          <label className="label">Import Into</label>
          <div className="flex rounded-lg bg-gray-100 dark:bg-gray-700 p-1 w-fit">
            {(["checking", "card"] as SourceTab[]).map(t => (
              <button key={t} type="button"
                onClick={() => { setTab(t); setSourceId(null); setPreview(null); }}
                className={`px-4 py-1.5 text-sm font-medium rounded-md transition-colors capitalize ${tab === t ? "bg-white dark:bg-gray-800 shadow-sm text-gray-900 dark:text-gray-100" : "text-gray-500 dark:text-gray-400"}`}>
                {t === "checking" ? "Checking Account" : "Credit Card"}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="label">{tab === "checking" ? "Account" : "Credit Card"}</label>
          <select className="input w-full max-w-sm" value={sourceId ?? ""} onChange={e => setSourceId(parseInt(e.target.value))}>
            <option value="">Select…</option>
            {sources.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </div>

        {/* Drop zone */}
        <div
          onDrop={handleDrop}
          onDragOver={e => e.preventDefault()}
          onClick={() => fileRef.current?.click()}
          className="border-2 border-dashed border-gray-300 dark:border-gray-600 rounded-xl p-10 text-center cursor-pointer hover:border-indigo-400 hover:bg-indigo-50/40 dark:hover:bg-indigo-900/10 transition-colors"
        >
          <Upload size={32} className="mx-auto text-gray-400 mb-3" />
          <p className="text-sm font-medium text-gray-700 dark:text-gray-300">Drop a CSV file here or click to browse</p>
          <p className="text-xs text-gray-400 mt-1">Chase checking, Chase card, Apple Card, or generic CSV</p>
          <input ref={fileRef} type="file" accept=".csv" className="hidden" onChange={handleFileInput} />
        </div>

        {previewMut.isPending && <p className="text-sm text-gray-500 text-center">Parsing file…</p>}

        {error && (
          <div className="flex items-center gap-2 text-red-600 text-sm bg-red-50 dark:bg-red-900/20 rounded-lg px-3 py-2">
            <AlertCircle size={16} />
            {error}
            <button onClick={() => setError(null)} className="ml-auto"><X size={14} /></button>
          </div>
        )}
      </div>

      {/* Preview table */}
      {preview && (
        <div className="card space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-semibold text-gray-900 dark:text-gray-100">Preview — {preview.stats.total} rows</h3>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                <span className="text-green-600 font-medium">{preview.stats.categorized} auto-categorized</span>
                {preview.stats.needs_review > 0 && (
                  <span className="text-amber-600 font-medium"> · {preview.stats.needs_review} need review</span>
                )}
                {" · "}format: {preview.format}
              </p>
            </div>
            <button
              onClick={confirmImport}
              disabled={confirmMut.isPending || needsReviewCount > 0}
              className="btn-primary"
              title={needsReviewCount > 0 ? "Assign categories to all rows first" : undefined}
            >
              {confirmMut.isPending ? "Importing…" : `Import ${editedRows.length} Transactions`}
            </button>
          </div>

          {needsReviewCount > 0 && (
            <p className="text-xs text-amber-600 bg-amber-50 dark:bg-amber-900/20 rounded-lg px-3 py-2">
              Assign a category to all {needsReviewCount} highlighted rows before importing.
            </p>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-700">
                  <th className="text-left py-2 pr-4 text-gray-500 font-medium">Date</th>
                  <th className="text-left py-2 pr-4 text-gray-500 font-medium">Description</th>
                  <th className="text-right py-2 pr-4 text-gray-500 font-medium">Amount</th>
                  <th className="text-left py-2 text-gray-500 font-medium">Category</th>
                </tr>
              </thead>
              <tbody>
                {editedRows.map((row, idx) => (
                  <tr key={idx} className={`border-b border-gray-50 dark:border-gray-800 ${row.needs_review ? "bg-amber-50/50 dark:bg-amber-900/10" : ""}`}>
                    <td className="py-2 pr-4 text-gray-500 whitespace-nowrap">{row.date}</td>
                    <td className="py-2 pr-4 text-gray-800 dark:text-gray-200 max-w-xs truncate">{row.description}</td>
                    <td className={`py-2 pr-4 text-right font-semibold tabular-nums whitespace-nowrap ${row.amount < 0 ? "text-red-600" : "text-green-600"}`}>
                      {fmt(row.amount)}
                    </td>
                    <td className="py-2">
                      {row.needs_review ? (
                        <select
                          className="input py-1 text-xs"
                          value={editedRows[idx].category_id ?? ""}
                          onChange={e => setCategoryForRow(idx, parseInt(e.target.value))}
                        >
                          <option value="">Assign category…</option>
                          {allCats.map((c: any) => (
                            <option key={c.id} value={c.id}>{c.parent_id ? "  " : ""}{c.name}</option>
                          ))}
                        </select>
                      ) : (
                        <span className="badge-green">{row.category_name}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
