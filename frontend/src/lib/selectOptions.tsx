import React from "react";

/**
 * Shared <option> builders.
 *
 * Every dropdown in the app rendered its list in whatever order the API
 * returned — creation order, mostly — so finding an entry in a list of forty
 * meant reading all forty. These helpers sort alphabetically and, where the
 * data has a natural split, group with <optgroup> so the list can be scanned
 * by section instead of scanned end to end.
 *
 * Sorting uses localeCompare with numeric collation, so "Item 2" precedes
 * "Item 10" rather than following it.
 */

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

export function byName<T extends { name?: string }>(list: T[]): T[] {
  return [...(list ?? [])].sort((a, b) => collator.compare(a.name ?? "", b.name ?? ""));
}

/** Flatten the category tree (/categories returns parents with nested children). */
export function flattenCategories(tree: any[]): any[] {
  const out: any[] = [];
  const walk = (list: any[], parent: any | null) => {
    (list ?? []).forEach((c: any) => {
      out.push({ ...c, parentName: parent?.name ?? null });
      if (c.children?.length) walk(c.children, c);
    });
  };
  walk(tree ?? [], null);
  return out;
}

/**
 * Categories grouped under their parent, each group alphabetical, groups
 * themselves alphabetical. A parent that carries no children is listed under
 * "Other" rather than becoming a one-item group of itself.
 */
export function CategoryOptions(
  { categories, type, exclude }: { categories: any[]; type?: string; exclude?: Set<number> },
) {
  const all = flattenCategories(categories);
  const flat = all.filter((c: any) => (!type || c.type === type) && !(exclude?.has(c.id)));
  const groups = new Map<string, any[]>();
  flat.forEach((c: any) => {
    // A top-level category with children is a heading, not a choice: picking
    // it would file spend against a bucket rather than a real category.
    const hasChildren = all.some((x: any) => x.parent_id === c.id);
    if (hasChildren) return;
    const key = c.parentName ?? "Other";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(c);
  });
  const names = [...groups.keys()].sort(collator.compare);
  return (
    <>
      {names.map(g => (
        <optgroup key={g} label={g}>
          {byName(groups.get(g)!).map((c: any) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </optgroup>
      ))}
    </>
  );
}

const ACCOUNT_GROUPS: Record<string, string> = {
  checking: "Checking",
  savings: "Savings",
  money_market: "Money Market",
  investment: "Investment",
  other: "Other",
};

/** Accounts grouped by kind, alphabetical inside each. */
export function AccountOptions({ accounts, filter }: { accounts: any[]; filter?: (a: any) => boolean }) {
  const list = (accounts ?? []).filter(a => (filter ? filter(a) : true));
  const groups = new Map<string, any[]>();
  list.forEach((a: any) => {
    const key = ACCOUNT_GROUPS[a.type] ?? "Other";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(a);
  });
  const order = ["Checking", "Savings", "Money Market", "Investment", "Other"];
  const present = order.filter(o => groups.has(o));
  // One group is just a flat list wearing a heading.
  if (present.length <= 1) {
    return <>{byName(list).map((a: any) => <option key={a.id} value={a.id}>{a.name}</option>)}</>;
  }
  return (
    <>
      {present.map(g => (
        <optgroup key={g} label={g}>
          {byName(groups.get(g)!).map((a: any) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </optgroup>
      ))}
    </>
  );
}

/** Recurring items split by what settles them, alphabetical inside each. */
export function RecurringOptions({ items, filter }: { items: any[]; filter?: (i: any) => boolean }) {
  const list = (items ?? []).filter(i => (filter ? filter(i) : true));
  const card = byName(list.filter((i: any) => i.card_id));
  const checking = byName(list.filter((i: any) => !i.card_id));
  if (!card.length || !checking.length) {
    return <>{byName(list).map((i: any) => <option key={i.id} value={i.id}>{i.name}</option>)}</>;
  }
  return (
    <>
      <optgroup label="Paid from checking">
        {checking.map((i: any) => <option key={i.id} value={i.id}>{i.name}</option>)}
      </optgroup>
      <optgroup label="Charged to a card">
        {card.map((i: any) => <option key={i.id} value={i.id}>{i.name}</option>)}
      </optgroup>
    </>
  );
}


/**
 * Flat category list ordered so children sit under their parent and both
 * levels are alphabetical. For the selects that can't use <optgroup> because
 * they encode a composite value (e.g. "account:12"), this at least makes the
 * list scannable instead of creation-ordered.
 */
export function sortCategoryList(flat: any[], tree?: any[]): any[] {
  const parentName = new Map<number, string>();
  (tree ?? []).forEach((p: any) => parentName.set(p.id, p.name));
  const nameOf = (c: any) =>
    c.parent_id ? `${parentName.get(c.parent_id) ?? ""}\u0000${c.name}` : `${c.name}\u0000`;
  return [...(flat ?? [])].sort((a, b) => collator.compare(nameOf(a), nameOf(b)));
}
