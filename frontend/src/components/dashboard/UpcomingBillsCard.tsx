import { useNavigate } from "react-router-dom";
import { Calendar } from "lucide-react";
import { fmt } from "../../lib/utils";
import { maskIfHidden } from "../../store/balanceVisibility";

export function UpcomingBillsCard({ bills, hasRecurring, hidden }: { bills: any[]; hasRecurring: boolean; hidden: boolean }) {
  const navigate = useNavigate();
  const todayDate = new Date();
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-ink flex items-center gap-2"><Calendar size={16} /> Upcoming Bills</h3>
        <button onClick={() => navigate("/recurring")} className="text-xs text-accent hover:underline">Manage →</button>
      </div>
      {bills.length === 0 ? (
        <p className="text-sm text-muted text-center py-4">{!hasRecurring ? "No recurring bills set up" : "No bills due in the next 30 days"}</p>
      ) : (
        <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
          {bills.slice(0, 8).map((r: any) => {
            const [y, m, d] = r.due_date.split("-").map(Number);
            const dueDate = new Date(y, m - 1, d);
            const daysUntil = Math.ceil((dueDate.getTime() - todayDate.getTime()) / 86400000);
            return (
              <div key={`${r.recurring_item_id}-${r.due_date}`} className="flex items-center justify-between py-1">
                <div>
                  <p className="text-sm font-medium text-ink">{r.name}</p>
                  <p className="text-xs text-muted">
                    {dueDate.toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                    {" · "}
                    <span className={daysUntil <= 3 ? "text-red-600 font-medium" : "text-muted"}>
                      {daysUntil === 0 ? "Today" : daysUntil === 1 ? "Tomorrow" : `${daysUntil} days`}
                    </span>
                  </p>
                </div>
                <span className="text-sm font-semibold text-red-600 tabular-nums">
                  {maskIfHidden(hidden, fmt(r.amount))}
                  {r.is_actual && <span className="ml-1 text-[13px] font-normal text-muted align-middle">actual</span>}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
