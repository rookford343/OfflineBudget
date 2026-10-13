"""User-defined transaction rules engine — runs at import time after history lookup."""
from __future__ import annotations
import re
from dataclasses import dataclass
from backend import models


@dataclass
class RuleMatch:
    rule_id: int
    category_id: int | None
    is_transfer: bool


def apply_rules(
    description: str,
    rules: list[models.TransactionRule],
) -> RuleMatch | None:
    """Return the first matching rule (sorted by priority descending), or None."""
    for rule in sorted(rules, key=lambda r: r.priority, reverse=True):
        if not rule.is_active:
            continue
        if _matches(rule.pattern, getattr(rule.pattern_type, "value", rule.pattern_type), description):
            return RuleMatch(
                rule_id=rule.id,
                category_id=rule.category_id,
                is_transfer=rule.action == models.RuleAction.mark_transfer,
            )
    return None


def test_rule(pattern: str, pattern_type: str, description: str) -> bool:
    """Check whether a single rule pattern matches a sample description (for UI live preview)."""
    return _matches(pattern, pattern_type, description)


def _wildcard(pattern: str) -> re.Pattern:
    """`*` matches anything; every other character is literal.

    The "regex" rule type used to run the user's pattern as a real regex, and
    a pattern like `(a+)+$` backtracks for minutes on a short description,
    hanging the worker (CodeQL py/regex-injection). Escaping everything but
    `*` keeps the matching linear. No stored rule used regex syntax when this
    changed (2026-10-12)."""
    return re.compile(".*".join(re.escape(part) for part in pattern.split("*")), re.IGNORECASE)


def _matches(pattern: str, pattern_type: str, description: str) -> bool:
    """The one place a rule pattern is tested against a description."""
    desc_lower = description.lower()
    if pattern_type == "contains":
        return pattern.lower() in desc_lower
    if pattern_type == "startswith":
        return desc_lower.startswith(pattern.lower())
    if pattern_type == "regex":
        return _wildcard(pattern).search(description) is not None
    return False
