"""The card-payment model: what each active card will pay out of checking, and when.

One module the forecast (`build_forecast`) and the Household Snapshot's
explain notes both read, so a card payment has one definition. Per card, in
the order they are tried:

- Locked payoff: the last statement's `balance_due` on its due date, less any
  payment already pending at the bank. A due date inside the last week with
  the statement still unpaid is the same payoff, re-plannable onto today
  (`CardPaymentPlan.overdue`).
- Cycle estimate: the cycle after the locked payoff, derived from the card's
  own balance (running balance minus statemented balance, plus the pending
  figure `pending.card_pending` gives, plus subscriptions still to post
  before the statement closes).
- Second hop: the cycle after that, from fresh pending charges alone.
- Flat estimate: `monthly_spend_estimate` on every due date nothing better
  covers; without one, the card's own subscriptions routed to the due date
  of the statement that will carry them (`subscription_flat`).

Each payment carries a `basis` (the receipt behind its amount, shape in
`schemas.ForecastTransaction.basis`). See docs/architecture.md, "Card-payment
model".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session, joinedload

from backend import models
from backend.services.card_matching import match_payment_card
from backend.services.forecast_engine import (
    ScenarioProposal,
    _UNCONFIRMED_LOOKBACK_DAYS,
    _card_payoff_date_for_charge,
    _card_subscription_charges,
    _fires_on,
    _last_day_of_month,
    _most_recent_occurrence_on_or_before,
    _next_occurrence_on_or_after,
    is_card_bill_in_month,
)
from backend.services.pending import card_pending, checking_pending_debits


@dataclass(frozen=True)
class CardPayment:
    card_id: int
    due: date
    amount: Decimal
    locked: bool          # a known statement payoff (or a carried one merged into it), not a guess
    basis: dict           # same keys as ForecastTransaction.basis


@dataclass(frozen=True)
class CardPaymentPlan:
    payments: list[CardPayment]
    # Unpaid statement payoffs whose due date is already behind today (inside
    # the unconfirmed lookback, so not stale), whether or not that date is in
    # the window. Amounts are net of any payment already pending at the bank.
    overdue: list[CardPayment] = field(default_factory=list)


def window_planned_expenses(
    db: Session, user_id: int, start: date, end: date, proposal: ScenarioProposal | None = None,
) -> list[models.PlannedExpense]:
    """Unsettled one-offs expected in the window, plus a scenario's proposed ones.

    A settled one-off already happened, so the real transaction is in the
    ledger and the balance reflects it; projecting the estimate too would
    count the same money twice. Proposals are spliced in with the same window
    filter -- without it a proposal outside the window could still route a
    charge into it, so a scenario forecast would disagree with what
    committing the scenario produces."""
    planned = db.query(models.PlannedExpense).options(
        joinedload(models.PlannedExpense.category)
    ).filter(
        models.PlannedExpense.user_id == user_id,
        models.PlannedExpense.expected_date >= start,
        models.PlannedExpense.expected_date <= end,
        models.PlannedExpense.settled_on.is_(None),
    ).all()
    if proposal:
        planned = planned + [pe for pe in proposal.expenses if start <= pe.expected_date <= end]
    return planned


def card_one_offs_by_payoff(
    planned: list[models.PlannedExpense], account_id: int, cards_by_id: dict[int, models.CreditCard],
) -> dict[date, list[tuple[models.PlannedExpense, models.CreditCard]]]:
    """Card-linked one-offs keyed by the card's payoff date for them. A charge
    doesn't touch checking until the card gets paid off, so these land on the
    card's next statement due date, not their own. Only this account's (or
    unlinked) one-offs."""
    out: dict[date, list[tuple[models.PlannedExpense, models.CreditCard]]] = {}
    for pe in planned:
        if pe.account_id is not None and pe.account_id != account_id:
            continue
        card = cards_by_id.get(pe.card_id) if pe.card_id else None
        if card:
            out.setdefault(_card_payoff_date_for_charge(card, pe.expected_date), []).append((pe, card))
    return out


def pending_card_debits_by_card(
    db: Session, account: models.Account, cards: list[models.CreditCard], today: date,
) -> dict[int, list[models.AccountPendingTransaction]]:
    """Card payments the bank still lists as pending on this checking account
    (Plaid sync's AccountPendingTransaction snapshot), grouped by the card
    they pay. Only card-matching DEBITS count: any other pending debit is
    most likely a bill the walk already projects, and subtracting it as
    well would charge it twice. Pending credits are left alone too.

    Only while an ACTIVE Plaid link feeds this account: nothing else
    refreshes the snapshot, and stale rows would be subtracted forever."""
    out: dict[int, list[models.AccountPendingTransaction]] = {}
    for row in checking_pending_debits(db, account, today, card_payments_only=True):
        paid = match_payment_card(cards, row.description)
        if paid is not None:
            out.setdefault(paid.id, []).append(row)
    return out


def card_payments(
    db: Session, user: models.User, account: models.Account, start: date, end: date, *,
    include_unbilled_card_bills: bool, proposal: ScenarioProposal | None = None,
    today: date | None = None,
) -> list[CardPayment]:
    """Every card payment landing on `account` between `start` and `end`
    inclusive, in the order the forecast injects them (card by card)."""
    return card_payment_plan(
        db, user, account, start, end,
        include_unbilled_card_bills=include_unbilled_card_bills, proposal=proposal, today=today,
    ).payments


def card_payment_plan(
    db: Session, user: models.User, account: models.Account, start: date, end: date, *,
    include_unbilled_card_bills: bool, proposal: ScenarioProposal | None = None,
    today: date | None = None, planned: list[models.PlannedExpense] | None = None,
) -> CardPaymentPlan:
    """`card_payments` plus the overdue payoffs. `planned` is the window's
    one-offs when the caller already holds them (build_forecast does); the
    model reads them itself otherwise. They only feed each cycle estimate's
    `one_offs` context line."""
    today = today or date.today()
    user_id = user.id
    account_id = account.id
    out: list[CardPayment] = []
    overdue: list[CardPayment] = []

    # Card bills are paid from checking. CreditCard has no payment-account
    # link, so without this guard every payoff and estimate was injected into
    # whichever account was being forecast -- forecasting the user's savings drew
    # the Chase payoff and two monthly estimates out of it and ended at
    # -$15,000.00. Recurring credit_card_payment items are already scoped by
    # their own account_id and are unaffected.
    injects_card_bills = account.type == models.AccountType.checking
    if not injects_card_bills:
        return CardPaymentPlan(out, overdue)

    cards = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user_id,
        models.CreditCard.is_active == True,
    ).all()
    cards_by_id = {c.id: c for c in cards}
    proposal_items = list(proposal.items) if proposal else []
    pending_debits = pending_card_debits_by_card(db, account, cards, today)
    if planned is None:
        planned = window_planned_expenses(db, user_id, start, end, proposal)
    one_offs_by_payoff = card_one_offs_by_payoff(planned, account_id, cards_by_id)

    # Recurring items on this account: the card-linked expenses are what a
    # lightly-used card is expected to be charged (they drive its spend
    # estimate); a recurring credit_card_payment item already pays its card.
    account_items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.account_id == account_id,
        models.RecurringItem.is_active == True,
        models.RecurringItem.include_in_forecast == True,
    ).all()
    # A scenario's proposed items on this account, routed like the real ones.
    account_items += [i for i in proposal_items if i.account_id == account_id]
    card_items_by_card: dict[int, list[models.RecurringItem]] = {}
    for item in account_items:
        if item.type == models.RecurringType.expense and item.card_id is not None:
            card_items_by_card.setdefault(item.card_id, []).append(item)
    # CC payment injections: cards with next_payment_date set, balance_due > 0,
    # and no existing recurring CC payment item already handling this card (avoid double-count).
    recurring_cc_card_ids = {
        item.card_id for item in account_items if item.type == models.RecurringType.credit_card_payment
    }
    # Cards whose pending_charges came from the bank's pending feed rather
    # than being typed in. Those charges belong to the current cycle and are
    # already inside the carried payoff, so the second hop below must not
    # spend them again as the following cycle's payment.
    bank_feed_pending_card_ids = {
        card_id for (card_id,) in db.query(models.CardPendingTransaction.card_id).filter(
            models.CardPendingTransaction.user_id == user_id,
        ).distinct()
    }
    for card in (cards if injects_card_bills else []):
        if card.id in recurring_cc_card_ids:
            continue  # recurring CC payment item already handles this card

        if card.payment_sent_pending_sync:
            # Already subtracted once on today (pending_today_lines, after
            # today's anchor; it was the opening seed once). Every injection
            # path below this point -- locked payoff, carried-forward
            # estimate, flat monthly estimate -- would double it, because
            # marking a card doesn't change next_payment_date or
            # balance_due, the fields those paths key off. Confirmed live
            # by the final whole-branch review, 2026-08-28: a $5,000
            # payment left checking twice without this guard.
            continue

        # A payment already pending at the bank for this card. It comes off
        # checking today (pending_today_lines); here it comes off what's still
        # planned: first the statement payoff, then -- only while the
        # statement still stands -- any excess off the next cycle's
        # estimate. Once the card's own feed shows the statement paid
        # (balance_due 0), the payment is already a credit on the card and
        # current_balance excludes it, so the estimate needs nothing more.
        pending_paid = sum(
            (-Decimal(str(r.amount)) for r in pending_debits.get(card.id, [])), Decimal("0"),
        )
        statement_due = Decimal(str(card.balance_due or 0))
        excess_paid = max(pending_paid - statement_due, Decimal("0")) if statement_due > 0 else Decimal("0")

        # A next_payment_date that has gone stale must not swallow the balance.
        # the user's Apple Card sat at 2026-05-25 with $250.00 due while the forecast
        # ran August: the window check below never matched, so the card was
        # invisible to the forecast entirely -- no payoff, and no estimate
        # either, because its monthly_spend_estimate was 0. Cards that only sync
        # monthly will drift like this by design, so roll a past due date
        # forward to the next real one instead of dropping the money.
        #
        # Stale means older than the last _UNCONFIRMED_LOOKBACK_DAYS, though,
        # not merely past. A statement due a day or two ago and still unpaid
        # is not stale: its payment just hasn't posted. The walk still visits
        # that date (the Transactions page's trailing window, and the bridge
        # behind every start=today forecast), and _cc_actual_nearby drops the
        # payoff there once the real payment posts. Rolling it a month
        # forward instead dropped the statement outright and left only the
        # card's subscription estimate on its due date (Apple Card, found
        # live 2026-10-26, the day after its due date).
        next_payment = card.next_payment_date
        payment_is_stale = bool(
            next_payment is not None
            and next_payment < today - timedelta(days=_UNCONFIRMED_LOOKBACK_DAYS)
            and card.balance_due and card.balance_due > 0
        )
        # A due date reached with nothing due belongs to a statement that is
        # already paid: the card's feed keeps reporting the paid statement's
        # due date until the next statement arrives. That month gets nothing
        # -- no payoff, no estimate; the next cycle is planned on the
        # following due date (derived_due below). Without this the month
        # looked unclaimed and drew a flat estimate on the paid date (Chase,
        # found live 2026-10-26).
        paid_statement_due = bool(
            next_payment is not None
            and next_payment <= today
            and not (card.balance_due and card.balance_due > 0)
        )
        if payment_is_stale:
            next_payment = _next_occurrence_on_or_after(card.due_day, today)

        # The cycle right after a locked payoff is not a guess -- most of it is
        # already sitting on the card. the user derives it exactly this way
        # (2026-08-14): "based on current balance due on 8/25 of $7,000.00 and
        # running balance of $10,000.00 we get the forecast for next credit
        # card due date which would be 9/25." The gap between running balance
        # and statemented balance is spending already made that simply has not
        # been billed yet; add the subscriptions that will still post before
        # the statement closes and the cycle is nearly determined. A flat
        # monthly estimate ignores all of that and overstated the user's 9/25 payoff
        # by roughly $1,730.
        #
        # Computed before the stale-payment injection below (not after, as
        # originally written) because a stale `next_payment_date` rolls
        # forward using the same `_next_occurrence_on_or_after(due_day, ...)`
        # math this derives, so the two land on the identical date whenever
        # the real payoff already happened and is just waiting on bank sync --
        # need derived_amount in hand before deciding whether the stale
        # payment would double it up.
        derived_due: date | None = None
        derived_amount = Decimal("0")
        derived_basis: dict | None = None
        # balance_due at 0 is not "nothing owed" -- it means the last
        # statement is fully paid, but current_balance can still carry real,
        # already-spent debt that hasn't hit a statement yet (the user's Chase,
        # 2026-08-27: balance_due dropped to $0 right after payoff, while
        # current_balance still carried $5,000.00 of real spend). The
        # original guard required balance_due > 0, so that money silently
        # stopped being planned for the moment a card got paid off -- the
        # forecast fell back to the flat monthly_spend_estimate and
        # understated the very next payoff. `carried` below already computes
        # the right number in both cases (it's current_balance minus
        # whatever's already been billed); only the guard was too narrow.
        if (
            next_payment is not None
            and card.current_balance is not None
            and (
                (card.balance_due and card.balance_due > 0)
                or Decimal(str(card.current_balance)) > 0
            )
        ):
            carried = (
                Decimal(str(card.current_balance))
                + card_pending(card, today)
                - Decimal(str(card.balance_due))
            )
            carried = max(carried, Decimal("0"))
            # Forward-searching for "the next close" from today skips right
            # past a close that happened only a few days ago -- current_balance
            # already carries that cycle's real spend the moment it closes,
            # but the forward search finds the FOLLOWING month's close
            # instead, deriving a payoff one whole cycle late. Confirmed live
            # 2026-09-02: Chase's real close was 8/28 (5 days before today),
            # forward search found 9/28 instead, deriving a payoff due 10/25
            # -- not the real 9/25 the user already knew from his bank. A separate
            # flat-estimate fallback elsewhere in this function fills the
            # now-unclaimed 9/25 slot with a generic guess instead, which is
            # the number that was actually distorting budget_snapshot.py's
            # Left to Spend / Safety Margin.
            #
            # Only recognized when balance_due == 0, though -- NOT unconditionally
            # (a first version of this fix was; regression found live
            # 2026-09-02, hours after the user hand-entered a real, current,
            # non-stale balance_due of $6,000.00 due 9/25). balance_due == 0
            # means "nothing billed for the recent close yet", which is
            # exactly the gap this fix exists for. balance_due > 0 means a
            # real bill for that close ALREADY EXISTS -- the user's $6,000.00 IS the
            # money from the 8/28 close, injected separately below via
            # next_payment. Recognizing the same close here too made the
            # carried estimate ($1,000.00 of spend that will belong to the
            # FOLLOWING cycle, not this one) land on the SAME 9/25 date as
            # that real payment: $6,000.00 and $1,000.00 both charged on 9/25,
            # double-counting the $1,000.00 slice. With balance_due > 0 the
            # forward search below is what's wanted -- it correctly skips to
            # the NEXT unbilled close (9/28, due 10/25), where that new
            # spend actually belongs. the user's own worked example (2026-08-14,
            # asked on the 14th with a 28th statement_day) still finds the
            # 28th of THAT month either way, because 17 days separate the
            # 14th from July's close -- outside the lookback regardless.
            # Today, not the window's start: the cycle after a locked payoff
            # is one fact about the card, so a window opening next month must
            # place it where a window opening today does (it fell a month late
            # in a future window, and that month got a flat estimate instead).
            anchor = today
            if not (card.balance_due and card.balance_due > 0):
                recent_close = _most_recent_occurrence_on_or_before(card.statement_day, anchor)
                if (anchor - recent_close).days <= _UNCONFIRMED_LOOKBACK_DAYS:
                    next_close = recent_close
                else:
                    next_close = _next_occurrence_on_or_after(card.statement_day, anchor)
            else:
                next_close = _next_occurrence_on_or_after(card.statement_day, anchor)
            derived_due = _next_occurrence_on_or_after(card.due_day, next_close + timedelta(days=1))
            # The Safety Margin floor opts out of part of this sum: it
            # subtracts this month's card bills not yet charged on its own (the
            # user's sheet, '2026 Overview'!B18), and counting them here as well
            # charged them twice (found live 2026-10-01). Only those, though:
            # the cursor starts after today, so a bill in today's month is one
            # charged_so_far has not counted yet. A bill charged in a LATER
            # month before this close is nobody else's to subtract, and
            # dropping it too left the floor optimistic by a whole month of
            # subscriptions (found live 2026-10-30). The Forecast page keeps
            # every bill in the payoff.
            subscriptions_before_close = Decimal("0")
            cursor = today + timedelta(days=1)
            while cursor <= next_close:
                for item in card_items_by_card.get(card.id, []):
                    if not _fires_on(item, cursor):
                        continue
                    if (
                        not include_unbilled_card_bills
                        and (cursor.year, cursor.month) == (today.year, today.month)
                        and is_card_bill_in_month(item, cursor)
                    ):
                        continue
                    subscriptions_before_close += item.amount
                cursor += timedelta(days=1)
            derived_amount = carried + subscriptions_before_close
            derived_amount = max(derived_amount - excess_paid, Decimal("0"))
            # The breakdown behind `derived_amount`, for the explain panel.
            # `carried` blends two different stories and the note must not
            # flatten them into one "pending" label: live pending_charges
            # (money the bank already knows about, not yet posted) versus
            # spending that already POSTED to current_balance since the last
            # statement closed but was never itself "pending" (a card with
            # $0 pending and spending carried -- labeling that "pending" was
            # simply wrong). pending_live is
            # capped at `carried` so the split can never claim more live
            # pending than the carried total actually contains (the carried
            # clamp to >= 0 above can shrink the total below the card's own
            # pending_charges figure, e.g. a recent overpayment).
            pending_live = min(card_pending(card, today), carried)
            spent_since_statement = carried - pending_live
            last_close = _most_recent_occurrence_on_or_before(card.statement_day, anchor)
            # Mirrors the math above exactly, including the excess_paid
            # trim -- taken off the carried pieces first (spent-since-statement,
            # then live pending), then off the subscriptions slice -- so
            # pending + spent_since_statement + subscriptions always nets to
            # derived_amount pre-one_offs. A card-routed one-off landing on
            # this exact due date (`derived_due`) is real spending that
            # belongs to this cycle too, but it renders as its OWN forecast
            # line below (one_offs_by_payoff), not folded into
            # derived_amount -- so one_offs is accurate context here, not an
            # addend of derived_amount. It is 0 whenever no such one-off
            # exists, which is the common case (confirmed against the
            # user's real Chase cycle, 2026-10-29).
            basis_subscriptions = subscriptions_before_close
            remaining_excess = excess_paid
            if remaining_excess > 0:
                trim = min(spent_since_statement, remaining_excess)
                spent_since_statement -= trim
                remaining_excess -= trim
            if remaining_excess > 0:
                trim = min(pending_live, remaining_excess)
                pending_live -= trim
                remaining_excess -= trim
            if remaining_excess > 0:
                basis_subscriptions = max(basis_subscriptions - remaining_excess, Decimal("0"))
            basis_one_offs = sum(
                (abs(Decimal(str(pe.amount))) for pe, c in one_offs_by_payoff.get(derived_due, []) if c.id == card.id),
                Decimal("0"),
            )
            derived_basis = {
                "kind": "cycle_estimate",
                "pending": pending_live,
                "spent_since_statement": spent_since_statement,
                "statement_date": last_close,
                "subscriptions_before_close": basis_subscriptions,
                "one_offs": basis_one_offs,
                "close_date": next_close,
            }

        # Second hop: the cycle right after the one just derived above.
        # There is no "carried" real balance signal for it yet -- that
        # window has not started accruing real spend as of today -- but a
        # fresh pending_charges figure (the user's own hand-tracked read of what
        # is already posting toward it, per his spreadsheet, 2026-08-28) is
        # still better than jumping straight to the flat monthly estimate.
        # Only one hop: cycles beyond this one have no real signal at all
        # and keep the flat estimate, matching the user's own unedited
        # spreadsheet cells for every month past this one.
        second_close: date | None = None
        second_due: date | None = None
        second_amount = Decimal("0")
        if derived_due is not None and card.monthly_spend_estimate and card.monthly_spend_estimate > 0:
            # Restricted to monthly_spend_estimate cards only (controller
            # ruling, final whole-branch review, 2026-08-28): on a
            # subscription-driven card, this hop's suppression logic below
            # would delete that month's subscription-based projection
            # instead of supplementing it, since _covered_by_real_payment
            # is shared with the subscription-fallback branch further down
            # this function. The spec's scope was always manually-estimated
            # cards (the user's Chase); subscription-driven cards (Apple Card)
            # keep their existing, untouched projection unchanged.
            second_close = _next_occurrence_on_or_after(card.statement_day, derived_due + timedelta(days=1))
            second_due = _next_occurrence_on_or_after(card.due_day, second_close + timedelta(days=1))
            second_amount = (
                Decimal("0") if card.id in bank_feed_pending_card_ids
                else card_pending(card, today)
            )
        # No carried balance and no subscriptions-before-close signal exists
        # for this hop yet (see comment above) -- the whole amount, when
        # there is one, is the fresh pending-charges read.
        second_basis: dict | None = (
            {
                "kind": "cycle_estimate", "pending": second_amount,
                "spent_since_statement": Decimal("0"), "statement_date": None,
                "subscriptions_before_close": Decimal("0"), "one_offs": Decimal("0"),
                "close_date": second_close,
            }
            if second_due is not None else None
        )

        # A stale next_payment_date rolled forward lands on the exact date
        # derived_due just computed above whenever the real payoff already
        # happened and is only waiting on bank sync to confirm it (both use
        # `_next_occurrence_on_or_after(due_day, ...)` anchored near `today`).
        # Injecting the old balance_due there on top of derived_amount would
        # double-charge the card -- $7,500.00 (the stale, presumably
        # already-paid balance) plus $5,000.00 (the next cycle's own carried
        # estimate) on the same day (confirmed live 2026-08-26, crashed the
        # forecast to -$3,500.00). Trust that the payoff happened and fold the
        # two into one line rather than dropping either: the carried figure
        # IS the real, known money (current_balance minus the last statement,
        # both hard numbers) plus a small subscription projection, so it
        # belongs on the "CC Payment" / is_cc_locked=True side, not
        # downgraded to "CC Estimate" just because it merged with the stale
        # payoff (the user, 2026-08-26). Only merge when derived_amount is
        # actually going to cover the money; a card with nothing carried and
        # no card-linked subscriptions (derived_amount == 0) has nothing
        # standing in for the stale payment, and dropping it there
        # resurrects the original "Apple Card invisible" bug this rollover
        # was written to fix. Same date + a real number to replace it with
        # is what makes merging it safe.
        payment_double_counts_derived = bool(
            payment_is_stale
            and derived_due is not None
            and next_payment == derived_due
            and derived_amount > 0
        )

        if payment_double_counts_derived:
            if start <= derived_due <= end:
                out.append(CardPayment(card.id, derived_due, derived_amount, True, derived_basis))
        elif (
            next_payment is not None
            and next_payment < today
            and card.balance_due and card.balance_due > 0
            and statement_due - pending_paid > 0
        ):
            # Due in the last week (not stale) and still unpaid. Recorded
            # whether or not the due date is in this window: a window that
            # starts today never visits it, but still re-plans it after
            # today's auto anchor (see replan_overdue_on_today).
            overdue.append(CardPayment(
                card.id, next_payment, statement_due - pending_paid, True,
                {"kind": "locked", "due_date": next_payment},
            ))
            if start <= next_payment <= end:
                out.append(CardPayment(
                    card.id, next_payment, statement_due - pending_paid, True,
                    {"kind": "locked", "due_date": next_payment},
                ))
        elif (
            next_payment is not None
            and start <= next_payment <= end
            and card.balance_due and card.balance_due > 0
        ):
            # balance_due only, NOT + pending_charges -- the user's real
            # spreadsheet forecast pays off only the last-statement total on
            # the due date ("2026 Forecast" row 24: "=L23-5000.00-100.00",
            # no pending-charges term), and separately counts pending_charges
            # exactly once via budget_snapshot.py's Left to Spend.
            # Adding it here too double-counted it: once in this payoff
            # projection, once again downstream. Confirmed live 2026-08-09.
            #
            # A payment for this statement already pending at the bank is
            # subtracted today (see pending_today_lines), so only what it
            # doesn't cover is still to be paid on the due date.
            still_due = statement_due - pending_paid
            if still_due > 0:
                out.append(CardPayment(
                    card.id, next_payment, still_due, True,
                    {"kind": "locked", "due_date": next_payment},
                ))

        def _covered_by_real_payment(when: date) -> bool:
            """Something better than an estimate already lands in this month --
            either the locked balance_due payoff, or the carried-balance figure
            derived above. A flat estimate on top of either would charge the
            same statement twice."""
            if derived_due is not None and (derived_due.year, derived_due.month) == (when.year, when.month):
                return True
            if second_due is not None and second_amount > 0 and (second_due.year, second_due.month) == (when.year, when.month):
                return True
            return (
                next_payment is not None
                and next_payment.year == when.year
                and next_payment.month == when.month
                and (bool(card.balance_due and card.balance_due > 0) or paid_statement_due)
            )

        # Already folded into the locked payments above when it merged with the
        # stale payoff -- injecting it again here would be the exact
        # double-count this whole block exists to prevent.
        if (
            not payment_double_counts_derived
            and derived_due is not None
            and start <= derived_due <= end
            and derived_amount > 0
        ):
            out.append(CardPayment(card.id, derived_due, derived_amount, False, derived_basis))

        if (
            second_due is not None
            and start <= second_due <= end
            and second_amount > 0
        ):
            out.append(CardPayment(card.id, second_due, second_amount, False, second_basis))

        if card.monthly_spend_estimate and card.monthly_spend_estimate > 0:
            # A manually-set estimate wins: it is the user's own read on a card he
            # spends freely from (Chase, $5,500/mo), which subscriptions alone
            # would badly understate.
            estimate = Decimal(str(card.monthly_spend_estimate))
            flat_basis = {"kind": "flat", "monthly_amount": estimate}
            cur = date(start.year, start.month, 1)
            while cur <= end:
                due_day = min(card.due_day, _last_day_of_month(cur))
                inject_date = date(cur.year, cur.month, due_day)
                if start <= inject_date <= end and not _covered_by_real_payment(inject_date):
                    out.append(CardPayment(card.id, inject_date, estimate, False, flat_basis))
                cur = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)
        else:
            # No manual estimate: build one from the subscriptions actually
            # assigned to this card. the user's Apple Card is only ever charged by
            # its subscriptions, and bank sync refreshes it monthly at best, so
            # the recurring items are a better forward signal than a balance
            # that is stale most of the time (his call, 2026-08-14). Charges are
            # routed through _card_payoff_date_for_charge rather than dropped on
            # the due date in their own month -- a subscription billed the 30th
            # misses that statement's close and is not paid off for another full
            # cycle.
            #
            # The Safety Margin walk (include_unbilled_card_bills=False) leaves
            # out the charges it subtracts on its own: a bill still to come in
            # today's month that is on that month's card-bills list (the same
            # rule as the cycle estimate's cursor above). Keeping them here
            # took each one off twice.
            def _subtracted_elsewhere(item, charge_date: date) -> bool:
                return (
                    not include_unbilled_card_bills
                    and charge_date > today
                    and (charge_date.year, charge_date.month) == (today.year, today.month)
                    and is_card_bill_in_month(item, charge_date)
                )

            by_payoff: dict[date, Decimal] = {}
            for charge_date, amount in _card_subscription_charges(
                card_items_by_card.get(card.id, []), start, end, skip=_subtracted_elsewhere,
            ).items():
                payoff = _card_payoff_date_for_charge(card, charge_date)
                by_payoff[payoff] = by_payoff.get(payoff, Decimal("0")) + amount
            for payoff, amount in sorted(by_payoff.items()):
                if start <= payoff <= end and not _covered_by_real_payment(payoff):
                    out.append(CardPayment(
                        card.id, payoff, amount, False,
                        {"kind": "subscription_flat", "monthly_amount": amount},
                    ))
    return CardPaymentPlan(out, overdue)
