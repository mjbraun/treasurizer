#!/usr/bin/env python3
# ABOUTME: One-off audit of Chase statement PDFs against PayHOA payment-groups
# ABOUTME: Finds check deposits into the HOA's Chase account that were never
# ABOUTME: credited to any unit in PayHOA.

"""Chase statement PDF audit.

Parses every Chase statement PDF in the account-dump folder, extracts every
deposit, and cross-references against PayHOA payment-groups to find deposits
that hit the bank but were never credited to a unit.

Usage:
    uv run python scripts/chase_audit.py
    uv run python scripts/chase_audit.py --statements-dir /path/to/statements
    uv run python scripts/chase_audit.py --json  # machine-readable output
"""

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from treasurizer.tools.reconciliation import _fetch_all_pages, _parse_iso_date  # noqa: E402
from treasurizer.client import get_client  # noqa: E402

DEFAULT_STATEMENTS_DIR = Path(
    "/Users/mjbraun/Documents/Personal/1357 Statements/account-dump/statements"
)

STATEMENT_PERIOD_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s*(\d{1,2}),?\s*(\d{4})\s*through\s*"
    r"(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s*(\d{1,2}),?\s*(\d{4})",
    re.IGNORECASE,
)

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

DEPOSIT_LINE_RE = re.compile(r"^(\d{2})/(\d{2})\s+(.+?)\s+\$?([\d,]+\.\d{2})\s*$")


@dataclass
class Deposit:
    statement: str
    date: date
    amount: float
    description: str

    def to_dict(self) -> dict:
        return {
            "statement": self.statement,
            "date": self.date.isoformat(),
            "amount": self.amount,
            "description": self.description,
        }


def parse_statement_period(text: str) -> tuple[date, date] | None:
    match = STATEMENT_PERIOD_RE.search(text.replace("\n", " "))
    if not match:
        return None
    start = date(int(match.group(3)), MONTHS[match.group(1).lower()], int(match.group(2)))
    end = date(int(match.group(6)), MONTHS[match.group(4).lower()], int(match.group(5)))
    return start, end


def resolve_date(mm: int, dd: int, period: tuple[date, date]) -> date:
    """MM/DD from statement text -> full date using statement period."""
    start, end = period
    # Try start year first
    for year in (start.year, end.year):
        try:
            d = date(year, mm, dd)
            if start <= d <= end:
                return d
        except ValueError:
            continue
    # Fall back to start year even if outside period (defensive)
    try:
        return date(start.year, mm, dd)
    except ValueError:
        return date(end.year, mm, dd)


def extract_deposits_from_pdf(path: Path) -> list[Deposit]:
    with pdfplumber.open(path) as pdf:
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    period = parse_statement_period(full_text)
    if not period:
        return []

    deposits: list[Deposit] = []
    in_deposits = False
    for line in full_text.split("\n"):
        stripped = line.strip()
        if "*start*deposits and additions" in stripped:
            in_deposits = True
            continue
        if "*end*deposits and additions" in stripped:
            in_deposits = False
            continue
        if not in_deposits:
            continue
        if stripped.startswith("Total Deposits"):
            continue
        if stripped in ("DEPOSITS AND ADDITIONS", "DATE DESCRIPTION AMOUNT"):
            continue

        m = DEPOSIT_LINE_RE.match(stripped)
        if not m:
            continue
        mm = int(m.group(1))
        dd = int(m.group(2))
        description = m.group(3).strip()
        amount = float(m.group(4).replace(",", ""))
        d = resolve_date(mm, dd, period)
        deposits.append(
            Deposit(
                statement=path.name,
                date=d,
                amount=amount,
                description=description,
            )
        )
    return deposits


def is_unit_payment(deposit: Deposit) -> bool:
    """Heuristic: is this deposit likely a unit owner's dues payment?"""
    desc = deposit.description.upper()
    # Check-style deposits
    if "CREDIT / DEPOSIT" in desc or desc == "DEPOSIT" or desc.startswith("DEPOSIT ID NUMBER"):
        return True
    # PayHOA processed payments
    if "PAYHOA" in desc:
        return True
    # Legacy Buildium processed payments
    if "BUILDIUM" in desc:
        return True
    return False


async def load_payment_groups() -> list[dict]:
    session = await get_client()
    pgs = await _fetch_all_pages(
        session,
        "/payment-groups",
        {"perPage": 100, "column": "createdAt", "direction": "asc"},
    )
    result = []
    for pg in pgs:
        d = _parse_iso_date(pg.get("createdAt"))
        if d is None:
            continue
        result.append(
            {
                "id": pg["id"],
                "date": d,
                "net_cents": int(pg.get("net") or 0),
                "gross_cents": int(pg.get("gross") or 0),
                "payor_id": pg.get("payorId"),
            }
        )
    return result


def reconcile(deposits: list[Deposit], pgs: list[dict], tolerance_days: int = 10) -> dict:
    """Match each deposit to the first unused PG with matching amount and near date."""
    matched_pg_ids: set[int] = set()
    matched: list[dict] = []
    unmatched: list[Deposit] = []

    # Sort deposits by date ascending for stable matching
    for dep in sorted(deposits, key=lambda d: d.date):
        dep_cents = int(round(dep.amount * 100))
        match = None
        for pg in pgs:
            if pg["id"] in matched_pg_ids:
                continue
            if pg["net_cents"] != dep_cents:
                continue
            if abs((pg["date"] - dep.date).days) > tolerance_days:
                continue
            match = pg
            break
        if match is None:
            unmatched.append(dep)
        else:
            matched_pg_ids.add(match["id"])
            matched.append({"deposit": dep.to_dict(), "pg_id": match["id"]})
    return {"matched": matched, "unmatched": [d.to_dict() for d in unmatched]}


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--statements-dir", type=Path, default=DEFAULT_STATEMENTS_DIR)
    parser.add_argument("--json", action="store_true", help="Output JSON instead of human summary")
    parser.add_argument("--tolerance-days", type=int, default=10)
    parser.add_argument(
        "--from",
        dest="start_date",
        type=str,
        default=None,
        help="Only include deposits on/after this date (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start_date) if args.start_date else None

    pdfs = sorted(args.statements_dir.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs in {args.statements_dir}", file=sys.stderr)
        return 1

    all_deposits: list[Deposit] = []
    for pdf in pdfs:
        try:
            deps = extract_deposits_from_pdf(pdf)
        except Exception as exc:
            print(f"WARN: failed to parse {pdf.name}: {exc}", file=sys.stderr)
            continue
        all_deposits.extend(deps)

    if start_date:
        all_deposits = [d for d in all_deposits if d.date >= start_date]

    unit_deposits = [d for d in all_deposits if is_unit_payment(d)]

    pgs = await load_payment_groups()
    if start_date:
        pgs = [p for p in pgs if p["date"] >= start_date]
    result = reconcile(unit_deposits, pgs, tolerance_days=args.tolerance_days)

    if args.json:
        print(
            json.dumps(
                {
                    "statements_scanned": len(pdfs),
                    "total_deposits_extracted": len(all_deposits),
                    "unit_payment_candidates": len(unit_deposits),
                    "payment_groups": len(pgs),
                    "matched_count": len(result["matched"]),
                    "unmatched_count": len(result["unmatched"]),
                    "unmatched": result["unmatched"],
                },
                indent=2,
            )
        )
    else:
        print(f"Statements scanned: {len(pdfs)}")
        print(f"Deposits extracted: {len(all_deposits)}")
        print(f"Unit-payment candidates: {len(unit_deposits)}")
        print(f"Payment-groups loaded: {len(pgs)}")
        print(f"Matched: {len(result['matched'])}")
        print(f"Unmatched (no PG credited to any unit): {len(result['unmatched'])}")
        print()
        print("=== UNMATCHED DEPOSITS ===")
        for d in result["unmatched"]:
            print(f"  {d['date']}  ${d['amount']:>8.2f}  {d['description'][:70]}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
