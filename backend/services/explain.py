"""Receipts for calculated numbers.

A calculator records its steps as it goes, using its own variables, so the
explanation can't drift from the math. replay() re-runs the steps and must
land on the displayed value to the cent (tests enforce this per metric).
"""
from __future__ import annotations
from decimal import Decimal
from backend import schemas

CENTS = Decimal("0.01")


class ExplainBuilder:
    def __init__(self, title: str):
        self.title = title
        self.rows: list[schemas.ExplainRow] = []

    def _row(self, op, label, amount, note=None, children=None):
        self.rows.append(schemas.ExplainRow(
            op=op, label=label, amount=amount, note=note, children=children or [],
        ))
        return self

    def start(self, label: str, amount: Decimal, note: str | None = None, children=None):
        return self._row("start", label, amount, note, children)

    def add(self, label: str, amount: Decimal, note: str | None = None, children=None):
        return self._row("add", label, amount, note, children)

    def subtract(self, label: str, amount: Decimal, note: str | None = None, children=None):
        return self._row("subtract", label, amount, note, children)

    def divide(self, label: str, divisor: Decimal, note: str | None = None):
        return self._row("divide", label, divisor, note)

    def build(self, result: Decimal) -> schemas.Explanation:
        rows = self.rows + [schemas.ExplainRow(op="result", label=self.title, amount=result)]
        return schemas.Explanation(title=self.title, result=result, rows=rows)


def replay(explanation: schemas.Explanation) -> Decimal:
    value = Decimal("0")
    for row in explanation.rows:
        if row.op == "start":
            value = row.amount
        elif row.op == "add":
            value += row.amount
        elif row.op == "subtract":
            value -= row.amount
        elif row.op == "divide":
            value = (value / row.amount).quantize(CENTS)
    return value


def children_consistent(explanation: schemas.Explanation) -> bool:
    return all(
        sum((c.amount for c in row.children), Decimal("0")) == row.amount
        for row in explanation.rows if row.children
    )
