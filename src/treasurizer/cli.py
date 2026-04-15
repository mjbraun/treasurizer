# ABOUTME: CLI entry point for Treasurizer
# ABOUTME: Typer-based commands for querying PayHOA financial data

import asyncio
import json
import sys
from typing import Annotated, Any

import typer

from treasurizer.tools.accounts import (
    get_balance_discrepancy,
    get_bank_accounts,
    get_reconciliation_history,
)
from treasurizer.tools.reconciliation import (
    compare_transaction_totals,
    find_potential_sign_errors,
    find_transactions_by_amount,
    find_unmatched_deposits,
    get_transaction_detail,
)
from treasurizer.tools.reports import (
    get_account_balances_summary,
    get_balance_sheet,
    get_general_ledger,
    get_reconciliation_report,
)
from treasurizer.tools.units import audit_unit, get_unit_payments, get_units
from treasurizer.tools.transactions import (
    get_transactions,
    get_unreconciled_transactions,
    get_unreviewed_transactions,
    search_transactions,
    update_transaction,
)

app = typer.Typer(help="PayHOA financial data CLI")
accounts_app = typer.Typer(help="Bank account commands")
transactions_app = typer.Typer(help="Transaction commands")
reports_app = typer.Typer(help="Financial report commands")
reconciliation_app = typer.Typer(help="Reconciliation helper commands")
units_app = typer.Typer(help="Unit and owner commands")

app.add_typer(accounts_app, name="accounts")
app.add_typer(transactions_app, name="transactions")
app.add_typer(reports_app, name="reports")
app.add_typer(reconciliation_app, name="reconciliation")
app.add_typer(units_app, name="units")


def _output(data: Any) -> None:
    print(json.dumps(data, indent=2, default=str))


def _error(msg: str, exc_type: str = "Error") -> None:
    print(json.dumps({"error": msg, "type": exc_type}), file=sys.stderr)
    raise typer.Exit(1)


def _run(coro: Any) -> Any:
    try:
        return asyncio.run(coro)
    except Exception as exc:
        _error(str(exc), type(exc).__name__)


# ---------------------------------------------------------------------------
# accounts
# ---------------------------------------------------------------------------


@accounts_app.command("list")
def accounts_list() -> None:
    """List all bank accounts with Plaid and ledger balances."""
    result = _run(get_bank_accounts())
    _output([acc.model_dump() for acc in result])


@accounts_app.command("balance")
def accounts_balance(
    account_id: Annotated[int | None, typer.Option("--account", help="Account ID")] = None,
) -> None:
    """Show balance discrepancies between bank and ledger."""
    result = _run(get_balance_discrepancy(account_id=account_id))
    _output(result)


@accounts_app.command("reconciliation-history")
def accounts_reconciliation_history(
    account_id: Annotated[int, typer.Argument(help="Bank account ID")],
) -> None:
    """List past reconciliations for an account."""
    result = _run(get_reconciliation_history(account_id=account_id))
    _output([r.model_dump() for r in result])


# ---------------------------------------------------------------------------
# transactions
# ---------------------------------------------------------------------------


@transactions_app.command("list")
def transactions_list(
    account_id: Annotated[int | None, typer.Option("--account", help="Account ID")] = None,
    start_date: Annotated[
        str | None, typer.Option("--from", help="Start date (YYYY-MM-DD)")
    ] = None,
    end_date: Annotated[str | None, typer.Option("--to", help="End date (YYYY-MM-DD)")] = None,
    page: Annotated[int, typer.Option(help="Page number")] = 1,
    per_page: Annotated[int, typer.Option("--per-page", help="Results per page (max 100)")] = 50,
) -> None:
    """List transactions with optional filters."""
    result = _run(
        get_transactions(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            page=page,
            per_page=per_page,
        )
    )
    _output(result)


@transactions_app.command("unreviewed")
def transactions_unreviewed(
    account_id: Annotated[int | None, typer.Option("--account", help="Account ID")] = None,
    limit: Annotated[int, typer.Option(help="Maximum results")] = 50,
) -> None:
    """List transactions not yet reviewed."""
    result = _run(get_unreviewed_transactions(account_id=account_id, limit=limit))
    _output(result)


@transactions_app.command("unreconciled")
def transactions_unreconciled(
    account_id: Annotated[int, typer.Argument(help="Bank account ID")],
    start_date: Annotated[
        str | None, typer.Option("--from", help="Start date (YYYY-MM-DD)")
    ] = None,
    end_date: Annotated[str | None, typer.Option("--to", help="End date (YYYY-MM-DD)")] = None,
) -> None:
    """List transactions not yet reconciled."""
    result = _run(
        get_unreconciled_transactions(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
        )
    )
    _output(result)


@transactions_app.command("search")
def transactions_search(
    query: Annotated[str, typer.Argument(help="Search string")],
    account_id: Annotated[int | None, typer.Option("--account", help="Account ID")] = None,
    start_date: Annotated[
        str | None, typer.Option("--from", help="Start date (YYYY-MM-DD)")
    ] = None,
    end_date: Annotated[str | None, typer.Option("--to", help="End date (YYYY-MM-DD)")] = None,
    limit: Annotated[int, typer.Option(help="Maximum results")] = 50,
) -> None:
    """Search transactions by description."""
    result = _run(
        search_transactions(
            query=query,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
    )
    _output(result)


@transactions_app.command("update")
def transactions_update(
    transaction_id: Annotated[int, typer.Argument(help="Transaction ID")],
    category_id: Annotated[int | None, typer.Option("--category", help="Category ID")] = None,
    memo: Annotated[str | None, typer.Option("--memo", help="Memo text")] = None,
    approve: Annotated[
        bool | None, typer.Option("--approve/--no-approve", help="Set approval status")
    ] = None,
) -> None:
    """Update a transaction's category, memo, and/or approval status."""
    result = _run(
        update_transaction(
            transaction_id=transaction_id,
            category_id=category_id,
            memo=memo,
            approved=approve,
        )
    )
    _output(result)


@transactions_app.command("detail")
def transactions_detail(
    transaction_id: Annotated[int, typer.Argument(help="Transaction ID")],
) -> None:
    """Get full details of a specific transaction."""
    result = _run(get_transaction_detail(transaction_id=transaction_id))
    _output(result)


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------


@reports_app.command("balance-sheet")
def reports_balance_sheet(
    as_of_date: Annotated[
        str | None, typer.Option("--date", help="As-of date (YYYY-MM-DD)")
    ] = None,
) -> None:
    """Get the balance sheet."""
    result = _run(get_balance_sheet(as_of_date=as_of_date))
    _output(result)


@reports_app.command("general-ledger")
def reports_general_ledger(
    start_date: Annotated[str, typer.Argument(help="Start date (YYYY-MM-DD)")],
    end_date: Annotated[str, typer.Argument(help="End date (YYYY-MM-DD)")],
    page: Annotated[int, typer.Option(help="Page number (0-indexed)")] = 0,
    page_size: Annotated[int, typer.Option("--page-size", help="Entries per page")] = 50,
) -> None:
    """Get general ledger entries for a date range."""
    result = _run(
        get_general_ledger(
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )
    )
    _output(result)


@reports_app.command("reconciliation")
def reports_reconciliation(
    reconciliation_id: Annotated[int, typer.Argument(help="Reconciliation ID")],
) -> None:
    """Get details of a specific reconciliation."""
    result = _run(get_reconciliation_report(reconciliation_id=reconciliation_id))
    _output(result)


@reports_app.command("account-balances")
def reports_account_balances() -> None:
    """Summarize all account balances with discrepancy detection."""
    result = _run(get_account_balances_summary())
    _output(result)


# ---------------------------------------------------------------------------
# reconciliation
# ---------------------------------------------------------------------------


@reconciliation_app.command("find-by-amount")
def reconciliation_find_by_amount(
    amount: Annotated[float, typer.Argument(help="Target amount in dollars")],
    tolerance: Annotated[float, typer.Option(help="Match tolerance in dollars")] = 0.01,
    account_id: Annotated[int | None, typer.Option("--account", help="Account ID")] = None,
    start_date: Annotated[
        str | None, typer.Option("--from", help="Start date (YYYY-MM-DD)")
    ] = None,
    end_date: Annotated[str | None, typer.Option("--to", help="End date (YYYY-MM-DD)")] = None,
    limit: Annotated[int, typer.Option(help="Maximum results")] = 50,
) -> None:
    """Find transactions matching a specific dollar amount."""
    result = _run(
        find_transactions_by_amount(
            target_amount=amount,
            tolerance=tolerance,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
    )
    _output(result)


@reconciliation_app.command("sign-errors")
def reconciliation_sign_errors(
    account_id: Annotated[int | None, typer.Option("--account", help="Account ID")] = None,
    start_date: Annotated[
        str | None, typer.Option("--from", help="Start date (YYYY-MM-DD)")
    ] = None,
    end_date: Annotated[str | None, typer.Option("--to", help="End date (YYYY-MM-DD)")] = None,
) -> None:
    """Find transactions with potentially wrong credit/debit sign."""
    result = _run(
        find_potential_sign_errors(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
        )
    )
    _output(result)


@reconciliation_app.command("unmatched-deposits")
def reconciliation_unmatched_deposits(
    start_date: Annotated[
        str | None, typer.Option("--from", help="Start date (YYYY-MM-DD)")
    ] = None,
    end_date: Annotated[str | None, typer.Option("--to", help="End date (YYYY-MM-DD)")] = None,
    date_tolerance_days: Annotated[
        int,
        typer.Option(
            "--tolerance-days", help="Date tolerance (days) for matching PG to bank deposit"
        ),
    ] = 10,
) -> None:
    """Find bank deposits that aren't linked to any unit's payment record."""
    result = _run(
        find_unmatched_deposits(
            start_date=start_date,
            end_date=end_date,
            date_tolerance_days=date_tolerance_days,
        )
    )
    _output(result)


@reconciliation_app.command("compare-totals")
def reconciliation_compare_totals(
    account_id: Annotated[int, typer.Argument(help="Bank account ID")],
    start_date: Annotated[str, typer.Argument(help="Start date (YYYY-MM-DD)")],
    end_date: Annotated[str, typer.Argument(help="End date (YYYY-MM-DD)")],
) -> None:
    """Calculate credit/debit totals for a date range."""
    result = _run(
        compare_transaction_totals(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
        )
    )
    _output(result)


# ---------------------------------------------------------------------------
# units
# ---------------------------------------------------------------------------


@units_app.command("list")
def units_list() -> None:
    """List all units with current balance and monthly dues."""
    result = _run(get_units())
    _output([u.model_dump() for u in result])


@units_app.command("payments")
def units_payments(
    unit_id: Annotated[int, typer.Argument(help="Unit ID")],
    limit: Annotated[int, typer.Option(help="Maximum results")] = 50,
) -> None:
    """Show payment history for a unit's owner."""
    result = _run(get_unit_payments(unit_id=unit_id, limit=limit))
    _output(result)


@units_app.command("audit")
def units_audit(
    unit_id: Annotated[int, typer.Argument(help="Unit ID")],
    start_date: Annotated[
        str | None, typer.Option("--from", help="Start date (YYYY-MM-DD)")
    ] = None,
    date_tolerance_days: Annotated[
        int,
        typer.Option(
            "--tolerance-days", help="Date tolerance (days) for matching PG to bank deposit"
        ),
    ] = 10,
) -> None:
    """Reconcile a unit's payment-groups against bank deposits."""
    result = _run(
        audit_unit(
            unit_id=unit_id,
            start_date=start_date,
            date_tolerance_days=date_tolerance_days,
        )
    )
    _output(result)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
