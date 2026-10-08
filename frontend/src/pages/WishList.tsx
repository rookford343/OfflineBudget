import { useQuery } from "@tanstack/react-query";
import { Gift } from "lucide-react";
import ScenarioEditor from "../components/wish/ScenarioEditor";
import { scenariosApi } from "../api";

// Minimal stub: renders the editor for the first scenario. Replaced in Task 7
// with the full Wish List page (item list, cushion, plan option UI).
export default function WishList() {
  const { data: scenarios = [] } = useQuery<{ id: number }[]>({
    queryKey: ["scenarios"],
    queryFn: scenariosApi.list,
  });
  const first = scenarios[0] ?? null;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Gift className="w-5 h-5" />
        <h1 className="text-xl font-semibold">Wish List</h1>
      </div>
      {first ? (
        <ScenarioEditor scenarioId={first.id} accountId={undefined} />
      ) : (
        <p className="text-sm text-gray-500">No scenarios yet.</p>
      )}
    </div>
  );
}
