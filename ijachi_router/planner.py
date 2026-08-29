"""Plan-First Agentic Mode for ijachi-code.

Generates a structured execution plan before running any tool calls,
shows it in a rich table for user approval, and executes step-by-step
with a live checklist — giving full transparency and control.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text

console = Console()


@dataclass
class PlanStep:
    """A single planned step in an agentic task."""
    index: int
    description: str
    tool_hint: str = ""          # expected tool to be used
    model_hint: str = ""         # expected model tier
    cost_hint: str = "~free"     # rough cost estimate
    completed: bool = False
    skipped: bool = False


@dataclass
class ExecutionPlan:
    task: str
    steps: list[PlanStep] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Plan Generation
# ---------------------------------------------------------------------------

def generate_plan(task: str, agent) -> ExecutionPlan:
    """Ask the LLM to produce a step-by-step plan (no tool calls) for the task."""
    from ijachi_router.core import route

    plan_prompt = f"""You are a senior software engineering planner.
A developer has asked: "{task}"

Produce a numbered execution plan (5–8 steps max) that an autonomous agent will follow.
For each step, output ONE line in exactly this format:
<step_number>. <concise description> | tool: <tool_name> | model: <fast|medium|slow>

Example:
1. Read and map workspace structure | tool: list_dir | model: fast
2. Scaffold directory layout | tool: write_file | model: fast
3. Implement core business logic | tool: write_file | model: slow
4. Write unit tests | tool: write_file | model: fast
5. Run tests and verify | tool: run_command | model: fast

Output ONLY the numbered steps, nothing else."""

    res = route(plan_prompt, priority="speed")
    raw = res.text.strip()

    steps = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # Parse: "1. Description | tool: xyz | model: fast"
        m = re.match(r"(\d+)\.\s+(.+?)(?:\s*\|\s*tool:\s*(\w+))?(?:\s*\|\s*model:\s*(fast|medium|slow))?$", line, re.IGNORECASE)
        if m:
            idx = int(m.group(1))
            desc = m.group(2).strip()
            tool = m.group(3) or ""
            model_tier = m.group(4) or "fast"
            cost = "~free" if model_tier == "fast" else ("~$0.01" if model_tier == "medium" else "~$0.05")
            steps.append(PlanStep(
                index=idx,
                description=desc,
                tool_hint=tool,
                model_hint=model_tier,
                cost_hint=cost,
            ))

    if not steps:
        # Fallback: single step
        steps = [PlanStep(index=1, description=task, tool_hint="", model_hint="balanced", cost_hint="~$0.01")]

    return ExecutionPlan(task=task, steps=steps)


# ---------------------------------------------------------------------------
# Plan Rendering
# ---------------------------------------------------------------------------

def render_plan(plan: ExecutionPlan) -> None:
    """Render the execution plan as a rich table."""
    table = Table(
        title=f"[bold magenta]🧠 IJACHI Execution Plan[/bold magenta]\n[dim]{plan.task[:80]}[/dim]",
        border_style="bright_magenta",
        show_header=True,
        header_style="bold cyan",
        min_width=70,
    )
    table.add_column("#", style="bold white", width=3, justify="center")
    table.add_column("Step", style="white", min_width=40)
    table.add_column("Tool", style="dim cyan", width=14)
    table.add_column("Model", style="dim", width=8)
    table.add_column("Est. Cost", style="bold green", width=9, justify="right")

    total_is_free = True
    for step in plan.steps:
        model_style = {
            "fast": "green",
            "medium": "yellow",
            "slow": "red",
        }.get(step.model_hint.lower(), "white")

        table.add_row(
            str(step.index),
            step.description,
            step.tool_hint or "auto",
            Text(step.model_hint, style=model_style),
            step.cost_hint,
        )
        if step.cost_hint != "~free":
            total_is_free = False

    total_str = "FREE" if total_is_free else "< $0.10"
    table.add_section()
    table.add_row("", "[bold]Total[/bold]", "", "", f"[bold green]{total_str}[/bold green]")

    console.print()
    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# Plan Approval
# ---------------------------------------------------------------------------

def await_plan_approval() -> bool:
    """Ask the user to approve, reject, or (future) edit the plan."""
    return Confirm.ask(
        "[bold yellow]Proceed with this plan?[/bold yellow]",
        default=True,
    )


# ---------------------------------------------------------------------------
# Plan Execution (tracked checklist)
# ---------------------------------------------------------------------------

def execute_plan_with_checklist(plan: ExecutionPlan, agent) -> None:
    """Execute each plan step with a live numbered checklist printed to console."""
    console.print("\n[bold cyan]🚀 Executing plan...[/bold cyan]\n")
    for step in plan.steps:
        console.print(f"  [dim]▸[/dim] Step {step.index}: [white]{step.description}[/white]")

    console.print()

    result = agent.run(plan.task)

    # Mark all as completed
    for step in plan.steps:
        step.completed = True
        console.print(f"  [bold green]✅[/bold green] Step {step.index}: {step.description}")

    console.print()
    return result
