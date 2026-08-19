import { Check } from "lucide-react";

interface ProgressRingProps {
  pct: number;
  size?: number;
  strokeWidth?: number;
  color?: string;
  label?: string;
  sublabel?: string;
  complete?: boolean;
}

export function ProgressRing({
  pct,
  size = 88,
  strokeWidth = 7,
  color = "#6366f1",
  label,
  sublabel,
  complete = false,
}: ProgressRingProps) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.min(100, Math.max(0, pct));
  const dashOffset = circumference - (clamped / 100) * circumference;
  const cx = size / 2;
  const cy = size / 2;
  const displayLabel = label ?? `${Math.round(clamped)}%`;

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle
          cx={cx} cy={cy} r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          className="stroke-gray-200 dark:stroke-[#3a4051]"
        />
        <circle
          cx={cx} cy={cy} r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          style={{ transition: "stroke-dashoffset 0.8s cubic-bezier(0.34, 1.56, 0.64, 1)" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        {complete ? (
          <Check size={Math.round(size * 0.28)} style={{ color }} />
        ) : (
          <>
            <span className="text-sm font-bold tabular-nums leading-none text-gray-900 dark:text-white">
              {displayLabel}
            </span>
            {sublabel && (
              <span className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 tabular-nums leading-none">
                {sublabel}
              </span>
            )}
          </>
        )}
      </div>
    </div>
  );
}
