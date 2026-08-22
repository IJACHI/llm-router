"""Unit tests for live status spinners and progress indicators."""

from __future__ import annotations

import pytest
from ijachi_router.ui import status_spinner, live_status_message, set_theme


def test_status_spinner_standard():
    set_theme("dark")
    with status_spinner("Testing operations...") as spinner:
        spinner.update("Progress step 1...")
        spinner.update("Progress step 2...")


def test_status_spinner_accessible(capsys):
    set_theme("accessible")
    with status_spinner("Accessible operation...") as spinner:
        spinner.update("Step accessible 1...")
    
    live_status_message("Notice message")
    captured = capsys.readouterr()
    assert "status: Accessible operation..." in captured.out
    assert "status: Step accessible 1..." in captured.out
    assert "status: Notice message" in captured.out

    # Reset
    set_theme("dark")
