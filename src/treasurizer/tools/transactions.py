# ABOUTME: Transaction tools for PayHOA
# ABOUTME: Query, filter, and analyze transactions from bank accounts

import json
from datetime import date, datetime
from typing import TYPE_CHECKING

from treasurizer.client import with_auth_retry
from treasurizer.types import Transaction, cents_to_decimal

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastmcp import FastMCP

    from treasurizer.auth import PayHOASession


def register_transaction_tools(mcp: "FastMCP", get_client: "Callable") -> None:
    """Register transaction tools with the MCP server."""

    @mcp.tool
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
        """
        Query transactions with flexible filtering.

        Args:
            account_id: Filter by bank account ID
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            reviewed: Filter by review status (True/False/None for all)
            reconciled: Filter by reconciliation status
            page: Page number (1-indexed)
            per_page: Results per page (max 100)

        Returns:
            Dict with transactions list and pagination info
        """
        session: PayHOASession = await get_client()

        # Build filters object
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

        # Build query params
        params = {
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
            # Parse transaction date
            txn_date = None
            if txn.get("transactionDate"):
                try:
                    txn_date = datetime.fromisoformat(
                        txn["transactionDate"].replace("Z", "+00:00")
                    ).date()
                except (ValueError, TypeError):
                    pass

            # Check reconciliation status
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
                        txn.get("bankReconciliationTransaction", {}).get(
                            "bankReconciliationId"
                        )
                        if txn.get("bankReconciliationTransaction")
                        else None
                    ),
                )
            )

        # Extract pagination info
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

    @mcp.tool
    @with_auth_retry
    async def get_unreviewed_transactions(
        account_id: int | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Get transactions that haven't been reviewed yet.

        These are transactions imported from Plaid that need categorization
        or approval.

        Args:
            account_id: Filter by bank account ID (default: all accounts)
            limit: Maximum results to return

        Returns:
            List of unreviewed transactions
        """
        result = await get_transactions(
            account_id=account_id,
            reviewed=False,
            per_page=limit,
        )
        return result["transactions"]

    @mcp.tool
    @with_auth_retry
    async def get_unreconciled_transactions(
        account_id: int,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict]:
        """
        Get transactions not yet included in a bank reconciliation.

        Use this to identify transactions that should be reconciled
        but haven't been cleared yet.

        Args:
            account_id: Bank account ID
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            List of unreconciled transactions
        """
        result = await get_transactions(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            reconciled=False,
            per_page=100,
        )
        return result["transactions"]

    @mcp.tool
    @with_auth_retry
    async def search_transactions(
        query: str,
        account_id: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Search transactions by description.

        Args:
            query: Search string to match against description
            account_id: Filter by bank account ID
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            limit: Maximum results to return

        Returns:
            List of matching transactions
        """
        # Get transactions and filter locally by query
        # PayHOA may not support server-side text search
        result = await get_transactions(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            per_page=min(limit * 2, 100),  # Fetch extra to account for filtering
        )

        query_lower = query.lower()
        matching = [
            txn
            for txn in result["transactions"]
            if query_lower in txn.get("description", "").lower()
            or query_lower in (txn.get("memo") or "").lower()
        ]

        return matching[:limit]
