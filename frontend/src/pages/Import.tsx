import React, { useState, useRef, useEffect, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { importApi, accountsApi, cardsApi, categoriesApi, recurringApi } from "../api";
import { fmt } from "../lib/utils";
import { Upload, CheckCircle, AlertCircle, X, ArrowLeftRight, HelpCircle, Repeat, ChevronDown } from "lucide-react";
import HelpPanel from "../components/HelpPanel";
import { useNavigate } from "react-router-dom";
import { sortCategoryList, byName } from "../lib/selectOptions";

type SourceTab = "checking" | "card";

function descriptionKey(desc: string): string {
  let key = desc.toLowerCase().trim();
  // Zelle: normalize "zelle [payment] from/to NAME [ID]" to a stable group key
  const zelleMatch = key.match(/^zelle(?:\s+payment)?\s+(from|to)\s+([a-z][a-z\s\-]+?)(?:\s+[a-z0-9]{6,})?$/);
  if (zelleMatch) {
    return `zelle ${zelleMatch[1]} ${zelleMatch[2].trim()}`;
  }
  // Strip POS/payment prefixes (SQ*, TST*, PP*)
  key = key.replace(/^(sq|tst|pp)\*\s*/i, "");
  // Strip "WEB ID: 1234567890" and "ACH ID: ..." patterns
  key = key.replace(/\s+(?:web|ach|ppd|ccd)\s+id:?\s*\S*/gi, "");
  // Strip short-prefix dash reference codes with digits e.g. " ST-D5L4V9H1G4T7", " ACH-1234ABCD"
  key = key.replace(/\s+[a-z]{1,5}-[a-z0-9]*\d[a-z0-9]*/gi, "");
  // Strip reference codes after *, #, / — including optional space
  key = key.replace(/[\*#\/]\s*[a-z0-9]*\d[a-z0-9]*/gi, "");
  // Strip common TLD suffixes
  key = key.replace(/\.(com|cc|net|org|co|io)\b/g, "");
  // Strip trailing store/location numbers (4+ digits, captures trailing city names too)
  key = key.replace(/\s+\d{4,}.*$/, "");
  // Strip trailing punctuation left by removed tokens
  key = key.replace(/[\.\,\-\s]+$/, "");
  return key.replace(/\s+/g, " ").trim();
}

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
  suggested_recurring_item_id: number | null;
  suggested_recurring_item_name: string | null;
}

const COLOR_SWATCHES = ["#6366f1", "#22c55e", "#ef4444", "#f59e0b", "#3b82f6", "#8b5cf6", "#ec4899", "#14b8a6"];

export default function Import() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);

  const [tab, setTab] = useState<SourceTab>("checking");
  const [sourceId, setSourceId] = useState<number | null>(null);
  const [skipCat, setSkipCat] = useState(false);
  const [preview, setPreview] = useState<{ format: string; rows: any[]; stats: any } | null>(null);
  const [editedRows, setEditedRows] = useState<PreviewRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<{ imported: number; skipped_duplicates: number } | null>(null);
  const [showHelp, setShowHelp] = useState(false);
  const [inlineCatRow, setInlineCatRow] = useState<number | null>(null);
  const [inlineCatName, setInlineCatName] = useState("");
  const [inlineCatColor, setInlineCatColor] = useState("#6366f1");
  const [recurringModal, setRecurringModal] = useState<{ name: string; amount: string; dayOfMonth: string; categoryId: string; accountId: string; startDate: string } | null>(null);
  const [groupByDesc, setGroupByDesc] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [recurringSuccess, setRecurringSuccess] = useState<string | null>(null);

  const { data: accounts = [] } = useQuery({ queryKey: ["accounts"], queryFn: accountsApi.list });
  const { data: cards = [] } = useQuery({ queryKey: ["cards"], queryFn: cardsApi.list });
  const { data: categories = [] } = useQuery({ queryKey: ["categories"], queryFn: categoriesApi.list });
  const { data: recurringItems = [] } = useQuery({ queryKey: ["recurring"], queryFn: () => recurringApi.list() });

  const checkingAccounts = accounts.filter((a: any) => a.type === "checking");
  const incomeCats = sortCategoryList(categories.flatMap((c: any) => [c, ...(c.children ?? [])]).filter((c: any) => c.type === "income"), categories as any[]);
  const expenseCats = sortCategoryList(categories.flatMap((c: any) => [c, ...(c.children ?? [])]).filter((c: any) => c.type === "expense"), categories as any[]);
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
        recurring_item_id: r.suggested_recurring_item_id ?? null,
        suggested_recurring_item_id: r.suggested_recurring_item_id ?? null,
        suggested_recurring_item_name: r.suggested_recurring_item_name ?? null,
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
      qc.invalidateQueries({ queryKey: ["forecast-quarters"] });
      qc.invalidateQueries({ queryKey: ["forecast-multi-year"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
    onError: (e: any) => setError(e?.response?.data?.detail ?? "Import failed"),
  });

  const createRecurringMut = useMutation({
    mutationFn: (data: object) => recurringApi.create(data),
    onSuccess: (r: any) => {
      qc.invalidateQueries({ queryKey: ["recurring"] });
      setRecurringModal(null);
      setRecurringSuccess(`"${r.name}" added to recurring expenses`);
      setTimeout(() => setRecurringSuccess(null), 3000);
    },
  });

  const updateRecurringMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: object }) => recurringApi.update(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["recurring"] }),
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
    if (skipCat) fd.append("skip_categorization", "true");
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

  const groupedRows = useMemo(() => {
    if (!groupByDesc || editedRows.length === 0) return null;
    const groups = new Map<string, number[]>();
    editedRows.forEach((row, idx) => {
      const key = descriptionKey(row.description);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(idx);
    });
    return Array.from(groups.entries())
      .map(([groupKey, indices]) => ({
        indices,
        groupKey,
        row: editedRows[indices[0]],
        totalAmount: indices.reduce((sum, i) => sum + Number(editedRows[i].amount), 0),
        count: indices.length,
        allIncluded: indices.every(i => editedRows[i].included),
      }))
      .sort((a, b) => a.groupKey.localeCompare(b.groupKey));
  }, [groupByDesc, editedRows]);

  function setCategoryForGroup(indices: number[], value: string) {
    if (value === "new") { setInlineCatRow(indices[0]); return; }
    const catId = value ? parseInt(value) : null;
    const cat = catId ? allCats.find((c: any) => c.id === catId) : null;
    setEditedRows(rows => rows.map((r, i) =>
      indices.includes(i) ? { ...r, category_id: catId, category_name: cat?.name ?? null, needs_review: false } : r
    ));
  }

  function toggleGroupIncluded(indices: number[]) {
    const allIncluded = indices.every(i => editedRows[i].included);
    setEditedRows(rows => rows.map((r, i) => indices.includes(i) ? { ...r, included: !allIncluded } : r));
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
        is_transfer: r.is_transfer,
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

        <label className="flex items-center gap-2 cursor-pointer w-fit">
          <input type="checkbox" checked={skipCat} onChange={e => setSkipCat(e.target.checked)} className="rounded" />
          <span className="text-sm text-gray-600 dark:text-gray-300">Skip auto-categorization (import uncategorized)</span>
        </label>

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
            <div className="flex items-center gap-2 flex-wrap">
              <label className="flex items-center gap-1.5 cursor-pointer text-xs text-gray-600 dark:text-gray-300">
                <input type="checkbox" checked={groupByDesc} onChange={e => setGroupByDesc(e.target.checked)} className="rounded" />
                Group by description
              </label>
              <button onClick={toggleSelectAll} className="btn-secondary text-xs px-3 py-1.5">
                {editedRows.every(r => r.included) ? "Deselect All" : "Select All"}
              </button>
              {needsReviewCount > 0 && (
                <button
                  onClick={() => setEditedRows(rows => rows.map(r =>
                    r.needs_review ? { ...r, needs_review: false, category_id: null, category_name: null } : r
                  ))}
                  className="btn-secondary text-xs px-3 py-1.5 text-amber-700 dark:text-amber-400"
                >
                  Clear all categories ({needsReviewCount})
                </button>
              )}
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

          {groupByDesc && groupedRows ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 dark:border-gray-700">
                    <th className="text-left py-2 pr-2 text-gray-500 font-medium w-8"></th>
                    <th className="text-left py-2 pr-2 text-gray-500 font-medium w-6"></th>
                    <th className="text-left py-2 pr-4 text-gray-500 font-medium">Description</th>
                    <th className="text-right py-2 pr-4 text-gray-500 font-medium">Total</th>
                    <th className="text-left py-2 pr-4 text-gray-500 font-medium">Category</th>
                    {tab === "card" && <th className="text-left py-2 text-gray-500 font-medium w-8"></th>}
                  </tr>
                </thead>
                <tbody>
                  {groupedRows.map(({ indices, groupKey, row, totalAmount, count, allIncluded }) => {
                    const representative = editedRows[indices[0]];
                    const needsReviewGroup = indices.some(i => editedRows[i].needs_review);
                    const isExpanded = expandedGroups.has(groupKey);
                    return (
                      <React.Fragment key={groupKey}>
                        <tr className={`border-b border-gray-50 dark:border-gray-800 ${needsReviewGroup ? "bg-amber-50/50 dark:bg-amber-900/10" : ""}`}>
                          <td className="py-2 pr-2">
                            <input type="checkbox" checked={allIncluded} onChange={() => toggleGroupIncluded(indices)} className="rounded border-gray-300" />
                          </td>
                          <td className="py-2 pr-2">
                            {count > 1 && (
                              <button type="button" className="btn-ghost p-0.5 text-gray-400 hover:text-indigo-500"
                                onClick={() => setExpandedGroups(s => { const n = new Set(s); n.has(groupKey) ? n.delete(groupKey) : n.add(groupKey); return n; })}>
                                <ChevronDown size={14} className={`transition-transform ${isExpanded ? "" : "-rotate-90"}`} />
                              </button>
                            )}
                          </td>
                          <td className="py-2 pr-4 text-gray-800 dark:text-gray-200 max-w-xs">
                            <div className="flex items-center gap-2">
                              <span className="truncate">{row.description}</span>
                              {count > 1 && <span className="shrink-0 px-1.5 py-0.5 rounded-full bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300 text-xs font-medium">{count}×</span>}
                            </div>
                          </td>
                          <td className={`py-2 pr-4 text-right font-semibold tabular-nums whitespace-nowrap ${totalAmount < 0 ? "text-red-600" : "text-green-600"}`}>
                            {fmt(totalAmount)}
                          </td>
                          <td className="py-2 min-w-[180px]">
                            <select
                              className={`input py-1 text-xs w-full ${needsReviewGroup ? "border-amber-300" : ""}`}
                              value={representative.category_id ?? ""}
                              onChange={e => setCategoryForGroup(indices, e.target.value)}
                            >
                              <option value="">No category</option>
                              {tab === "checking" && incomeCats.length > 0 && (
                                <optgroup label="── Income ──">
                                  {incomeCats.map((c: any) => <option key={c.id} value={c.id}>{c.parent_id ? "  " : ""}{c.name}</option>)}
                                </optgroup>
                              )}
                              <optgroup label="── Expenses ──">
                                {expenseCats.map((c: any) => <option key={c.id} value={c.id}>{c.parent_id ? "  " : ""}{c.name}</option>)}
                              </optgroup>
                              <option value="new">+ New category…</option>
                            </select>
                          </td>
                          {tab === "card" && (
                            <td className="py-2">
                              <button type="button" title="Add as recurring expense" className="btn-ghost p-1 text-gray-400 hover:text-indigo-500"
                                onClick={() => setRecurringModal({
                                  name: row.description,
                                  amount: String(Math.abs(Number(row.amount))),
                                  dayOfMonth: String(new Date(row.date + "T12:00:00").getDate()),
                                  categoryId: representative.category_id ? String(representative.category_id) : "",
                                  accountId: checkingAccounts.length > 0 ? String((checkingAccounts[0] as any).id) : "",
                                  startDate: new Date().toISOString().split("T")[0],
                                })}>
                                <Repeat size={14} />
                              </button>
                            </td>
                          )}
                        </tr>
                        {isExpanded && indices.map(i => {
                          const r = editedRows[i];
                          return (
                            <tr key={`exp-${i}`} className="border-b border-gray-50 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-800/30">
                              <td className="py-1.5 pr-2 pl-4">
                                <input type="checkbox" checked={r.included} onChange={() => toggleIncluded(i)} className="rounded border-gray-300" />
                              </td>
                              <td></td>
                              <td className="py-1.5 pr-4 text-xs text-gray-500 pl-2">{r.date}</td>
                              <td className={`py-1.5 pr-4 text-right text-xs tabular-nums whitespace-nowrap ${Number(r.amount) < 0 ? "text-red-500" : "text-green-500"}`}>
                                {fmt(Number(r.amount))}
                              </td>
                              <td colSpan={tab === "card" ? 2 : 1} className="py-1.5 text-xs text-gray-400 pl-2">{r.notes || "—"}</td>
                            </tr>
                          );
                        })}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
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
                  {tab === "card" && <th className="text-left py-2 text-gray-500 font-medium w-8"></th>}
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
                          {row.suggested_recurring_item_name && row.recurring_item_id === row.suggested_recurring_item_id && (
                            <span className="text-xs text-amber-600 dark:text-amber-400 font-medium block mb-0.5">→ {row.suggested_recurring_item_name}</span>
                          )}
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
                          {(() => {
                            if (!row.recurring_item_id) return null;
                            const linked = (recurringItems as any[]).find((r: any) => r.id === row.recurring_item_id);
                            if (!linked) return null;
                            const txnAmt = Math.abs(Number(row.amount));
                            const recurAmt = Math.abs(Number(linked.amount));
                            if (Math.abs(txnAmt - recurAmt) < 0.01) return null;
                            return (
                              <button type="button"
                                className="mt-0.5 text-xs text-amber-600 hover:text-amber-700 underline block"
                                onClick={() => updateRecurringMut.mutate({ id: linked.id, data: { amount: txnAmt } })}>
                                Update to {fmt(txnAmt)}
                              </button>
                            );
                          })()}
                        </td>
                      )}
                      {tab === "card" && (
                        <td className="py-2">
                          <button
                            type="button"
                            title="Add as recurring expense"
                            className="btn-ghost p-1 text-gray-400 hover:text-indigo-500"
                            onClick={() => setRecurringModal({
                              name: row.description,
                              amount: String(Math.abs(row.amount)),
                              dayOfMonth: String(new Date(row.date + "T12:00:00").getDate()),
                              categoryId: row.category_id ? String(row.category_id) : "",
                              accountId: checkingAccounts.length > 0 ? String((checkingAccounts[0] as any).id) : "",
                              startDate: new Date().toISOString().split("T")[0],
                            })}
                          >
                            <Repeat size={14} />
                          </button>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          )}
        </div>
      )}
      {showHelp && <HelpPanel title="Import Transactions" body={"Upload a CSV file to import transactions from your bank.\n\nSupported formats: Chase checking, Chase card, Apple Card, and generic CSV.\n\nEach row gets auto-categorized. You can change any category using the dropdown — or create a new category inline with '+ New category…'\n\nTransfer rows (CC autopay, etc.) are detected and unchecked by default to prevent double-counting. You can re-check them if needed."} onClose={() => setShowHelp(false)} />}

      {recurringSuccess && (
        <div className="fixed bottom-6 right-6 bg-green-600 text-white text-sm px-4 py-2 rounded-xl shadow-lg z-50">
          {recurringSuccess}
        </div>
      )}

      {recurringModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-gray-900 dark:text-gray-100">Add as Recurring Expense</h3>
              <button onClick={() => setRecurringModal(null)} className="text-gray-400 hover:text-gray-600"><X size={16} /></button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="label">Name</label>
                <input className="input" value={recurringModal.name} onChange={e => setRecurringModal(m => m && { ...m, name: e.target.value })} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Amount ($)</label>
                  <input type="number" step="0.01" className="input" value={recurringModal.amount} onChange={e => setRecurringModal(m => m && { ...m, amount: e.target.value })} />
                </div>
                <div>
                  <label className="label">Day of Month</label>
                  <input type="number" min="1" max="31" className="input" value={recurringModal.dayOfMonth} onChange={e => setRecurringModal(m => m && { ...m, dayOfMonth: e.target.value })} />
                </div>
              </div>
              <div>
                <label className="label">Linked Account</label>
                <select className="input" value={recurringModal.accountId} onChange={e => setRecurringModal(m => m && { ...m, accountId: e.target.value })}>
                  <option value="">Select account…</option>
                  {checkingAccounts.map((a: any) => (
                    <option key={a.id} value={a.id}>{a.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">Start Date</label>
                <input type="date" className="input" value={recurringModal.startDate} onChange={e => setRecurringModal(m => m && { ...m, startDate: e.target.value })} />
              </div>
              <div>
                <label className="label">Category (optional)</label>
                <select className="input" value={recurringModal.categoryId} onChange={e => setRecurringModal(m => m && { ...m, categoryId: e.target.value })}>
                  <option value="">No category</option>
                  {expenseCats.map((c: any) => (
                    <option key={c.id} value={c.id}>{c.parent_id ? "  " : ""}{c.name}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => createRecurringMut.mutate({
                  name: recurringModal.name,
                  amount: parseFloat(recurringModal.amount),
                  day_of_month: parseInt(recurringModal.dayOfMonth),
                  category_id: recurringModal.categoryId ? parseInt(recurringModal.categoryId) : null,
                  account_id: parseInt(recurringModal.accountId),
                  start_date: recurringModal.startDate,
                  card_id: tab === "card" && sourceId ? sourceId : null,
                  type: "expense",
                  frequency: "monthly",
                  is_active: true,
                })}
                disabled={!recurringModal.name || !recurringModal.amount || !recurringModal.accountId || !recurringModal.startDate || createRecurringMut.isPending}
                className="btn-primary flex-1"
              >
                {createRecurringMut.isPending ? "Saving…" : "Add Recurring"}
              </button>
              <button onClick={() => setRecurringModal(null)} className="btn-secondary">Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
