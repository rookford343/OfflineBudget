import { describe, expect, test } from "bun:test";
import { blankCheckingLevel, bodyFromDraft, draftFromRule, sourceAccounts } from "../src/lib/checkingLevel";

const accounts = [
  { id: 1, type: "checking", name: "Main Checking" },
  { id: 2, type: "money_market", name: "Money Market" },
  { id: 3, type: "savings", name: "Savings" },
  { id: 4, type: "savings", name: "Emergency" },
];

describe("sourceAccounts", () => {
  test("drops the checking account and lists savings-type accounts first", () => {
    expect(sourceAccounts(accounts, 1).map((a) => a.id)).toEqual([3, 4, 2]);
  });
});

describe("draftFromRule / bodyFromDraft", () => {
  test("no rule yet: defaults, with the first savings account preselected", () => {
    expect(draftFromRule(null, 3)).toEqual({ ...blankCheckingLevel, from_account_id: "3" });
  });

  test("round-trips a saved rule with a sweep", () => {
    const rule = {
      id: 9, from_account_id: 3, to_account_id: 1, action_threshold: "500.00", target_floor: "1000.00",
      increment: "1000.00", check_day: 5, is_active: true, sweep_ceiling: "3000.00", sweep_to_account_id: 2,
    };
    const draft = draftFromRule(rule, 3);
    expect(draft.sweep_on).toBe(true);
    expect(bodyFromDraft(draft, 1)).toEqual({
      from_account_id: 3, to_account_id: 1, action_threshold: "500.00", target_floor: "1000.00",
      increment: "1000.00", check_day: 5, is_active: true, sweep_ceiling: "3000.00", sweep_to_account_id: 2,
    });
  });

  test("sweep off sends both sweep fields as null", () => {
    const draft = { ...blankCheckingLevel, from_account_id: "3", action_threshold: "500", target_floor: "1000",
      sweep_on: false, sweep_ceiling: "3000", sweep_to_account_id: "2" };
    const body = bodyFromDraft(draft, 1);
    expect(body.sweep_ceiling).toBeNull();
    expect(body.sweep_to_account_id).toBeNull();
  });
});
