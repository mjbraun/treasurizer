# ABOUTME: Transaction tools for PayHOA
# ABOUTME: Query, filter, and analyze transactions from bank accounts

import json
from datetime import date, datetime

from treasurizer.client import get_client, with_auth_retry
from treasurizer.types import Transaction, cents_to_decimal


@with_auth_retry
async def get_transactions(
    account_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    reviewed: bool | None = None,
    reconciled: bool | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """Query transactions with flexible filtering."""
    session = await get_client()

    filters: dict = {}
    if account_id is not None:
        filters["account"] = account_id
    if reviewed is not None:
        filters["reviewed"] = reviewed
    if start_date:
        filters["startDate"] = start_date
    if end_date:
        filters["endDate"] = end_date
    if reconciled is not None:
        filters["reconciled"] = reconciled

    params: dict = {
        "page": page,
        "perPage": min(per_page, 100),
        "column": "transactionDate",
        "direction": "desc",
    }
    if filters:
        params["filters"] = json.dumps(filters)

    response = await session.get("/transactions", params=params)
    data = response.json()

    transactions = []
    for txn in data.get("data", []):
        txn_date = None
        if txn.get("transactionDate"):
            try:
                txn_date = datetime.fromisoformat(
                    txn["transactionDate"].replace("Z", "+00:00")
                ).date()
            except (ValueError, TypeError):
                pass

        is_reconciled = txn.get("bankReconciliationTransaction") is not None

        transactions.append(
            Transaction(
                id=txn["id"],
                date=txn_date or date.today(),
                amount=cents_to_decimal(txn.get("amount")),
                description=txn.get("description", ""),
                memo=txn.get("memo"),
                category_id=txn.get("categoryId"),
                bank_account_id=txn.get("bankAccountId"),
                is_pending=txn.get("pending", False),
                is_approved=txn.get("approved", True),
                is_reconciled=is_reconciled,
                reconciliation_id=(
                    txn.get("bankReconciliationTransaction", {}).get("bankReconciliationId")
                    if txn.get("bankReconciliationTransaction")
                    else None
                ),
            )
        )

    pagination = {
        "current_page": data.get("current_page", page),
        "last_page": data.get("last_page", 1),
        "per_page": data.get("per_page", per_page),
        "total": data.get("total", len(transactions)),
    }

    return {
        "transactions": [t.model_dump() for t in transactions],
        "pagination": pagination,
    }


@with_auth_retry
async def get_unreviewed_transactions(
    account_id: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """Get transactions that haven't been reviewed yet."""
    result = await get_transactions(
        account_id=account_id,
        reviewed=False,
        per_page=limit,
    )
    return result["transactions"]


@with_auth_retry
async def get_unreconciled_transactions(
    account_id: int,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """Get transactions not yet included in a bank reconciliation."""
    result = await get_transactions(
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
        reconciled=False,
        per_page=100,
    )
    return result["transactions"]


@with_auth_retry
async def update_transaction(
    transaction_id: int,
    category_id: int | None = None,
    memo: str | None = None,
    approved: bool | None = None,
) -> dict:
    """Update a transaction's category, memo, and/or approval status."""
    session = await get_client()

    payload: dict = {}
    if category_id is not None:
        payload["categoryId"] = category_id
    if memo is not None:
        payload["memo"] = memo
    if approved is not None:
        payload["approved"] = approved

    response = await session.patch(f"/transactions/{transaction_id}", json=payload)
    if response.status_code >= 400:
        raise RuntimeError(
            f"Update failed with status {response.status_code}: {response.text[:200]}"
        )
    return {"updated": True, "transaction_id": transaction_id}


@with_auth_retry
async def search_transactions(
    query: str,
    account_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Search transactions by description."""
    result = await get_transactions(
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
        per_page=min(limit * 2, 100),
    )

    query_lower = query.lower()
    matching = [
        txn
        for txn in result["transactions"]
        if query_lower in txn.get("description", "").lower()
        or query_lower in (txn.get("memo") or "").lower()
    ]

    return matching[:limit]
