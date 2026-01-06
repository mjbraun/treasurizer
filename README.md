# Treasurizer

An MCP server that gives AI assistants access to PayHOA for condo association accounting and financial management.

## What It Does

Treasurizer enables AI assistants to help with HOA treasurer duties by providing access to PayHOA's financial data:

- **Account Management**: Query bank accounts, view balances, compare Plaid (bank) vs ledger balances
- **Transaction Analysis**: Search and filter transactions, find unreviewed or unreconciled entries
- **Financial Reports**: Generate balance sheets, view general ledger entries
- **Reconciliation Tools**: Find transactions by amount, detect sign errors, calculate period totals for bank statement comparison
- **Discrepancy Detection**: Identify and investigate differences between bank and ledger balances

## What is MCP?

**Model Context Protocol (MCP)** is an open standard that lets AI assistants connect to external data sources and tools. Think of it as a USB port for AI—it provides a standardized way for AI models to:

- Read data from external systems (databases, APIs, files)
- Execute actions (create records, trigger workflows)
- Access real-time information beyond their training data

### How MCP Integrates with AI Models

```
┌─────────────────┐     MCP Protocol      ┌─────────────────┐
│   AI Assistant  │◄────────────────────►│   MCP Server    │
│  (Claude, etc.) │   JSON-RPC over       │  (Treasurizer)  │
│                 │   stdio/SSE           │                 │
└─────────────────┘                       └────────┬────────┘
                                                   │
                                                   ▼
                                          ┌─────────────────┐
                                          │   PayHOA API    │
                                          └─────────────────┘
```

The AI assistant doesn't call PayHOA directly. Instead:
1. The assistant recognizes it needs financial data
2. It calls a tool provided by the MCP server (e.g., `get_transactions`)
3. The MCP server authenticates with PayHOA and fetches the data
4. Results are returned to the assistant, which can then reason about them

This keeps credentials secure (the AI never sees passwords) and provides a controlled interface to external systems.

## Installation

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- PayHOA account credentials

### Install from Source

```bash
git clone https://github.com/yourusername/treasurizer.git
cd treasurizer
uv sync
```

### Configure Credentials

**Option 1: Environment Variables**
```bash
export PAYHOA_EMAIL="your-email@example.com"
export PAYHOA_PASSWORD="your-password"
```

**Option 2: 1Password CLI** (recommended for security)
```bash
# Treasurizer will automatically retrieve credentials from:
# op://Private/app.payhoa.com/username
# op://Private/app.payhoa.com/password
```

## Usage with AI Assistants

### Claude Code / Codex CLI

Add Treasurizer to your Claude Code configuration:

```bash
# Add to your project's .mcp.json or ~/.claude/mcp.json
```

```json
{
  "mcpServers": {
    "treasurizer": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/treasurizer", "treasurizer"]
    }
  }
}
```

Then in Claude Code, you can ask questions like:
- "What's the current bank balance?"
- "Show me unreconciled transactions from last month"
- "Is there a discrepancy between the bank and ledger balance?"
- "Find all transactions around $150 from October"

### Claude Desktop / ChatGPT Desktop

For Claude Desktop, add to your `claude_desktop_config.json`:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "treasurizer": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/treasurizer", "treasurizer"]
    }
  }
}
```

For ChatGPT Desktop or other assistants with MCP support, the configuration pattern is similar—consult your assistant's documentation for the exact config file location.

### Other AI Agents

Any AI agent that supports the MCP protocol can use Treasurizer. The general pattern is:

1. Configure the agent to spawn Treasurizer as a subprocess
2. Point to the `uv run treasurizer` command (or `python -m treasurizer.server`)
3. The agent communicates via JSON-RPC over stdio

For agents using Server-Sent Events (SSE) transport instead of stdio, you'll need to run Treasurizer with an HTTP adapter (not currently included).

## Available Tools

| Tool | Description |
|------|-------------|
| `get_bank_accounts` | List all connected bank accounts with balances |
| `get_balance_discrepancy` | Compare bank vs ledger balance to find discrepancies |
| `get_transactions` | Query transactions with flexible filters |
| `get_unreviewed_transactions` | Find transactions needing review |
| `get_unreconciled_transactions` | Find transactions not yet reconciled |
| `search_transactions` | Search by description text |
| `get_balance_sheet` | Generate balance sheet report |
| `get_general_ledger` | View ledger entries for a date range |
| `get_reconciliation_history` | View past bank reconciliations |
| `find_transactions_by_amount` | Find transactions matching a specific amount |
| `get_transaction_detail` | Get full details including raw API fields |
| `find_potential_sign_errors` | Detect transactions with suspicious debit/credit signs |
| `compare_transaction_totals` | Calculate period totals for reconciliation |

## Development

```bash
# Install dev dependencies
uv sync --dev

# Run tests
uv run pytest

# Type checking
uv run mypy src

# Linting
uv run ruff check src
```

## How It Works

Treasurizer authenticates with PayHOA using their web API:

1. Obtains a CSRF token from `/sanctum/csrf-cookie`
2. Posts credentials to `/login` to get a JWT token
3. Uses the JWT for subsequent API calls to `/organizations/{org_id}/...`

Session tokens are cached locally at `~/.treasurizer/session.json` (with 0600 permissions) to avoid repeated logins.

## License

MIT
