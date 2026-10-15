"""Persistent Session Store for ijachi-llm-router.

Document 3.10 & 3.11 (SC-01, SC-08, SC-09):
- Location: ~/.ijachi-llmr/sessions/<session_id>/
- events.jsonl: append-only with flush after each event
- state.json: write-to-temp then atomic rename (crash-safe)
- tool_results/: full tool outputs stored on disk, referenced by ID
- checkpoints/: file snapshots before writes
- Configurable retention (prune sessions older than N days)
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from ijachi_router.session.checkpoints import CheckpointManager
from ijachi_router.session.events import CanonicalEvent
from ijachi_router.session.state import SessionState

_DEFAULT_SESSIONS_ROOT = Path.home() / ".ijachi-llmr" / "sessions"


class SessionStore:
    """Manages the disk storage and recovery for a single session."""

    def __init__(self, session_id: str | None = None, root_dir: Path | None = None, workspace_dir: Path | None = None):
        self.root_dir = Path(root_dir or _DEFAULT_SESSIONS_ROOT)
        self.session_id = session_id or f"ses_{uuid.uuid4().hex[:8]}"
        self.session_dir = self.root_dir / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self.events_file = self.session_dir / "events.jsonl"
        self.state_file = self.session_dir / "state.json"
        self.tool_results_dir = self.session_dir / "tool_results"
        self.tool_results_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoints_dir = self.session_dir / "checkpoints"

        self.workspace_dir = Path(workspace_dir or Path.cwd()).resolve()
        self.checkpoints = CheckpointManager(self.checkpoints_dir)
        self.state = SessionState(self.session_id, workspace_dir=self.workspace_dir)

        if self.state_file.exists():
            self._load_state()

    @property
    def ledger(self):
        return self.state.ledger

    @property
    def cost_ledger(self) -> dict[str, Any]:
        return {
            "call_count": self.state.turn_count,
            "total_cost_usd": self.state.total_cost_usd,
            "total_input_tokens": self.state.total_input_tokens,
            "total_output_tokens": self.state.total_output_tokens,
            "model_costs": self.state.model_costs,
        }

    def record_turn(
        self,
        user_text: str,
        assistant_text: str,
        model: str,
        provider: str,
        cost_usd: float = 0.0,
        in_tokens: int = 0,
        out_tokens: int = 0,
    ) -> None:
        ev_u = CanonicalEvent.create_user_message(user_text, session_id=self.session_id)
        ev_a = CanonicalEvent.create_assistant_message(
            assistant_text,
            session_id=self.session_id,
            model={"provider": provider, "id": model},
            usage={"cost_usd": cost_usd, "input_tokens": in_tokens, "output_tokens": out_tokens},
        )
        self.append_event(ev_u)
        self.append_event(ev_a)
        self.state.record_usage(model, cost_usd, in_tokens, out_tokens)
        self.state.turn_count += 1
        self.state.current_model = model
        self.state.current_provider = provider
        self.save_state()

    def track_file_read(self, path: Path | str) -> None:
        self.state.record_file_read(str(path))

    def track_file_write(self, path: Path | str) -> None:
        self.state.record_file_write(str(path))

    def append_event(self, event: CanonicalEvent) -> None:
        """Append an event to events.jsonl and flush immediately (atomic append)."""
        event.session_id = self.session_id
        payload = json.dumps(event.to_dict())
        with open(self.events_file, "a", encoding="utf-8") as f:
            f.write(payload + "\n")
            f.flush()
            os.fsync(f.fileno())

    def read_events(self, committed_only: bool = True) -> list[CanonicalEvent]:
        """Read all canonical events from disk."""
        if not self.events_file.exists():
            return []
        events: list[CanonicalEvent] = []
        with open(self.events_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        evt = CanonicalEvent.from_dict(data)
                        if not committed_only or evt.committed:
                            events.append(evt)
                    except Exception:
                        continue
        return events

    def store_tool_result(self, tool_name: str, full_output: str) -> str:
        """Store long tool output in full on disk and return content ID (FR-05)."""
        result_id = f"tr_{uuid.uuid4().hex[:8]}"
        target = self.tool_results_dir / f"{result_id}.txt"
        target.write_text(full_output, encoding="utf-8")
        return result_id

    def read_tool_result(self, result_id: str) -> str | None:
        target = self.tool_results_dir / f"{result_id}.txt"
        if target.exists():
            return target.read_text(encoding="utf-8", errors="replace")
        return None

    def save_state(self) -> None:
        """Atomic write-to-temp then rename for state snapshot."""
        data = self.state.to_dict()
        data["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        content = json.dumps(data, indent=2)

        temp_fd, temp_path = tempfile.mkstemp(dir=str(self.session_dir), prefix="state_", suffix=".tmp")
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self.state_file)
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise

    def _load_state(self) -> None:
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            self.state = SessionState.from_dict(data)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Session discovery, resume & prune helpers
# ---------------------------------------------------------------------------

def list_sessions(root_dir: Path | None = None) -> list[dict[str, Any]]:
    """List all stored sessions with metadata."""
    base = Path(root_dir or _DEFAULT_SESSIONS_ROOT)
    if not base.exists():
        return []
    results: list[dict[str, Any]] = []
    for sdir in sorted(base.iterdir(), key=lambda d: d.stat().st_mtime, reverse=True):
        if sdir.is_dir():
            state_p = sdir / "state.json"
            if state_p.exists():
                try:
                    data = json.loads(state_p.read_text(encoding="utf-8"))
                    results.append({
                        "id": sdir.name,
                        "workspace": data.get("workspace_dir", ""),
                        "turns": data.get("turn_count", 0),
                        "cost": data.get("total_cost_usd", 0.0),
                        "model": data.get("current_model", ""),
                        "updated_at": data.get("updated_at", ""),
                        "mtime": sdir.stat().st_mtime,
                    })
                except Exception:
                    continue
    return results


def find_most_recent_session(workspace_dir: str | Path, root_dir: Path | None = None) -> str | None:
    """Find the ID of the most recent session for a given workspace path."""
    ws_canonical = str(Path(workspace_dir).resolve())
    for s in list_sessions(root_dir):
        if s.get("workspace") == ws_canonical:
            return s["id"]
    return None


def prune_sessions(max_days: int = 30, root_dir: Path | None = None) -> int:
    """Remove sessions older than max_days (default 30 days)."""
    base = Path(root_dir or _DEFAULT_SESSIONS_ROOT)
    if not base.exists():
        return 0
    cutoff = time.time() - (max_days * 86400)
    pruned = 0
    for sdir in base.iterdir():
        if sdir.is_dir() and sdir.stat().st_mtime < cutoff:
            shutil.rmtree(sdir, ignore_errors=True)
            pruned += 1
    return pruned
