import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Plus, Trash2, CalendarClock } from "lucide-react";
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, Legend } from "recharts";
import { scenariosApi, accountsApi, cardsApi, recurringApi, forecastApi } from "../api";

type Scenario = {
  id: number;
  name: string;
  status: string;
  committed_at: string | null;
  notes: string | null;
  created_at: string;
  overrides: { id: number; recurring_item_id: number; amount_delta: string }[];
  proposed_items: {
    id: number; name: string; amount: string; type: string; frequency: string;
    day_of_month: number; month_of_year: number | null; start_date: string;
    end_date: string | null; account_id: number; card_id: number | null;
  }[];
  proposed_expenses: {
    id: number; name: string; amount: string; expected_date: string;
    direction: string; account_id: number | null; card_id: number | null;
  }[];
};

const money = (v: string | number) =>
  `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

// The backend refuses many scenario mutations with a 409 and an explanatory
// `detail` string (commit conflicts, uncommit-blocked-by-owned-override,
// mutating a committed scenario, etc). Surface that message verbatim; fall
// back to a generic one rather than ever rendering "[object Object]".
const errorDetail = (err: unknown, fallback: string): string => {
  const detail = (err as any)?.response?.data?.detail;
  return typeof detail === "string" && detail.trim() ? detail : fallback;
};

function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p className="text-sm text-red-700 bg-red-50 rounded px-2 py-1.5">
      {message}
    </p>
  );
}

export default function Scenarios() {
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [newName, setNewName] = useState("");
  const [accountId, setAccountId] = useState<number | null>(null);
  // Default is one scenario against baseline; this set adds further lines for
  // comparing options against each other, which is available but not the
  // default (Dan, 2026-09-20).
  const [compareIds, setCompareIds] = useState<number[]>([]);
  const year = new Date().getFullYear();

  const { data: scenarios = [] } = useQuery<Scenario[]>({
    queryKey: ["scenarios"],
    queryFn: scenariosApi.list,
  });
  const { data: accounts = [] } = useQuery<any[]>({
    queryKey: ["accounts"],
    queryFn: accountsApi.list,
  });
  const { data: cards = [] } = useQuery<any[]>({
    queryKey: ["cards"],
    queryFn: cardsApi.list,
  });
  const { data: recurring = [] } = useQuery<any[]>({
    queryKey: ["recurring"],
    queryFn: () => recurringApi.list(),
  });

  const activeAccountId =
    accountId ?? (accounts.find((a) => a.type === "checking")?.id ?? accounts[0]?.id ?? null);

  const selected = scenarios.find((s) => s.id === selectedId) ?? null;
  const committed = selected?.status === "committed";
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["scenarios"] });
    qc.invalidateQueries({ queryKey: ["scenario-impact"] });
  };

  const { data: impact } = useQuery<any>({
    queryKey: ["scenario-impact", selectedId, activeAccountId],
    queryFn: () => scenariosApi.impact(selectedId!, activeAccountId!),
    enabled: selectedId !== null && activeAccountId !== null,
  });

  const { data: baselineQuarters = [] } = useQuery<any[]>({
    queryKey: ["scenario-baseline", activeAccountId, year],
    queryFn: () => forecastApi.quarters(activeAccountId!, year),
    enabled: activeAccountId !== null,
  });

  const lineIds = selectedId === null ? compareIds : [selectedId, ...compareIds.filter((i) => i !== selectedId)];
  const { data: scenarioLines = [] } = useQuery<{ id: number; days: any[] }[]>({
    queryKey: ["scenario-lines", activeAccountId, year, lineIds],
    queryFn: async () => Promise.all(
      lineIds.map(async (id) => ({
        id,
        days: await forecastApi.quartersWithScenarioId(activeAccountId!, year, id),
      })),
    ),
    enabled: activeAccountId !== null && lineIds.length > 0,
  });

  // Quarter summaries carry nested `days` (ForecastEntry: date + projected_balance),
  // flattened into a date-keyed map exactly as Forecast.tsx does.
  const flatten = (quarters: any[]) => {
    const out: Record<string, number> = {};
    quarters.forEach((q: any) =>
      (q.days ?? []).forEach((d: any) => { out[d.date] = parseFloat(d.projected_balance); }),
    );
    return out;
  };
  const baselineMap = flatten(baselineQuarters);
  const lineMaps = scenarioLines.map((l) => ({ id: l.id, map: flatten(l.days) }));
  const chartRows = Object.keys(baselineMap).sort().map((dateKey) => {
    const row: Record<string, any> = { date: dateKey, baseline: baselineMap[dateKey] };
    lineMaps.forEach((l) => { row[`s${l.id}`] = l.map[dateKey]; });
    return row;
  });
  const lineColors = ["#2563eb", "#16a34a", "#c2410c", "#7c3aed"];

  const createScenario = useMutation({
    mutationFn: () => scenariosApi.create({ name: newName.trim() }),
    onSuccess: (s: Scenario) => { setNewName(""); setSelectedId(s.id); invalidate(); },
  });
  const removeScenario = useMutation({
    mutationFn: (id: number) => scenariosApi.remove(id),
    onSuccess: () => { setSelectedId(null); invalidate(); },
  });
  const addItem = useMutation({
    mutationFn: (data: object) => scenariosApi.createItem(selected!.id, data),
    onSuccess: invalidate,
  });
  const dropItem = useMutation({
    mutationFn: (itemId: number) => scenariosApi.removeItem(selected!.id, itemId),
    onSuccess: invalidate,
  });
  const addExpense = useMutation({
    mutationFn: (data: object) => scenariosApi.createExpense(selected!.id, data),
    onSuccess: invalidate,
  });
  const dropExpense = useMutation({
    mutationFn: (id: number) => scenariosApi.removeExpense(selected!.id, id),
    onSuccess: invalidate,
  });
  const addOverride = useMutation({
    mutationFn: (data: object) => scenariosApi.createOverride(selected!.id, data),
    onSuccess: invalidate,
  });
  const dropOverride = useMutation({
    mutationFn: (id: number) => scenariosApi.removeOverride(selected!.id, id),
    onSuccess: invalidate,
  });
  const commit = useMutation({
    mutationFn: () => scenariosApi.commit(selected!.id),
    onSuccess: () => {
      invalidate();
      qc.invalidateQueries({ queryKey: ["recurring"] });
      qc.invalidateQueries({ queryKey: ["planned-expenses"] });
    },
  });
  const uncommit = useMutation({
    mutationFn: () => scenariosApi.uncommit(selected!.id),
    onSuccess: () => {
      invalidate();
      qc.invalidateQueries({ queryKey: ["recurring"] });
      qc.invalidateQueries({ queryKey: ["planned-expenses"] });
    },
  });

  // Clear every mutation's stale error banner when the user switches to a
  // different scenario -- a 409 from the previously selected scenario should
  // not linger over an unrelated one.
  useEffect(() => {
    addItem.reset(); dropItem.reset();
    addExpense.reset(); dropExpense.reset();
    addOverride.reset(); dropOverride.reset();
    commit.reset(); uncommit.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <FlaskConical className="w-5 h-5" />
        <h1 className="text-xl font-semibold">Scenarios</h1>
      </div>

      <div className="card p-4 space-y-3">
        <h2 className="font-medium">Your scenarios</h2>
        <div className="flex flex-wrap gap-2">
          {scenarios.map((s) => (
            <button
              key={s.id}
              onClick={() => setSelectedId(s.id)}
              className={`px-3 py-1.5 rounded border text-sm ${
                s.id === selectedId ? "border-blue-500 font-medium" : "border-gray-300"
              }`}
            >
              {s.name}
              {s.status === "committed" && (
                <span className="ml-2 text-xs px-1.5 py-0.5 rounded bg-green-100 text-green-800">
                  committed
                </span>
              )}
            </button>
          ))}
          {scenarios.length === 0 && (
            <p className="text-sm text-gray-500">
              No scenarios yet. Create one to test a change before it is real.
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <input
            className="input"
            placeholder="New scenario name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <button
            className="btn"
            disabled={!newName.trim()}
            onClick={() => createScenario.mutate()}
          >
            <Plus className="w-4 h-4" /> Create
          </button>
          {selected && (
            <button className="btn" onClick={() => removeScenario.mutate(selected.id)}>
              <Trash2 className="w-4 h-4" /> Delete
            </button>
          )}
        </div>
        <ErrorNote message={createScenario.isError ? errorDetail(createScenario.error, "Could not create the scenario.") : null} />
        <ErrorNote message={removeScenario.isError ? errorDetail(removeScenario.error, "Could not delete this scenario.") : null} />
      </div>

      {selected && (
        <>
          <ProposedItemsSection
            scenario={selected}
            accounts={accounts}
            cards={cards}
            disabled={committed}
            onAdd={(data) => addItem.mutate(data)}
            onDrop={(id) => dropItem.mutate(id)}
            addError={addItem.isError ? errorDetail(addItem.error, "Could not add this item.") : null}
            dropError={dropItem.isError ? errorDetail(dropItem.error, "Could not remove this item.") : null}
          />
          <ProposedExpensesSection
            scenario={selected}
            accounts={accounts}
            cards={cards}
            disabled={committed}
            onAdd={(data) => addExpense.mutate(data)}
            onDrop={(id) => dropExpense.mutate(id)}
            addError={addExpense.isError ? errorDetail(addExpense.error, "Could not add this expense.") : null}
            dropError={dropExpense.isError ? errorDetail(dropExpense.error, "Could not remove this expense.") : null}
          />
          <OverridesSection
            scenario={selected}
            recurring={recurring}
            disabled={committed}
            onAdd={(data) => addOverride.mutate(data)}
            onDrop={(id) => dropOverride.mutate(id)}
            addError={addOverride.isError ? errorDetail(addOverride.error, "Could not add this tweak.") : null}
            dropError={dropOverride.isError ? errorDetail(dropOverride.error, "Could not remove this tweak.") : null}
          />

          {impact && (
            <div className="card p-4">
              <h2 className="font-medium mb-3">Impact</h2>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-500">
                    <th className="py-1">Figure</th>
                    <th className="py-1">Baseline</th>
                    <th className="py-1">Scenario</th>
                    <th className="py-1">Change</th>
                  </tr>
                </thead>
                <tbody>
                  {([
                    ["3-month low", "low", true],
                    ["Weekly safety margin", "safety_margin_weekly", true],
                    ["Total monthly commitments", "total_monthly_commitments", false],
                  ] as [string, string, boolean][]).map(([label, key, higherIsBetter]) => {
                    const base = Number(impact.baseline[key]);
                    const scen = Number(impact.scenario[key]);
                    const delta = scen - base;
                    const good = higherIsBetter ? delta >= 0 : delta <= 0;
                    return (
                      <tr key={key} className="border-t">
                        <td className="py-1.5">{label}</td>
                        <td className="py-1.5">{money(base)}</td>
                        <td className="py-1.5">{money(scen)}</td>
                        <td className={`py-1.5 ${good ? "text-green-700" : "text-red-700"}`}>
                          {delta >= 0 ? "+" : "−"}{money(Math.abs(delta))}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {impact.scenario.low_date && (
                <p className="text-xs text-gray-500 mt-2">
                  Scenario low lands {impact.scenario.low_date}.
                </p>
              )}
            </div>
          )}

          <div className="card p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-medium">Projected balance</h2>
              <select
                className="input w-auto"
                value={activeAccountId ?? ""}
                onChange={(e) => setAccountId(parseInt(e.target.value, 10))}
              >
                {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </div>
            <div className="flex flex-wrap gap-2 text-sm">
              <span className="text-gray-500">Also compare:</span>
              {scenarios.filter((s) => s.id !== selected.id).map((s) => (
                <label key={s.id} className="inline-flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={compareIds.includes(s.id)}
                    onChange={(e) => setCompareIds(
                      e.target.checked
                        ? [...compareIds, s.id]
                        : compareIds.filter((i) => i !== s.id),
                    )}
                  />
                  {s.name}
                </label>
              ))}
            </div>
            <div style={{ height: 320 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartRows}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v: any) => money(v)} />
                  <Legend />
                  <Line type="monotone" dataKey="baseline" name="Baseline"
                        stroke="#6b7280" strokeWidth={2} dot={false} />
                  {lineMaps.map((l, idx) => (
                    <Line
                      key={l.id}
                      type="monotone"
                      dataKey={`s${l.id}`}
                      name={scenarios.find((s) => s.id === l.id)?.name ?? `Scenario ${l.id}`}
                      stroke={lineColors[idx % lineColors.length]}
                      strokeWidth={2}
                      strokeDasharray="5 3"
                      dot={false}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="card p-4 space-y-2">
            {committed ? (
              <>
                <p className="text-sm">
                  Committed{selected.committed_at ? ` ${selected.committed_at.slice(0, 10)}` : ""}.
                  Its items are now real recurring items and planned expenses.
                </p>
                <button
                  className="btn"
                  onClick={() => {
                    const ok = window.confirm(
                      "Uncommit deletes the recurring items and planned expenses this " +
                      "scenario created and restores the amounts it changed. Any edits " +
                      "you made to those rows since committing will be lost. Continue?",
                    );
                    if (ok) uncommit.mutate();
                  }}
                >
                  Uncommit
                </button>
                <ErrorNote message={uncommit.isError ? errorDetail(uncommit.error, "Could not uncommit this scenario.") : null} />
              </>
            ) : (
              <>
                <p className="text-sm text-gray-500">
                  Committing creates real recurring items and planned expenses from
                  this scenario, and applies its amount tweaks. It can be reversed.
                </p>
                <button
                  className="btn"
                  disabled={
                    selected.proposed_items.length === 0 &&
                    selected.proposed_expenses.length === 0 &&
                    selected.overrides.length === 0
                  }
                  onClick={() => commit.mutate()}
                >
                  Commit to forecast
                </button>
                <ErrorNote message={commit.isError ? errorDetail(commit.error, "Could not commit this scenario.") : null} />
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function ProposedItemsSection({ scenario, accounts, cards, disabled, onAdd, onDrop, addError, dropError }: {
  scenario: Scenario; accounts: any[]; cards: any[]; disabled: boolean;
  onAdd: (data: object) => void; onDrop: (id: number) => void;
  addError: string | null; dropError: string | null;
}) {
  const [form, setForm] = useState({
    name: "", amount: "", type: "expense", frequency: "monthly",
    day_of_month: "1", month_of_year: "", start_date: "", end_date: "",
    account_id: "", card_id: "",
  });
  const set = (k: string, v: string) => setForm({ ...form, [k]: v });

  // A card carrying a manual monthly spend estimate ignores its subscriptions
  // entirely, so a proposal routed to it changes nothing at all. Correct
  // existing behavior, but invisible -- it reads as "the scenario is broken".
  const chosenCard = cards.find((c) => String(c.id) === form.card_id);
  const estimateWarning =
    form.type === "expense" && chosenCard && Number(chosenCard.monthly_spend_estimate ?? 0) > 0;

  const ready = form.name.trim() && form.amount && form.start_date && form.account_id;

  return (
    <div className="card p-4 space-y-3">
      <h2 className="font-medium">Proposed recurring items</h2>
      {scenario.proposed_items.length === 0 && (
        <p className="text-sm text-gray-500">Nothing proposed yet.</p>
      )}
      <ul className="divide-y">
        {scenario.proposed_items.map((i) => (
          <li key={i.id} className="py-2 flex items-center justify-between text-sm">
            <span>
              {i.name} — {money(i.amount)} {i.frequency}
              {i.end_date && (
                <span className="ml-2 inline-flex items-center gap-1 text-xs text-amber-700">
                  <CalendarClock className="w-3 h-3" /> ends {i.end_date}
                </span>
              )}
            </span>
            {!disabled && (
              <button className="btn-ghost" onClick={() => onDrop(i.id)}>
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </li>
        ))}
      </ul>

      {!disabled && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <input className="input" placeholder="Name" value={form.name}
                 onChange={(e) => set("name", e.target.value)} />
          <input className="input" placeholder="Amount" value={form.amount}
                 onChange={(e) => set("amount", e.target.value)} />
          <select className="input" value={form.type} onChange={(e) => set("type", e.target.value)}>
            <option value="expense">Expense</option>
            <option value="income">Income</option>
          </select>
          <select className="input" value={form.frequency}
                  onChange={(e) => set("frequency", e.target.value)}>
            <option value="monthly">Monthly</option>
            <option value="yearly">Yearly</option>
            <option value="quarterly">Quarterly</option>
            <option value="weekly">Weekly</option>
            <option value="biweekly">Biweekly</option>
          </select>
          <input className="input" type="number" placeholder="Day of month"
                 value={form.day_of_month} onChange={(e) => set("day_of_month", e.target.value)} />
          <input className="input" type="number" placeholder="Month (yearly/qtr)"
                 value={form.month_of_year} onChange={(e) => set("month_of_year", e.target.value)} />
          <input className="input" type="date" value={form.start_date}
                 onChange={(e) => set("start_date", e.target.value)} />
          <input className="input" type="date" placeholder="End date"
                 value={form.end_date} onChange={(e) => set("end_date", e.target.value)} />
          <select className="input" value={form.account_id}
                  onChange={(e) => set("account_id", e.target.value)}>
            <option value="">Account…</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <select className="input" value={form.card_id}
                  onChange={(e) => set("card_id", e.target.value)}>
            <option value="">No card (hits checking)</option>
            {cards.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <button
            className="btn col-span-2"
            disabled={!ready}
            onClick={() => onAdd({
              name: form.name.trim(),
              amount: form.amount,
              type: form.type,
              frequency: form.frequency,
              day_of_month: parseInt(form.day_of_month || "1", 10),
              month_of_year: form.month_of_year ? parseInt(form.month_of_year, 10) : null,
              start_date: form.start_date,
              end_date: form.end_date || null,
              account_id: parseInt(form.account_id, 10),
              card_id: form.card_id ? parseInt(form.card_id, 10) : null,
            })}
          >
            <Plus className="w-4 h-4" /> Add proposed item
          </button>
        </div>
      )}

      <ErrorNote message={addError} />
      <ErrorNote message={dropError} />

      {estimateWarning && (
        <p className="text-sm text-amber-700">
          {chosenCard.name} has a manual monthly spend estimate of{" "}
          {money(chosenCard.monthly_spend_estimate)}, and that estimate governs the
          forecast instead of the card's individual charges. A proposal routed here
          will not change the forecast. Clear the card's estimate, or pick a card
          without one, to see this item's effect.
        </p>
      )}
    </div>
  );
}

function ProposedExpensesSection({ scenario, accounts, cards, disabled, onAdd, onDrop, addError, dropError }: {
  scenario: Scenario; accounts: any[]; cards: any[]; disabled: boolean;
  onAdd: (data: object) => void; onDrop: (id: number) => void;
  addError: string | null; dropError: string | null;
}) {
  const [form, setForm] = useState({
    name: "", amount: "", expected_date: "", direction: "outflow",
    account_id: "", card_id: "", funding_account_id: "",
  });
  const set = (k: string, v: string) => setForm({ ...form, [k]: v });
  const ready = form.name.trim() && form.amount && form.expected_date;

  return (
    <div className="card p-4 space-y-3">
      <h2 className="font-medium">Proposed one-off expenses</h2>
      {scenario.proposed_expenses.length === 0 && (
        <p className="text-sm text-gray-500">Nothing proposed yet.</p>
      )}
      <ul className="divide-y">
        {scenario.proposed_expenses.map((e) => (
          <li key={e.id} className="py-2 flex items-center justify-between text-sm">
            <span>{e.name} — {money(e.amount)} on {e.expected_date}</span>
            {!disabled && (
              <button className="btn-ghost" onClick={() => onDrop(e.id)}>
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </li>
        ))}
      </ul>

      {!disabled && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <input className="input" placeholder="Name" value={form.name}
                 onChange={(e) => set("name", e.target.value)} />
          <input className="input" placeholder="Amount" value={form.amount}
                 onChange={(e) => set("amount", e.target.value)} />
          <input className="input" type="date" value={form.expected_date}
                 onChange={(e) => set("expected_date", e.target.value)} />
          <select className="input" value={form.direction}
                  onChange={(e) => set("direction", e.target.value)}>
            <option value="outflow">Money out</option>
            <option value="inflow">Money in</option>
          </select>
          <select className="input" value={form.account_id}
                  onChange={(e) => set("account_id", e.target.value)}>
            <option value="">Any account</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <select className="input" value={form.card_id}
                  onChange={(e) => set("card_id", e.target.value)}>
            <option value="">No card</option>
            {cards.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <select className="input" value={form.funding_account_id}
                  onChange={(e) => set("funding_account_id", e.target.value)}>
            <option value="">No funding transfer</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>Fund from {a.name}</option>)}
          </select>
          <button
            className="btn"
            disabled={!ready}
            onClick={() => onAdd({
              name: form.name.trim(),
              amount: form.amount,
              expected_date: form.expected_date,
              direction: form.direction,
              account_id: form.account_id ? parseInt(form.account_id, 10) : null,
              card_id: form.card_id ? parseInt(form.card_id, 10) : null,
              funding_account_id: form.funding_account_id
                ? parseInt(form.funding_account_id, 10) : null,
            })}
          >
            <Plus className="w-4 h-4" /> Add one-off
          </button>
        </div>
      )}

      <ErrorNote message={addError} />
      <ErrorNote message={dropError} />
    </div>
  );
}

function OverridesSection({ scenario, recurring, disabled, onAdd, onDrop, addError, dropError }: {
  scenario: Scenario; recurring: any[]; disabled: boolean;
  onAdd: (data: object) => void; onDrop: (id: number) => void;
  addError: string | null; dropError: string | null;
}) {
  const [itemId, setItemId] = useState("");
  const [delta, setDelta] = useState("");
  const nameOf = (id: number) => recurring.find((r) => r.id === id)?.name ?? `#${id}`;

  return (
    <div className="card p-4 space-y-3">
      <h2 className="font-medium">Amount tweaks on existing items</h2>
      {scenario.overrides.length === 0 && (
        <p className="text-sm text-gray-500">No tweaks yet.</p>
      )}
      <ul className="divide-y">
        {scenario.overrides.map((o) => (
          <li key={o.id} className="py-2 flex items-center justify-between text-sm">
            <span>{nameOf(o.recurring_item_id)} — {money(o.amount_delta)} change</span>
            {!disabled && (
              <button className="btn-ghost" onClick={() => onDrop(o.id)}>
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </li>
        ))}
      </ul>
      {!disabled && (
        <div className="flex flex-wrap gap-2">
          <select className="input" value={itemId} onChange={(e) => setItemId(e.target.value)}>
            <option value="">Recurring item…</option>
            {recurring.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
          <input className="input" placeholder="Change (e.g. -200)" value={delta}
                 onChange={(e) => setDelta(e.target.value)} />
          <button
            className="btn"
            disabled={!itemId || !delta}
            onClick={() => {
              onAdd({ recurring_item_id: parseInt(itemId, 10), amount_delta: delta });
              setItemId(""); setDelta("");
            }}
          >
            <Plus className="w-4 h-4" /> Add tweak
          </button>
        </div>
      )}

      <ErrorNote message={addError} />
      <ErrorNote message={dropError} />
    </div>
  );
}
