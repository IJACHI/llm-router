"""Execution Sandbox and Secrets Redaction Pipeline.

Document 5.5 & 5.6 (SEC-03, SEC-05, SEC-06, SEC-07):
- Canonicalize all file paths; reject path traversal or symlinks pointing outside workspace roots
- Sensitive file deny-list (.env*, *.pem, *.key, id_rsa*, credentials)
- Subprocess environment scrub (strip API keys, secrets, tokens)
- Output redaction pipeline (replaces key patterns with [REDACTED:token])
- Output cap (30,000 chars) and per-command timeout (120s)
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from pathlib import Path
from typing import Any

# Sensitive file patterns never read or indexed without explicit approval (SEC-07)
_SENSITIVE_PATTERNS = [
    ".env*", "*.pem", "*.key", "id_rsa*", "id_ed25519*",
    ".aws/credentials", ".npmrc", ".pypirc", ".netrc",
]

# Patterns for secret redaction in tool output (SEC-06)
_KEY_PATTERNS = [
    (r"(sk-[a-zA-Z0-9_\-]{20,})", "[REDACTED:api_key]"),
    (r"(ghp_[a-zA-Z0-9]{36})", "[REDACTED:github_token]"),
    (r"(AKIA[0-9A-Z]{16})", "[REDACTED:aws_access_key]"),
    (r"([A-Za-z0-9+/]{40})", "[REDACTED:aws_secret_key]"),
    (r"(eyJ[a-zA-Z0-9_\-]{20,}\.[a-zA-Z0-9_\-]{20,}\.[a-zA-Z0-9_\-]*)", "[REDACTED:jwt]"),
]


def redact_secrets(text: str) -> str:
    """Scrub known API keys, tokens, and credentials from text (SEC-06)."""
    if not text:
        return ""
    result = text
    for pattern, replacement in _KEY_PATTERNS:
        result = re.sub(pattern, replacement, result)
    return result


class WorkspaceSandbox:
    """Enforces file system boundaries and executes scrubbed subprocesses."""

    def __init__(self, workspace_dir: Path | str | None = None, extra_roots: list[Path | str] | None = None):
        self.primary_root = Path(workspace_dir or Path.cwd()).resolve()
        self.roots = [self.primary_root]
        if extra_roots:
            for r in extra_roots:
                self.roots.append(Path(r).resolve())

    def canonicalize_path(self, target_path: str | Path) -> Path:
        """Resolve path and verify it is strictly within authorized workspace roots (SEC-03)."""
        p = Path(target_path)
        if not p.is_absolute():
            resolved = (self.primary_root / p).resolve()
        else:
            resolved = p.resolve()

        # Check if resolved path is inside any workspace root
        for root in self.roots:
            try:
                resolved.relative_to(root)
                return resolved
            except ValueError:
                continue

        raise PermissionError(f"Path traversal denied: '{target_path}' resolves outside workspace roots.")

    def resolve_safe_path(self, target_path: str | Path) -> Path:
        """Alias for canonicalize_path."""
        return self.canonicalize_path(target_path)

    def is_sensitive_file(self, target_path: str | Path) -> bool:
        """Check if path matches the sensitive file deny-list (SEC-07)."""
        name = Path(target_path).name
        for pattern in _SENSITIVE_PATTERNS:
            if fnmatch.fnmatch(name, pattern):
                return True
        return False

    def _scrub_environment(self, env: dict[str, str]) -> dict[str, str]:
        """Scrub sensitive keys from a provided environment dict."""
        clean: dict[str, str] = {}
        for k, v in env.items():
            k_upper = k.upper()
            if (
                k_upper.endswith("_API_KEY")
                or k_upper.endswith("_KEY")
                or k_upper.endswith("_TOKEN")
                or k_upper.endswith("_SECRET")
                or k_upper.startswith("AWS_")
                or k_upper.startswith("AZURE_")
                or "IJACHI" in k_upper
            ):
                continue
            clean[k] = v
        return clean

    def get_scrubbed_env(self) -> dict[str, str]:
        """Produce a clean environment dict with all secrets scrubbed (SEC-05)."""
        clean_env = self._scrub_environment(dict(os.environ))
        clean_env["PAGER"] = "cat"
        return clean_env

    def run_sandboxed_command(
        self,
        command: str,
        cwd: Path | str | None = None,
        timeout_sec: int = 120,
        output_cap: int = 30_000,
    ) -> tuple[int, str, str]:
        """Execute a command in scrubbed environment with timeout and output cap."""
        work_dir = Path(cwd).resolve() if cwd else self.primary_root
        scrubbed_env = self.get_scrubbed_env()

        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=work_dir,
                env=scrubbed_env,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                stdin=subprocess.DEVNULL,  # No interactive hanging (Doc 5.5)
            )
            stdout_redacted = redact_secrets(proc.stdout)
            stderr_redacted = redact_secrets(proc.stderr)

            # Cap output to avoid context overflow
            if len(stdout_redacted) > output_cap:
                stdout_redacted = stdout_redacted[:output_cap] + f"\n... [Output capped at {output_cap} chars]"
            if len(stderr_redacted) > output_cap:
                stderr_redacted = stderr_redacted[:output_cap] + f"\n... [Error output capped at {output_cap} chars]"

            return proc.returncode, stdout_redacted, stderr_redacted

        except subprocess.TimeoutExpired:
            return 124, "", f"Command timed out after {timeout_sec} seconds."
        except Exception as e:
            return 1, "", f"Execution error: {e}"
