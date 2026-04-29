export function fmt(amount: number | string, opts?: Intl.NumberFormatOptions): string {
  const n = typeof amount === "string" ? parseFloat(amount) : amount;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    ...opts,
  }).format(n);
}

export function fmtDate(d: string): string {
  return new Date(d + "T12:00:00").toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function cx(...classes: (string | undefined | null | false)[]): string {
  return classes.filter(Boolean).join(" ");
}

export function utilColor(pct: number): string {
  if (pct < 30) return "text-green-600";
  if (pct < 70) return "text-amber-600";
  return "text-red-600";
}

export function utilBg(pct: number): string {
  if (pct < 30) return "bg-green-500";
  if (pct < 70) return "bg-amber-500";
  return "bg-red-500";
}

export function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function firstOfMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}
