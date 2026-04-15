# ABOUTME: Reconciliation helper tools for PayHOA
# ABOUTME: Tools to help investigate and resolve balance discrepancies

import json
from datetime import date, datetime
from decimal import Decimal

from treasurizer.client import get_client, with_auth_retry
from treasurizer.types import cents_to_decimal

DUES_CATEGORY_ID = 854772  # Assessments
DEPOSIT_KEYWORDS = ("CREDIT / DEPOSIT", "DEPOSIT ID NUMBER", "PAYHOA DEPOSIT")


@with_auth_retry
async def find_transactions_by_amount(
    target_amount: float,
    tolerance: float = 0.01,
    account_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Find transactions near a specific dollar amount."""
    session = await get_client()

    filters: dict = {}
    if account_id is not None:
        filters["account"] = account_id
    if start_date:
        filters["startDate"] = start_date
    if end_date:
        filters["endDate"] = end_date

    target = Decimal(str(target_amount))
    tol = Decimal(str(tolerance))
    matching = []

    for page in range(1, 100):
        params: dict = {
            "page": page,
            "perPage": 100,
            "column": "transactionDate",
            "direction": "desc",
        }
        if filters:
            params["filters"] = json.dumps(filters)

        response = await session.get("/transactions", params=params)
        data = response.json()
        txns = data.get("data", [])

        if not txns:
            break

        for txn in txns:
            amt = abs(cents_to_decimal(txn.get("amount")))
            orig_amt = abs(cents_to_decimal(txn.get("originalAmount")))

            if abs(amt - target) <= tol or abs(orig_amt - target) <= tol:
                txn_date = txn.get("transactionDate", "")[:10]
                matching.append(
                    {
                        "id": txn["id"],
                        "date": txn_date,
                        "amount": float(cents_to_decimal(txn.get("amount"))),
                        "original_amount": float(cents_to_decimal(txn.get("originalAmount"))),
                        "description": txn.get("description", ""),
                        "memo": txn.get("memo"),
                        "is_credit": txn.get("originalAmount", 0) < 0,
                        "is_debit": txn.get("originalAmount", 0) > 0,
                    }
                )

            if len(matching) >= limit:
                break

        if len(matching) >= limit:
            break

    return matching


@with_auth_retry
async def get_transaction_detail(transaction_id: int) -> dict:
    """Get full raw details of a specific transaction."""
    session = await get_client()

    for page in range(1, 100):
        params: dict = {
            "page": page,
            "perPage": 100,
            "column": "id",
            "direction": "desc",
        }

        response = await session.get("/transactions", params=params)
        data = response.json()
        txns = data.get("data", [])

        if not txns:
            break

        for txn in txns:
            if txn["id"] == transaction_id:
                txn_date = None
                if txn.get("transactionDate"):
                    try:
                        txn_date = (
                            datetime.fromisoformat(txn["transactionDate"].replace("Z", "+00:00"))
                            .date()
                            .isoformat()
                        )
                    except (ValueError, TypeError):
                        txn_date = txn.get("transactionDate", "")[:10]

                original_amount_cents = txn.get("originalAmount", 0)
                amount_cents = txn.get("amount", 0)

                return {
                    "id": txn["id"],
                    "date": txn_date,
                    "description": txn.get("description", ""),
                    "memo": txn.get("memo"),
                    "amount": float(cents_to_decimal(amount_cents)),
                    "original_amount": float(cents_to_decimal(original_amount_cents)),
                    "amount_cents": amount_cents,
                    "original_amount_cents": original_amount_cents,
                    "is_credit": original_amount_cents < 0,
                    "is_debit": original_amount_cents > 0,
                    "sign_interpretation": (
                        "CREDIT (money IN)"
                        if original_amount_cents < 0
                        else "DEBIT (money OUT)"
                        if original_amount_cents > 0
                        else "ZERO"
                    ),
                    "is_pending": txn.get("pending", False),
                    "is_approved": txn.get("approved", True),
                    "is_journal_entry": txn.get("journalEntry", False),
                    "bank_account_id": txn.get("bankAccountId"),
                    "category_id": txn.get("categoryId"),
                    "reconciliation": txn.get("bankReconciliationTransaction"),
                    "has_splits": bool(txn.get("children")),
                    "split_count": len(txn.get("children", [])),
                }

    return {"error": f"Transaction {transaction_id} not found"}


@with_auth_retry
async def find_potential_sign_errors(
    account_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """Find transactions where the sign might be wrong."""
    session = await get_client()

    credit_keywords = [
        "deposit",
        "credit",
        "payment received",
        "incoming",
        "refund",
        "reimbursement",
        "interest earned",
        "dividend",
    ]
    debit_keywords = [
        "payment to",
        "withdrawal",
        "transfer out",
        "fee",
        "expense",
        "bill pay",
        "check paid",
    ]

    filters: dict = {}
    if account_id is not None:
        filters["account"] = account_id
    if start_date:
        filters["startDate"] = start_date
    if end_date:
        filters["endDate"] = end_date

    suspicious = []

    for page in range(1, 100):
        params: dict = {
            "page": page,
            "perPage": 100,
            "column": "transactionDate",
            "direction": "desc",
        }
        if filters:
            params["filters"] = json.dumps(filters)

        response = await session.get("/transactions", params=params)
        data = response.json()
        txns = data.get("data", [])

        if not txns:
            break

        for txn in txns:
            desc = (txn.get("description", "") or "").lower()
            memo = (txn.get("memo", "") or "").lower()
            combined = f"{desc} {memo}"

            original_amount = txn.get("originalAmount", 0)
            is_currently_debit = original_amount > 0
            is_currently_credit = original_amount < 0

            issue = None

            if is_currently_debit:
                for keyword in credit_keywords:
                    if keyword in combined:
                        issue = f"Recorded as DEBIT but description contains '{keyword}'"
                        break

            if is_currently_credit:
                for keyword in debit_keywords:
                    if keyword in combined:
                        issue = f"Recorded as CREDIT but description contains '{keyword}'"
                        break

            if issue:
                txn_date = txn.get("transactionDate", "")[:10]
                suspicious.append(
                    {
                        "id": txn["id"],
                        "date": txn_date,
                        "description": txn.get("description", ""),
                        "memo": txn.get("memo"),
                        "amount": float(cents_to_decimal(txn.get("amount"))),
                        "original_amount": float(cents_to_decimal(original_amount)),
                        "current_sign": "DEBIT (out)" if is_currently_debit else "CREDIT (in)",
                        "issue": issue,
                    }
                )

    return suspicious


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


def _is_dues_deposit(txn: dict) -> bool:
    if (txn.get("originalAmount") or 0) >= 0:
        return False
    if txn.get("categoryId") == DUES_CATEGORY_ID:
        return True
    if txn.get("categoryId") is None:
        desc = (txn.get("description") or "").upper()
        return any(k in desc for k in DEPOSIT_KEYWORDS)
    return False


async def _fetch_all_pages(session, path: str, base_params: dict) -> list[dict]:
    """Fetch all pages from a paginated PayHOA endpoint; supports both pagination shapes."""
    results: list[dict] = []
    page = 1
    while True:
        params = {**base_params, "page": page}
        response = await session.get(path, params=params)
        data = response.json()
        page_items = data.get("data", []) if isinstance(data, dict) else data
        if not page_items:
            break
        results.extend(page_items)
        meta = (data.get("meta") or {}) if isinstance(data, dict) else {}
        last_page = int(meta.get("lastPage") or data.get("last_page") or 1)
        if page >= last_page:
            break
        page += 1
    return results


@with_auth_retry
async def find_unmatched_deposits(
    start_date: str | None = None,
    end_date: str | None = None,
    date_tolerance_days: int = 10,
) -> list[dict]:
    """Find bank deposits without a matching payment-group.

    These are likely payments that hit the HOA's bank account but were never
    linked to a specific unit in PayHOA, so the unit's ledger was never
    credited. Most commonly: check deposits that require manual entry in the
    PayHOA UI to match.

    Matching rule: a payment-group matches a bank deposit when the PG's `net`
    (cents) equals the deposit amount and their dates are within
    `date_tolerance_days`. Each PG can satisfy at most one deposit.
    """
    session = await get_client()

    # PayHOA's startDate/endDate filters require BOTH to be set; a single filter
    # returns an empty list. Fetch everything and filter client-side for safety.
    txn_params = {
        "perPage": 100,
        "column": "transactionDate",
        "direction": "asc",
    }
    all_txns = await _fetch_all_pages(session, "/transactions", txn_params)

    deposits: list[dict] = []
    for t in all_txns:
        if not _is_dues_deposit(t):
            continue
        d = _parse_iso_date(t.get("transactionDate"))
        if d is None:
            continue
        if start_date and d < date.fromisoformat(start_date):
            continue
        if end_date and d > date.fromisoformat(end_date):
            continue
        deposits.append(
            {
                "id": t["id"],
                "date": d.isoformat(),
                "amount_cents": abs(int(t.get("originalAmount") or 0)),
                "amount": float(cents_to_decimal(abs(int(t.get("originalAmount") or 0)))),
                "description": t.get("description", ""),
                "category_id": t.get("categoryId"),
            }
        )

    pg_params = {
        "perPage": 100,
        "column": "createdAt",
        "direction": "asc",
    }
    all_pgs = await _fetch_all_pages(session, "/payment-groups", pg_params)

    pgs = []
    for pg in all_pgs:
        d = _parse_iso_date(pg.get("createdAt"))
        if d is None:
            continue
        pgs.append(
            {
                "id": pg["id"],
                "date": d,
                "net_cents": int(pg.get("net") or 0),
                "gross_cents": int(pg.get("gross") or 0),
                "payor_id": pg.get("payorId"),
            }
        )

    matched_pg_ids: set[int] = set()
    unmatched: list[dict] = []

    for dep in deposits:
        dep_date = date.fromisoformat(dep["date"])
        match = None
        for pg in pgs:
            if pg["id"] in matched_pg_ids:
                continue
            if pg["net_cents"] != dep["amount_cents"]:
                continue
            if abs((pg["date"] - dep_date).days) > date_tolerance_days:
                continue
            match = pg
            break
        if match is None:
            dep.pop("amount_cents", None)
            unmatched.append(dep)
        else:
            matched_pg_ids.add(match["id"])

    return unmatched


@with_auth_retry
async def compare_transaction_totals(
    account_id: int,
    start_date: str,
    end_date: str,
) -> dict:
    """Calculate transaction totals for a date range."""
    session = await get_client()

    filters = {
        "account": account_id,
        "startDate": start_date,
        "endDate": end_date,
    }

    total_credits = Decimal("0.00")
    total_debits = Decimal("0.00")
    credit_count = 0
    debit_count = 0
    transaction_count = 0

    for page in range(1, 100):
        params: dict = {
            "page": page,
            "perPage": 100,
            "column": "transactionDate",
            "direction": "asc",
            "filters": json.dumps(filters),
        }

        response = await session.get("/transactions", params=params)
        data = response.json()
        txns = data.get("data", [])

        if not txns:
            break

        for txn in txns:
            original_amount = txn.get("originalAmount", 0)
            amount = cents_to_decimal(original_amount)
            transaction_count += 1

            if original_amount < 0:
                total_credits += abs(amount)
                credit_count += 1
            elif original_amount > 0:
                total_debits += abs(amount)
                debit_count += 1

    net_change = total_credits - total_debits

    return {
        "account_id": account_id,
        "start_date": start_date,
        "end_date": end_date,
        "total_credits": float(total_credits),
        "credit_count": credit_count,
        "total_debits": float(total_debits),
        "debit_count": debit_count,
        "net_change": float(net_change),
        "transaction_count": transaction_count,
        "note": "Credits are money IN (deposits), debits are money OUT (payments)",
    }
