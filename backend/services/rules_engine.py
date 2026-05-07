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
    desc_lower = description.lower()
    for rule in sorted(rules, key=lambda r: r.priority, reverse=True):
        if not rule.is_active:
            continue
        pattern = rule.pattern
        matched = False
        if rule.pattern_type == models.RulePatternType.contains:
            matched = pattern.lower() in desc_lower
        elif rule.pattern_type == models.RulePatternType.startswith:
            matched = desc_lower.startswith(pattern.lower())
        elif rule.pattern_type == models.RulePatternType.regex:
            try:
                matched = bool(re.search(pattern, description, re.IGNORECASE))
            except re.error:
                continue
        if matched:
            return RuleMatch(
                rule_id=rule.id,
                category_id=rule.category_id,
                is_transfer=rule.action == models.RuleAction.mark_transfer,
            )
    return None


def test_rule(pattern: str, pattern_type: str, description: str) -> bool:
    """Check whether a single rule pattern matches a sample description (for UI live preview)."""
    desc_lower = description.lower()
    if pattern_type == "contains":
        return pattern.lower() in desc_lower
    if pattern_type == "startswith":
        return desc_lower.startswith(pattern.lower())
    if pattern_type == "regex":
        try:
            return bool(re.search(pattern, description, re.IGNORECASE))
        except re.error:
            return False
    return False
