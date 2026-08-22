"""Enhanced Interactive Prompt Engine for ijachi-code.

Wraps prompt_toolkit.PromptSession to provide Claude Code-style terminal UX:

Prompt Features
---------------
- Multi-line input  : Ctrl+J or backslash+Enter for newline; Enter to submit
- @ file autocomplete : typing '@' triggers workspace file-path completion
- / command launcher : typing '/' shows searchable built-in + skill commands
- ! shell mode       : '!<cmd>' runs a shell command inline and shows output
- Large-paste collapse: pastes >10 lines shown as [Pasted text #N +N lines]
- Vim editing mode   : configurable via config.yaml ``vim_mode: true``

Navigation & Recovery
---------------------
- Up/Down arrow      : recall prompt history (scoped by CWD)
- Ctrl+R             : incremental history search
- Ctrl+S             : stash current draft and restore later
- Ctrl+L             : clear/redraw screen
- Ctrl+O             : open transcript viewer (callback hook)
- Ctrl+T             : toggle task checklist (callback hook)
- Double-Esc         : clear draft or open rewind menu (callback hook)
- ?                  : show keybinding help from empty prompt
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable

# prompt_toolkit imports — all guarded; if not installed we fall back to
# a simple input() loop so the app degrades gracefully.
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import Completer, Completion, WordCompleter
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.styles import Style
    _HAS_PROMPT_TOOLKIT = True
except ImportError:
    _HAS_PROMPT_TOOLKIT = False


# ---------------------------------------------------------------------------
# Paste collapse
# ---------------------------------------------------------------------------

_PASTE_COUNTER: list[int] = [0]  # Mutable counter (avoids global keyword)

def _collapse_paste(text: str, threshold_lines: int = 10) -> tuple[str, str | None]:
    """Collapse large pastes into a compact placeholder.

    Args:
        text: The full pasted text.
        threshold_lines: Lines above which to collapse.

    Returns:
        Tuple of (display_text, original_text_or_None).
        If collapsed, display_text is the placeholder and original_text is the full content.
        If not collapsed, display_text == text and original_text is None.
    """
    lines = text.splitlines()
    if len(lines) <= threshold_lines:
        return text, None
    _PASTE_COUNTER[0] += 1
    n = _PASTE_COUNTER[0]
    extra = len(lines) - 3
    placeholder = f"[Pasted text #{n} +{extra} lines]"
    return placeholder, text


# ---------------------------------------------------------------------------
# Workspace file completer
# ---------------------------------------------------------------------------

class WorkspaceCompleter(Completer):
    """Provides '@'-triggered file-path autocompletion and '/'-triggered command completion.

    Args:
        workspace_root: Root directory to scan for files.
        commands: List of known slash-commands.
        skill_names: List of known skill names for '/' completion.
    """

    def __init__(
        self,
        workspace_root: Path,
        commands: list[str] | None = None,
        skill_names: list[str] | None = None,
    ) -> None:
        self.workspace_root = workspace_root
        self.commands = commands or []
        self.skill_names = skill_names or []
        self._file_cache: list[str] = []
        self._cache_valid = False

    def _refresh_file_cache(self) -> None:
        """Scan workspace for files (cached; reset on each prompt cycle)."""
        ignored = {".git", "node_modules", "__pycache__", ".venv", "venv", ".env", "dist", "build"}
        files: list[str] = []
        try:
            for p in self.workspace_root.rglob("*"):
                if p.is_file() and not any(part in ignored for part in p.parts):
                    rel = str(p.relative_to(self.workspace_root))
                    files.append(rel)
                if len(files) >= 500:
                    break
        except Exception:
            pass
        self._file_cache = files
        self._cache_valid = True

    def get_completions(self, document, complete_event):
        """Yield completions for '@' (files) and '/' (commands/skills)."""
        text = document.text_before_cursor

        # '/' command launcher
        slash_match = None
        for i in range(len(text) - 1, -1, -1):
            if text[i] == "/":
                if i == 0 or text[i - 1] in (" ", "\n", "\t"):
                    slash_match = text[i + 1:]
                    break
                break

        if slash_match is not None:
            all_commands = self.commands + [f"skill:{n}" for n in self.skill_names]
            for cmd in all_commands:
                if cmd.startswith(slash_match.lower()):
                    yield Completion(cmd, start_position=-len(slash_match), display=f"/{cmd}")
            return

        # '@' file mention autocomplete
        at_match = None
        for i in range(len(text) - 1, -1, -1):
            if text[i] == "@":
                at_match = text[i + 1:]
                break
            if text[i] in (" ", "\n", "\t"):
                break

        if at_match is not None:
            if not self._cache_valid:
                self._refresh_file_cache()
            query = at_match.lower()
            for f in self._file_cache:
                if query in f.lower():
                    yield Completion(f, start_position=-len(at_match))

    def invalidate_cache(self) -> None:
        """Force re-scan of workspace files on next completion request."""
        self._cache_valid = False


# ---------------------------------------------------------------------------
# Status bar / bottom toolbar
# ---------------------------------------------------------------------------

def _make_toolbar(
    model: str,
    cwd: Path,
    cost_usd: float,
    permission_mode: str,
    context_pct: float,
    git_branch: str,
    history_index: int = 0,
    history_total: int = 0,
    accept_edits_on: bool = False,
    agent_count: int = 0,
    toast_badge: str = "",
) -> Callable[[], HTML]:
    """Return a prompt_toolkit bottom_toolbar callable that renders the status bar.

    Args:
        model: Current model name (e.g. 'claude-3-5-sonnet-20241022').
        cwd: Current working directory.
        cost_usd: Cumulative session cost in USD.
        permission_mode: 'manual', 'accept-edits', 'plan', or 'auto'.
        context_pct: Context window utilization 0.0–1.0.
        git_branch: Current git branch name (empty if not a git repo).
        history_index: Current position in prompt history.
        history_total: Total number of turns so far.
        accept_edits_on: Whether auto-accept edits mode is enabled.
        agent_count: Number of active background agents/tasks.
        toast_badge: Optional transient toast badge markup.

    Returns:
        A callable that prompt_toolkit calls to render the toolbar HTML.
    """
    mode_icons = {
        "manual": "⏸ manual",
        "accept-edits": "✏ accept-edits",
        "plan": "📋 plan",
        "auto": "⏵⏵ auto",
    }
    mode_label = mode_icons.get(permission_mode, permission_mode)
    branch_str = f" ⎇ {git_branch}" if git_branch else ""
    ctx_bar = f" ctx:{context_pct * 100:.0f}%"
    cost_str = f" ${cost_usd:.4f}"
    # Abbreviate CWD
    home = str(Path.home())
    cwd_str = str(cwd).replace(home, "~")
    model_short = model.split("/")[-1][:28]

    history_str = ""
    if history_total > 0:
        history_str = f" — History {history_index}/{history_total} —"

    accept_str = "▶▶ accept edits on" if accept_edits_on else "▶▶ accept edits off"
    agent_str = f" ⇦ {agent_count} agent{'s' if agent_count != 1 else ''}" if agent_count else ""

    def toolbar() -> HTML:
        parts = [
            f"<b>🤖 {model_short}</b>",
            f"  <ansicyan>{cwd_str}</ansicyan>",
            f"<ansigreen>{branch_str}</ansigreen>",
            f"  <ansiblue>{ctx_bar}</ansiblue>",
            f"  <ansiyellow>{cost_str}</ansiyellow>",
        ]
        if history_str:
            parts.append(f"  <ansimagenta>{history_str}</ansimagenta>")
        parts.append(f"  <ansigray>| {mode_label}</ansigray>")
        parts.append(f"  <ansigray>| {accept_str}</ansigray>")
        parts.append(f"  <ansigray>| esc interrupt | ctrl+t tasks | ctrl+o transcript</ansigray>")
        if agent_str:
            parts.append(f"  <ansiyellow>{agent_str}</ansiyellow>")
        if toast_badge:
            parts.append(f"  {toast_badge}")
        return HTML("".join(parts))

    return toolbar


def _get_git_branch(cwd: Path) -> str:
    """Return current git branch name, or empty string if not a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=cwd, timeout=2,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Keybinding help
# ---------------------------------------------------------------------------

_HELP_TEXT = r"""
╔══════════════════════════════════════════════════════════════════╗
║           ijachi-code Keyboard Shortcuts                         ║
╠══════════════════════════════════════════════════════════════════╣
║  Enter              Submit prompt                                  ║
║  Ctrl+J             New line (multi-line input)                  ║
║  \ + Enter         New line (alternate)                         ║
║  Up / Down          Recall prompt history                        ║
║  Ctrl+R             Search prompt history                          ║
║  Ctrl+S             Stash/restore current draft                    ║
║  Ctrl+L             Clear / redraw screen                          ║
║  Ctrl+O             Open transcript viewer                         ║
║  Ctrl+T             Toggle live task checklist                     ║
║  Shift+Tab          Cycle permission mode                            ║
║  Ctrl+B             Background current Bash command              ║
║  Ctrl+C / Esc       Cancel / interrupt                             ║
║  Double-Esc         Clear draft or open rewind menu                ║
║  @<path>            Insert file path autocomplete                  ║
║  /<command>         Open slash-command launcher                    ║
║  /mode              Cycle permission mode                            ║
║  /init              Generate CLAUDE.md context file                ║
║  !<cmd>             Run shell command inline                      ║
║  ?                  Show this help (from empty prompt)             ║
║  exit / quit        End session                                    ║
╚══════════════════════════════════════════════════════════════════╝
"""

# ---------------------------------------------------------------------------
# Draft stash
# ---------------------------------------------------------------------------

_stash: list[str] = []  # Simple one-slot stash


# ---------------------------------------------------------------------------
# PromptEngine
# ---------------------------------------------------------------------------

class PromptEngine:
    """Enhanced prompt session wrapping prompt_toolkit for ijachi-code.

    Provides all Claude Code-style prompt features: multi-line input, file
    autocomplete, slash commands, shell mode, paste collapse, history search,
    draft stash, and keybindings.

    Falls back to a plain ``input()`` loop if prompt_toolkit is unavailable.

    Args:
        workspace_root: Workspace root used for file autocomplete and history scoping.
        model: Active model name displayed in the status bar.
        vim_mode: If True, enable Vi editing mode.
        permission_mode: Initial autonomy mode label.
        on_transcript_open: Callback invoked when Ctrl+O is pressed.
        on_checklist_toggle: Callback invoked when Ctrl+T is pressed.
        on_rewind: Callback invoked on double-Esc from empty prompt.
        skill_names: List of skill names for '/' autocomplete.
    """

    #: Built-in slash commands offered in the '/' launcher
    BUILTIN_COMMANDS: list[str] = [
        "model", "priority", "mode", "theme", "config", "tasks", "skills", "help",
        "memory", "stats", "init", "exit", "quit",
    ]

    def __init__(
        self,
        workspace_root: Path | str | None = None,
        model: str = "unknown",
        vim_mode: bool = False,
        permission_mode: str = "manual",
        on_transcript_open: Callable[[], None] | None = None,
        on_checklist_toggle: Callable[[], None] | None = None,
        on_rewind: Callable[[], None] | None = None,
        skill_names: list[str] | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root or Path.cwd()).resolve()
        self.model = model
        self.vim_mode = vim_mode
        self.permission_mode = permission_mode
        self.on_transcript_open = on_transcript_open
        self.on_checklist_toggle = on_checklist_toggle
        self.on_rewind = on_rewind
        self.skill_names = skill_names or []

        # Session state
        self._session_cost: float = 0.0
        self._context_pct: float = 0.0
        self._paste_store: dict[int, str] = {}  # paste_index → full content
        self._esc_count: list[int] = [0]  # Double-Esc tracker
        self._history_index: int = 0
        self._history_total: int = 0
        self._agent_count: int = 0
        self._toast_badge: str = ""
        self._accept_edits_on: bool = False

        # History file scoped by CWD (hex suffix avoids path separator issues)
        hist_dir = Path.home() / ".ijachi-llmr" / "prompt_history"
        hist_dir.mkdir(parents=True, exist_ok=True)
        cwd_key = str(self.workspace_root).replace("/", "_").replace("\\", "_")
        hist_file = hist_dir / f"{cwd_key}.txt"

        self._completer = WorkspaceCompleter(
            workspace_root=self.workspace_root,
            commands=self.BUILTIN_COMMANDS,
            skill_names=self.skill_names,
        )

        if _HAS_PROMPT_TOOLKIT:
            self._session = PromptSession(
                history=FileHistory(str(hist_file)),
                completer=self._completer,
                auto_suggest=AutoSuggestFromHistory(),
                vi_mode=self.vim_mode,
                multiline=Condition(lambda: False),  # Default single-line; Ctrl+J toggles
                key_bindings=self._build_keybindings(),
                style=self._build_style(),
            )
        else:
            self._session = None

    # ------------------------------------------------------------------
    # Key bindings
    # ------------------------------------------------------------------

    def _build_keybindings(self):
        """Build and return the custom key binding set."""
        if not _HAS_PROMPT_TOOLKIT:
            return None

        kb = KeyBindings()

        @kb.add("c-j")  # Ctrl+J → insert newline
        def _newline(event):
            event.current_buffer.insert_text("\n")

        @kb.add("\\", "enter")  # backslash + Enter → insert newline
        def _backslash_newline(event):
            buf = event.current_buffer
            if buf.text.endswith("\\"):
                buf.delete_before_cursor(1)
            buf.insert_text("\n")

        @kb.add("c-s")  # Ctrl+S → stash / restore draft
        def _stash(event):
            buf = event.current_buffer
            if buf.text.strip():
                _stash.clear()  # type: ignore[attr-defined]
                _stash.append(buf.text)
                buf.set_document(type(buf.document)("", 0))
                event.app.output.write("\n[Draft stashed. Press Ctrl+S again to restore.]\n")
            elif _stash:
                buf.insert_text(_stash.pop())

        @kb.add("c-l")  # Ctrl+L → clear screen
        def _clear(event):
            event.app.renderer.clear()

        @kb.add("c-o")  # Ctrl+O → transcript viewer
        def _open_transcript(event):
            if self.on_transcript_open:
                self.on_transcript_open()

        @kb.add("c-t")  # Ctrl+T → task checklist toggle
        def _toggle_checklist(event):
            if self.on_checklist_toggle:
                self.on_checklist_toggle()

        @kb.add("escape")  # Double-Esc → rewind menu or clear
        def _esc_handler(event):
            self._esc_count[0] += 1
            buf = event.current_buffer
            if self._esc_count[0] >= 2:
                self._esc_count[0] = 0
                if buf.text.strip():
                    buf.set_document(type(buf.document)("", 0))
                elif self.on_rewind:
                    self.on_rewind()
            else:
                # Single Esc in non-vi mode: fall through
                pass

        return kb

    # ------------------------------------------------------------------
    # Style
    # ------------------------------------------------------------------

    def _build_style(self):
        """Build and return the prompt_toolkit Style object."""
        if not _HAS_PROMPT_TOOLKIT:
            return None
        return Style.from_dict({
            "prompt":        "ansibrightblue bold",
            "completion-menu.completion": "bg:ansiblue ansiwhite",
            "completion-menu.completion.current": "bg:ansicyan ansiblack bold",
            "auto-suggestion": "ansibrightblack italic",
            "bottom-toolbar": "bg:ansiblack ansiwhite",
        })

    # ------------------------------------------------------------------
    # Shell mode
    # ------------------------------------------------------------------

    def _handle_shell_mode(self, text: str) -> tuple[bool, str]:
        """If *text* starts with '!', run it as a shell command and return output.

        Args:
            text: Raw prompt text (may or may not start with '!').

        Returns:
            Tuple of (was_shell_command, output_string).
        """
        stripped = text.strip()
        if not stripped.startswith("!"):
            return False, text
        cmd = stripped[1:].strip()
        if not cmd:
            return True, ""
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=30, cwd=self.workspace_root,
            )
            out = result.stdout.strip()
            err = result.stderr.strip()
            parts = [f"$ {cmd}"]
            if out:
                parts.append(out)
            if err:
                parts.append(f"[stderr] {err}")
            return True, "\n".join(parts)
        except subprocess.TimeoutExpired:
            return True, f"$ {cmd}\n[timed out after 30s]"
        except Exception as exc:
            return True, f"$ {cmd}\n[error: {exc}]"

    # ------------------------------------------------------------------
    # Main prompt method
    # ------------------------------------------------------------------

    def prompt(
        self,
        prompt_text: str = "ijachi-code> ",
        model: str | None = None,
        cost_usd: float | None = None,
        context_pct: float | None = None,
        history_index: int | None = None,
        history_total: int | None = None,
        agent_count: int | None = None,
        toast_badge: str | None = None,
        accept_edits_on: bool | None = None,
    ) -> str | None:
        """Show the prompt and return the user's input.

        Handles '?' help, '!' shell mode, paste collapse, and multiline input.
        Invalidates file autocomplete cache before each prompt.

        Args:
            prompt_text: The prompt string displayed to the user.
            model: Override the model name in the status bar.
            cost_usd: Override cumulative cost in the status bar.
            context_pct: Override context utilization (0.0–1.0) in the status bar.
            history_index: Current position in conversation history.
            history_total: Total conversation turns so far.
            agent_count: Number of active background agents/tasks.
            toast_badge: Transient toast badge markup for the status bar.
            accept_edits_on: Whether auto-accept edits mode is enabled.

        Returns:
            User input string, or None on Ctrl+C / EOF.
        """
        if model is not None:
            self.model = model
        if cost_usd is not None:
            self._session_cost = cost_usd
        if context_pct is not None:
            self._context_pct = context_pct
        if history_index is not None:
            self._history_index = history_index
        if history_total is not None:
            self._history_total = history_total
        if agent_count is not None:
            self._agent_count = agent_count
        if toast_badge is not None:
            self._toast_badge = toast_badge
        if accept_edits_on is not None:
            self._accept_edits_on = accept_edits_on

        self._completer.invalidate_cache()
        git_branch = _get_git_branch(self.workspace_root)

        if not _HAS_PROMPT_TOOLKIT or self._session is None:
            # Graceful fallback
            try:
                return input(prompt_text)
            except (KeyboardInterrupt, EOFError):
                return None

        toolbar = _make_toolbar(
            model=self.model,
            cwd=self.workspace_root,
            cost_usd=self._session_cost,
            permission_mode=self.permission_mode,
            context_pct=self._context_pct,
            git_branch=git_branch,
            history_index=self._history_index,
            history_total=self._history_total,
            accept_edits_on=self._accept_edits_on,
            agent_count=self._agent_count,
            toast_badge=self._toast_badge,
        )

        try:
            raw = self._session.prompt(
                HTML(f"<b><ansicyan>{prompt_text}</ansicyan></b>"),
                bottom_toolbar=toolbar,
                key_bindings=self._build_keybindings(),
            )
        except KeyboardInterrupt:
            return None
        except EOFError:
            return None

        if raw is None:
            return None

        # '?' from empty prompt → show help
        if raw.strip() == "?":
            print(_HELP_TEXT)
            return self.prompt(
                prompt_text,
                model,
                cost_usd,
                context_pct,
                history_index=history_index,
                history_total=history_total,
                agent_count=agent_count,
                toast_badge=toast_badge,
                accept_edits_on=accept_edits_on,
            )

        # '!' shell mode
        is_shell, shell_output = self._handle_shell_mode(raw)
        if is_shell:
            if shell_output:
                print(shell_output)
            return None  # Shell command handled; don't route to LLM

        # Paste collapse — store full content, return placeholder to caller
        lines = raw.splitlines()
        if len(lines) > 10:
            placeholder, original = _collapse_paste(raw)
            if original:
                idx = _PASTE_COUNTER[0]
                self._paste_store[idx] = original
                return placeholder  # Caller sees placeholder; full text is in paste_store

        return raw

    def resolve_pastes(self, text: str) -> str:
        """Expand any paste placeholders in *text* back to the full content.

        Args:
            text: Prompt text potentially containing '[Pasted text #N ...]' placeholders.

        Returns:
            Text with all paste placeholders replaced by their full content.
        """
        import re
        def replacer(m: re.Match) -> str:
            idx = int(m.group(1))
            return self._paste_store.get(idx, m.group(0))
        return re.sub(r"\[Pasted text #(\d+)[^\]]*\]", replacer, text)

    def set_history_index(self, index: int, total: int) -> None:
        """Update the history position shown in the status bar."""
        self._history_index = index
        self._history_total = total

    def set_agent_count(self, count: int) -> None:
        """Update the live background-agent count in the status bar."""
        self._agent_count = count

    def set_toast_badge(self, badge: str) -> None:
        """Set a transient toast badge markup for the status bar."""
        self._toast_badge = badge

    def set_accept_edits_on(self, enabled: bool) -> None:
        """Toggle the accept-edits indicator in the status bar."""
        self._accept_edits_on = enabled

    def update_cost(self, cost_usd: float) -> None:
        """Update the cumulative session cost shown in the status bar.

        Args:
            cost_usd: Amount to add to the running session total.
        """
        self._session_cost += cost_usd

    def set_permission_mode(self, mode: str) -> None:
        """Update the permission mode label in the status bar.

        Args:
            mode: One of 'manual', 'accept-edits', 'plan', 'auto'.
        """
        self.permission_mode = mode
