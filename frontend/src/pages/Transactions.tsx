import { useState, useEffect, useRef } from "react";
import { useQuery, useQueries, useMutation, useQueryClient } from "@tanstack/react-query";
import { transactionsApi, accountsApi, categoriesApi, cardsApi, authApi, reconciliationApi, exportsApi, dayCheckpointsApi, recurringApi } from "../api";
import { fmt, today, firstOfMonth, quickRange } from "../lib/utils";
import { Plus, Trash2, X, HelpCircle, CheckCircle2, AlertCircle, Download, Link2, Check, Upload, Landmark, Code2 } from "lucide-react";
import HelpPanel from "../components/HelpPanel";
import { VerificationFlagButton } from "../components/VerificationFlagButton";

// A single row shape both checking transactions and card charges normalize
// into for the "All" tab -- lets one table render a chronological, source-
// tagged view across every account and card without either data shape
// leaking through.
interface UnifiedRow {
  id: number;
  kind: "checking" | "card";
  date: string;
  description: string;
  // Normalized to checking's sign convention (spend = negative, credit/
  // refund = positive) regardless of source. Card transactions store the
  // OPPOSITE convention (positive = charge) -- displaying that raw would
  // color every card purchase green in a list that's mostly checking debits.
  amount: number;
  source: string;
  sourceLabel: string;
  externalId: string | null;
  categoryName: string | null;
  notes: string | null;
  recurringName: string | null;
  isActual: boolean;
}

function RawDataButton({ externalId }: { externalId: string }) {
  const [open, setOpen] = useState(false);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["raw-txn", externalId],
    queryFn: () => transactionsApi.raw(externalId),
    enabled: open,
    retry: false,
  });
  return (
    <div className="relative inline-block">
      <button
        onClick={() => setOpen(o => !o)}
        className="text-gray-300 hover:text-amber-500 shrink-0"
        title="View raw bank data (debug)"
      >
        <Code2 size={13} />
      </button>
      {open && (
        <div className="absolute z-10 right-0 mt-1 w-80 max-h-64 overflow-auto card p-2 shadow-lg text-left">
          {isLoading && <p className="text-xs text-gray-400">Loading…</p>}
          {isError && <p className="text-xs text-gray-400">No raw data captured for this transaction — turn on "Capture Raw Bank Data" in Settings → Preferences before the next sync.</p>}
          {data && (
            <pre className="text-[10px] whitespace-pre-wrap break-all text-gray-600 dark:text-gray-300">
              {JSON.stringify(JSON.parse(data.raw_json), null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

// Small inline indicator for where a transaction came from -- manual entry is
// the unmarked default (most common, shouldn't add visual noise); CSV/OFX
// import and bank sync each get a distinct icon + tooltip.
function SourceBadge({ source }: { source: string }) {
  if (source === "csv_import") return <span title="Imported from CSV/OFX" className="shrink-0"><Upload size={12} className="text-blue-400" /></span>;
  if (source === "bank_sync") return <span title="Synced from your bank" className="shrink-0"><Landmark size={12} className="text-indigo-400" /></span>;
  return null;
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

type TxnTab = "all" | "checking" | "card" | "reconcile";

interface CategoryCellProps {
  txnId: number;
  catId: number | null;
  onSave: (id: number | null) => void;
  editingCatId: number | null;
  setEditingCatId: (id: number | null) => void;
  allCats: any[];
  catMap: Record<number, string>;
}

function CategoryCell({ txnId, catId, onSave, editingCatId, setEditingCatId, allCats, catMap }: CategoryCellProps) {
  const isEditing = editingCatId === txnId;
  if (isEditing) {
    return (
      <select
        autoFocus
        className="input py-0.5 text-xs"
        defaultValue={catId ?? ""}
        onBlur={() => setEditingCatId(null)}
        onChange={e => {
          const val = e.target.value;
          onSave(val === "" ? null : parseInt(val));
        }}
      >
        <option value="">No category</option>
        {allCats.map((c: any) => (
          <option key={c.id} value={c.id}>{c.parent_id ? "  " : ""}{c.name}</option>
        ))}
      </select>
    );
  }
  return (
    <button
      onClick={() => setEditingCatId(txnId)}
      className={`px-2 py-0.5 rounded text-xs font-medium transition-colors hover:opacity-80 ${
        catId ? "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300" : "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400"
      }`}
    >
      {catId ? catMap[catId] ?? "—" : "Uncategorized"}
    </button>
  );
}

const emptyForm = { account_id: "", category_id: "", date: today(), amount: "", description: "", notes: "" };

export default function Transactions() {
  const qc = useQueryClient();
  const [showHelp, setShowHelp] = useState(false);
  // Defaults to the unified view: the question is almost always "what happened
  // recently", not "what happened on this one account", and the split tabs
  // made you check two places to answer it.
  const [txnTab, setTxnTab] = useState<TxnTab>("all");
  const [start, setStart] = useState(firstOfMonth());
  const [end, setEnd] = useState(today());
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ ...emptyForm });
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [editingCatId, setEditingCatId] = useState<number | null>(null);
  const [editingNotesId, setEditingNotesId] = useState<number | null>(null);
  const [notesValue, setNotesValue] = useState("");
  const [selectedCardId, setSelectedCardId] = useState<number | null>(null);
  const [reconcileAccountId, setReconcileAccountId] = useState<number | null>(null);
  const now = new Date();
  const [reconcileYear, setReconcileYear] = useState(now.getFullYear());
  const [reconcileMonth, setReconcileMonth] = useState(now.getMonth() + 1);
  const [linkingTxnId, setLinkingTxnId] = useState<number | null>(null);
  const [addForRecurringId, setAddForRecurringId] = useState<number | null>(null);
  const [markReconciledBalance, setMarkReconciledBalance] = useState("");

  // Search & filter state
  const [searchQ, setSearchQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [filterCatId, setFilterCatId] = useState<number | null>(null);
  const [filterAmountMin, setFilterAmountMin] = useState("");
  const [filterAmountMax, setFilterAmountMax] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setDebouncedQ(searchQ), 300);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [searchQ]);

  const { data: txns = [], isLoading } = useQuery({
    queryKey: ["transactions", start, end, debouncedQ, filterCatId, filterAmountMin, filterAmountMax],
    queryFn: () => transactionsApi.list({
      start, end,
      q: debouncedQ || undefined,
      category_id: filterCatId || undefined,
      amount_min: filterAmountMin || undefined,
      amount_max: filterAmountMax || undefined,
    }),
    enabled: txnTab === "checking" || txnTab === "all",
  });
  const { data: accounts = [] } = useQuery({ queryKey: ["accounts"], queryFn: accountsApi.list });
  const { data: categories = [] } = useQuery({ queryKey: ["categories"], queryFn: categoriesApi.list });
  // Always loaded, not reconcile-only: the unified list names the recurring
  // item a row settles, which is what distinguishes a bill from a purchase.
  const { data: allRecurring = [] } = useQuery({
    queryKey: ["recurring", "all"],
    queryFn: () => recurringApi.list(false),
  });
  const { data: cards = [] } = useQuery({ queryKey: ["cards"], queryFn: cardsApi.list });
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: authApi.me });

  const activeCardId = selectedCardId ?? (cards[0]?.id ?? null);

  const { data: cardTxns = [], isLoading: cardLoading } = useQuery({
    queryKey: ["card-transactions", activeCardId, start, end],
    queryFn: () => cardsApi.transactions(activeCardId!, { start, end }),
    enabled: txnTab === "card" && !!activeCardId,
  });

  // "All" tab: every card in parallel, unfiltered by the single-card
  // selector the "Credit Cards" tab uses. useQueries (not N useQuery calls)
  // because `cards` is only known after its own query resolves -- a fixed
  // number of hooks can't be written for a dynamic card count.
  const allCardsQueries = useQueries({
    queries: (cards as any[]).map((c: any) => ({
      queryKey: ["card-transactions", c.id, start, end],
      queryFn: () => cardsApi.transactions(c.id, { start, end }),
      enabled: txnTab === "all",
    })),
  });
  const allCardsLoading = txnTab === "all" && allCardsQueries.some(q => q.isLoading);

  const cardNameMap: Record<number, string> = Object.fromEntries((cards as any[]).map((c: any) => [c.id, c.name]));
  const accountNameMap: Record<number, string> = Object.fromEntries((accounts as any[]).map((a: any) => [a.id, a.name]));
  // /categories returns a TREE -- six top-level rows with nested children --
  // so a flat map over the response only knows the parents, and every
  // transaction filed against a child (which is nearly all of them) rendered
  // as "Uncategorized". Walk it.
  const categoryNameMap: Record<number, string> = {};
  const walkCategories = (list: any[]) => list.forEach((c: any) => {
    categoryNameMap[c.id] = c.name;
    if (c.children?.length) walkCategories(c.children);
  });
  walkCategories(categories as any[]);
  const recurringNameMap: Record<number, string> = Object.fromEntries((allRecurring as any[]).map((r: any) => [r.id, r.name]));

  const unifiedRows: UnifiedRow[] = txnTab === "all" ? [
    ...txns.map((t: any) => ({
      id: t.id, kind: "checking" as const, date: t.date, description: t.description,
      amount: parseFloat(t.amount), source: t.source, sourceLabel: accountNameMap[t.account_id] ?? "Checking",
      externalId: t.external_id ?? null,
      categoryName: categoryNameMap[t.category_id] ?? null,
      notes: t.notes ?? null,
      // Naming the recurring item a row settles is what turns "another $500.89
      // debit" into "that's the Rivian payment" without opening anything.
      recurringName: recurringNameMap[t.recurring_item_id] ?? null,
      isActual: t.is_actual !== false,
    })),
    ...allCardsQueries.flatMap((q, i) => (q.data ?? []).map((t: any) => ({
      id: t.id, kind: "card" as const, date: t.date, description: t.merchant || t.description || "",
      amount: -parseFloat(t.amount), // flip: card convention is positive=charge, opposite of checking
      source: t.source, sourceLabel: cardNameMap[(cards as any[])[i]?.id] ?? "Card",
      externalId: t.external_id ?? null,
      categoryName: categoryNameMap[t.category_id] ?? null,
      notes: t.description && t.merchant && t.description !== t.merchant ? t.description : null,
      recurringName: null,
      isActual: true,
    }))),
  ]
    .filter(r => {
      if (debouncedQ && !r.description.toLowerCase().includes(debouncedQ.toLowerCase())) return false;
      const amt = Math.abs(r.amount);
      if (filterAmountMin && amt < parseFloat(filterAmountMin)) return false;
      if (filterAmountMax && amt > parseFloat(filterAmountMax)) return false;
      return true;
    })
    .sort((a, b) => b.date.localeCompare(a.date) || b.id - a.id) : [];

  const activeReconcileAccountId = reconcileAccountId ?? ((accounts as any[]).filter((a: any) => a.type === "checking")[0]?.id ?? null);
  const { data: reconcileData, isLoading: reconcileLoading } = useQuery({
    queryKey: ["reconcile", activeReconcileAccountId, reconcileYear, reconcileMonth],
    queryFn: () => reconciliationApi.get(activeReconcileAccountId!, reconcileYear, reconcileMonth),
    enabled: txnTab === "reconcile" && !!activeReconcileAccountId,
  });
  const { data: recurringItems = [] } = useQuery({
    queryKey: ["recurring"],
    queryFn: () => recurringApi.list(),
    enabled: txnTab === "reconcile",
  });

  const allCats = categories.flatMap((c: any) => [c, ...(c.children ?? [])]);

  const createMut = useMutation({
    mutationFn: transactionsApi.create,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      setShowForm(false);
      setForm({ ...emptyForm });
    },
  });
  const deleteMut = useMutation({
    mutationFn: transactionsApi.remove,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      setDeleteId(null);
    },
  });
  const updateCatMut = useMutation({
    mutationFn: ({ id, data }: any) => transactionsApi.update(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      setEditingCatId(null);
    },
  });
  const updateNotesMut = useMutation({
    mutationFn: ({ id, notes }: { id: number; notes: string | null }) => transactionsApi.update(id, { notes }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["transactions"] }); setEditingNotesId(null); },
  });
  const updateCardCatMut = useMutation({
    mutationFn: ({ cardId, txnId, data }: any) => cardsApi.updateTransaction(cardId, txnId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["card-transactions"] });
      setEditingCatId(null);
    },
  });

  const linkRecurringMut = useMutation({
    mutationFn: ({ txnId, recurringItemId }: { txnId: number; recurringItemId: number }) =>
      transactionsApi.update(txnId, { recurring_item_id: recurringItemId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reconcile"] });
      setLinkingTxnId(null);
    },
  });

  const addRecurringTxnMut = useMutation({
    mutationFn: (data: object) => transactionsApi.create(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reconcile"] });
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      setAddForRecurringId(null);
    },
  });

  const markReconciledMut = useMutation({
    mutationFn: ({ year, month, balance }: { year: number; month: number; balance: number }) => {
      // Use last day of the reconcile month as the day-level anchor
      const lastDay = new Date(year, month, 0);
      const dateStr = `${lastDay.getFullYear()}-${String(lastDay.getMonth() + 1).padStart(2, '0')}-${String(lastDay.getDate()).padStart(2, '0')}`;
      return dayCheckpointsApi.upsert(dateStr, activeReconcileAccountId!, balance, "Reconciled");
    },
    onSuccess: () => {
      setMarkReconciledBalance("");
      qc.invalidateQueries({ queryKey: ["day-checkpoints"] });
      qc.invalidateQueries({ queryKey: ["forecast-quarters"] });
      qc.invalidateQueries({ queryKey: ["forecast-multi-year"] });
    },
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    createMut.mutate({
      ...form,
      account_id: parseInt(form.account_id),
      category_id: form.category_id ? parseInt(form.category_id) : null,
      amount: parseFloat(form.amount),
    });
  }

  function handleCatChange(txnId: number, catId: number | null) {
    updateCatMut.mutate({ id: txnId, data: { category_id: catId } });
  }

  function handleCardCatChange(txnId: number, catId: number | null) {
    if (!activeCardId) return;
    updateCardCatMut.mutate({ cardId: activeCardId, txnId, data: { category_id: catId } });
  }

  const accountMap = Object.fromEntries(accounts.map((a: any) => [a.id, a.name]));
  const catMap = Object.fromEntries(allCats.map((c: any) => [c.id, c.name]));
  const loading = txnTab === "checking" ? isLoading : txnTab === "all" ? (isLoading || allCardsLoading) : cardLoading;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100 flex items-center gap-1.5">Transactions <button onClick={() => setShowHelp(true)} className="text-gray-400 hover:text-indigo-500 font-normal"><HelpCircle size={15} /></button></h2>
          {txnTab !== "reconcile" && (
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {txnTab === "checking"
                ? `${txns.length} transaction${txns.length !== 1 ? "s" : ""}`
                : txnTab === "all"
                  ? `${unifiedRows.length} transaction${unifiedRows.length !== 1 ? "s" : ""} across ${1 + (cards as any[]).length} account${(cards as any[]).length !== 0 ? "s" : ""}`
                  : `${cardTxns.length} card charge${cardTxns.length !== 1 ? "s" : ""}`}
            </p>
          )}
        </div>
        <div className="flex gap-2 flex-wrap">
          <div className="flex rounded-lg bg-gray-100 dark:bg-gray-700 p-1">
            {(["all", "checking", "card", "reconcile"] as TxnTab[]).map(t => (
              <button key={t} type="button"
                onClick={() => setTxnTab(t)}
                className={`px-3 py-1 text-xs font-medium rounded-md capitalize transition-colors ${txnTab === t ? "bg-white dark:bg-gray-800 shadow-sm text-gray-900 dark:text-gray-100" : "text-gray-500 dark:text-gray-300"}`}>
                {t === "all" ? "All" : t === "checking" ? "Checking" : t === "card" ? "Credit Cards" : "Reconcile"}
              </button>
            ))}
          </div>
          {txnTab === "card" && cards.length > 0 && (
            <select className="input w-auto text-sm" value={activeCardId ?? ""} onChange={e => setSelectedCardId(parseInt(e.target.value))}>
              {cards.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
          {txnTab !== "reconcile" && <>
            <div className="flex gap-1">
              {([["Mo", "month"], ["3 Mo", "3months"], ["YTD", "ytd"], ["Last Yr", "lastyear"]] as const).map(([label, p]) => (
                <button key={p} type="button" className="px-2 py-1 text-xs rounded-md bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 hover:text-indigo-600 dark:hover:text-indigo-400" onClick={() => { const r = quickRange(p); setStart(r.start); setEnd(r.end); }}>{label}</button>
              ))}
            </div>
            <input type="date" className="input w-auto" value={start} onChange={e => setStart(e.target.value)} />
            <span className="self-center text-gray-400">→</span>
            <input type="date" className="input w-auto" value={end} onChange={e => setEnd(e.target.value)} />
          </>}
          {txnTab === "checking" && (
            <>
              <button
                onClick={() => exportsApi.downloadTransactions({ start, end }).then(blob => downloadBlob(blob, "transactions.csv"))}
                className="btn-secondary text-sm"
                title="Export CSV"
              >
                <Download size={15} />
              </button>
              <button onClick={() => setShowForm(true)} className="btn-primary"><Plus size={16} /> Add</button>
            </>
          )}
        </div>
      </div>

      {/* Filter bar — checking and all tabs */}
      {(txnTab === "checking" || txnTab === "all") && (
        <div className="flex flex-wrap gap-2">
          <input
            className="input flex-1 min-w-[12rem] text-sm"
            placeholder="Search descriptions…"
            value={searchQ}
            onChange={e => setSearchQ(e.target.value)}
          />
          {txnTab === "checking" && (
            <select
              className="input w-auto text-sm"
              value={filterCatId ?? ""}
              onChange={e => setFilterCatId(e.target.value ? parseInt(e.target.value) : null)}
            >
              <option value="">All categories</option>
              {allCats.map((c: any) => (
                <option key={c.id} value={c.id}>{c.parent_id ? "  " : ""}{c.name}</option>
              ))}
            </select>
          )}
          <input type="number" className="input w-28 text-sm" placeholder="Min $" step="0.01"
            value={filterAmountMin} onChange={e => setFilterAmountMin(e.target.value)} />
          <input type="number" className="input w-28 text-sm" placeholder="Max $" step="0.01"
            value={filterAmountMax} onChange={e => setFilterAmountMax(e.target.value)} />
          {(searchQ || filterCatId || filterAmountMin || filterAmountMax) && (
            <button
              onClick={() => { setSearchQ(""); setFilterCatId(null); setFilterAmountMin(""); setFilterAmountMax(""); }}
              className="btn-ghost text-sm text-gray-400 px-2"
              title="Clear filters"
            ><X size={14} /></button>
          )}
        </div>
      )}

      {txnTab !== "reconcile" && <div className="card overflow-hidden p-0">
        {loading && <p className="text-sm text-gray-400 text-center py-8">Loading…</p>}

        {/* All: checking + every card, merged and sorted chronologically */}
        {txnTab === "all" && !loading && (
          <>
            {unifiedRows.length === 0 && <p className="text-sm text-gray-400 text-center py-8">No transactions in this period</p>}
            {unifiedRows.length > 0 && (
              <table className="w-full text-sm">
                <thead className="bg-gray-50 dark:bg-gray-800/50 border-b border-gray-100 dark:border-gray-700">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase hidden lg:table-cell">Category</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase hidden md:table-cell">Source</th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Amount</th>
                    {me?.debug_capture_raw_bank_data && <th className="px-4 py-3 w-8"></th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
                  {unifiedRows.map(r => (
                    <tr key={`${r.kind}-${r.id}`} className="hover:bg-gray-50 dark:hover:bg-gray-800/30">
                      <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                        {new Date(r.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                      </td>
                      <td className="px-4 py-3 text-gray-900 dark:text-gray-100 max-w-sm">
                        <div className="truncate flex items-center gap-1.5">
                          <SourceBadge source={r.source} />
                          {r.description}
                          {!r.isActual && (
                            <span className="shrink-0 text-[10px] uppercase tracking-wide px-1 rounded bg-gray-100 dark:bg-gray-800 text-gray-500">
                              pending
                            </span>
                          )}
                        </div>
                        {/* Everything that doesn't earn a column of its own but
                            changes what the row means. */}
                        <div className="flex flex-wrap items-center gap-x-2 text-xs text-gray-400">
                          <span className="lg:hidden">{r.categoryName ?? "Uncategorized"}</span>
                          <span className="md:hidden">{r.sourceLabel}</span>
                          {r.recurringName && (
                            <span className="text-indigo-500 dark:text-indigo-300">↻ {r.recurringName}</span>
                          )}
                          {r.notes && <span className="truncate italic">{r.notes}</span>}
                        </div>
                      </td>
                      <td className="px-4 py-3 hidden lg:table-cell">
                        {r.categoryName
                          ? <span className="text-xs text-gray-600 dark:text-gray-300">{r.categoryName}</span>
                          : <span className="text-xs text-gray-300 dark:text-gray-400 italic">Uncategorized</span>}
                      </td>
                      <td className="px-4 py-3 text-gray-500 hidden md:table-cell">
                        <span className={`text-xs px-1.5 py-0.5 rounded ${r.kind === "card" ? "bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400" : "bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400"}`}>
                          {r.sourceLabel}
                        </span>
                      </td>
                      <td className={`px-4 py-3 text-right font-semibold tabular-nums ${r.amount >= 0 ? "text-green-600" : "text-red-600"}`}>
                        {r.amount >= 0 ? "+" : ""}{fmt(r.amount)}
                      </td>
                      {me?.debug_capture_raw_bank_data && (
                        <td className="px-4 py-3 text-right">
                          {r.externalId && <RawDataButton externalId={r.externalId} />}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}

        {/* Checking transactions */}
        {txnTab === "checking" && !loading && (
          <>
            {txns.length === 0 && <p className="text-sm text-gray-400 text-center py-8">No transactions in this period</p>}
            {txns.length > 0 && (
              <table className="w-full text-sm">
                <thead className="bg-gray-50 dark:bg-gray-800/50 border-b border-gray-100 dark:border-gray-700">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase hidden sm:table-cell">Category</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase hidden md:table-cell">Account</th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Amount</th>
                    <th className="px-4 py-3 w-16"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
                  {txns.map((t: any) => (
                    <tr key={t.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/30">
                      <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                        {new Date(t.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                      </td>
                      <td className="px-4 py-3 text-gray-900 dark:text-gray-100 max-w-xs">
                        <div className="truncate flex items-center gap-1.5"><SourceBadge source={t.source} />{t.description}</div>
                        {editingNotesId === t.id ? (
                          <input
                            autoFocus
                            className="input py-0.5 text-xs mt-0.5 w-full"
                            value={notesValue}
                            onChange={e => setNotesValue(e.target.value)}
                            onBlur={() => updateNotesMut.mutate({ id: t.id, notes: notesValue || null })}
                            onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); updateNotesMut.mutate({ id: t.id, notes: notesValue || null }); } if (e.key === "Escape") setEditingNotesId(null); }}
                            placeholder="Add note…"
                          />
                        ) : (
                          <button
                            onClick={() => { setEditingNotesId(t.id); setNotesValue(t.notes ?? ""); }}
                            className={`text-xs truncate block max-w-full text-left ${t.notes ? "text-gray-400 dark:text-gray-400 hover:text-indigo-500" : "text-gray-200 dark:text-gray-300 hover:text-gray-400"}`}
                          >
                            {t.notes || "add note…"}
                          </button>
                        )}
                      </td>
                      <td className="px-4 py-3 hidden sm:table-cell">
                        <CategoryCell txnId={t.id} catId={t.category_id} onSave={catId => handleCatChange(t.id, catId)} editingCatId={editingCatId} setEditingCatId={setEditingCatId} allCats={allCats} catMap={catMap} />
                      </td>
                      <td className="px-4 py-3 text-gray-500 hidden md:table-cell">{accountMap[t.account_id] ?? "—"}</td>
                      <td className={`px-4 py-3 text-right font-semibold tabular-nums ${parseFloat(t.amount) >= 0 ? "text-green-600" : "text-red-600"}`}>
                        {parseFloat(t.amount) >= 0 ? "+" : ""}{fmt(t.amount)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-2">
                          <VerificationFlagButton
                            feature="transactions"
                            referenceType="transaction"
                            referenceId={t.id}
                            observed={{ date: t.date, amount: t.amount, description: t.description, category: t.category_id ? catMap[t.category_id] ?? null : null, category_id: t.category_id }}
                            expectedFields={[{ key: "amount", label: "Amount" }]}
                          />
                          <button onClick={() => setDeleteId(t.id)} className="text-gray-300 hover:text-red-500"><Trash2 size={14} /></button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}

        {/* Card transactions */}
        {txnTab === "card" && !loading && (
          <>
            {cards.length === 0 && <p className="text-sm text-gray-400 text-center py-8">No credit cards configured</p>}
            {cards.length > 0 && cardTxns.length === 0 && <p className="text-sm text-gray-400 text-center py-8">No card transactions in this period</p>}
            {cardTxns.length > 0 && (
              <table className="w-full text-sm">
                <thead className="bg-gray-50 dark:bg-gray-800/50 border-b border-gray-100 dark:border-gray-700">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Merchant</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase hidden sm:table-cell">Category</th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Amount</th>
                    <th className="px-4 py-3 w-10"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
                  {cardTxns.map((t: any) => (
                    <tr key={t.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/30">
                      <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                        {new Date(t.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                      </td>
                      <td className="px-4 py-3 text-gray-900 dark:text-gray-100 max-w-xs">
                        <div className="truncate flex items-center gap-1.5"><SourceBadge source={t.source} />{t.merchant}</div>
                      </td>
                      <td className="px-4 py-3 hidden sm:table-cell">
                        <CategoryCell txnId={t.id} catId={t.category_id} onSave={catId => handleCardCatChange(t.id, catId)} editingCatId={editingCatId} setEditingCatId={setEditingCatId} allCats={allCats} catMap={catMap} />
                      </td>
                      <td className="px-4 py-3 text-right font-semibold tabular-nums text-red-600">
                        {fmt(t.amount)}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <VerificationFlagButton
                          feature="transactions"
                          referenceType="card_transaction"
                          referenceId={t.id}
                          observed={{ date: t.date, amount: t.amount, merchant: t.merchant, category: t.category_id ? catMap[t.category_id] ?? null : null, category_id: t.category_id }}
                          expectedFields={[{ key: "amount", label: "Amount" }]}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>}

      {/* Reconcile tab */}
      {txnTab === "reconcile" && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <select className="input w-auto text-sm" value={activeReconcileAccountId ?? ""} onChange={e => setReconcileAccountId(parseInt(e.target.value))}>
              {(accounts as any[]).filter((a: any) => a.type === "checking").map((a: any) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
            <select className="input w-auto text-sm" value={reconcileYear} onChange={e => setReconcileYear(parseInt(e.target.value))}>
              {[-1, 0, 1].map(d => { const y = new Date().getFullYear() + d; return <option key={y} value={y}>{y}</option>; })}
            </select>
            <select className="input w-auto text-sm" value={reconcileMonth} onChange={e => setReconcileMonth(parseInt(e.target.value))}>
              {["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"].map((m, i) => (
                <option key={i+1} value={i+1}>{m}</option>
              ))}
            </select>
            {/* Mark reconciled */}
            <div className="flex items-center gap-2 ml-auto">
              <input
                type="number" step="0.01" placeholder="Actual balance"
                className="input w-36 text-sm"
                value={markReconciledBalance}
                onChange={e => setMarkReconciledBalance(e.target.value)}
              />
              <button
                className="btn-primary text-xs px-3 py-2 flex items-center gap-1"
                disabled={!markReconciledBalance || markReconciledMut.isPending}
                onClick={() => {
                  markReconciledMut.mutate({ year: reconcileYear, month: reconcileMonth, balance: parseFloat(markReconciledBalance) });
                }}
              >
                <Check size={13} />
                {markReconciledMut.isPending ? "Saving…" : "Mark Reconciled"}
              </button>
            </div>
          </div>
          {reconcileLoading && <p className="text-sm text-gray-400 text-center py-8">Loading…</p>}
          {!reconcileLoading && reconcileData && (
            <div className="space-y-4">
              {reconcileData.matched.length > 0 && (
                <div className="card p-0 overflow-hidden">
                  <div className="px-4 py-3 bg-green-50 dark:bg-green-900/20 border-b border-green-100 dark:border-green-800 flex items-center gap-2">
                    <CheckCircle2 size={15} className="text-green-600" />
                    <h3 className="text-sm font-semibold text-green-800 dark:text-green-300">Matched ({reconcileData.matched.length})</h3>
                  </div>
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 dark:bg-gray-800/50">
                      <tr>
                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase hidden sm:table-cell">Recurring Item</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Actual</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase hidden sm:table-cell">Expected</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase hidden md:table-cell">Variance</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
                      {reconcileData.matched.map((item: any) => (
                        <tr key={item.transaction_id} className="hover:bg-gray-50 dark:hover:bg-gray-800/30">
                          <td className="px-4 py-2 text-gray-500 whitespace-nowrap">
                            {new Date(item.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                          </td>
                          <td className="px-4 py-2 text-gray-900 dark:text-gray-100 max-w-xs truncate">{item.description}</td>
                          <td className="px-4 py-2 text-gray-500 hidden sm:table-cell">{item.recurring_name}</td>
                          <td className={`px-4 py-2 text-right font-semibold tabular-nums ${parseFloat(item.actual_amount) >= 0 ? "text-green-600" : "text-red-600"}`}>
                            {fmt(item.actual_amount)}
                          </td>
                          <td className="px-4 py-2 text-right text-gray-500 tabular-nums hidden sm:table-cell">{fmt(item.expected_amount)}</td>
                          <td className={`px-4 py-2 text-right tabular-nums hidden md:table-cell ${Math.abs(parseFloat(item.variance)) > 0.01 ? "text-amber-600" : "text-gray-400"}`}>
                            {parseFloat(item.variance) > 0 ? "+" : ""}{fmt(item.variance)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {reconcileData.unmatched_recurring.length > 0 && (
                <div className="card p-0 overflow-hidden">
                  <div className="px-4 py-3 bg-amber-50 dark:bg-amber-900/20 border-b border-amber-100 dark:border-amber-800 flex items-center gap-2">
                    <AlertCircle size={15} className="text-amber-600" />
                    <h3 className="text-sm font-semibold text-amber-800 dark:text-amber-300">Expected but not recorded ({reconcileData.unmatched_recurring.length})</h3>
                  </div>
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 dark:bg-gray-800/50">
                      <tr>
                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Recurring Item</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Expected Amount</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase hidden sm:table-cell">Expected Day</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
                      {reconcileData.unmatched_recurring.map((item: any) => (
                        <tr key={item.recurring_item_id} className="hover:bg-gray-50 dark:hover:bg-gray-800/30">
                          <td className="px-4 py-2 text-gray-900 dark:text-gray-100">{item.name}</td>
                          <td className="px-4 py-2 text-right font-semibold tabular-nums text-red-600">{fmt(item.expected_amount)}</td>
                          <td className="px-4 py-2 text-right text-gray-500 hidden sm:table-cell">{item.expected_day ?? "last"}</td>
                          <td className="px-4 py-2 text-right">
                            {addForRecurringId === item.recurring_item_id ? (
                              <div className="flex items-center gap-2 justify-end">
                                <span className="text-xs text-gray-500">Add {reconcileYear}-{String(reconcileMonth).padStart(2, "0")}-{String(item.expected_day ?? 28).padStart(2, "0")} for {fmt(item.expected_amount)}?</span>
                                <button
                                  className="text-xs bg-green-600 hover:bg-green-700 text-white px-2 py-1 rounded font-medium"
                                  disabled={addRecurringTxnMut.isPending}
                                  onClick={() => addRecurringTxnMut.mutate({
                                    account_id: activeReconcileAccountId,
                                    recurring_item_id: item.recurring_item_id,
                                    date: `${reconcileYear}-${String(reconcileMonth).padStart(2, "0")}-${String(Math.min(item.expected_day ?? 28, 28)).padStart(2, "0")}`,
                                    amount: -Math.abs(Number(item.expected_amount)),
                                    description: item.name,
                                    is_actual: true,
                                  })}
                                >Confirm</button>
                                <button className="text-xs text-gray-400 hover:text-gray-600" onClick={() => setAddForRecurringId(null)}>Cancel</button>
                              </div>
                            ) : (
                              <button
                                className="text-xs text-blue-600 hover:text-blue-700 flex items-center gap-1 ml-auto"
                                onClick={() => setAddForRecurringId(item.recurring_item_id)}
                              >
                                <Plus size={12} /> Add transaction
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {reconcileData.unmatched_transactions.length > 0 && (
                <div className="card p-0 overflow-hidden">
                  <div className="px-4 py-3 bg-blue-50 dark:bg-blue-900/20 border-b border-blue-100 dark:border-blue-800 flex items-center gap-2">
                    <AlertCircle size={15} className="text-blue-600" />
                    <h3 className="text-sm font-semibold text-blue-800 dark:text-blue-300">Unlinked transactions ({reconcileData.unmatched_transactions.length})</h3>
                  </div>
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 dark:bg-gray-800/50">
                      <tr>
                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Amount</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Link</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
                      {reconcileData.unmatched_transactions.map((item: any) => (
                        <tr key={item.transaction_id} className="hover:bg-gray-50 dark:hover:bg-gray-800/30">
                          <td className="px-4 py-2 text-gray-500 whitespace-nowrap">
                            {new Date(item.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                          </td>
                          <td className="px-4 py-2 text-gray-900 dark:text-gray-100 max-w-xs truncate">{item.description}</td>
                          <td className={`px-4 py-2 text-right font-semibold tabular-nums ${parseFloat(item.amount) >= 0 ? "text-green-600" : "text-red-600"}`}>
                            {fmt(item.amount)}
                          </td>
                          <td className="px-4 py-2 text-right">
                            {linkingTxnId === item.transaction_id ? (
                              <div className="flex items-center gap-2 justify-end">
                                <select
                                  className="input text-xs py-1 w-44"
                                  onChange={e => {
                                    if (e.target.value) {
                                      linkRecurringMut.mutate({ txnId: item.transaction_id, recurringItemId: parseInt(e.target.value) });
                                    }
                                  }}
                                  defaultValue=""
                                >
                                  <option value="">Select recurring…</option>
                                  {(recurringItems as any[])
                                    .filter((r: any) => r.account_id === activeReconcileAccountId || !r.account_id)
                                    .map((r: any) => (
                                      <option key={r.id} value={r.id}>{r.name} ({fmt(r.amount)})</option>
                                    ))
                                  }
                                </select>
                                <button className="text-xs text-gray-400 hover:text-gray-600" onClick={() => setLinkingTxnId(null)}>✕</button>
                              </div>
                            ) : (
                              <button
                                className="text-xs text-indigo-600 hover:text-indigo-700 flex items-center gap-1 ml-auto"
                                onClick={() => setLinkingTxnId(item.transaction_id)}
                              >
                                <Link2 size={12} /> Link
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {!reconcileData.matched.length && !reconcileData.unmatched_recurring.length && !reconcileData.unmatched_transactions.length && (
                <div className="card text-center py-8 text-gray-400">No transactions or recurring items for this month.</div>
              )}
            </div>
          )}
          {!reconcileLoading && !reconcileData && <div className="card text-center py-8 text-gray-400">Select an account and month to reconcile.</div>}
        </div>
      )}

      {showForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-md">
            <div className="flex justify-between items-center mb-5">
              <h3 className="font-bold text-gray-900 dark:text-gray-100">Add Transaction</h3>
              <button onClick={() => setShowForm(false)} className="btn-ghost p-1"><X size={18} /></button>
            </div>
            <form onSubmit={submit} className="space-y-3">
              <div>
                <label className="label">Account</label>
                <select className="input" value={form.account_id} onChange={e => setForm({ ...form, account_id: e.target.value })} required>
                  <option value="">Select…</option>
                  {accounts.map((a: any) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
              </div>
              <div><label className="label">Date</label><input type="date" className="input" value={form.date} onChange={e => setForm({ ...form, date: e.target.value })} required /></div>
              <div><label className="label">Description</label><input className="input" placeholder="Duke Energy bill" value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} required /></div>
              <div>
                <label className="label">Amount (negative = expense)</label>
                <input type="number" step="0.01" className="input" placeholder="-180.00" value={form.amount} onChange={e => setForm({ ...form, amount: e.target.value })} required />
              </div>
              <div>
                <label className="label">Category</label>
                <select className="input" value={form.category_id} onChange={e => setForm({ ...form, category_id: e.target.value })}>
                  <option value="">None</option>
                  {allCats.map((c: any) => <option key={c.id} value={c.id}>{c.parent_id ? "  " : ""}{c.name}</option>)}
                </select>
              </div>
              <div><label className="label">Notes</label><input className="input" value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} /></div>
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1">Add Transaction</button>
                <button type="button" onClick={() => setShowForm(false)} className="btn-secondary flex-1">Cancel</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {showHelp && <HelpPanel title="Transactions" body={"View and manage your transactions.\n\nChecking tab: all imported and manually entered checking account transactions. Click the category badge on any row to reassign it.\n\nCredit Cards tab: card charges by card. Click the category badge to reassign.\n\nUse the date range filter to narrow the view. The Add button creates a manual checking transaction."} onClose={() => setShowHelp(false)} />}

      {deleteId && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm text-center">
            <h3 className="font-bold text-gray-900 dark:text-gray-100 mb-1">Delete this transaction?</h3>
            <p className="text-sm text-gray-500 mb-5">This will reverse its effect on the account balance.</p>
            <div className="flex gap-3">
              <button onClick={() => deleteMut.mutate(deleteId)} className="btn-danger flex-1">Delete</button>
              <button onClick={() => setDeleteId(null)} className="btn-secondary flex-1">Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
