"""Inbuilt Workspace State Checkpoint & Version Control Manager for ijachi-code.

Provides step-by-step state snapshotting, undo/rewind capability, and point-in-time
workspace recovery across all tool calls and agentic tasks.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.table import Table

console = Console()


@dataclass
class Checkpoint:
    id: str
    timestamp: str
    description: str
    files: dict[str, str | None]  # rel_path -> previous text content (None if file didn't exist)
    step_number: int | None = None

    @property
    def formatted_time(self) -> str:
        try:
            dt = datetime.fromisoformat(self.timestamp)
            return dt.strftime("%H:%M:%S")
        except Exception:
            return self.timestamp


class CheckpointManager:
    """Manages workspace snapshots and step-by-step undo/rewind recovery points."""

    def __init__(self, workspace_root: Path | str | None = None):
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
        self.checkpoints_dir = self.workspace_root / ".ijachi" / "checkpoints"
        self._index_file = self.checkpoints_dir / "index.json"
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        """Create checkpoints storage directory if missing."""
        try:
            self.checkpoints_dir.mkdir(parents=True, exist_ok=True)
            if not self._index_file.exists():
                self._index_file.write_text("[]", encoding="utf-8")
        except Exception:
            pass

    def _load_index(self) -> list[dict[str, Any]]:
        """Load list of checkpoint records from disk."""
        if not self._index_file.exists():
            return []
        try:
            return json.loads(self._index_file.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_index(self, records: list[dict[str, Any]]) -> None:
        """Save checkpoint records to disk."""
        try:
            self._index_file.write_text(json.dumps(records, indent=2), encoding="utf-8")
        except Exception:
            pass

    def snapshot_file_before_action(self, rel_path: str, action_desc: str = "File modification") -> str:
        """Take a lightweight snapshot of a single file before it is written or edited.

        Args:
            rel_path: Relative path to the file in the workspace.
            action_desc: Brief description of the pending action.

        Returns:
            The generated checkpoint ID.
        """
        full_path = self.workspace_root / rel_path
        prev_content: str | None = None
        if full_path.exists() and full_path.is_file():
            try:
                prev_content = full_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                prev_content = None

        return self.create_checkpoint(
            description=f"{action_desc}: {rel_path}",
            files_map={rel_path: prev_content},
        )

    def create_checkpoint(
        self,
        description: str,
        files_map: dict[str, str | None],
        step_number: int | None = None,
    ) -> str:
        """Create and persist a new workspace state checkpoint.

        Args:
            description: Human-readable task or tool description.
            files_map: Dict mapping relative paths to their PREVIOUS content (or None if newly created).
            step_number: Optional step index in multi-step agent loop.

        Returns:
            The unique checkpoint ID string.
        """
        now = datetime.now()
        chk_id = f"chk_{now.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000}"
        
        checkpoint = Checkpoint(
            id=chk_id,
            timestamp=now.isoformat(),
            description=description,
            files=files_map,
            step_number=step_number,
        )

        records = self._load_index()
        records.append(asdict(checkpoint))
        # Keep at most the last 50 checkpoints to save disk space
        if len(records) > 50:
            records = records[-50:]
        self._save_index(records)
        return chk_id

    def list_checkpoints(self) -> list[Checkpoint]:
        """Return all available checkpoints ordered chronologically."""
        records = self._load_index()
        return [
            Checkpoint(
                id=r["id"],
                timestamp=r["timestamp"],
                description=r["description"],
                files=r.get("files", {}),
                step_number=r.get("step_number"),
            )
            for r in records
        ]

    def undo_last(self) -> tuple[bool, str]:
        """Revert the most recent checkpoint.

        Returns:
            (success: bool, message: str)
        """
        records = self._load_index()
        if not records:
            return False, "No previous checkpoints available to undo."

        last_record = records.pop()
        chk = Checkpoint(
            id=last_record["id"],
            timestamp=last_record["timestamp"],
            description=last_record["description"],
            files=last_record.get("files", {}),
            step_number=last_record.get("step_number"),
        )

        success, msg = self._apply_restore(chk)
        if success:
            self._save_index(records)
        return success, msg

    def restore_checkpoint(self, checkpoint_id: str) -> tuple[bool, str]:
        """Revert workspace to a specific checkpoint by ID.

        Args:
            checkpoint_id: Checkpoint ID string (e.g. 'chk_20260822_...').

        Returns:
            (success: bool, message: str)
        """
        records = self._load_index()
        target_record = None
        target_idx = -1
        for idx, r in enumerate(records):
            if r["id"] == checkpoint_id or checkpoint_id in r["id"]:
                target_record = r
                target_idx = idx
                break

        if not target_record:
            return False, f"Checkpoint '{checkpoint_id}' not found."

        chk = Checkpoint(
            id=target_record["id"],
            timestamp=target_record["timestamp"],
            description=target_record["description"],
            files=target_record.get("files", {}),
            step_number=target_record.get("step_number"),
        )

        success, msg = self._apply_restore(chk)
        if success:
            # Trim index up to the restored checkpoint
            self._save_index(records[: target_idx + 1])
        return success, msg

    def _apply_restore(self, checkpoint: Checkpoint) -> tuple[bool, str]:
        """Apply the file reversions defined in a checkpoint."""
        reverted_files: list[str] = []
        errors: list[str] = []

        for rel_path, prev_content in checkpoint.files.items():
            full_path = self.workspace_root / rel_path
            try:
                if prev_content is None:
                    # File was newly created in this step -> delete it
                    if full_path.exists():
                        full_path.unlink(missing_ok=True)
                        reverted_files.append(f"{rel_path} (deleted new file)")
                else:
                    # Restore previous content
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.write_text(prev_content, encoding="utf-8")
                    reverted_files.append(f"{rel_path} (restored)")
            except Exception as e:
                errors.append(f"{rel_path}: {e}")

        if errors:
            return False, f"Errors restoring checkpoint {checkpoint.id}: {'; '.join(errors)}"

        files_summary = ", ".join(reverted_files) if reverted_files else "none"
        return True, f"✓ Reverted state to [{checkpoint.id}] ({checkpoint.description}). Files: {files_summary}"

    def print_checkpoints_table(self) -> None:
        """Render a Rich table of all available workspace checkpoints."""
        checkpoints = self.list_checkpoints()
        if not checkpoints:
            console.print("[yellow]No workspace checkpoints recorded yet.[/yellow]")
            return

        table = Table(
            title=f"🕒 Inbuilt Workspace State Checkpoints ({len(checkpoints)} total)",
            box=box.ROUNDED,
            header_style="bold cyan",
        )
        table.add_column("ID", style="bold green", width=26)
        table.add_column("Time", style="dim", width=10)
        table.add_column("Task / Action Description", style="white")
        table.add_column("Files Tracked", style="cyan", width=22)

        for chk in reversed(checkpoints):
            files_str = ", ".join(chk.files.keys()) if chk.files else "none"
            table.add_row(
                chk.id,
                chk.formatted_time,
                chk.description,
                files_str[:22],
            )

        console.print(table)
