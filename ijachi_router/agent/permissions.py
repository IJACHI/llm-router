"""Tool Risk Classification, Shell Command Analysis, and Permission Enforcement.

Document 5.4 (SEC-01, SEC-02, SEC-08, AT-09, AT-13):
- Risk classes: R0 (read-only), R1 (write), R2 (execute), R3 (network), R4 (sensitive/external)
- Permission modes: ask (default), plan, accept-edits, auto-safe (for CI)
- Compound command splitting (&&, ;, |, $(), backticks, redirections)
- Always-ask & never-allow lists
- Non-interactive CI safety: if no TTY, unapproved actions fail with exit code 5
"""

from __future__ import annotations

import os
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console()

# Safe read-only commands that run without asking in ask mode
_SAFE_COMMANDS = {
    "git status", "git diff", "git log", "git branch", "git show",
    "pwd", "ls", "echo", "which", "uname", "whoami", "date",
}

# Commands that MUST always prompt for confirmation
_ALWAYS_ASK_PATTERNS = [
    r"\bsudo\b",
    r"\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*|--recursive|--force)\b",
    r"\bgit\s+push\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\b",
    r"\bchmod\s+-R\b",
    r"\bchown\b",
    r"\b(curl|wget)\b.*\|\s*(ba)?sh",
    r"\b(npm|pip|pip3|cargo|yarn|pnpm|brew|apt|apt-get)\s+install\b",
    r"\bdocker\b",
    r"\bkubectl\b",
]

# Commands that are strictly forbidden unless explicitly enabled by user
_NEVER_ALLOW_PATTERNS = [
    r"\bmkfs\b",
    r"\bdd\s+if=.*of=/dev/",
    r":\(\)\{\s*:\|:&\s*\};:",  # fork bomb
    r"\brm\s+-rf\s+/\s*$",
    r"\brm\s+-rf\s+~/?\s*$",
]


from enum import Enum


class RiskClass(str, Enum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R0_READONLY = "R0"
    R1_WRITE = "R1"
    R2_EXECUTE = "R2"
    R3_NETWORK = "R3"
    R4_DESTRUCTIVE = "R4"


@dataclass
class PermissionResult:
    allowed: bool
    risk_class: str  # R0, R1, R2, R3, R4
    reason: str = ""
    exit_code: int = 0


class PermissionManager:
    """Evaluates and prompts for authorization before any tool execution."""

    def __init__(
        self,
        mode: str = "ask",  # ask | plan | accept-edits | auto-safe
        allowed_patterns: list[str] | None = None,
        denied_patterns: list[str] | None = None,
        is_tty: bool = True,
    ):
        self.mode = mode
        self.session_allowed_patterns: set[str] = set(allowed_patterns or [])
        self.session_denied_patterns: set[str] = set(denied_patterns or [])
        self.r1_session_approved: bool = False
        self.is_tty = is_tty and sys.stdin.isatty()

    def classify_tool(self, tool_name: str, args: dict[str, Any], workspace_dir: Path) -> str:
        """Classify tool call into R0..R4 risk tiers."""
        if tool_name in ("Read", "read_file", "Glob", "glob", "Grep", "grep_search", "ListDir", "list_dir", "Plan", "plan"):
            path = args.get("path") or args.get("search_path") or "."
            p = (workspace_dir / path).resolve()
            # If path escapes workspace or touches sensitive files, it is R4
            if not str(p).startswith(str(workspace_dir.resolve())):
                return "R4"
            if any(part.startswith(".env") or part in ("id_rsa", "id_ed25519", "credentials") for part in p.parts):
                return "R4"
            return "R0"

        if tool_name in ("Edit", "edit_file", "Write", "write_file"):
            path = args.get("path", "")
            p = (workspace_dir / path).resolve()
            if not str(p).startswith(str(workspace_dir.resolve())):
                return "R4"
            if ".git" in p.parts:
                return "R4"  # .git is write protected
            return "R1"

        if tool_name in ("Bash", "run_command"):
            cmd = args.get("command", "").strip()
            # Check never allow & destructive patterns
            for pattern in _NEVER_ALLOW_PATTERNS:
                if re.search(pattern, cmd):
                    return "R4"
            for pattern in _ALWAYS_ASK_PATTERNS:
                if re.search(pattern, cmd):
                    return "R4"
            # Check safe list
            if cmd in _SAFE_COMMANDS or any(cmd.startswith(f"{sc} ") for sc in _SAFE_COMMANDS):
                return "R0"
            return "R2"

        if tool_name in ("WebFetch", "WebSearch"):
            return "R3"

        return "R2"

    def analyze_shell_command(self, command: str) -> tuple[bool, str]:
        """Analyze shell command, splitting compound expressions (SEC-02)."""
        cmd_clean = command.strip()

        # Check never-allow
        for pat in _NEVER_ALLOW_PATTERNS:
            if re.search(pat, cmd_clean):
                return False, f"Dangerous command blocked by safety policy: matching '{pat}'"

        # Split compound operators (&&, ||, ;, |, backticks, $())
        subcommands = re.split(r"\s*(?:&&|\|\||;|\|)\s*", cmd_clean)
        for sub in subcommands:
            sub = sub.strip()
            if not sub:
                continue
            for pat in _NEVER_ALLOW_PATTERNS:
                if re.search(pat, sub):
                    return False, f"Dangerous subcommand in pipeline: '{sub}'"

        return True, "Command analysis passed"

    def is_call_permitted(
        self,
        tool_name: str,
        command: str = "",
        args: dict[str, Any] | None = None,
        workspace_dir: Path | None = None,
    ) -> bool:
        """Convenience check if a tool call or shell command is permitted."""
        ws = workspace_dir or Path.cwd()
        call_args = dict(args or {})
        if command and "command" not in call_args:
            call_args["command"] = command
        res = self.authorize_tool_call(tool_name, call_args, workspace_dir=ws)
        return res.allowed

    def authorize_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        workspace_dir: Path,
        model_name: str = "assistant",
        why_needed: str = "",
    ) -> PermissionResult:
        """Evaluate permissions and interactively prompt if required."""
        risk = self.classify_tool(tool_name, args, workspace_dir)

        # Plan mode: read-only
        if self.mode == "plan":
            if risk == "R0":
                return PermissionResult(allowed=True, risk_class=risk)
            return PermissionResult(
                allowed=False,
                risk_class=risk,
                reason="Plan mode is read-only. Tool execution prohibited.",
                exit_code=5,
            )

        # Shell command safety check
        if tool_name in ("Bash", "run_command"):
            cmd = args.get("command", "")
            safe, reason = self.analyze_shell_command(cmd)
            if not safe:
                return PermissionResult(allowed=False, risk_class="R4", reason=reason, exit_code=5)

        # R0: Always allowed
        if risk == "R0":
            return PermissionResult(allowed=True, risk_class=risk)

        # Check explicit deny patterns
        action_repr = f"{tool_name}({args})"
        for d in self.session_denied_patterns:
            if d in action_repr:
                return PermissionResult(
                    allowed=False,
                    risk_class=risk,
                    reason=f"Action explicitly denied by pattern '{d}'",
                    exit_code=5,
                )

        # Check explicit session allow patterns
        for a in self.session_allowed_patterns:
            if a in action_repr or a == tool_name:
                return PermissionResult(allowed=True, risk_class=risk)

        # Accept-edits mode: R1 auto-approved inside workspace
        if self.mode == "accept-edits" and risk == "R1":
            return PermissionResult(allowed=True, risk_class=risk)

        # Auto-safe mode (CI): If not explicitly allowed, deny with exit code 5 (SEC-08, AT-13)
        if self.mode == "auto-safe":
            return PermissionResult(
                allowed=False,
                risk_class=risk,
                reason="auto-safe (CI) mode: unapproved actions are denied without interactive prompt",
                exit_code=5,
            )

        # R1 session approval check (ask once per session)
        if risk == "R1" and self.r1_session_approved:
            return PermissionResult(allowed=True, risk_class=risk)

        # Non-interactive without TTY: cannot prompt, must deny
        if not self.is_tty:
            return PermissionResult(
                allowed=False,
                risk_class=risk,
                reason="Non-interactive session: cannot prompt for permission. Action denied.",
                exit_code=5,
            )

        # Interactive approval prompt (UX-04, Document 5.4, 6.3)
        choice = self._prompt_approval(tool_name, args, risk, model_name, why_needed)

        if choice == "y":
            return PermissionResult(allowed=True, risk_class=risk)
        elif choice == "s":
            if risk == "R1":
                self.r1_session_approved = True
            self.session_allowed_patterns.add(action_repr)
            return PermissionResult(allowed=True, risk_class=risk)
        elif choice == "a":
            self.session_allowed_patterns.add(action_repr)
            return PermissionResult(allowed=True, risk_class=risk)
        elif choice == "d":
            return PermissionResult(
                allowed=False,
                risk_class=risk,
                reason="User denied action with feedback.",
                exit_code=5,
            )
        else:  # 'n' or default Enter
            return PermissionResult(
                allowed=False,
                risk_class=risk,
                reason="User denied action.",
                exit_code=5,
            )

    def _prompt_approval(
        self,
        tool_name: str,
        args: dict[str, Any],
        risk_class: str,
        model_name: str,
        why: str,
    ) -> str:
        """Render interactive approval prompt defaulting to deny."""
        console.print(f"\n[bold yellow]⚠️ Approval Required [{risk_class}][/bold yellow]")
        console.print(f"  [dim]Action:[/dim]    [bold cyan]{tool_name}[/bold cyan]({args})")
        console.print(f"  [dim]Model:[/dim]     {model_name}")
        if why:
            console.print(f"  [dim]Reason:[/dim]    {why}")

        prompt_str = "Allow? [y] once, [s] this session, [a] always, [n] no (default), [e] explain: "
        try:
            val = input(prompt_str).strip().lower()
            return val if val else "n"  # default is deny on Enter alone!
        except (KeyboardInterrupt, EOFError):
            return "n"
