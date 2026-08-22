"""Unit tests for inbuilt workspace state checkpoints, version control, and full-auto mode."""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest
from ijachi_router.checkpoint_manager import CheckpointManager
from ijachi_router.agent import WorkspaceTools, AgenticRouter


def test_checkpoint_manager_snapshot_and_undo():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        mgr = CheckpointManager(workspace_root=root)

        # 1. Create a file
        test_file = root / "app.py"
        test_file.write_text("v1 = 10\n", encoding="utf-8")

        # Snapshot before edit
        chk_id = mgr.snapshot_file_before_action("app.py", action_desc="Edit app.py")
        assert chk_id.startswith("chk_")

        # 2. Modify the file to v2
        test_file.write_text("v2 = 20\n", encoding="utf-8")
        assert test_file.read_text(encoding="utf-8") == "v2 = 20\n"

        # 3. Undo the modification
        ok, msg = mgr.undo_last()
        assert ok is True
        assert "Reverted state" in msg
        assert test_file.read_text(encoding="utf-8") == "v1 = 10\n"


def test_checkpoint_undo_newly_created_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        mgr = CheckpointManager(workspace_root=root)

        # Snapshot a file that does not exist yet (prev_content = None)
        chk_id = mgr.snapshot_file_before_action("new_module.py", action_desc="Create new_module")
        new_file = root / "new_module.py"
        new_file.write_text("print('hello')\n", encoding="utf-8")
        assert new_file.exists()

        # Undo should delete the newly created file
        ok, msg = mgr.undo_last()
        assert ok is True
        assert not new_file.exists()


def test_restore_specific_checkpoint():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        mgr = CheckpointManager(workspace_root=root)
        f = root / "config.json"
        
        # State 1
        f.write_text('{"version": 1}', encoding="utf-8")
        chk1 = mgr.snapshot_file_before_action("config.json", action_desc="State 1")

        # State 2
        f.write_text('{"version": 2}', encoding="utf-8")
        chk2 = mgr.snapshot_file_before_action("config.json", action_desc="State 2")

        # State 3
        f.write_text('{"version": 3}', encoding="utf-8")

        # Restore State 1 directly
        ok, msg = mgr.restore_checkpoint(chk1)
        assert ok is True
        assert f.read_text(encoding="utf-8") == '{"version": 1}'


def test_workspace_tools_auto_snapshot_on_write():
    with tempfile.TemporaryDirectory() as tmpdir:
        tools = WorkspaceTools(root_dir=tmpdir, accessible=True)
        # Write file with require_approval=False
        out = tools.write_file("index.html", "<h1>Hello</h1>", require_approval=False)
        assert "Successfully wrote" in out

        # Verify a checkpoint was automatically recorded
        checkpoints = tools.checkpoints.list_checkpoints()
        assert len(checkpoints) >= 1
        assert "index.html" in checkpoints[-1].description


def test_dangerous_command_blocked_in_run_command():
    tools = WorkspaceTools(root_dir=".", accessible=True)
    res = tools.run_command("rm -rf /", require_approval=False)
    assert "Security Error" in res
    assert "prohibited" in res


def test_agentic_router_full_auto_mode():
    agent = AgenticRouter(root_dir=".", full_auto=True)
    assert agent.full_auto is True
    assert agent.require_approval is False
    agent.set_full_auto(False)
    assert agent.full_auto is False
    assert agent.require_approval is True
