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
import uuid
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
        cp_id = f"cp_{len(self.checkpoint_stack) + 1}_{int(datetime.datetime.now().timestamp())}_{uuid.uuid4().hex[:6]}"
        cp_dir = self.checkpoints_dir / cp_id
        cp_dir.mkdir(parents=True, exist_ok=True)

        snapshots = [self._snapshot(f) for f in files]

        entry = {
            "id": cp_id,
            "name": name,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "snapshots": snapshots,
        }
        self.checkpoint_stack.append(entry)
        self._save_index()
        return cp_id

    @staticmethod
    def _snapshot(file_path: str | Path) -> dict[str, Any]:
        p = Path(file_path).resolve()
        if p.exists() and p.is_file():
            try:
                content = p.read_text(encoding="utf-8")
            except Exception:
                content = None  # binary/undecodable: cannot be restored faithfully
            return {"path": str(p), "rel_path": str(file_path), "exists": True, "content": content}
        return {"path": str(p), "rel_path": str(file_path), "exists": False, "content": None}

    def add_to_checkpoint(self, checkpoint_id: str, files: list[str | Path]) -> None:
        """Add pre-modification snapshots of *files* to an existing checkpoint (change set)."""
        cp = next((c for c in self.checkpoint_stack if c["id"] == checkpoint_id), None)
        if cp is None:
            return
        known = {s["path"] for s in cp["snapshots"]}
        for f in files:
            snap = self._snapshot(f)
            if snap["path"] not in known:
                cp["snapshots"].append(snap)
                known.add(snap["path"])
        self._save_index()

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

        skipped = [s for s in last_cp.get("snapshots", []) if s.get("exists") and s.get("content") is None]
        for snap in skipped:
            restored.append(f"Could not restore non-text file '{snap.get('rel_path')}'")
        msg = f"✓ Undid checkpoint '{last_cp.get('name', last_cp['id'])}':\n" + "\n".join(restored)
        return True, msg

    def session_diff(self) -> str:
        """Unified diff of every file changed in this session vs. its earliest snapshot."""
        if not self.checkpoint_stack:
            return "No checkpoints recorded."
        earliest: dict[str, dict[str, Any]] = {}
        for cp in self.checkpoint_stack:
            for snap in cp.get("snapshots", []):
                earliest.setdefault(snap["path"], snap)
        diffs = []
        for path, snap in earliest.items():
            target = Path(path)
            old = (snap.get("content") or "").splitlines(keepends=True)
            new = target.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if target.exists() else []
            rel = snap.get("rel_path", target.name)
            d = "".join(difflib.unified_diff(old, new, fromfile=f"a/{rel}", tofile=f"b/{rel}"))
            if d:
                diffs.append(d)
        return "\n".join(diffs) if diffs else "No changes in this session."

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
