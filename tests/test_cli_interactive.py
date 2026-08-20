"""Unit tests for Universal Global Launcher (ijachi, ijachi-code)."""

from __future__ import annotations

import sys
import pytest
from cli import code_main


def test_code_main_entrypoint(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["ijachi", "launcher"])
    with pytest.raises(SystemExit) as exc_info:
        code_main()
    assert exc_info.value.code == 0
