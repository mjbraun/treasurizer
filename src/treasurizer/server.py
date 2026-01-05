# ABOUTME: MCP server entry point for Treasurizer
# ABOUTME: Configures FastMCP and registers PayHOA tools

import logging

from fastmcp import FastMCP

from treasurizer.client import get_client
from treasurizer.tools.accounts import register_account_tools

logger = logging.getLogger(__name__)


def create_server() -> FastMCP:
    """
    Create and configure the Treasurizer MCP server.

    Returns:
        Configured FastMCP server instance
    """
    mcp = FastMCP(
        name="treasurizer",
        instructions="""
Treasurizer provides access to PayHOA for condo association accounting and
financial management. You can:

- Query bank accounts and their current balances
- View the general ledger and ledger balances
- Query transactions with flexible filters (date range, account, category)
- Reconcile bank balances against ledger balances
- Find discrepancies between bank and ledger entries
- View owner accounts and payment history
- Track assessments, fees, and payments

For reconciliation, compare get_bank_balance() against get_ledger_balance()
to identify discrepancies. Use get_unmatched_transactions() to find entries
that exist in one system but not the other.

Common discrepancy sources:
- Pending transactions not yet posted to ledger
- Manual adjustments not synced
- Timing differences on month-end
- Voided checks or reversed transactions
""",
    )

    # Register all tools with access to the client factory
    register_account_tools(mcp, get_client)

    return mcp


def main() -> None:
    """Run the MCP server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    server = create_server()
    server.run()


if __name__ == "__main__":
    main()
