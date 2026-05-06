import { useState, useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { importApi, accountsApi, cardsApi, categoriesApi, recurringApi } from "../api";
import { fmt } from "../lib/utils";
import { Upload, CheckCircle, AlertCircle, X, ArrowLeftRight, HelpCircle } from "lucide-react";
import HelpPanel from "../components/HelpPanel";
import { useNavigate } from "react-router-dom";

type SourceTab = "checking" | "card";

interface PreviewRow {
  date: string;
  description: string;
  amount: number;
  category_id: number | null;
  category_name: string | null;
  needs_review: boolean;
  is_transfer: boolean;
  included: boolean;
  notes: string;
  recurring_item_id: number | null;
}

const COLOR_SWATCHES = ["#6366f1", "#22c55e", "#ef4444", "#f59e0b", "#3b82f6", "#8b5cf6", "#ec4899", "#14b8a6"];

export default function Import() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);

  const [tab, setTab] = useState<SourceTab>("checking");
  const [sourceId, setSourceId] = useState<number | null>(null);
  const [preview, setPreview] = useState<{ format: string; rows: any[]; stats: any } | null>(null);
  const [editedRows, setEditedRows] = useState<PreviewRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<{ imported: number; skipped_duplicates: number } | null>(null);
  const [showHelp, setShowHelp] = useState(false);
  const [inlineCatRow, setInlineCatRow] = useState<number | null>(null);
  const [inlineCatName, setInlineCatName] = useState("");
  const [inlineCatColor, setInlineCatColor] = useState("#6366f1");

  const { data: accounts = [] } = useQuery({ queryKey: ["accounts"], queryFn: accountsApi.list });
  const { data: cards = [] } = useQuery({ queryKey: ["cards"], queryFn: cardsApi.list });
  const { data: categories = [] } = useQuery({ queryKey: ["categories"], queryFn: categoriesApi.list });
  const { data: recurringItems = [] } = useQuery({ queryKey: ["recurring"], queryFn: () => recurringApi.list(), enabled: tab === "checking" });

  const checkingAccounts = accounts.filter((a: any) => a.type === "checking");
  const incomeCats = categories.flatMap((c: any) => [c, ...(c.children ?? [])]).filter((c: any) => c.type === "income");
  const expenseCats = categories.flatMap((c: any) => [c, ...(c.children ?? [])]).filter((c: any) => c.type === "expense");
  const allCats = [...incomeCats, ...expenseCats];
  const sources = tab === "checking" ? checkingAccounts : cards;

  // Auto-select first source on initial load and when tab changes
  useEffect(() => {
    if (sourceId === null && sources.length > 0) {
      setSourceId((sources[0] as any).id);
    }
  }, [tab, checkingAccounts, cards]);

  const previewMut = useMutation({
    mutationFn: importApi.preview,
    onSuccess: (data) => {
      setPreview(data);
      setEditedRows(data.rows.map((r: any) => ({
        ...r,
        included: !r.is_transfer,
        notes: "",
        recurring_item_id: null,
      })));
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

  const createCatMut = useMutation({
    mutationFn: (data: object) => categoriesApi.create(data),
    onSuccess: (newCat: any) => {
      qc.invalidateQueries({ queryKey: ["categories"] });
      if (inlineCatRow !== null) {
        setEditedRows(rows => rows.map((r, i) =>
          i === inlineCatRow
            ? { ...r, category_id: newCat.id, category_name: newCat.name, needs_review: false }
            : r
        ));
      }
      setInlineCatRow(null);
      setInlineCatName("");
    },
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

  function setCategoryForRow(idx: number, value: string) {
    if (value === "new") {
      setInlineCatRow(idx);
      setInlineCatName("");
      return;
    }
    const catId = parseInt(value);
    const cat = allCats.find((c: any) => c.id === catId);
    setEditedRows(rows => rows.map((r, i) =>
      i === idx ? { ...r, category_id: catId, category_name: cat?.name ?? null, needs_review: false } : r
    ));
    if (inlineCatRow === idx) setInlineCatRow(null);
  }

  function toggleIncluded(idx: number) {
    setEditedRows(rows => rows.map((r, i) => i === idx ? { ...r, included: !r.included } : r));
  }

  function submitInlineCat(idx: number) {
    if (!inlineCatName.trim()) return;
    const rowType = editedRows[idx]?.amount > 0 ? "income" : "expense";
    createCatMut.mutate({ name: inlineCatName.trim(), type: rowType, color: inlineCatColor });
  }

  function toggleSelectAll() {
    const allIncluded = editedRows.every(r => r.included);
    setEditedRows(rows => rows.map(r => ({ ...r, included: !allIncluded })));
  }

  function confirmImport() {
    if (!sourceId) return;
    const activeRows = editedRows.filter(r => r.included);
    const payload: any = {
      rows: activeRows.map(r => ({
        date: r.date,
        description: r.description,
        amount: r.amount,
        category_id: r.category_id,
        notes: r.notes || null,
        recurring_item_id: r.recurring_item_id || null,
      }))
    };
    if (tab === "checking") payload.account_id = sourceId;
    else payload.card_id = sourceId;
    confirmMut.mutate(payload);
  }

  const includedRows = editedRows.filter(r => r.included);
  const needsReviewCount = includedRows.filter(r => r.needs_review).length;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100 flex items-center gap-1.5">Import Transactions <button onClick={() => setShowHelp(true)} className="text-gray-400 hover:text-indigo-500 font-normal"><HelpCircle size={15} /></button></h2>
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
        <label
          htmlFor="csv-file-input"
          onDrop={handleDrop}
          onDragOver={e => e.preventDefault()}
          className="block border-2 border-dashed border-gray-300 dark:border-gray-600 rounded-xl p-10 text-center cursor-pointer hover:border-indigo-400 hover:bg-indigo-50/40 dark:hover:bg-indigo-900/10 transition-colors"
        >
          <Upload size={32} className="mx-auto text-gray-400 mb-3" />
          <p className="text-sm font-medium text-gray-700 dark:text-gray-300">Drop a CSV file here or click to browse</p>
          <p className="text-xs text-gray-400 mt-1">Chase checking, Chase card, Apple Card, or generic CSV</p>
          <input id="csv-file-input" ref={fileRef} type="file" accept=".csv" className="hidden" onChange={handleFileInput} />
        </label>

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
                {editedRows.filter(r => r.is_transfer && !r.included).length > 0 && (
                  <span className="text-gray-500 font-medium"> · {editedRows.filter(r => r.is_transfer && !r.included).length} transfers skipped</span>
                )}
                {" · "}format: {preview.format}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={toggleSelectAll} className="btn-secondary text-xs px-3 py-1.5">
                {editedRows.every(r => r.included) ? "Deselect All" : "Select All"}
              </button>
              <button
                onClick={confirmImport}
                disabled={confirmMut.isPending || needsReviewCount > 0}
                className="btn-primary"
                title={needsReviewCount > 0 ? "Assign categories to all rows first" : undefined}
              >
                {confirmMut.isPending ? "Importing…" : `Import ${includedRows.length} Transactions`}
              </button>
            </div>
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
                  <th className="text-left py-2 pr-4 text-gray-500 font-medium w-8"></th>
                  <th className="text-left py-2 pr-4 text-gray-500 font-medium">Date</th>
                  <th className="text-left py-2 pr-4 text-gray-500 font-medium">Description</th>
                  <th className="text-right py-2 pr-4 text-gray-500 font-medium">Amount</th>
                  <th className="text-left py-2 pr-4 text-gray-500 font-medium">Category</th>
                  <th className="text-left py-2 pr-4 text-gray-500 font-medium">Notes</th>
                  {tab === "checking" && <th className="text-left py-2 text-gray-500 font-medium">Recurring</th>}
                </tr>
              </thead>
              <tbody>
                {editedRows.map((row, idx) => {
                  const isTransfer = row.is_transfer && !row.included;
                  return (
                    <tr key={idx} className={`border-b border-gray-50 dark:border-gray-800 ${
                      isTransfer ? "opacity-50" : row.needs_review ? "bg-amber-50/50 dark:bg-amber-900/10" : ""
                    }`}>
                      <td className="py-2 pr-2">
                        <input
                          type="checkbox"
                          checked={row.included}
                          onChange={() => toggleIncluded(idx)}
                          className="rounded border-gray-300"
                        />
                      </td>
                      <td className="py-2 pr-4 text-gray-500 whitespace-nowrap">{row.date}</td>
                      <td className="py-2 pr-4 text-gray-800 dark:text-gray-200 max-w-xs">
                        <div className="truncate">{row.description}</div>
                        {row.is_transfer && (
                          <div className="flex items-center gap-1 mt-0.5">
                            <ArrowLeftRight size={11} className="text-gray-400" />
                            <span className="text-xs text-gray-400">transfer — skip to avoid double-counting</span>
                          </div>
                        )}
                      </td>
                      <td className={`py-2 pr-4 text-right font-semibold tabular-nums whitespace-nowrap ${row.amount < 0 ? "text-red-600" : "text-green-600"}`}>
                        {fmt(row.amount)}
                      </td>
                      <td className="py-2 min-w-[180px]">
                        {inlineCatRow === idx ? (
                          <div className="space-y-1">
                            <input
                              autoFocus
                              className="input py-1 text-xs w-full"
                              placeholder="Category name…"
                              value={inlineCatName}
                              onChange={e => setInlineCatName(e.target.value)}
                              onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); submitInlineCat(idx); } if (e.key === "Escape") setInlineCatRow(null); }}
                            />
                            <div className="flex items-center gap-1 flex-wrap">
                              {COLOR_SWATCHES.map(c => (
                                <button key={c} type="button"
                                  onClick={() => setInlineCatColor(c)}
                                  className={`w-5 h-5 rounded-full border-2 ${inlineCatColor === c ? "border-gray-800" : "border-transparent"}`}
                                  style={{ background: c }}
                                />
                              ))}
                            </div>
                            <div className="flex gap-1">
                              <button onClick={() => submitInlineCat(idx)} disabled={createCatMut.isPending} className="btn-primary text-xs py-1 px-2">
                                {createCatMut.isPending ? "…" : "Add"}
                              </button>
                              <button onClick={() => setInlineCatRow(null)} className="btn-secondary text-xs py-1 px-2">Cancel</button>
                            </div>
                          </div>
                        ) : (
                          <select
                            className={`input py-1 text-xs w-full ${row.needs_review ? "border-amber-300" : ""}`}
                            value={editedRows[idx].category_id ?? ""}
                            onChange={e => setCategoryForRow(idx, e.target.value)}
                          >
                            <option value="">No category</option>
                            {tab === "checking" && incomeCats.length > 0 && (
                              <optgroup label="── Income ──">
                                {incomeCats.map((c: any) => (
                                  <option key={c.id} value={c.id}>{c.parent_id ? "  " : ""}{c.name}</option>
                                ))}
                              </optgroup>
                            )}
                            <optgroup label="── Expenses ──">
                              {expenseCats.map((c: any) => (
                                <option key={c.id} value={c.id}>{c.parent_id ? "  " : ""}{c.name}</option>
                              ))}
                            </optgroup>
                            <option value="new">+ New category…</option>
                          </select>
                        )}
                      </td>
                      <td className="py-2 pr-4 min-w-[120px]">
                        <input
                          className="input py-1 text-xs w-full"
                          placeholder="note…"
                          value={row.notes}
                          onChange={e => setEditedRows(rows => rows.map((r, i) => i === idx ? { ...r, notes: e.target.value } : r))}
                        />
                      </td>
                      {tab === "checking" && (
                        <td className="py-2 min-w-[160px]">
                          <select
                            className="input py-1 text-xs w-full"
                            value={row.recurring_item_id ?? ""}
                            onChange={e => setEditedRows(rows => rows.map((r, i) => i === idx ? { ...r, recurring_item_id: e.target.value ? parseInt(e.target.value) : null } : r))}
                          >
                            <option value="">None</option>
                            {(recurringItems as any[]).map((item: any) => (
                              <option key={item.id} value={item.id}>{item.name}</option>
                            ))}
                          </select>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {showHelp && <HelpPanel title="Import Transactions" body={"Upload a CSV file to import transactions from your bank.\n\nSupported formats: Chase checking, Chase card, Apple Card, and generic CSV.\n\nEach row gets auto-categorized. You can change any category using the dropdown — or create a new category inline with '+ New category…'\n\nTransfer rows (CC autopay, etc.) are detected and unchecked by default to prevent double-counting. You can re-check them if needed."} onClose={() => setShowHelp(false)} />}
    </div>
  );
}
