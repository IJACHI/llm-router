"""Interactive prompt input with autocompletion and shortcuts.

Document 6.3:
- Multi-line input (Alt+Enter, Ctrl+J, or \\+Enter for newline; Enter submits)
- / slash command autocomplete
- @ file path autocomplete (attaches file content as context)
- !command shortcut to run a shell command through permissions
- #note shortcut to append note to project memory file
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style


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
    "prompt": "fg:#00e5ff bold",
    "bottom-toolbar": "bg:#0d1117 fg:#4a9eff",
})

_session: PromptSession | None = None


def get_prompt_session(history_file: Path, completer: Completer) -> PromptSession:
    """Retrieve or initialize the persistent PromptSession."""
    global _session
    if _session is None:
        history = FileHistory(str(history_file))
        kb = KeyBindings()

        @kb.add("enter")
        def _handle_enter(event):
            buf = event.current_buffer
            if buf.text.endswith("\\"):
                buf.delete_before_cursor(count=1)
                buf.insert_text("\n")
            else:
                buf.validate_and_handle()

        @kb.add("escape", "enter")
        @kb.add("c-j")
        def _newline(event):
            event.current_buffer.insert_text("\n")

        _session = PromptSession(
            history=history,
            completer=completer,
            complete_while_typing=True,
            auto_suggest=AutoSuggestFromHistory(),
            key_bindings=kb,
            style=_PROMPT_STYLE,
            multiline=False,
        )
    else:
        _session.completer = completer
    return _session


def prompt_user_input(
    commands: dict[str, str],
    toolbar_fn: Callable,
    history_file: Path,
) -> str | None:
    """Read a user message via prompt_toolkit with completion and multiline support."""
    completer = SlashAndFileCompleter(commands)
    session = get_prompt_session(history_file, completer)

    status = toolbar_fn()
    if status:
        from rich.console import Console
        Console().print(status)

    try:
        text = session.prompt([("class:prompt", "> ")])
        return text.strip()
    except KeyboardInterrupt:
        return ""
    except EOFError:
        return "__EXIT__"
