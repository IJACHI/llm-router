"""ijachi-code — Claude Code-style agentic terminal coding assistant CLI.

Document 2.1, 2.7, Document 6:
- Interactive REPL: ijachi-code [chat]
- Prompt seed: ijachi-code "prompt"
- Non-interactive Print mode: ijachi-code -p "prompt" (reads stdin when piped)
- Autonomous agent: ijachi-code agent "task"
- Test repair loop: ijachi-code fix --command "pytest"
- Multi-model consensus: ijachi-code consensus "task"
- Index symbols: ijachi-code index
- Commit generator: ijachi-code commit
- Session resume: ijachi-code --continue, ijachi-code --resume [id]
- Doctor diagnostics: ijachi-code doctor
"""

from __future__ import annotations

import json
import os
import select
import sys
from pathlib import Path

import click

from ijachi_router.agent.limits import LoopLimits
from ijachi_router.agent.loop import AgentSessionLoop
from ijachi_router.doctor import print_doctor_report
from ijachi_router.session.store import SessionStore, find_most_recent_session
from ijachi_router.ui.render import render_markdown, render_turn_footer
from ijachi_router.ui.repl import InteractiveREPL


OPTS_WITH_VALUE = {
    "--resume",
    "--mode",
    "--priority",
    "--autonomy",
    "--max-cost",
    "--budget",
    "--model",
    "--allow-providers",
    "--deny-providers",
    "--permission-mode",
    "--cwd",
    "--max-turns",
    "--timeout",
    "--prompt",
}


class CodeCLI(click.Group):
    """Custom Click Group to support subcommands and bare prompts cleanly."""

    def parse_args(self, ctx, args):
        if not args:
            return super().parse_args(ctx, args)

        i = 0
        non_opts = []
        opts = []
        while i < len(args):
            arg = args[i]
            if arg == "--":
                non_opts.extend(args[i + 1:])
                break
            if arg in OPTS_WITH_VALUE:
                opts.append(arg)
                if i + 1 < len(args):
                    opts.append(args[i + 1])
                    i += 2
                else:
                    i += 1
                continue
            if any(arg.startswith(f"{opt}=") for opt in OPTS_WITH_VALUE):
                opts.append(arg)
                i += 1
                continue
            if arg.startswith("-"):
                opts.append(arg)
                i += 1
                continue
            non_opts.append(arg)
            i += 1

        if non_opts:
            if non_opts[0] in self.commands:
                # Subcommand invoked directly
                return super().parse_args(ctx, args)
            else:
                # Bare prompt provided: combine non-options into --prompt
                prompt = " ".join(non_opts)
                return super().parse_args(ctx, [*opts, "--prompt", prompt])

        return super().parse_args(ctx, args)


@click.group(cls=CodeCLI, invoke_without_command=True)
@click.option("-p", "--print", "print_mode", is_flag=True, help="Non-interactive print mode: output answer and exit.")
@click.option("--prompt", default=None, help="Initial prompt to seed conversation or run.")
@click.option("--continue", "continue_flag", is_flag=True, help="Resume the most recent session for this workspace.")
@click.option("--resume", "resume_id", default=None, help="Resume session by ID.")
@click.option("--mode", "--priority", "priority", type=click.Choice(["efficient", "cheapest", "best", "best-fit", "cost", "speed", "quality", "balanced"]), default=None, help="Routing preference mode (default: efficient).")
@click.option("--max-cost", type=float, default=None, help="Max cost USD per turn.")
@click.option("--budget", type=float, default=None, help="Max budget USD for session.")
@click.option("--model", "pinned_model", default=None, help="Pin a specific model.")
@click.option("--allow-providers", default=None, help="Comma-separated allowed providers.")
@click.option("--deny-providers", default=None, help="Comma-separated denied providers.")
@click.option("--autonomy", "--permission-mode", "permission_mode", type=click.Choice(["auto", "semi-auto", "manual", "ask", "accept-edits", "plan", "auto-safe"]), default="manual", help="Execution autonomy mode (auto, semi-auto, manual).")
@click.option("--local-only", is_flag=True, help="Strictly allow only local models (Ollama/custom).")
@click.option("--sandbox/--no-sandbox", "sandbox", default=None, help="Run shell commands in an OS sandbox (default: on in auto mode).")
@click.option("--cwd", default=None, help="Target workspace path.")
@click.option("--worktree", "worktree", default=None, help="Work on an isolated git worktree + branch ijachi/<NAME>.")
@click.option("--json", "json_output", is_flag=True, help="Machine-readable JSON output.")
@click.option("--no-color", is_flag=True, help="Disable ANSI color codes.")
@click.option("--image", "images", multiple=True, type=click.Path(exists=True, dir_okay=False), help="Attach an image (repeatable).")
@click.option("--max-turns", type=int, default=50, help="Max tool iterations per turn.")
@click.option("--timeout", type=int, default=300, help="Command timeout in seconds.")
@click.pass_context
def main(
    ctx: click.Context,
    print_mode: bool,
    prompt: str | None,
    continue_flag: bool,
    resume_id: str | None,
    priority: str | None,
    max_cost: float | None,
    budget: float | None,
    pinned_model: str | None,
    allow_providers: str | None,
    deny_providers: str | None,
    permission_mode: str,
    local_only: bool,
    sandbox: bool | None,
    cwd: str | None,
    worktree: str | None,
    json_output: bool,
    no_color: bool,
    images: tuple[str, ...],
    max_turns: int,
    timeout: int,
):
    """ijachi-code: The multi-model agentic pair programmer for your terminal."""
    if no_color:
        os.environ["NO_COLOR"] = "1"

    if ctx.invoked_subcommand is not None:
        return

    # No subcommand -> open interactive session or handle piped stdin
    workspace_path = Path(cwd).resolve() if cwd else Path.cwd()
    if worktree:
        from ijachi_router.gitflow import GitError, create_worktree
        try:
            workspace_path = create_worktree(workspace_path, worktree)
        except GitError as e:
            click.echo(f"Error: could not create worktree: {e}", err=True)
            sys.exit(3)
        click.echo(f"🌿 Working in {workspace_path} (branch ijachi/{workspace_path.name})", err=True)

    piped_stdin = ""
    if not sys.stdin.isatty():
        try:
            r, _, _ = select.select([sys.stdin], [], [], 0.0)
            if r:
                piped_stdin = sys.stdin.read().strip()
        except Exception:
            pass

    session_id = resume_id
    if continue_flag and not session_id:
        session_id = find_most_recent_session(workspace_path)

    store = SessionStore(session_id=session_id, workspace_dir=workspace_path)
    if priority:
        store.state.priority = priority
    if budget is not None:
        store.state.budget_usd = budget
    if pinned_model:
        store.state.pinned_model = pinned_model

    allow_set = set(p.strip() for p in allow_providers.split(",")) if allow_providers else None
    deny_set = set(p.strip() for p in deny_providers.split(",")) if deny_providers else None

    limits = LoopLimits(
        max_turns=max_turns,
        max_cost_per_turn_usd=max_cost,
        session_budget_usd=budget,
        timeout_sec=timeout,
    )
    loop_kwargs = {
        "limits": limits,
        "local_only": local_only,
        "allow_providers": allow_set,
        "deny_providers": deny_set,
        "sandbox": sandbox,
    }

    input_text = prompt or piped_stdin
    if prompt and piped_stdin:
        input_text = f"{prompt}\n\n{piped_stdin}"

    if print_mode or (not sys.stdin.isatty() and input_text):
        if not input_text:
            click.echo("Error: No prompt or stdin provided for print mode.", err=True)
            sys.exit(1)

        # Headless runs can never prompt: anything not explicitly safe is denied (SEC-08).
        p_mode = "auto-safe" if not sys.stdin.isatty() else permission_mode
        loop = AgentSessionLoop(store=store, permission_mode=p_mode, **loop_kwargs)
        try:
            # Keep stdout for the answer only (scriptable / --json); progress UI goes to stderr.
            import contextlib
            with contextlib.redirect_stdout(sys.stderr):
                res = loop.execute_turn(input_text, images=list(images) or None)
            if json_output:
                out = {
                    "text": res.text,
                    "model": res.model_used,
                    "provider": res.provider_used,
                    "cost_usd": res.cost_usd,
                    "latency_sec": res.latency_sec,
                    "tokens": {"in": res.input_tokens, "out": res.output_tokens},
                    "completed": res.completed,
                    "limit_hit": res.limit_hit,
                    "denied_actions": res.denied_actions,
                    "session_id": store.session_id,
                }
                click.echo(json.dumps(out, indent=2))
            else:
                click.echo(res.text)
            # Exit codes: 0 ok, 1 stopped by a limit, 5 an action needed approval it could not get.
            if res.denied_actions and loop.permissions.mode == "auto-safe":
                sys.exit(5)
            sys.exit(0 if res.completed else 1)
        except PermissionError:
            sys.exit(5)
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(3)

    # Interactive REPL
    repl = InteractiveREPL(
        store=store,
        priority=priority or "balanced",
        budget_usd=budget,
        pinned_model=pinned_model,
        permission_mode=permission_mode,
        loop_kwargs=loop_kwargs,
    )
    if input_text:
        res = repl.loop.execute_turn(input_text, images=list(images) or None)
        if not res.streamed:
            render_markdown(res.text)
        render_turn_footer(
            model=f"{res.provider_used}/{res.model_used}",
            in_tokens=res.input_tokens,
            out_tokens=res.output_tokens,
            cost_usd=res.cost_usd,
            latency_sec=res.latency_sec,
        )
    repl.start()


@main.command(name="chat")
@click.option("--prompt", "-m", default=None, help="Initial prompt to seed conversation.")
@click.option("--priority", type=click.Choice(["cost", "speed", "quality", "balanced"]), default="balanced")
@click.option("--budget", type=float, default=None)
@click.option("--permission-mode", type=click.Choice(["ask", "accept-edits", "plan", "auto-safe"]), default="ask")
def chat_cmd(prompt, priority, budget, permission_mode):
    """Start an interactive session in the current directory."""
    store = SessionStore(workspace_dir=Path.cwd())
    repl = InteractiveREPL(store=store, priority=priority, budget_usd=budget, permission_mode=permission_mode)
    if prompt:
        res = repl.loop.execute_turn(prompt)
        if not res.streamed:
            render_markdown(res.text)
        render_turn_footer(
            model=f"{res.provider_used}/{res.model_used}",
            in_tokens=res.input_tokens,
            out_tokens=res.output_tokens,
            cost_usd=res.cost_usd,
            latency_sec=res.latency_sec,
        )
    repl.start()


@main.command(name="agent")
@click.argument("task")
@click.option("--priority", type=click.Choice(["cost", "speed", "quality", "balanced"]), default="balanced")
@click.option("--max-steps", type=int, default=25)
def agent_cmd(task, priority, max_steps):
    """Run an autonomous multi-step coding task."""
    store = SessionStore(workspace_dir=Path.cwd())
    store.state.priority = priority
    limits = LoopLimits(max_turns=max_steps)
    loop = AgentSessionLoop(store=store, limits=limits)
    res = loop.execute_turn(task)
    click.echo(res.text)
    sys.exit(0 if res.completed else 1)


@main.command(name="fix")
@click.option("--command", "-c", default="pytest", help="Test command to run and repair.")
@click.option("--max-retries", "-r", default=5, type=int, help="Maximum repair attempts.")
def fix_cmd(command, max_retries):
    """Automated test-repair loop (Doc 2.6)."""
    from ijachi_router.agent.sandbox import WorkspaceSandbox

    sandbox = WorkspaceSandbox()
    store = SessionStore(workspace_dir=Path.cwd())
    loop = AgentSessionLoop(store=store, permission_mode="accept-edits")

    click.echo(f"🧪 Running automated test-repair loop for '{command}' (max {max_retries} attempts)...")
    for attempt in range(1, max_retries + 2):
        code, stdout, stderr = sandbox.run_sandboxed_command(command)
        if code == 0:
            if attempt == 1:
                click.echo(click.style("✅ Tests already pass — nothing to repair.", fg="green"))
            else:
                click.echo(click.style(f"✅ Tests pass after {attempt - 1} repair attempt(s)!", fg="green"))
            return
        if attempt > max_retries:
            break

        click.echo(click.style(f"❌ Attempt {attempt} failed (code {code}). Diagnosing and proposing fix...", fg="yellow"))
        prompt = (
            f"Test command '{command}' failed with exit code {code}.\n"
            f"Output (last 12000 chars):\n{(stdout + chr(10) + stderr)[-12000:]}\n"
            f"Analyze the error, inspect workspace files, and apply necessary edits to fix the tests."
        )
        res = loop.execute_turn(prompt)
        click.echo(res.text)

    click.echo(click.style(f"❌ Could not repair tests after {max_retries} attempts.", fg="red"))
    sys.exit(1)


@main.command(name="consensus")
@click.argument("task")
@click.option("--priority", type=click.Choice(["cost", "speed", "quality", "balanced"]), default="quality")
def consensus_cmd(task, priority):
    """Two-model peer review and synthesis (Doc 2.6)."""
    from ijachi_router.consensus import consensus_route
    click.echo("⚖️ Executing two-model consensus review...")
    res = consensus_route(prompt=task, priority=priority)
    click.echo(res.final_text)


@main.command(name="index")
def index_cmd():
    """Build or update workspace symbol index (Doc 2.6)."""
    from ijachi_router.indexer import WorkspaceIndexer
    indexer = WorkspaceIndexer()
    symbols = indexer.index_workspace()
    click.echo(click.style(f"✓ Indexed {len(symbols)} workspace symbols in .ijachi/symbols.json", fg="green"))


@main.command(name="commit")
@click.option("--message", "-m", default=None, help="Commit message override.")
def commit_cmd(message):
    """Generate conventional commit message and commit staged changes (Doc 2.6)."""
    from ijachi_router.agent.sandbox import WorkspaceSandbox
    from ijachi_router.core import route

    import shlex

    sandbox = WorkspaceSandbox()
    code, stdout, _ = sandbox.run_sandboxed_command("git diff --staged")
    if not stdout.strip():
        _, unstaged, _ = sandbox.run_sandboxed_command("git diff")
        if unstaged.strip() and click.confirm("Nothing is staged. Stage all tracked changes (git add -u)?", default=False):
            sandbox.run_sandboxed_command("git add -u")
            _, stdout, _ = sandbox.run_sandboxed_command("git diff --staged")
        else:
            click.echo("No staged changes to commit.")
            return

    if not message:
        prompt = f"Generate a single-line conventional commit message (e.g. feat: ..., fix: ...) for this diff:\n\n{stdout[:2000]}"
        res = route(prompt, priority="speed")
        lines = [ln.strip().strip("`").strip() for ln in res.text.strip().splitlines() if ln.strip().strip("`").strip()]
        message = lines[0] if lines else "chore: update"

    click.echo(f"Generated commit message: {message}")
    if click.confirm("Commit changes with this message?", default=True):
        # Quote the (model-generated) message so it can never be interpreted by the shell.
        c, out, err = sandbox.run_sandboxed_command(f"git commit -m {shlex.quote(message)}")
        if c == 0:
            click.echo(click.style(f"✓ Committed: {message}", fg="green"))
        else:
            click.echo(f"Commit error: {err}", err=True)


@main.command(name="pr")
@click.option("--title", default=None, help="PR title (default: generated from the diff).")
@click.option("--base", default=None, help="Base branch (default: the repository's default branch).")
@click.option("--ready", is_flag=True, help="Open as ready for review instead of draft.")
@click.option("--yes", "-y", is_flag=True, help="Do not ask before committing / pushing / opening the PR.")
def pr_cmd(title, base, ready, yes):
    """Commit this task's changes, push the branch and open a pull request."""
    from ijachi_router.core import route
    from ijachi_router.gitflow import (GitError, commit_all, create_pr, default_branch, diff_for_message,
                                       ensure_feature_branch, push, repo_root, status)
    try:
        root = repo_root(Path.cwd())
        st = status(root)
        if not st["gh"]:
            raise click.ClickException("GitHub CLI (gh) is required: https://cli.github.com")
        if not st["has_remote"]:
            raise click.ClickException("This repository has no remote to push to.")
        diff = diff_for_message(root, staged=False)
        if not diff.strip() and not st["dirty"]:
            ahead = subprocess_ahead(root, base or st["default"])
            if not ahead:
                click.echo("No changes to open a PR for.")
                return
        if not title:
            res = route(
                "Write a conventional-commit style title (max 72 chars, one line, no quotes) for this change:\n\n" + diff,
                priority="cheapest",
            )
            title = res.text.strip().splitlines()[0].strip('"` ')[:72] or "Update"
        click.echo(f"Title: {title}")
        branch = ensure_feature_branch(root, title)
        if st["dirty"]:
            if not yes and not click.confirm(f"Commit all changes on branch '{branch}'?", default=True):
                return
            commit_all(root, title)
        body_res = route(
            "Write a concise GitHub pull request description in Markdown with sections '## Summary' (bullets) "
            "and '## Testing' for this diff. Do not invent tests that are not in the diff.\n\n" + diff_for_message(root, staged=False) +
            "\n\n" + _log_since(root, base or default_branch(root)),
            priority="cheapest",
        )
        body = body_res.text.strip() + "\n\n🤖 Opened with ijachi-code"
        if not yes and not click.confirm(f"Push '{branch}' and open a {'ready' if ready else 'draft'} PR?", default=True):
            return
        push(root, branch)
        url = create_pr(root, title, body, base or default_branch(root), draft=not ready)
        click.echo(click.style(f"✓ Pull request: {url}", fg="green"))
    except GitError as e:
        raise click.ClickException(str(e)) from e


def subprocess_ahead(root, base: str) -> int:
    import subprocess
    out = subprocess.run(["git", "rev-list", "--count", f"{base}..HEAD"], cwd=root, capture_output=True, text=True)
    try:
        return int(out.stdout.strip() or 0)
    except ValueError:
        return 0


def _log_since(root, base: str) -> str:
    import subprocess
    out = subprocess.run(["git", "log", "--oneline", f"{base}..HEAD"], cwd=root, capture_output=True, text=True)
    return "Commits:\n" + out.stdout.strip() if out.stdout.strip() else ""


@main.command(name="doctor")
def doctor_cmd():
    """Run full environment and model diagnostics."""
    print_doctor_report()


@main.command(name="update")
def update_cmd():
    """Check and pull the latest updates from GitHub."""
    from ijachi_router.updater import update_ijachi
    msg = update_ijachi()
    click.echo(msg)


if __name__ == "__main__":
    main()

