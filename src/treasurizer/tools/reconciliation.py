# ABOUTME: Reconciliation helper tools for PayHOA
# ABOUTME: Tools to help investigate and resolve balance discrepancies

import json
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from treasurizer.client import with_auth_retry
from treasurizer.types import cents_to_decimal

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastmcp import FastMCP

    from treasurizer.auth import PayHOASession


def register_reconciliation_tools(mcp: "FastMCP", get_client: "Callable") -> None:
    """Register reconciliation helper tools with the MCP server."""

    @mcp.tool
    @with_auth_retry
    async def find_transactions_by_amount(
        target_amount: float,
        tolerance: float = 0.01,
        account_id: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Find transactions near a specific dollar amount.

        Useful for tracking down small discrepancies by finding transactions
        that match a specific amount (like a missing $2.00 deposit).

        Args:
            target_amount: Amount to search for (e.g., 2.00 for $2)
            tolerance: How close amounts need to be (default $0.01)
            account_id: Filter by bank account ID
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            limit: Maximum results to return

        Returns:
            List of transactions matching the amount criteria
        """
        session: PayHOASession = await get_client()

        # Build filters
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

        # Paginate through all transactions
        for page in range(1, 100):  # Safety limit
            params = {
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
                # Check both amount and originalAmount
                amt = abs(cents_to_decimal(txn.get("amount")))
                orig_amt = abs(cents_to_decimal(txn.get("originalAmount")))

                if abs(amt - target) <= tol or abs(orig_amt - target) <= tol:
                    txn_date = txn.get("transactionDate", "")[:10]
                    matching.append({
                        "id": txn["id"],
                        "date": txn_date,
                        "amount": float(cents_to_decimal(txn.get("amount"))),
                        "original_amount": float(cents_to_decimal(txn.get("originalAmount"))),
                        "description": txn.get("description", ""),
                        "memo": txn.get("memo"),
                        "is_credit": txn.get("originalAmount", 0) < 0,
                        "is_debit": txn.get("originalAmount", 0) > 0,
                    })

                if len(matching) >= limit:
                    break

            if len(matching) >= limit:
                break

        return matching

    @mcp.tool
    @with_auth_retry
    async def get_transaction_detail(transaction_id: int) -> dict:
        """
        Get full raw details of a specific transaction.

        Returns all fields including originalAmount, which indicates whether
        the transaction is a credit (negative) or debit (positive).

        Args:
            transaction_id: The transaction ID to retrieve

        Returns:
            Full transaction details including raw API fields
        """
        session: PayHOASession = await get_client()

        # Fetch all transactions and find the one we want
        # PayHOA API doesn't seem to have a direct single-transaction endpoint
        for page in range(1, 100):
            params = {
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
                    # Parse and return detailed info
                    txn_date = None
                    if txn.get("transactionDate"):
                        try:
                            txn_date = datetime.fromisoformat(
                                txn["transactionDate"].replace("Z", "+00:00")
                            ).date().isoformat()
                        except (ValueError, TypeError):
                            txn_date = txn.get("transactionDate", "")[:10]

                    original_amount_cents = txn.get("originalAmount", 0)
                    amount_cents = txn.get("amount", 0)

                    return {
                        "id": txn["id"],
                        "date": txn_date,
                        "description": txn.get("description", ""),
                        "memo": txn.get("memo"),
                        # Amounts in dollars
                        "amount": float(cents_to_decimal(amount_cents)),
                        "original_amount": float(cents_to_decimal(original_amount_cents)),
                        # Raw cents values for debugging
                        "amount_cents": amount_cents,
                        "original_amount_cents": original_amount_cents,
                        # Sign interpretation
                        "is_credit": original_amount_cents < 0,
                        "is_debit": original_amount_cents > 0,
                        "sign_interpretation": (
                            "CREDIT (money IN)" if original_amount_cents < 0
                            else "DEBIT (money OUT)" if original_amount_cents > 0
                            else "ZERO"
                        ),
                        # Status fields
                        "is_pending": txn.get("pending", False),
                        "is_approved": txn.get("approved", True),
                        "is_journal_entry": txn.get("journalEntry", False),
                        "bank_account_id": txn.get("bankAccountId"),
                        "category_id": txn.get("categoryId"),
                        # Reconciliation info
                        "reconciliation": txn.get("bankReconciliationTransaction"),
                        # Children (splits)
                        "has_splits": bool(txn.get("children")),
                        "split_count": len(txn.get("children", [])),
                    }

        return {"error": f"Transaction {transaction_id} not found"}

    @mcp.tool
    @with_auth_retry
    async def find_potential_sign_errors(
        account_id: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict]:
        """
        Find transactions where the sign might be wrong.

        Looks for transactions where originalAmount is positive (debit/out)
        but the description suggests it should be a credit (deposit, payment
        received, etc.) or vice versa.

        This helps identify data entry errors that can cause balance discrepancies.

        Args:
            account_id: Filter by bank account ID
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            List of potentially miscategorized transactions
        """
        session: PayHOASession = await get_client()

        # Keywords that suggest credits (money IN)
        credit_keywords = [
            "deposit", "credit", "payment received", "incoming",
            "refund", "reimbursement", "interest earned", "dividend"
        ]

        # Keywords that suggest debits (money OUT)
        debit_keywords = [
            "payment to", "withdrawal", "transfer out", "fee",
            "expense", "bill pay", "check paid"
        ]

        # Build filters
        filters: dict = {}
        if account_id is not None:
            filters["account"] = account_id
        if start_date:
            filters["startDate"] = start_date
        if end_date:
            filters["endDate"] = end_date

        suspicious = []

        for page in range(1, 100):
            params = {
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

                # Check if debit but has credit keywords
                if is_currently_debit:
                    for keyword in credit_keywords:
                        if keyword in combined:
                            issue = f"Recorded as DEBIT but description contains '{keyword}'"
                            break

                # Check if credit but has debit keywords
                if is_currently_credit:
                    for keyword in debit_keywords:
                        if keyword in combined:
                            issue = f"Recorded as CREDIT but description contains '{keyword}'"
                            break

                if issue:
                    txn_date = txn.get("transactionDate", "")[:10]
                    suspicious.append({
                        "id": txn["id"],
                        "date": txn_date,
                        "description": txn.get("description", ""),
                        "memo": txn.get("memo"),
                        "amount": float(cents_to_decimal(txn.get("amount"))),
                        "original_amount": float(cents_to_decimal(original_amount)),
                        "current_sign": "DEBIT (out)" if is_currently_debit else "CREDIT (in)",
                        "issue": issue,
                    })

        return suspicious

    @mcp.tool
    @with_auth_retry
    async def compare_transaction_totals(
        account_id: int,
        start_date: str,
        end_date: str,
    ) -> dict:
        """
        Calculate transaction totals for a date range to help reconciliation.

        Sums all credits (deposits) and debits (payments) to compare against
        bank statement totals.

        Args:
            account_id: Bank account ID
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            Summary of credits, debits, and net change
        """
        session: PayHOASession = await get_client()

        filters = {
            "account": account_id,
            "startDate": start_date,
            "endDate": end_date,
        }

        total_credits = Decimal("0.00")
        total_debits = Decimal("0.00")
        credit_count = 0
        debit_count = 0
        transactions = []

        for page in range(1, 100):
            params = {
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

                if original_amount < 0:
                    # Credit (money in)
                    total_credits += abs(amount)
                    credit_count += 1
                elif original_amount > 0:
                    # Debit (money out)
                    total_debits += abs(amount)
                    debit_count += 1

                transactions.append({
                    "date": txn.get("transactionDate", "")[:10],
                    "amount": float(amount),
                    "type": "credit" if original_amount < 0 else "debit",
                })

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
            "transaction_count": len(transactions),
            "note": "Credits are money IN (deposits), debits are money OUT (payments)",
        }
