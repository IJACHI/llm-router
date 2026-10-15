"""Checkpoints manager for file snapshotting and undo support.

Document 3.2, 5.5, FR-03, SEC-09:
Before the first write of each turn, touched files are snapshotted.
/undo restores them. Checkpoints limit the cost of mistakes.
"""

from __future__ import annotations

import datetime
import difflib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FileSnapshot:
    path: str
    original_content: str | None  # None if file didn't exist before
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())


class CheckpointManager:
    """Manages file checkpoints per session and turn for undo support."""

    def __init__(self, checkpoints_dir: Path):
        self.checkpoints_dir = Path(checkpoints_dir)
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_stack: list[dict[str, Any]] = []
        self._load_index()

    @property
    def snapshots(self) -> dict[str, dict[str, Any]]:
        """Map of checkpoint name and id to checkpoint entry."""
        out = {}
        for cp in self.checkpoint_stack:
            out[cp["name"]] = cp
            out[cp["id"]] = cp
        return out

    def _index_path(self) -> Path:
        return self.checkpoints_dir / "index.json"

    def _load_index(self) -> None:
        if self._index_path().exists():
            try:
                data = json.loads(self._index_path().read_text(encoding="utf-8"))
                self.checkpoint_stack = data.get("checkpoints", [])
            except Exception:
                self.checkpoint_stack = []

    def _save_index(self) -> None:
        try:
            self._index_path().write_text(
                json.dumps({"checkpoints": self.checkpoint_stack}, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def create_checkpoint(self, name: str, files: list[str | Path]) -> str:
        """Snapshot current state of target files before modifying them."""
        cp_id = f"cp_{len(self.checkpoint_stack) + 1}_{int(datetime.datetime.now().timestamp())}"
        cp_dir = self.checkpoints_dir / cp_id
        cp_dir.mkdir(parents=True, exist_ok=True)

        snapshots: list[dict[str, Any]] = []
        for file_path in files:
            p = Path(file_path).resolve()
            rel_str = str(file_path)
            if p.exists() and p.is_file():
                try:
                    content = p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    content = None
                snapshots.append({
                    "path": str(p),
                    "rel_path": rel_str,
                    "exists": True,
                    "content": content,
                })
            else:
                snapshots.append({
                    "path": str(p),
                    "rel_path": rel_str,
                    "exists": False,
                    "content": None,
                })

        entry = {
            "id": cp_id,
            "name": name,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "snapshots": snapshots,
        }
        self.checkpoint_stack.append(entry)
        self._save_index()
        return cp_id

    def undo_last(self) -> tuple[bool, str]:
        """Restore files to the state captured in the most recent checkpoint."""
        if not self.checkpoint_stack:
            return False, "No checkpoints available to undo."

        last_cp = self.checkpoint_stack.pop()
        self._save_index()

        restored = []
        for snap in last_cp.get("snapshots", []):
            target_path = Path(snap["path"])
            if snap.get("exists"):
                content = snap.get("content")
                if content is not None:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_text(content, encoding="utf-8")
                    restored.append(f"Restored '{snap.get('rel_path', target_path.name)}'")
            else:
                if target_path.exists():
                    target_path.unlink()
                    restored.append(f"Removed created file '{snap.get('rel_path', target_path.name)}'")

        msg = f"✓ Undid checkpoint '{last_cp.get('name', last_cp['id'])}':\n" + "\n".join(restored)
        return True, msg

    def diff_from_checkpoint(self, checkpoint_id: str | None = None) -> str:
        """Compute unified diff between current files and a checkpoint."""
        if not self.checkpoint_stack:
            return "No checkpoints recorded."

        cp = self.checkpoint_stack[-1] if not checkpoint_id else next(
            (c for c in self.checkpoint_stack if c["id"] == checkpoint_id), self.checkpoint_stack[-1]
        )

        diffs = []
        for snap in cp.get("snapshots", []):
            target = Path(snap["path"])
            old_lines = (snap.get("content") or "").splitlines(keepends=True)
            new_content = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
            new_lines = new_content.splitlines(keepends=True)
            diff = difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{snap.get('rel_path', target.name)}",
                tofile=f"b/{snap.get('rel_path', target.name)}",
            )
            diff_text = "".join(diff)
            if diff_text:
                diffs.append(diff_text)

        return "\n".join(diffs) if diffs else "No differences found against checkpoint."
