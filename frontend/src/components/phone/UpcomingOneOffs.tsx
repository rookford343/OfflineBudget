import { useQuery } from "@tanstack/react-query";
import { plannedExpensesApi } from "../../api";
import { fmt, today } from "../../lib/utils";
import { useBalancesHidden, maskIfHidden } from "../../store/balanceVisibility";

const shortDate = (iso: string) =>
  new Date(iso + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });

/** The next 5 future planned outflows: name · date · amount. */
export default function UpcomingOneOffs() {
  const hidden = useBalancesHidden();
  const { data = [], isLoading } = useQuery<any[]>({
    queryKey: ["planned-expenses"],
    queryFn: () => plannedExpensesApi.list(false),
  });
  const todayStr = today();
  const items = data
    .filter((p) => p.direction === "outflow" && !p.is_settled && p.expected_date >= todayStr)
    .sort((a, b) => a.expected_date.localeCompare(b.expected_date))
    .slice(0, 5);

  return (
    <div className="card">
      <h3 className="mb-2 font-semibold text-gray-900 dark:text-gray-100">Upcoming one-offs</h3>
      {isLoading ? (
        <p className="py-2 text-sm text-gray-400">Loading…</p>
      ) : items.length === 0 ? (
        <p className="py-2 text-sm text-gray-400 dark:text-gray-500">Nothing planned</p>
      ) : (
        <div className="divide-y divide-gray-100 dark:divide-gray-700">
          {items.map((p) => (
            <div key={p.id} className="flex items-center justify-between gap-3 py-2 text-sm">
              <span className="min-w-0 truncate text-gray-900 dark:text-gray-100">
                {p.name} <span className="text-gray-400">· {shortDate(p.expected_date)}</span>
              </span>
              <span className="shrink-0 font-medium tabular-nums text-gray-900 dark:text-gray-100">
                {maskIfHidden(hidden, fmt(parseFloat(p.amount)))}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
