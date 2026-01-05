# ABOUTME: Bank account tools for PayHOA
# ABOUTME: Query bank accounts, balances, and Plaid sync status

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from treasurizer.client import with_auth_retry
from treasurizer.types import BankAccount, Reconciliation, cents_to_decimal

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastmcp import FastMCP

    from treasurizer.auth import PayHOASession


def register_account_tools(mcp: "FastMCP", get_client: "Callable") -> None:
    """Register bank account tools with the MCP server."""

    @mcp.tool
    @with_auth_retry
    async def get_bank_accounts() -> list[BankAccount]:
        """
        List all bank accounts connected to PayHOA.

        Returns bank accounts with both Plaid (bank) balance and
        PayHOA ledger balance. Compare these to find discrepancies.
        """
        session: PayHOASession = await get_client()
        response = await session.get("/bank-accounts")
        data = response.json()

        accounts = []
        for acc in data:
            # Parse Plaid sync time
            last_synced = None
            if acc.get("plaidToken", {}).get("transactionsLastPulled"):
                try:
                    last_synced = datetime.fromisoformat(
                        acc["plaidToken"]["transactionsLastPulled"].replace(" ", "T")
                    )
                except (ValueError, TypeError):
                    pass

            # Get institution name from Plaid token
            institution = None
            if acc.get("plaidToken", {}).get("institution", {}).get("name"):
                institution = acc["plaidToken"]["institution"]["name"]

            # Get ledger balance from fixedAsset
            ledger_balance = cents_to_decimal(
                acc.get("fixedAsset", {}).get("balance")
                or acc.get("depositBankAccount", {}).get("internalBalance")
            )

            # Get pending funds
            pending = cents_to_decimal(acc.get("depositBankAccount", {}).get("pendingFunds"))

            accounts.append(
                BankAccount(
                    id=acc["id"],
                    name=acc.get("friendlyName", "Unknown"),
                    last4=acc.get("last4"),
                    institution=institution,
                    plaid_balance=cents_to_decimal(acc.get("plaidBalance")),
                    ledger_balance=ledger_balance,
                    pending_funds=pending,
                    unreviewed_count=acc.get("unreviewedTransactionsCount", 0),
                    last_synced=last_synced,
                )
            )

        return accounts

    @mcp.tool
    @with_auth_retry
    async def get_balance_discrepancy(account_id: int | None = None) -> dict:
        """
        Compare bank balance vs ledger balance to find discrepancies.

        Args:
            account_id: Specific account to check (default: all accounts)

        Returns:
            Summary of discrepancies with possible causes
        """
        session: PayHOASession = await get_client()
        response = await session.get("/bank-accounts")
        data = response.json()

        discrepancies = []
        for acc in data:
            if account_id and acc["id"] != account_id:
                continue

            plaid_balance = cents_to_decimal(acc.get("plaidBalance"))
            ledger_balance = cents_to_decimal(
                acc.get("fixedAsset", {}).get("balance")
                or acc.get("depositBankAccount", {}).get("internalBalance")
            )
            pending = cents_to_decimal(acc.get("depositBankAccount", {}).get("pendingFunds"))

            diff = plaid_balance - ledger_balance

            if diff != Decimal("0.00"):
                possible_causes = []

                # Check if pending funds explain the difference
                if pending > Decimal("0.00"):
                    possible_causes.append(
                        f"Pending funds in transit: ${pending:.2f}"
                    )

                # Check if difference matches pending
                if abs(diff - pending) < Decimal("0.01"):
                    possible_causes.append(
                        "Difference matches pending funds - likely timing issue"
                    )

                # Small differences might be rounding
                if abs(diff) < Decimal("1.00"):
                    possible_causes.append(
                        "Small difference may be rounding in fee calculations"
                    )

                # Unreviewed transactions
                unreviewed = acc.get("unreviewedTransactionsCount", 0)
                if unreviewed > 0:
                    possible_causes.append(
                        f"{unreviewed} unreviewed transactions may affect balance"
                    )

                if not possible_causes:
                    possible_causes.append(
                        "Unknown cause - manual investigation recommended"
                    )

                discrepancies.append({
                    "account_id": acc["id"],
                    "account_name": acc.get("friendlyName", "Unknown"),
                    "bank_balance": float(plaid_balance),
                    "ledger_balance": float(ledger_balance),
                    "difference": float(diff),
                    "pending_funds": float(pending),
                    "possible_causes": possible_causes,
                })

        return {
            "total_accounts": len(data),
            "accounts_with_discrepancy": len(discrepancies),
            "discrepancies": discrepancies,
        }

    @mcp.tool
    @with_auth_retry
    async def get_reconciliation_history(account_id: int) -> list[Reconciliation]:
        """
        Get past bank reconciliations for an account.

        Args:
            account_id: Bank account ID to get history for

        Returns:
            List of completed reconciliations
        """
        session: PayHOASession = await get_client()
        response = await session.get("/bank-accounts")
        data = response.json()

        # Find the account
        account = None
        for acc in data:
            if acc["id"] == account_id:
                account = acc
                break

        if not account:
            return []

        reconciliations = []
        for rec in account.get("reconciliations", []):
            completed_at = None
            if rec.get("completedAt"):
                try:
                    completed_at = datetime.fromisoformat(
                        rec["completedAt"].replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    pass

            # Parse dates
            start_date = None
            end_date = None
            if rec.get("startDate"):
                try:
                    start_date = datetime.fromisoformat(
                        rec["startDate"].replace("Z", "+00:00")
                    ).date()
                except (ValueError, TypeError):
                    pass
            if rec.get("endDate"):
                try:
                    end_date = datetime.fromisoformat(
                        rec["endDate"].replace("Z", "+00:00")
                    ).date()
                except (ValueError, TypeError):
                    pass

            if start_date and end_date:
                reconciliations.append(
                    Reconciliation(
                        id=rec["id"],
                        start_date=start_date,
                        end_date=end_date,
                        starting_balance=cents_to_decimal(rec.get("startingBalance")),
                        ending_balance=cents_to_decimal(rec.get("endingBalance")),
                        total_deposits=cents_to_decimal(rec.get("totalDeposits")),
                        total_payments=cents_to_decimal(rec.get("totalPayments")),
                        completed_at=completed_at,
                    )
                )

        # Sort by end date descending
        reconciliations.sort(key=lambda r: r.end_date, reverse=True)
        return reconciliations
