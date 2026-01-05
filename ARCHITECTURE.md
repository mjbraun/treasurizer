<!-- ABOUTME: Architecture design for PayHOA MCP server -->
<!-- ABOUTME: Covers API discovery, auth, and condo association accounting features -->

# PayHOA MCP Server Architecture

## Overview

An MCP server enabling AI agents to interact with PayHOA for condo association accounting and reconciliation. This server is built by reverse-engineering PayHOA's private API through traffic inspection.

**Primary use case**: Condo association financial management and reconciliation.

## Technology Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Framework | [FastMCP 2.x](https://github.com/jlowin/fastmcp) | Production-ready, handles protocol complexity |
| HTTP Client | httpx | Async HTTP with connection pooling |
| Package Manager | uv | Fast, modern, reproducible builds |
| Python | 3.11+ | Modern async features |

## API Discovery

PayHOA does not have a public API. The following endpoints were discovered via mitmproxy traffic inspection (January 2026).

### Base URL

```
https://core.payhoa.com
```

### Authentication

PayHOA uses JWT Bearer tokens with the following headers:

```http
Authorization: Bearer <jwt_token>
x-legfi-site-id: 2
```

The JWT payload contains:
```json
{
  "legfi": {
    "id": 599811,
    "memberId": 616374,
    "orgId": 18707,
    "orgName": "1357 Madison Park Condo Association",
    "admin": true,
    "timezone": "US/Eastern"
  }
}
```

Session cookies are also required:
- `XSRF-TOKEN` - CSRF protection
- `payhoa_core_session` - Session cookie

### Discovered Endpoints

#### Bank Accounts
```
GET /organizations/{orgId}/bank-accounts
```
Returns connected bank accounts with Plaid balances and reconciliation history.

Key fields:
- `plaidBalance` - Current bank balance (in cents)
- `plaidAccount.balances.current` - Plaid-reported balance
- `fixedAsset.balance` - Ledger balance for this account
- `depositBankAccount.internalBalance` - Internal balance tracking
- `depositBankAccount.pendingFunds` - Funds in transit
- `reconciliations[]` - Past reconciliation records

#### Transactions
```
GET /organizations/{orgId}/transactions?page=1&perPage=50&filters={...}
```
Query parameters:
- `page` - Page number (1-indexed)
- `perPage` - Results per page (default 50)
- `column` - Sort column (e.g., "transactionDate")
- `direction` - Sort direction ("asc" or "desc")
- `filters` - JSON object with filters:
  - `account` - Bank account ID
  - `reviewed` - Whether reviewed (true/false)

Transaction fields:
- `id` - Transaction ID
- `amount` - Amount in cents (positive = income, negative = expense)
- `description` - Transaction description
- `transactionDate` - ISO date
- `categoryId` - Category ID
- `bankAccountId` - Associated bank account
- `approved` - Whether approved
- `bankReconciliationTransaction` - Reconciliation status

#### Balance Sheet
```
GET /organizations/{orgId}/reports/balance-sheet/0?asOfDate=YYYY-MM-DD
```
Returns balance sheet with nested structure:
- Assets
  - Bank Accounts
  - Other Assets (Accounts Receivable, Funds in Transit)
- Liabilities and Equity

Amounts are in cents.

#### Reconciliation Report
```
GET /organizations/{orgId}/reports/reconciliations/0?reconciliation={reconciliationId}
```
Returns reconciliation summary and cleared transactions.

#### General Ledger
```
POST /organizations/{orgId}/reports/general-ledger/json
```
Request body:
```json
{
  "startDate": "YYYY-MM-DD",
  "endDate": "YYYY-MM-DD",
  "pageSize": 50,
  "page": 0,
  "showMemoColumn": false
}
```

#### Other Endpoints
- `GET /organizations/{orgId}?with=preferences` - Organization details
- `GET /organizations/{orgId}/units` - Condo units
- `GET /organizations/{orgId}/people-list` - Members/owners
- `GET /organizations/{orgId}/vendors` - Vendors
- `GET /organizations/{orgId}/transactions/rules` - Auto-categorization rules
- `GET /plaid-tokens` - Plaid connection status

## Data Model

### Amounts

All monetary amounts are stored as **integers in cents**:
- `2301777` = $23,017.77
- `100000` = $1,000.00

### Key IDs (Example)

| Entity | ID |
|--------|-----|
| Organization | 18707 |
| Bank Account (Chase) | 34311 |
| User/Member | 616374 |

## Reconciliation Analysis

The $2.00 discrepancy between bank and ledger appears in:

| Source | Balance |
|--------|---------|
| Plaid (bank) | $23,017.77 |
| fixedAsset.balance (ledger) | $23,015.77 |
| **Difference** | $2.00 |

Possible causes:
1. Rounding differences in fee calculations
2. Unposted journal entries
3. Timing differences in Plaid sync
4. PayHOA internal accounting bug

## Project Structure

```
treasurizer/
├── pyproject.toml          # Dependencies & project config
├── uv.lock                 # Locked dependencies
├── .python-version         # Python version (3.11)
├── README.md
├── ARCHITECTURE.md         # This file
│
├── src/
│   └── treasurizer/
│       ├── __init__.py
│       ├── server.py       # MCP server entry point
│       ├── auth.py         # Session management
│       ├── client.py       # PayHOA client wrapper
│       ├── exceptions.py   # Custom exceptions
│       ├── types.py        # Pydantic models
│       │
│       └── tools/          # MCP tool implementations
│           ├── __init__.py
│           ├── accounts.py     # Bank account tools
│           ├── transactions.py # Transaction tools
│           ├── reports.py      # Balance sheet, GL tools
│           └── reconciliation.py # Reconciliation tools
│
└── tests/
    ├── conftest.py         # Fixtures
    └── test_*.py           # Tests
```

## Tool Taxonomy

### Phase 1: Core Read Operations

| Tool | Description |
|------|-------------|
| `get_bank_accounts` | List bank accounts with Plaid balances |
| `get_bank_balance` | Get current bank balance for an account |
| `get_ledger_balance` | Get current ledger balance for an account |
| `get_transactions` | Query transactions with filters |
| `get_balance_sheet` | Get balance sheet as of date |
| `get_general_ledger` | Get GL entries for date range |

### Phase 2: Reconciliation Tools

| Tool | Description |
|------|-------------|
| `get_reconciliation_status` | Current reconciliation state |
| `get_reconciliation_history` | Past reconciliations |
| `find_balance_discrepancy` | Compare bank vs ledger |
| `get_unreconciled_transactions` | Transactions not yet reconciled |

### Phase 3: Analysis Tools

| Tool | Description |
|------|-------------|
| `get_pending_deposits` | Funds in transit |
| `get_owner_balances` | Unit owner account balances |
| `get_assessment_status` | Who has paid/unpaid |

## Security Considerations

1. **Credentials**: Stored in 1Password, retrieved via `op` CLI
2. **Session tokens**: Cached locally with file permissions 600
3. **Rate limiting**: PayHOA returns `x-ratelimit-limit: 600`
4. **No destructive operations**: Read-only access initially

## References

- [FastMCP Documentation](https://gofastmcp.com/)
- [MCP Specification](https://modelcontextprotocol.io/)
- [Monarcher](https://github.com/mjbraun/monarcher) - Similar pattern for Monarch Money
