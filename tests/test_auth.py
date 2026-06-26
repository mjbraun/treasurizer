# ABOUTME: Tests for PayHOA authentication and credential retrieval
# ABOUTME: Covers 1Password account selection and env-var overrides

from unittest.mock import MagicMock, patch

from treasurizer.auth import (
    DEFAULT_OP_ACCOUNT,
    get_credentials,
    get_credentials_from_1password,
)


def _op_account_for_calls(mock_run) -> str:
    """Extract the --account value passed to every op read call (asserting consistency)."""
    accounts = set()
    for call in mock_run.call_args_list:
        cmd = call.args[0]
        assert "--account" in cmd, f"op read missing --account: {cmd}"
        accounts.add(cmd[cmd.index("--account") + 1])
    assert len(accounts) == 1, f"inconsistent accounts: {accounts}"
    return accounts.pop()


def test_credentials_read_from_personal_account_by_default(monkeypatch):
    monkeypatch.delenv("PAYHOA_OP_ACCOUNT", raising=False)
    with patch("treasurizer.auth.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="value\n")
        username, password = get_credentials_from_1password()

    assert (username, password) == ("value", "value")
    assert _op_account_for_calls(mock_run) == DEFAULT_OP_ACCOUNT == "my.1password.com"


def test_credentials_account_respects_env_override(monkeypatch):
    monkeypatch.setenv("PAYHOA_OP_ACCOUNT", "flyio")
    with patch("treasurizer.auth.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="value\n")
        get_credentials_from_1password()

    assert _op_account_for_calls(mock_run) == "flyio"


def test_get_credentials_prefers_env_vars(monkeypatch):
    monkeypatch.setenv("PAYHOA_EMAIL", "person@example.com")
    monkeypatch.setenv("PAYHOA_PASSWORD", "hunter2")
    with patch("treasurizer.auth.subprocess.run") as mock_run:
        assert get_credentials() == ("person@example.com", "hunter2")
    mock_run.assert_not_called()
