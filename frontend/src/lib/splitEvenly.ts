/** Split `totalDollars` into `count` legs that sum back to the exact total,
 *  working in integer cents so float division can't lose a penny. The first
 *  `totalCents % count` legs each get one extra cent. */
export function splitEvenly(totalDollars: number, count: number): number[] {
  const totalCents = Math.round(totalDollars * 100);
  const base = Math.floor(totalCents / count);
  const remainder = totalCents % count;
  return Array.from({ length: count }, (_, i) => (base + (i < remainder ? 1 : 0)) / 100);
}
