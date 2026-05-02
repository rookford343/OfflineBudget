import { TrendingUp, TrendingDown } from "lucide-react";

interface TrendBadgeProps {
  pct: number | null;
  inverse?: boolean;
  size?: "sm" | "md";
}

export function TrendBadge({ pct, inverse = false, size = "sm" }: TrendBadgeProps) {
  if (pct === null || pct === undefined || pct === 0) {
    return <span className="text-xs text-gray-400 tabular-nums">—</span>;
  }

  const iconSize = size === "sm" ? 12 : 14;
  const isPositive = pct > 0;
  const isGood = isPositive ? !inverse : inverse;
  const color = isGood ? "#22c55e" : "#ef4444";
  const Icon = isPositive ? TrendingUp : TrendingDown;

  return (
    <span className="inline-flex items-center gap-0.5 text-xs font-medium tabular-nums" style={{ color }}>
      <Icon size={iconSize} />
      {Math.abs(pct).toFixed(1)}%
    </span>
  );
}
