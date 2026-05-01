import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from sqlalchemy.orm import Session
from backend import models
from backend.schemas import RecurringSuggestion


def _normalize(description: str) -> str:
    """Lowercase and strip non-alphanumeric chars for fuzzy matching."""
    return re.sub(r"[^a-z0-9 ]", "", description.lower()).strip()


def detect_patterns(
    db: Session,
    user_id: int,
    min_occurrences: int = 2,
) -> list[RecurringSuggestion]:
    """Scan transaction history for recurring patterns not already in recurring_items."""
    cutoff = date.today() - timedelta(days=395)  # ~13 months — enough for reliable pattern detection
    transactions = (
        db.query(models.Transaction)
        .filter(
            models.Transaction.user_id == user_id,
            models.Transaction.is_actual == True,
            models.Transaction.amount < 0,
            models.Transaction.date >= cutoff,
        )
        .order_by(models.Transaction.date)
        .all()
    )

    # Group by normalized description
    groups: dict[str, list[models.Transaction]] = defaultdict(list)
    for t in transactions:
        key = _normalize(t.description)
        if key:
            groups[key].append(t)

    # Existing recurring item names to filter out
    existing = {
        _normalize(r.name)
        for r in db.query(models.RecurringItem)
        .filter(models.RecurringItem.user_id == user_id, models.RecurringItem.is_active == True)
        .all()
    }

    suggestions: list[RecurringSuggestion] = []
    for key, txns in groups.items():
        if key in existing:
            continue
        if len(txns) < min_occurrences:
            continue

        dates = sorted(t.date for t in txns)
        if len(dates) < 2:
            continue

        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        avg_gap = sum(gaps) / len(gaps)

        if 28 <= avg_gap <= 32 and len(txns) >= 2:
            frequency = "monthly"
        elif 5 <= avg_gap <= 9 and len(txns) >= 3:
            frequency = "weekly"
        else:
            continue

        amounts = [abs(t.amount) for t in txns]
        med_amount = Decimal(str(round(float(median(amounts)), 2)))

        suggestions.append(RecurringSuggestion(
            description=txns[0].description,
            median_amount=med_amount,
            frequency=frequency,
            occurrences=len(txns),
        ))

    return sorted(suggestions, key=lambda s: s.occurrences, reverse=True)
