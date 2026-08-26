"""Plan Mode workflow for ijachi-code.

Implements structured plan mode execution:
  - Enter / exit plan mode
  - Generate a structured `.router/plan.md` from a task description
  - Show a truncated preview with line counts
  - Confirm with the user before any code modifications
  - Generate `AGENTS.md` context files on demand via `/init`

Usage
-----
::

    from ijachi_router.plan_mode import PlanModePlanner
    planner = PlanModePlanner(workspace_root=Path.cwd())
    preview = planner.plan("Add user authentication")
    if planner.confirm_plan(preview):
        ...
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text

from ijachi_router.core import route
from ijachi_router.ui import _console as console

_PLAN_SYSTEM_PROMPT = """You are ijachi-code's planning assistant.

Given a user task, produce a concise, structured implementation plan in Markdown.
The plan should include:
1. A one-line summary of the goal.
2. A numbered list of concrete steps.
3. Files that will be created, modified, or deleted.
4. Any tests that should be added or updated.
5. Risks or assumptions.

Do not write code. Do not execute tools. Only produce the plan document."""

_AGENTS_MD_PROMPT = """You are ijachi-code's context assistant.

Read the workspace files described in the user's prompt and produce a concise
AGENTS.md context file for this project. The output should be valid Markdown
and include:
- Project purpose and architecture overview
- Key files and their roles
- Build/test commands
- Coding conventions used in the repo
- Any important dependencies or constraints

Keep the file under 200 lines so it fits in future context windows."""


@dataclass
class PlanPreview:
    """Lightweight summary of a generated plan."""

    task: str
    plan_path: Path
    total_lines: int
    preview_lines: list[str]
    approved: bool = False


class PlanModePlanner:
    """Generate and confirm implementation plans before code changes."""

    def __init__(
        self,
        workspace_root: Path | str | None = None,
        accessible: bool = False,
    ) -> None:
        self.workspace_root = Path(workspace_root or Path.cwd()).resolve()
        self.accessible = accessible
        self.plan_dir = self.workspace_root / ".router"
        self.plan_file = self.plan_dir / "plan.md"

    def plan(
        self,
        task: str,
        preview_lines: int = 20,
    ) -> PlanPreview:
        """Generate a plan from *task*, save it to `.router/plan.md`, and return a preview.

        Args:
            task: The user's high-level task description.
            preview_lines: Number of lines to include in the preview.

        Returns:
            :class:`PlanPreview` with the saved path and approval state.
        """
        self._announce("Entered plan mode")
        prompt = f"Task: {task}\n\nWrite an implementation plan in Markdown."
        try:
            res = route(
                prompt=prompt,
                system_prompt=_PLAN_SYSTEM_PROMPT,
                priority="quality",
                max_tokens=4096,
                timeout=10,
            )
            plan_text = res.text
        except Exception as exc:
            plan_text = f"# Plan generation failed\n\nCould not generate plan: {exc}\n\nTask: {task}"

        self.plan_dir.mkdir(parents=True, exist_ok=True)
        self.plan_file.write_text(plan_text, encoding="utf-8")
        lines = plan_text.splitlines()

        self._announce("Exited plan mode")
        preview = PlanPreview(
            task=task,
            plan_path=self.plan_file,
            total_lines=len(lines),
            preview_lines=lines[:preview_lines],
        )
        self._show_preview(preview)
        return preview

    def confirm_plan(self, preview: PlanPreview | None = None) -> bool:
        """Ask the user to approve the generated plan.

        Args:
            preview: Optional preview object. If None, the latest plan on disk is used.

        Returns:
            True if the user approved the plan.
        """
        if preview is None:
            if not self.plan_file.exists():
                return False
            lines = self.plan_file.read_text(encoding="utf-8").splitlines()
            preview = PlanPreview(
                task="current plan",
                plan_path=self.plan_file,
                total_lines=len(lines),
                preview_lines=lines[:20],
            )

        if self.accessible:
            print(f"permission_required: Approve plan {preview.plan_path}? [y/n]: ")
            try:
                answer = input().strip().lower()
            except (KeyboardInterrupt, EOFError):
                answer = "n"
            approved = answer in ("y", "yes", "")
        else:
            console.print(f"\n[bold cyan]📋 Plan: {preview.plan_path}[/bold cyan]")
            console.print(
                f"[dim]Preview ({len(preview.preview_lines)} of {preview.total_lines} lines):[/dim]\n"
            )
            for line in preview.preview_lines:
                console.print(Text(line))
            approved = Confirm.ask("Approve this plan and proceed with implementation?", default=True)

        preview.approved = approved
        return approved

    def generate_agents_md(self, workspace_summary: str = "") -> Path:
        """Generate an AGENTS.md context file for the workspace.

        Args:
            workspace_summary: Optional summary of the workspace to guide generation.

        Returns:
            Path to the generated AGENTS.md file.
        """
        self._announce("Generating AGENTS.md")
        prompt = "Generate an AGENTS.md context file for this project."
        if workspace_summary:
            prompt += f"\n\nWorkspace summary:\n{workspace_summary}"
        try:
            res = route(
                prompt=prompt,
                system_prompt=_AGENTS_MD_PROMPT,
                priority="quality",
                max_tokens=4096,
                timeout=10,
            )
            content = res.text
        except Exception as exc:
            content = f"# AGENTS.md generation failed\n\n{exc}\n\nPlease write this file manually."

        agents_md = self.workspace_root / "AGENTS.md"
        agents_md.write_text(content, encoding="utf-8")
        self._announce(f"Wrote {len(content.splitlines())} lines to {agents_md}")
        return agents_md

    generate_claude_md = generate_agents_md


    def clear_plan(self) -> None:
        """Remove the generated plan file if it exists."""
        if self.plan_file.exists():
            self.plan_file.unlink()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _announce(self, message: str) -> None:
        """Show a plan-mode state marker."""
        if self.accessible:
            print(f"plan: {message}")
        else:
            marker = "●"
            console.print(f"[banner.title]{marker} {message}[/banner.title]")

    def _show_preview(self, preview: PlanPreview) -> None:
        """Render the plan preview panel."""
        if self.accessible:
            print(f"plan_file: {preview.plan_path}")
            print(f"plan_lines: {preview.total_lines}")
            for line in preview.preview_lines:
                print(f"  {line}")
            return

        body_lines = [Text(line) for line in preview.preview_lines]
        if preview.total_lines > len(preview.preview_lines):
            body_lines.append(
                Text.from_markup(
                    f"[dim]... {preview.total_lines - len(preview.preview_lines)} more lines[/dim]"
                )
            )
        body = Text("\n").join(body_lines) if body_lines else Text("(empty plan)")
        panel = Panel(
            body,
            title=f"[bold]📝 Plan Preview[/bold]",
            subtitle=f"[dim]Wrote {preview.total_lines} lines to {preview.plan_path}[/dim]",
            border_style="banner.border",
            padding=(0, 1),
        )
        console.print(panel)


def is_plan_mode(permission_mode: str) -> bool:
    """Return True if *permission_mode* indicates planning should run first."""
    return permission_mode.strip().lower() == "plan"
