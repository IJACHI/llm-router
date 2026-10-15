"""Tests for ijachi-code and ijachi-router CLI entry points.

Covers:
- AT-01 / BR-10: Doctor diagnostics command
- AT-16: Subcommands and flags in CLI
- Sessions management CLI
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from ijachi_router.cli.code import main as code_main
from ijachi_router.cli.router import main as router_main
from ijachi_router.doctor import run_doctor_checks


def test_doctor_diagnostics_checks():
    checks = run_doctor_checks()
    assert "python" in checks
    assert checks["python"]["ok"] is True
    assert "storage" in checks
    assert checks["storage"]["ok"] is True
    assert "terminal" in checks


def test_cli_router_doctor():
    runner = CliRunner()
    result = runner.invoke(router_main, ["doctor"])
    assert result.exit_code == 0
    assert "System Diagnostics" in result.output


def test_cli_code_doctor():
    runner = CliRunner()
    result = runner.invoke(code_main, ["doctor"])
    assert result.exit_code == 0
    assert "System Diagnostics" in result.output


def test_cli_code_help():
    runner = CliRunner()
    result = runner.invoke(code_main, ["--help"])
    assert result.exit_code == 0
    assert "ijachi-code" in result.output
    assert "agent" in result.output
    assert "fix" in result.output
    assert "consensus" in result.output
    assert "index" in result.output


def test_cli_router_sessions_list():
    runner = CliRunner()
    result = runner.invoke(router_main, ["sessions", "list"])
    assert result.exit_code == 0
    assert "sessions" in result.output.lower()


def test_cli_code_print_mode_text(tmp_path):
    from unittest.mock import MagicMock, patch
    runner = CliRunner()
    with patch("ijachi_router.agent.loop.AgentSessionLoop.execute_turn") as mock_turn:
        mock_turn.return_value = MagicMock(
            text="Hello world answer",
            completed=True,
            model_used="claude-3-5-sonnet",
            provider_used="anthropic",
            cost_usd=0.001,
            latency_sec=0.2,
            input_tokens=10,
            output_tokens=5,
        )
        res = runner.invoke(code_main, ["-p", "What is 2+2?", "--cwd", str(tmp_path)])
        assert res.exit_code == 0
        assert "Hello world answer" in res.output


def test_cli_code_print_mode_json(tmp_path):
    import json
    from unittest.mock import MagicMock, patch
    runner = CliRunner()
    with patch("ijachi_router.agent.loop.AgentSessionLoop.execute_turn") as mock_turn:
        mock_turn.return_value = MagicMock(
            text="JSON test response",
            completed=True,
            model_used="gpt-4o",
            provider_used="openai",
            cost_usd=0.002,
            latency_sec=0.3,
            input_tokens=20,
            output_tokens=10,
        )
        res = runner.invoke(code_main, ["-p", "--json", "What is 2+2?", "--cwd", str(tmp_path)])
        assert res.exit_code == 0
        data = json.loads(res.output)
        assert data["text"] == "JSON test response"
        assert data["model"] == "gpt-4o"
        assert data["completed"] is True


def test_cli_code_index(tmp_path):
    f = tmp_path / "main.py"
    f.write_text("def hello():\n    pass\n")
    runner = CliRunner()
    with patch("ijachi_router.indexer.WorkspaceIndexer.index_workspace", return_value=[{"symbol": "hello"}]):
        res = runner.invoke(code_main, ["--cwd", str(tmp_path), "index"])
        assert res.exit_code == 0
        assert "Indexed 1 workspace symbols" in res.output
