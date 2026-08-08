"""CSV format detection and row parsing for bank/card imports."""
from __future__ import annotations
import csv
import html
import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from backend.models import ImportFormat


_CC_TRANSFER_PATTERNS = (
    "CREDIT CRD AUTOPAY",
    "CREDIT CRD AUTOPA",
    "APPLECARD GSBANK",
    "CITI AUTOPAY",
    "AUTOPAY PAYMENT",
    "ONLINE PAYMENT - THANK",
    "AUTOMATIC PAYMENT",
)


def _is_cc_transfer(description: str) -> bool:
    upper = description.upper()
    return any(p in upper for p in _CC_TRANSFER_PATTERNS)


_ZELLE_RE = re.compile(
    r"^Zelle\s+payment\s+(from|to)\s+([A-Za-z][A-Za-z\s\-]+?)\s+[A-Za-z0-9]{6,}$",
    re.IGNORECASE,
)


def _clean_description(desc: str) -> str:
    desc = html.unescape(desc)
    m = _ZELLE_RE.match(desc.strip())
    if m:
        direction = m.group(1).lower()
        name = m.group(2).strip().title()
        return f"Zelle {direction} {name}"
    return desc.strip()


@dataclass
class ParsedRow:
    date: date
    description: str
    amount: Decimal  # positive = credit/income, negative = debit/charge
    is_transfer: bool = False
    # Upstream provider's transaction id, when the source has one (SimpleFIN).
    # CSV/OFX parsing never sets this, so those paths keep the legacy
    # date/amount/description dedup heuristic unchanged.
    external_id: str | None = None


def detect_format(headers: list[str]) -> ImportFormat:
    h = {h.strip().lower() for h in headers}
    if "posting date" in h and "details" in h:
        return ImportFormat.chase
    if "transaction date" in h and "category" in h and "merchant name" not in h:
        return ImportFormat.chase  # Chase card CSV
    if "transaction date" in h and "merchant" in h:
        return ImportFormat.apple
    if "transaction date" in h and "description" in h and "amount" in h:
        return ImportFormat.generic
    return ImportFormat.generic


def parse_csv(content: bytes) -> list[ParsedRow]:
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    fmt = detect_format(list(headers))

    rows: list[ParsedRow] = []
    for row in reader:
        parsed = _parse_row(fmt, row)
        if parsed:
            rows.append(parsed)
    return rows


def _parse_date(s: str) -> date | None:
    s = s.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d/%m/%Y"):
        try:
            from datetime import datetime
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(s: str) -> Decimal | None:
    s = s.strip().replace("$", "").replace(",", "").replace(" ", "")
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _parse_row(fmt: ImportFormat, row: dict) -> ParsedRow | None:
    # Normalize keys; skip None keys (extra columns past header) and handle None values
    keys = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k is not None}

    if fmt == ImportFormat.chase:
        # Chase checking: columns = Details, Posting Date, Description, Amount, Type, Balance, Check or Slip #
        # Chase card: Transaction Date, Post Date, Description, Category, Type, Amount, Memo
        if keys.get("type", "").lower() == "payment":
            return None  # Skip card statement payment rows; they are not transactions
        d_str = keys.get("posting date") or keys.get("transaction date") or ""
        desc = _clean_description(keys.get("description") or "")
        amount_str = keys.get("amount") or ""

    elif fmt == ImportFormat.apple:
        # Apple Card: Transaction Date, Clearing Date, Description, Merchant, Category, Type, Amount (USD), Purchased By
        d_str = keys.get("transaction date") or ""
        desc = _clean_description(keys.get("merchant") or keys.get("description") or "")
        amount_str = keys.get("amount (usd)") or keys.get("amount") or ""
        # Apple amounts are positive for charges, negate to make them negative debits
        parsed_date = _parse_date(d_str)
        parsed_amount = _parse_amount(amount_str)
        if not parsed_date or parsed_amount is None or not desc:
            return None
        return ParsedRow(date=parsed_date, description=desc, amount=-abs(parsed_amount))

    else:
        # Generic: try common column names
        d_str = (keys.get("date") or keys.get("transaction date")
                 or keys.get("posting date") or "")
        desc = _clean_description(
            keys.get("description") or keys.get("merchant")
            or keys.get("payee") or keys.get("name") or ""
        )
        amount_str = keys.get("amount") or ""

    parsed_date = _parse_date(d_str)
    parsed_amount = _parse_amount(amount_str)

    if not parsed_date or parsed_amount is None or not desc:
        return None

    return ParsedRow(
        date=parsed_date,
        description=desc,
        amount=parsed_amount,
        is_transfer=_is_cc_transfer(desc),
    )
