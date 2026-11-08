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
    (r"(sk-ant-[a-zA-Z0-9_\-]{20,})", "[REDACTED:anthropic_key]"),
    (r"(sk-[a-zA-Z0-9_\-]{20,})", "[REDACTED:api_key]"),
    (r"(gh[pousr]_[a-zA-Z0-9]{36,})", "[REDACTED:github_token]"),
    (r"(github_pat_[a-zA-Z0-9_]{40,})", "[REDACTED:github_token]"),
    (r"(xox[abprs]-[a-zA-Z0-9\-]{10,})", "[REDACTED:slack_token]"),
    (r"(AIza[0-9A-Za-z_\-]{35})", "[REDACTED:google_api_key]"),
    (r"(hf_[a-zA-Z0-9]{30,})", "[REDACTED:hf_token]"),
    (r"((?:AKIA|ASIA)[0-9A-Z]{16})", "[REDACTED:aws_access_key]"),
    (r"(eyJ[a-zA-Z0-9_\-]{20,}\.[a-zA-Z0-9_\-]{20,}\.[a-zA-Z0-9_\-]*)", "[REDACTED:jwt]"),
    (r"(-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----)", "[REDACTED:private_key]"),
]

# Generic `NAME=value` / `"name": "value"` assignments whose name looks secret. Matching on the
# name (not just the value shape) avoids redacting git SHAs, checksums and other 40-char hex.
_ASSIGNMENT_PATTERN = re.compile(
    r"""(?ix)
    (\b[A-Z0-9_\-]*(?:SECRET|PASSWORD|PASSWD|API_?KEY|ACCESS_?KEY|AUTH_?TOKEN|PRIVATE_?KEY|TOKEN)[A-Z0-9_\-]*\b
     ["']?\s*[:=]\s*["']?)
    ([^\s"']{8,})
    """
)


def redact_secrets(text: str) -> str:
    """Scrub known API keys, tokens, and credentials from text (SEC-06)."""
    if not text:
        return ""
    result = text
    for pattern, replacement in _KEY_PATTERNS:
        result = re.sub(pattern, replacement, result)
    result = _ASSIGNMENT_PATTERN.sub(
        lambda m: m.group(0) if m.group(2).startswith("[REDACTED") else f"{m.group(1)}[REDACTED:secret]",
        result,
    )
    return result


class WorkspaceSandbox:
    """Enforces file system boundaries and executes scrubbed subprocesses."""

    def __init__(self, workspace_dir: Path | str | None = None, extra_roots: list[Path | str] | None = None):
        self.primary_root = Path(workspace_dir or Path.cwd()).resolve()
        self.roots = [self.primary_root]
        self.os_sandbox = False      # wrap commands with sandbox-exec / bwrap (see os_sandbox.py)
        self.allow_network = False   # outbound network inside the OS sandbox
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
                or "PASSWORD" in k_upper
                or "CREDENTIAL" in k_upper
                or k_upper in ("HF_TOKEN", "GITHUB_TOKEN", "GH_TOKEN", "DATABASE_URL")
                or k_upper.startswith("GOOGLE_APPLICATION")
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

    def command_env(self, work_dir: Path) -> dict[str, str]:
        scrubbed_env = self.get_scrubbed_env()

        # Ensure essential binary paths (Homebrew, ~/.local/bin, and workspace venvs) are available in PATH
        current_path = scrubbed_env.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
        extra_paths: list[str] = []
        for venv_name in ("venv", ".venv"):
            v_bin = work_dir / venv_name / "bin"
            if v_bin.is_dir():
                extra_paths.append(str(v_bin))
        for p in ("/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local" / "bin")):
            if p not in current_path and Path(p).is_dir():
                extra_paths.append(p)
        if extra_paths:
            scrubbed_env["PATH"] = ":".join(extra_paths) + ":" + current_path
        return scrubbed_env

    def _argv(self, command: str, needs_network: bool = False):
        """(argv_or_command, contained) — the OS-sandboxed argv when enabled and available."""
        if self.os_sandbox:
            from ijachi_router.agent.os_sandbox import wrap_command
            argv = wrap_command(command, self.primary_root, allow_network=self.allow_network or needs_network)
            if argv is not None:
                return argv, True
        return command, False

    def start_background(self, command: str, needs_network: bool = False) -> str:
        from ijachi_router.agent.background import SHELLS

        target, _ = self._argv(command, needs_network)
        return SHELLS.start(target, self.primary_root, self.command_env(self.primary_root), command)

    def run_sandboxed_command(
        self,
        command: str,
        cwd: Path | str | None = None,
        timeout_sec: int = 120,
        output_cap: int = 30_000,
        needs_network: bool = False,
    ) -> tuple[int, str, str]:
        """Execute a command in scrubbed environment with timeout and output cap."""
        work_dir = Path(cwd).resolve() if cwd else self.primary_root
        scrubbed_env = self.command_env(work_dir)
        target, _contained = self._argv(command, needs_network)

        try:
            proc = subprocess.run(
                target,
                shell=isinstance(target, str),
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
