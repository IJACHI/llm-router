"""Conversation Transcript Viewer for ijachi-code.

Records every turn in the interactive chat session (user messages, assistant
responses, tool calls, tool outputs, and metadata) and provides a Ctrl+O
full-screen paged viewer with export options.

Features
--------
- Timestamped, model-tagged turn records
- Rich paged viewer via 'less' pager or inline Rich output
- Export to raw terminal scrollback (plain print)
- Open full transcript in ``$EDITOR`` / ``$VISUAL``
- Condensed vs. expanded tool-call display
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    """A single tool invocation recorded during an agent step."""

    tool_name: str
    """Name of the tool that was called (e.g. 'read_file')."""
    args: dict[str, Any]
    """Arguments passed to the tool."""
    output: str
    """Tool output returned (truncated to 2000 chars for storage)."""
    cost_usd: float = 0.0
    """Cost associated with the LLM call that triggered this tool."""


@dataclass
class TranscriptTurn:
    """One turn in the conversation transcript."""

    role: str
    """Either 'user' or 'assistant'."""
    content: str
    """The message content (user prompt or assistant response)."""
    model: str = ""
    """Model used for assistant turns."""
    provider: str = ""
    """Provider used for assistant turns."""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    """ISO 8601 timestamp."""
    cost_usd: float = 0.0
    """Cost of this turn in USD."""
    input_tokens: int = 0
    """Input token count."""
    output_tokens: int = 0
    """Output token count."""
    tool_calls: list[ToolCall] = field(default_factory=list)
    """Tool calls made during this assistant turn."""
    telemetry_summary: str = ""
    """Claude Code-style telemetry roll-up for this turn (e.g. 'read 2 files, ran 1 command')."""


# ---------------------------------------------------------------------------
# Transcript store
# ---------------------------------------------------------------------------

class Transcript:
    """Stores and manages the full conversation transcript for a session.

    Usage
    -----
    ::

        t = Transcript()
        t.add_user_turn("Write a hello world in Python")
        t.add_assistant_turn("Here it is:", model="gpt-4o", cost_usd=0.001)
        t.view()         # Rich paged viewer
        t.export_text()  # Plain print to scrollback
    """

    def __init__(self, session_id: str = "default") -> None:
        """Initialise a new transcript.

        Args:
            session_id: Identifier for this session (used in export filenames).
        """
        self.session_id = session_id
        self.turns: list[TranscriptTurn] = []
        self._total_cost: float = 0.0

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def add_user_turn(self, content: str) -> None:
        """Record a user message.

        Args:
            content: The user's raw prompt text.
        """
        self.turns.append(TranscriptTurn(role="user", content=content))
    def add_assistant_turn(
        self,
        content: str,
        model: str = "",
        provider: str = "",
        cost_usd: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        tool_calls: list[ToolCall] | None = None,
        telemetry_summary: str = "",
    ) -> None:
        """Record an assistant response.

        Args:
            content: The assistant's response text.
            model: Model name used for this response.
            provider: Provider used for this response.
            cost_usd: Cost of this response in USD.
            input_tokens: Input token count.
            output_tokens: Output token count.
            tool_calls: List of tool calls made during this response.
            telemetry_summary: Telemetry roll-up string for this turn.
        """
        self._total_cost += cost_usd
        self.turns.append(TranscriptTurn(
            role="assistant",
            content=content,
            model=model,
            provider=provider,
            cost_usd=cost_usd,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_calls=tool_calls or [],
            telemetry_summary=telemetry_summary,
        ))

    def add_tool_call(self, tool_name: str, args: dict, output: str, cost_usd: float = 0.0) -> None:
        """Append a tool call to the most recent assistant turn.

        Args:
            tool_name: Name of the tool.
            args: Tool arguments dictionary.
            output: Tool output string.
            cost_usd: Associated cost.
        """
        tc = ToolCall(tool_name=tool_name, args=args, output=output[:2000], cost_usd=cost_usd)
        if self.turns and self.turns[-1].role == "assistant":
            self.turns[-1].tool_calls.append(tc)

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def _format_turn_rich(self, turn: TranscriptTurn, expanded: bool = False) -> str:
        """Format a single turn as Rich markup.

        Args:
            turn: The turn to format.
            expanded: If True, show full tool call details.

        Returns:
            Rich markup string.
        """
        ts = turn.timestamp[:19].replace("T", " ")
        if turn.role == "user":
            return (
                f"\n[bold bright_blue]── you[/bold bright_blue] "
                f"[dim]{ts}[/dim]\n"
                f"{turn.content}\n"
            )

        model_tag = f"[dim cyan]{turn.model}[/dim cyan] " if turn.model else ""
        cost_tag = f"[dim]${turn.cost_usd:.4f}[/dim] " if turn.cost_usd else ""
        telemetry_tag = f"[dim]({turn.telemetry_summary})[/dim]\n" if turn.telemetry_summary else ""
        header = (
            f"\n[bold bright_green]── ijachi[/bold bright_green] "
            f"{model_tag}{cost_tag}[dim]{ts}[/dim]\n"
            f"{telemetry_tag}"
        )
        body = turn.content + "\n"

        if not turn.tool_calls:
            return header + body

        tool_lines = []
        for tc in turn.tool_calls:
            if expanded:
                args_str = json.dumps(tc.args, indent=2)
                tool_lines.append(
                    f"[bold yellow]  ⚙ tool: {tc.tool_name}[/bold yellow]\n"
                    f"[dim]  args: {args_str}[/dim]\n"
                    f"[dim]  output: {tc.output[:300]}{'...' if len(tc.output) > 300 else ''}[/dim]"
                )
            else:
                # Condensed single line
                tool_lines.append(f"[dim yellow]  ⚙ {tc.tool_name}({list(tc.args.keys())})[/dim yellow]")

        return header + body + "\n".join(tool_lines) + "\n"

    # ------------------------------------------------------------------
    # Viewer
    # ------------------------------------------------------------------

    def view(self, expanded: bool = False) -> None:
        """Open the full-screen paged transcript viewer.

        Uses the system 'less' pager if available, otherwise Rich inline rendering.

        Args:
            expanded: If True, show full tool call args and output.
        """
        try:
            from rich.console import Console
            from rich.rule import Rule
            from rich import box
        except ImportError:
            self.export_text(expanded=expanded)
            return

        console = Console(record=True)
        console.print(
            f"\n[bold cyan]ijachi-code Transcript Viewer[/bold cyan]  "
            f"[dim]session={self.session_id}  "
            f"turns={len(self.turns)}  "
            f"total_cost=${self._total_cost:.4f}[/dim]"
        )
        console.print(Rule(style="bright_blue"))

        if not self.turns:
            console.print("[dim]No turns recorded yet.[/dim]\n")
            return

        for i, turn in enumerate(self.turns):
            console.print(self._format_turn_rich(turn, expanded=expanded))

        console.print(Rule(style="bright_blue"))
        console.print(
            f"[dim]Use Ctrl+O to re-open · "
            f"[bold]e[/bold] to open in $EDITOR · "
            f"[bold]x[/bold] to export to scrollback · "
            f"[bold]q[/bold] to close[/dim]\n"
        )

        # Interactive viewer post-actions
        try:
            choice = input("Transcript action [e=editor / x=export / q=quit]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return

        if choice == "e":
            self.open_in_editor()
        elif choice == "x":
            self.export_text(expanded=True)

    def export_text(self, expanded: bool = False) -> None:
        """Print the full transcript as plain text to stdout (terminal scrollback).

        Args:
            expanded: If True, include full tool call args and output.
        """
        print(f"\n{'='*70}")
        print(f"ijachi-code Transcript  session={self.session_id}  turns={len(self.turns)}")
        print(f"Total cost: ${self._total_cost:.4f}")
        print("=" * 70)
        for turn in self.turns:
            ts = turn.timestamp[:19].replace("T", " ")
            if turn.role == "user":
                print(f"\nyou: [{ts}]")
                print(turn.content)
            else:
                print(f"\nijachi: [{ts}] model={turn.model} cost=${turn.cost_usd:.4f}")
                print(turn.content)
                for tc in turn.tool_calls:
                    if expanded:
                        print(f"  tool: {tc.tool_name}")
                        print(f"  args: {json.dumps(tc.args)}")
                        print(f"  output: {tc.output[:500]}")
                    else:
                        print(f"  tool: {tc.tool_name}({list(tc.args.keys())})")
        print("\n" + "=" * 70 + "\n")

    def open_in_editor(self) -> None:
        """Open the transcript as a JSON file in ``$EDITOR`` or ``$VISUAL``."""
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
        data = {
            "session_id": self.session_id,
            "total_cost_usd": self._total_cost,
            "turn_count": len(self.turns),
            "turns": [asdict(t) for t in self.turns],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp:
            json.dump(data, tmp, indent=2, default=str)
            tmp_path = tmp.name
        try:
            subprocess.run([editor, tmp_path])
        except Exception as exc:
            print(f"[error opening editor '{editor}': {exc}]")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def save(self, path: Path | str | None = None) -> Path:
        """Persist the transcript to a JSON file.

        Args:
            path: Destination path. Defaults to ``~/.ijachi-llmr/transcripts/<session_id>.json``.

        Returns:
            The path the transcript was saved to.
        """
        if path is None:
            dest_dir = Path.home() / ".ijachi-llmr" / "transcripts"
            dest_dir.mkdir(parents=True, exist_ok=True)
            path = dest_dir / f"{self.session_id}.json"
        path = Path(path)
        data = {
            "session_id": self.session_id,
            "total_cost_usd": self._total_cost,
            "turns": [asdict(t) for t in self.turns],
        }
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        return path

    @property
    def total_cost(self) -> float:
        """Cumulative cost for this session in USD."""
        return self._total_cost

    def __len__(self) -> int:
        """Return the number of turns in the transcript."""
        return len(self.turns)
