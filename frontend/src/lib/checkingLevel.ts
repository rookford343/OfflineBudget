/** "Keep checking at the right level" settings: form <-> API body.
 *
 *  The sweep only runs while the savings strategy is "Save each month"
 *  (backend: forecast_engine._sweep_active). Its fields are kept in the
 *  draft either way, so switching strategies back and forth doesn't lose
 *  them; the backend simply ignores them under "Pull from savings". */

export type CheckingLevelDraft = {
  from_account_id: string;
  action_threshold: string;
  target_floor: string;
  increment: string;
  check_day: string;
  is_active: boolean;
  sweep_on: boolean;
  sweep_ceiling: string;
  sweep_to_account_id: string;
};

export const blankCheckingLevel: CheckingLevelDraft = {
  from_account_id: "",
  action_threshold: "",
  target_floor: "",
  increment: "1000",
  check_day: "1",
  is_active: true,
  sweep_on: false,
  sweep_ceiling: "",
  sweep_to_account_id: "",
};

type Acct = { id: number; type: string; name?: string };

/** Accounts money can come from / go to: everything but the checking
 *  account itself, savings-type accounts first (keeping the given order
 *  within each group). */
export function sourceAccounts<T extends Acct>(accounts: readonly T[], checkingId: number | undefined): T[] {
  const others = accounts.filter((a) => a.id !== checkingId);
  return [...others.filter((a) => a.type === "savings"), ...others.filter((a) => a.type !== "savings")];
}

export function draftFromRule(rule: any | null | undefined, defaultFromId: number | undefined): CheckingLevelDraft {
  if (!rule) {
    return { ...blankCheckingLevel, from_account_id: defaultFromId != null ? String(defaultFromId) : "" };
  }
  return {
    from_account_id: String(rule.from_account_id),
    action_threshold: String(rule.action_threshold),
    target_floor: String(rule.target_floor),
    increment: String(rule.increment),
    check_day: String(rule.check_day),
    is_active: !!rule.is_active,
    sweep_on: rule.sweep_ceiling != null,
    sweep_ceiling: rule.sweep_ceiling != null ? String(rule.sweep_ceiling) : "",
    sweep_to_account_id: rule.sweep_to_account_id != null ? String(rule.sweep_to_account_id) : "",
  };
}

/** The PUT body. Sweep fields go out as null when the sweep is off. */
export function bodyFromDraft(d: CheckingLevelDraft, checkingId: number) {
  const sweep = d.sweep_on && d.sweep_ceiling !== "";
  return {
    from_account_id: parseInt(d.from_account_id),
    to_account_id: checkingId,
    action_threshold: d.action_threshold,
    target_floor: d.target_floor,
    increment: d.increment,
    check_day: parseInt(d.check_day),
    is_active: d.is_active,
    sweep_ceiling: sweep ? d.sweep_ceiling : null,
    sweep_to_account_id: sweep && d.sweep_to_account_id ? parseInt(d.sweep_to_account_id) : null,
  };
}
