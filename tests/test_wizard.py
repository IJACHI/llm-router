"""Unit tests for LauncherWizard & Interactive Provider Setup."""

from __future__ import annotations

import pytest
from ijachi_router.wizard import LauncherWizard


def test_launcher_wizard_status():
    wizard = LauncherWizard()
    status = wizard.get_provider_status()

    assert "anthropic" in status
    assert "openai" in status
    assert "groq" in status
    assert "local" in status
    assert status["local"]["active"] is True
    assert "ANTHROPIC_API_KEY" in status["anthropic"]["env_var"]


def test_print_welcome_table():
    # Verify table printing executes cleanly
    LauncherWizard.print_welcome_table()
