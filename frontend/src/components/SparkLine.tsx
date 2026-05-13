import { useId } from "react";

interface SparkLineProps {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
}

export function SparkLine({
  data,
  width = 64,
  height = 32,
  color = "#6366f1",
}: SparkLineProps) {
  // Need at least 2 points to draw a line.
  if (data.length < 2) return null;

  const gradientId = useId();
  const fillId = `sparkline-fill-${gradientId}`;

  const min = Math.min(...data);
  const max = Math.max(...data);
  // Flat-data guard: avoid divide-by-zero when every value is identical.
  const safeMin = min === max ? min - 1 : min;
  const safeMax = min === max ? max + 1 : max;
  const range = safeMax - safeMin;

  const pts: Array<[number, number]> = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((v - safeMin) / range) * height;
    return [x, y];
  });

  const pointsStr = pts.map(([x, y]) => `${x},${y}`).join(" ");

  // Closed polygon for the gradient fill: trace the line, then drop to the
  // bottom-right corner and close back across the bottom-left.
  const areaPoints: Array<[number, number]> = [
    ...pts,
    [width, height],
    [0, height],
  ];
  const areaStr = areaPoints.map(([x, y]) => `${x},${y}`).join(" ");

  const lastPt = pts[pts.length - 1];

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      overflow="visible"
      className="dark:opacity-80"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.35} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <polygon points={areaStr} fill={`url(#${fillId})`} stroke="none" />
      <polyline
        points={pointsStr}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={lastPt[0]} cy={lastPt[1]} r={2} fill={color} />
    </svg>
  );
}
