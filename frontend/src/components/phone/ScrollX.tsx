import type { ReactNode } from "react";

/** Horizontal scroller for content that must stay wide (tables, the Sankey).
 *  Bleeds into the page gutter below `lg` so the scroll area reaches the
 *  screen edge; at `lg`+ it is a plain scroller with no bleed. */
export default function ScrollX({ children }: { children: ReactNode }) {
  return <div className="overflow-x-auto -mx-4 px-4 lg:mx-0 lg:px-0">{children}</div>;
}
