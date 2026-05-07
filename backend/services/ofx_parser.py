"""OFX/QFX bank file parser (used for files downloaded from bank websites)."""
from __future__ import annotations
import io
from decimal import Decimal, InvalidOperation
from backend.services.csv_parser import ParsedRow, _is_cc_transfer


def parse_ofx(content: bytes) -> list[ParsedRow]:
    """Parse an OFX or QFX file and return a list of ParsedRow objects."""
    try:
        from ofxparse import OfxParser
    except ImportError:
        raise RuntimeError(
            "ofxparse is not installed. Run: pip install ofxparse"
        )

    ofx = OfxParser.parse(io.BytesIO(content))

    account = getattr(ofx, "account", None)
    if not account:
        return []

    statement = getattr(account, "statement", None)
    if not statement:
        return []

    rows: list[ParsedRow] = []
    for txn in statement.transactions:
        desc = (
            getattr(txn, "memo", "") or
            getattr(txn, "payee", "") or
            getattr(txn, "id", "") or ""
        ).strip()
        if not desc:
            continue

        raw_amount = getattr(txn, "amount", None)
        if raw_amount is None:
            continue
        try:
            amount = Decimal(str(raw_amount))
        except InvalidOperation:
            continue

        raw_date = getattr(txn, "date", None)
        if raw_date is None:
            continue
        txn_date = raw_date.date() if hasattr(raw_date, "date") else raw_date

        rows.append(ParsedRow(
            date=txn_date,
            description=desc,
            amount=amount,
            is_transfer=_is_cc_transfer(desc),
        ))

    return rows
