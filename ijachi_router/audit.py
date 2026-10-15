"""Local append-only audit logger.

Document 5.12:
Records approvals and denials (what, who, when), executed commands with exit codes,
file writes (path, hashes, not contents), routing decisions, provider failures.
Audit logs never contain secrets or prompt text by default.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

_AUDIT_LOG_FILE = Path.home() / ".ijachi-llmr" / "audit.log"


def log_audit_event(
    event_type: str,  # approval | denial | command | file_write | routing | failure
    details: dict[str, Any],
) -> None:
    """Append a structured audit entry to ~/.ijachi-llmr/audit.log."""
    try:
        _AUDIT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "event_type": event_type,
            "details": details,
        }
        with open(_AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass


class SecurityAuditLogger:
    """Configurable append-only audit logger (Document 5.12)."""

    def __init__(self, audit_log_path: Path | None = None):
        self.audit_log_path = audit_log_path or _AUDIT_LOG_FILE

    def log_action(
        self,
        action: str,
        target: str,
        risk_class: str,
        approved: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        try:
            self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "action": action,
                "target": target,
                "risk_class": risk_class,
                "approved": approved,
                "details": details or {},
            }
            with open(self.audit_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            pass
