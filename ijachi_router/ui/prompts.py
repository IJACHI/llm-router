"""Interactive prompt input with autocompletion and shortcuts.

Document 6.3:
- Multi-line input (Shift+Enter or \\+Enter for newline; Enter submits)
- / slash command autocomplete
- @ file path autocomplete (attaches file content as context)
- !command shortcut to run a shell command through permissions
- #note shortcut to append note to project memory file
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from prompt_toolkit import Application
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame


class SlashAndFileCompleter(Completer):
    """Provides autocomplete for /commands and @filepaths."""

    def __init__(self, commands: dict[str, str], root_dir: Path | None = None):
        self.commands = commands
        self.root_dir = Path(root_dir or Path.cwd()).resolve()

    def get_completions(self, document: Document, complete_event: CompleteEvent):
        text = document.text_before_cursor

        # 1. Slash commands
        if text.startswith("/"):
            word = text
            for cmd, desc in self.commands.items():
                if cmd.startswith(word):
                    yield Completion(cmd, start_position=-len(word), display_meta=desc)
            return

        # 2. File mentions (@path)
        last_word = text.split()[-1] if text.split() else ""
        if last_word.startswith("@"):
            query = last_word[1:]
            try:
                for p in self.root_dir.rglob(f"*{query}*"):
                    if not any(part.startswith(".") or part in ("node_modules", "venv", ".venv") for part in p.parts):
                        if p.is_file():
                            rel_path = f"@{p.relative_to(self.root_dir)}"
                            yield Completion(rel_path, start_position=-len(last_word))
            except Exception:
                pass


_PROMPT_STYLE = Style.from_dict({
    "frame": "fg:#00e5ff",
    "frame.border": "fg:#00e5ff",
    "frame.label": "fg:#00e5ff bold",
    "": "fg:#ffffff bg:#0d1117",
    "toolbar": "bg:#0d1117 fg:#4a9eff",
})


def prompt_user_input(
    commands: dict[str, str],
    toolbar_fn: Callable,
    history_file: Path,
) -> str | None:
    """Read a user message via prompt_toolkit with completion and multiline support."""
    history = FileHistory(str(history_file))
    completer = SlashAndFileCompleter(commands)
    submitted: list[str] = []
    cancelled: list[bool] = []

    buf = Buffer(
        history=history,
        completer=completer,
        complete_while_typing=True,
        auto_suggest=AutoSuggestFromHistory(),
        multiline=True,
    )

    kb = KeyBindings()

    @kb.add("enter")
    def _submit(event):
        text = buf.text
        # Support \ at end of line for manual multiline
        if text.endswith("\\"):
            buf.delete_before_cursor(count=1)
            buf.insert_text("\n")
            return
        submitted.append(text.strip())
        event.app.exit()

    @kb.add("s-enter")
    def _newline(event):
        buf.insert_text("\n")

    @kb.add("c-c")
    def _interrupt(event):
        cancelled.append(True)
        event.app.exit()

    @kb.add("c-d")
    def _eof(event):
        submitted.append("__EXIT__")
        event.app.exit()

    layout = Layout(
        HSplit([
            Frame(
                Window(
                    BufferControl(buffer=buf),
                    height=2,
                    get_line_prefix=lambda i, wrap_count: "  ",
                ),
                title=" ✍  Type a message (/ for commands, @ for files) ",
                style="class:frame",
            ),
            Window(
                FormattedTextControl(toolbar_fn),
                height=1,
                style="class:toolbar",
            ),
        ])
    )

    app = Application(
        layout=layout,
        key_bindings=kb,
        style=_PROMPT_STYLE,
        full_screen=False,
        mouse_support=False,
    )
    app.run()

    if cancelled:
        return None
    return submitted[0] if submitted else None
