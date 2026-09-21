"""What one occurrence of each recurring frequency costs per month on average.

Deliberately NOT the same treatment as budget_snapshot._monthly_expenses,
which charges a yearly bill in full in the month it lands to reconcile with
the spreadsheet's Leftover row. This is the "what does my life cost per
month" figure, so a yearly bill is a twelfth of itself.

Lives here rather than in routers/recurring.py so both the /recurring/breakdown
endpoint and the scenario impact figures read the same helper -- the two
screens then agree by construction, not because two implementations happen to
round the same way.
"""
from decimal import Decimal, ROUND_HALF_UP

from backend import models

MONTHLY_FACTOR = {
    models.RecurringFrequency.monthly: Decimal(1),
    models.RecurringFrequency.quarterly: Decimal(1) / Decimal(3),
    models.RecurringFrequency.yearly: Decimal(1) / Decimal(12),
    models.RecurringFrequency.weekly: Decimal(52) / Decimal(12),
    models.RecurringFrequency.biweekly: Decimal(26) / Decimal(12),
}


def monthly_equivalent(item) -> Decimal:
    """`item` is any object with `.amount` and `.frequency` -- a real
    RecurringItem or a transient one built from a scenario proposal."""
    factor = MONTHLY_FACTOR.get(item.frequency, Decimal(1))
    return (item.amount * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
