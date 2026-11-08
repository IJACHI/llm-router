"""Agent Loop Orchestrator with session continuity and fallback execution.

Document 2.3 (Agent loop requirements) & Document 4.4 (Data flow for one turn):
1. Append user_message event to canonical session log.
2. Route with the shared engine (routing.engine) using session-aware scoring and policy.
3. Assemble provider-neutral context; send it with native tool definitions when the model
   supports them (otherwise the JSON-in-text protocol), streaming text as it arrives.
4. Fall back across ranked candidates; a model that rejects native tools is retried in text mode.
5. Validate and authorize tool calls; execute with checkpoints before writes.
6. Enforce budgets, time limits, repetition detection and iteration limits.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from rich.console import Console

from ijachi_router.agent.limits import LoopLimits, RepetitionDetector
from ijachi_router.agent.permissions import PermissionManager
from ijachi_router.agent.sandbox import WorkspaceSandbox
from ijachi_router.agent.tools import ToolRuntime, native_tool_specs
from ijachi_router.config import ModelConfig, RouterConfig, load_config
from ijachi_router.context.assembler import _CONTEXT_EVENT_TYPES, AssembledContext, ContextAssembler
from ijachi_router.agent.completion import NO_CHANGES_PROMPT, clean_reply, continuation_prompt, is_build_request
from ijachi_router.fallback import get_circuit_breaker
from ijachi_router.metrics import log_result
from ijachi_router.providers import REGISTRY
from ijachi_router.providers.base import GenerationResult, ProviderError, ToolsUnsupportedError, new_call_id
from ijachi_router.routing.classifier import complexity_score, predict_category
from ijachi_router.routing.engine import NoEligibleModelError, rank_models
from ijachi_router.routing.escalation import EscalationTracker
from ijachi_router.routing.explain import CandidateEvaluation, RoutingExplanation
from ijachi_router.routing.features import extract_session_need
from ijachi_router.session.events import CanonicalEvent
from ijachi_router.session.store import SessionStore

console = Console()


@dataclass
class TurnResult:
    text: str
    model_used: str
    provider_used: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_sec: float
    explanation: RoutingExplanation | None = None
    completed: bool = True
    limit_hit: str | None = None
    denied_actions: int = 0
    streamed: bool = False  # final answer was already printed while streaming


# Output budget for agent turns: large enough for whole-file Write calls, small enough for
# every provider's output cap. Truncated output would otherwise corrupt tool calls.
_AGENT_MAX_TOKENS = 8192
_MAX_CONTINUATIONS = 3
_NEXT_STEP_HINT = "\n\n(Next: call another tool if more work is needed, or give your final answer if the task is done.)"
_TEST_COMMAND_HINTS = ("pytest", "npm test", "yarn test", "pnpm test", "go test", "cargo test", "unittest", "jest", "vitest", "make test")
_EDIT_TOOLS = ("Edit", "edit_file")
_WRITE_TOOLS = ("Edit", "Write", "edit_file", "write_file", "MultiEdit")

_MAIN_AGENT_ONLY_TOOLS = {"Explore"}

# provider/model pairs that rejected native tool definitions this process; use text mode.
_TEXT_ONLY_MODELS: set[str] = set()


def _count_workspace_files(root, cap: int = 5000) -> int:
    """Number of files in the workspace (skipping VCS/deps dirs), bounded for big repos."""
    import os
    skip = {".git", "node_modules", "venv", ".venv", "__pycache__", ".ijachi"}
    n = 0
    try:
        for _, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in skip]
            n += len(files)
            if n >= cap:
                return cap
    except OSError:
        return n
    return n


@dataclass
class _TurnState:
    turn_num: int
    original_message: str
    denied_actions: int = 0
    edited_since_last_test: bool = False
    edits: list[tuple[str, str, str]] = field(default_factory=list)
    explore_results: dict[str, str] = field(default_factory=dict)
    failed_calls: set[str] = field(default_factory=set)
    extra_cost: float = 0.0
    extra_in: int = 0
    extra_out: int = 0
    continuations: int = 0  # automatic "keep going" nudges this turn
    asked_for_files: bool = False
    files_at_start: int = 0


class AgentSessionLoop:
    """Orchestrates multi-turn interactive and one-shot agent tasks."""

    def __init__(
        self,
        store: SessionStore,
        config: RouterConfig | None = None,
        permission_mode: str = "ask",
        limits: LoopLimits | None = None,
        local_only: bool = False,
        allow_providers: set[str] | None = None,
        deny_providers: set[str] | None = None,
        depth: int = 0,
        quiet: bool = False,
        sandbox: bool | None = None,
    ):
        self.depth = depth    # 0 = main agent, 1 = Explore helper (cannot spawn helpers)
        self.quiet = quiet    # helpers run silently, possibly in parallel threads
        self.store = store
        self.state = store.state
        self.config = config or load_config()
        self.limits = limits or LoopLimits(
            max_turns=50,
            session_budget_usd=self.state.budget_usd,
        )
        self.local_only = local_only
        self.allow_providers = allow_providers
        self.deny_providers = deny_providers

        self.sandbox = WorkspaceSandbox(self.state.workspace_dir)
        from ijachi_router.settings import load_settings
        self.settings = load_settings(self.state.workspace_dir)
        self.permissions = PermissionManager(
            mode=permission_mode, rules=self.settings.get("permissions", {}),
        )
        self.tools = ToolRuntime(self.sandbox, self.state, self.store.checkpoints)
        self._configure_os_sandbox(sandbox)
        self.mcp = None
        if depth == 0 and self.settings.get("mcpServers"):
            from ijachi_router.agent.mcp import MCPManager
            self.mcp = MCPManager(self.settings["mcpServers"], cwd=str(self.state.workspace_dir))
            for name, err in self.mcp.errors.items():
                self._say(f"[yellow]⚠️  MCP server '{name}' failed to start: {err}[/yellow]")
        self.assembler = ContextAssembler(self.state.workspace_dir)
        self.escalation = EscalationTracker()
        self.repetition = RepetitionDetector(threshold=3)
        self.last_explanation: RoutingExplanation | None = None
        self.last_thought: str = ""
        self.last_context: AssembledContext | None = None
        self.verbose: bool = False
        self.stream_printer = None
        self.record_outcomes = True  # evaluation runs turn this off and record ground truth  # object with start()/feed(str)/end() -> str; set by the REPL

    # ── Routing ──────────────────────────────────────────────────────────────

    def _rank(self, need, priority: str, input_tokens: int):
        try:
            return rank_models(
                self.config,
                need,
                priority,
                allow_providers=self.allow_providers,
                deny_providers=self.deny_providers,
                local_only=self.local_only,
                max_cost_per_turn=self.limits.max_cost_per_turn_usd,
                pinned_model=self.state.pinned_model,
                current_model=self.state.current_model,
                cached_tokens=self.state.tokens_cached_estimate,
                input_tokens=input_tokens,
                quality_floor=2,
            )
        except NoEligibleModelError as e:
            raise ProviderError(str(e)) from e

    # ── Model call ───────────────────────────────────────────────────────────

    def _assemble(self, model: ModelConfig, events, pending_user_message: str, native: bool) -> AssembledContext:
        window = model.max_context
        if model.provider == "local":
            # Ollama only sees num_ctx tokens and silently drops the oldest (system prompt first).
            from ijachi_router.providers.local_provider import _DEFAULT_NUM_CTX
            window = min(window, _DEFAULT_NUM_CTX)
        if model.provider == "local":
            from ijachi_router.providers.local_provider import _DEFAULT_NUM_CTX
            window = min(window, _DEFAULT_NUM_CTX)
        return self.assembler.assemble(
            state=self.state,
            events=events,
            new_user_message=pending_user_message,
            model_window=window,
            provider_name=model.provider,
            reserved_output=_AGENT_MAX_TOKENS,
            native_tools=native,
            extra_tools=self.mcp.specs() if (self.mcp is not None and not native) else None,
        )

    def _generate(self, provider, ctx: AssembledContext, native: bool, deadline: float | None) -> GenerationResult:
        from ijachi_router.ui.activity import CatchyStatusSpinner

        remaining = 300.0
        if deadline is not None:
            remaining = min(300.0, max(10.0, deadline - time.monotonic()))
        kwargs: dict[str, Any] = {
            "system": ctx.system_prompt,
            "messages": ctx.messages,
            "max_tokens": _AGENT_MAX_TOKENS,
            "timeout": remaining,
        }
        if native:
            kwargs["tools"] = self._tool_specs()
        printer = self.stream_printer if (provider.supports_streaming and not self.quiet) else None
        if printer is not None:
            # Guard in both modes: some models leak tool-call JSON into text even with native tools.
            printer.start(json_guard=True)
            kwargs["on_text_delta"] = printer.feed
        flat_prompt = ctx.system_prompt + "\n\n" + "\n\n".join(
            f"{m['role'].title()}: {m.get('content') or ''}" for m in ctx.messages
        )
        self._last_printed = ""
        try:
            spinner = contextlib.nullcontext() if self.quiet else CatchyStatusSpinner(initial_phrase="Thinking...")
            with spinner:
                return provider.generate(flat_prompt, **kwargs)
        finally:
            if printer is not None:
                self._last_printed = printer.end()

    def _call_candidates(self, ranked, events, pending_user_message: str, deadline: float | None):
        """Try ranked candidates in order. Returns (result, model, context, native)."""
        for cand in ranked:
            model = cand.model
            breaker = get_circuit_breaker(model.provider)
            if not breaker.allow_request():
                continue
            provider_cls = REGISTRY.get(model.provider)
            if not provider_cls:
                continue
            provider = provider_cls(model_id=model.model_id, pricing=model.pricing)
            key = f"{model.provider}/{model.model_id}"
            native = bool(getattr(provider, "native_tools", False)) and key not in _TEXT_ONLY_MODELS
            try:
                ctx = self._assemble(model, events, pending_user_message, native)
                if self._maybe_summarize(events, ctx):
                    ctx = self._assemble(model, events, pending_user_message, native)
                try:
                    res = self._generate(provider, ctx, native, deadline)
                except ToolsUnsupportedError:
                    # This model/endpoint has no native tool calling: remember and use text mode.
                    _TEXT_ONLY_MODELS.add(key)
                    native = False
                    ctx = self._assemble(model, events, pending_user_message, native)
                    res = self._generate(provider, ctx, native, deadline)
                breaker.record_success()
                return res, model, ctx, native
            except Exception as e:  # noqa: BLE001 - any provider failure means "try the next one"
                breaker.record_failure()
                self._say(f"[dim yellow]Provider {model.provider} failed: {e}. Falling back...[/dim yellow]")
        raise ProviderError("All candidate models failed to generate response.")

    def _configure_os_sandbox(self, requested: bool | None) -> None:
        """Explicit flag > IJACHI_SANDBOX > settings > on by default in unattended 'auto' mode."""
        from ijachi_router.agent.os_sandbox import available, env_flag

        conf = self.settings.get("sandbox", {}) if isinstance(self.settings.get("sandbox"), dict) else {}
        enabled = requested
        if enabled is None:
            enabled = env_flag("IJACHI_SANDBOX")
        if enabled is None and "enabled" in conf:
            enabled = bool(conf["enabled"])
        if enabled is None:
            enabled = self.permissions.mode == "auto"
        self.sandbox.os_sandbox = bool(enabled) and available() is not None
        self.sandbox.allow_network = bool(conf.get("network", False))
        if enabled and available() is None and requested:
            self._say("[yellow]⚠️  OS sandbox requested but unavailable on this machine; commands run unsandboxed.[/yellow]")

    # ── UI (silenced for helper agents) ─────────────────────────────────────

    def _say(self, *args, **kwargs) -> None:
        if not self.quiet:
            console.print(*args, **kwargs)

    def _render_tool(self, *args, **kwargs) -> None:
        if not self.quiet:
            from ijachi_router.ui.activity import render_tool_activity
            render_tool_activity(*args, **kwargs)

    def _tool_specs(self) -> list[dict[str, Any]]:
        specs = native_tool_specs()
        if self.mcp is not None:
            specs = specs + self.mcp.specs()
        if self.depth >= 1:
            specs = [t for t in specs if t["name"] not in _MAIN_AGENT_ONLY_TOOLS]
        return specs

    # ── Model-written history summaries ──────────────────────────────────────

    def _maybe_summarize(self, events, ctx: AssembledContext, min_new: int = 6) -> bool:
        """Summarize history that no longer fits verbatim, once enough of it has fallen out."""
        if ctx.dropped_events <= 0:
            return False
        if self.state.rolling_summary and ctx.dropped_events - self.state.summary_event_count < min_new:
            return False
        committed = [e for e in events if e.committed and e.type in _CONTEXT_EVENT_TYPES]
        return self.summarize_history(committed[: ctx.dropped_events])

    def summarize_history(self, older_events, focus: str = "") -> bool:
        """Replace the rolling summary with a model-written one covering *older_events*."""
        from ijachi_router.context.compaction import SUMMARY_SYSTEM_PROMPT, CompactionEngine
        from ijachi_router.routing.engine import simple_need

        if not older_events:
            return False
        transcript = CompactionEngine.render_events(older_events)
        prior = self.state.rolling_summary if self.state.summary_event_count else ""
        prompt = (
            (f"Earlier summary (still valid):\n{prior}\n\n" if prior else "")
            + (f"Focus especially on: {focus}\n\n" if focus else "")
            + f"Session history to summarize:\n{transcript}"
        )
        try:
            ranking = rank_models(
                self.config, simple_need("summarization", 1.0, 0.3), "cheapest",
                allow_providers=self.allow_providers, deny_providers=self.deny_providers,
                local_only=self.local_only, quality_floor=2, input_tokens=len(prompt) // 4,
            )
        except NoEligibleModelError:
            return False
        for cand in ranking.ranked[:3]:
            provider_cls = REGISTRY.get(cand.model.provider)
            if not provider_cls:
                continue
            try:
                res = provider_cls(model_id=cand.model.model_id, pricing=cand.model.pricing).generate(
                    prompt, system=SUMMARY_SYSTEM_PROMPT, max_tokens=2000, timeout=120,
                )
            except Exception:  # noqa: BLE001
                continue
            if res.text.strip():
                self.state.rolling_summary = "# Summary of earlier session history\n" + res.text.strip()
                self.state.summary_event_count = len(older_events)
                self.state.record_usage(f"{cand.model.provider}/{cand.model.model_id}", res.cost_usd,
                                        res.input_tokens, res.output_tokens)
                self._say(f"[dim]🗜  Summarized {len(older_events)} earlier events with {cand.model.model_id} "
                          f"(${res.cost_usd:.4f})[/dim]")
                return True
        return False

    # ── Explore helper agents ────────────────────────────────────────────────

    def _explore(self, task: str) -> tuple[str, float, int, int]:
        """Run a read-only helper on a cheap model. Returns (report, cost, in_tokens, out_tokens)."""
        sub_store = SessionStore(
            root_dir=self.store.session_dir / "subagents",
            workspace_dir=Path(self.state.workspace_dir),
        )
        sub_store.state.priority = "cheapest"
        helper = AgentSessionLoop(
            sub_store,
            config=self.config,
            permission_mode="plan",
            limits=LoopLimits(max_turns=15, timeout_sec=240),
            local_only=self.local_only,
            allow_providers=self.allow_providers,
            deny_providers=self.deny_providers,
            depth=self.depth + 1,
            quiet=True,
        )
        helper.permissions.is_tty = False
        prompt = (
            "You are a read-only research helper for a coding agent. Investigate the task below using the "
            "read-only tools (RepoMap, Grep, Glob, Read, ListDir). Do not modify anything. Finish with a "
            "concise report: relevant file paths with line numbers, how the pieces fit together, and anything "
            f"surprising.\n\nTask: {task}"
        )
        try:
            res = helper.execute_turn(prompt)
        except Exception as e:  # noqa: BLE001
            return f"Explore helper failed: {e}", 0.0, 0, 0
        report = res.text or "(the helper returned no findings)"
        tag = f"[Explore via {res.provider_used}/{res.model_used} · ${res.cost_usd:.4f}]"
        return f"{tag}\n{report}", res.cost_usd, res.input_tokens, res.output_tokens

    def _prefetch_explores(self, calls: list[dict[str, Any]], ts: "_TurnState") -> None:
        """Run every Explore call of this step concurrently before the calls are processed."""
        tasks = [c for c in calls if c["name"] == "Explore" and self.depth == 0 and str((c.get("args") or {}).get("task", "")).strip()]
        if not tasks:
            return
        from concurrent.futures import ThreadPoolExecutor

        self._say(f"[dim]🔎 Exploring with {len(tasks)} helper agent(s)...[/dim]")
        with ThreadPoolExecutor(max_workers=min(4, len(tasks))) as pool:
            futures = {c["id"]: pool.submit(self._explore, str(c["args"]["task"])) for c in tasks}
            for call_id, fut in futures.items():
                report, cost, i, o = fut.result()
                ts.explore_results[call_id] = report
                ts.extra_cost += cost
                ts.extra_in += i
                ts.extra_out += o
                if cost:
                    self.state.record_usage("explore-helpers", cost, i, o)

    # ── Tool execution ───────────────────────────────────────────────────────

    def _run_tool(self, ts: _TurnState, name: str, args: dict, thought: str, model_name: str, call_id: str = "") -> str:
        if name == "Explore":
            if self.depth >= 1:
                return "Explore is not available to helper agents; investigate directly with the read-only tools."
            report = ts.explore_results.pop(call_id, None)
            if report is None:
                task = str(args.get("task", "")).strip()
                if not task:
                    return "Error: Explore needs a 'task'."
                report, cost, i, o = self._explore(task)
                ts.extra_cost += cost
                ts.extra_in += i
                ts.extra_out += o
                if cost:
                    self.state.record_usage("explore-helpers", cost, i, o)
            self._render_tool(name, args, success=True, output=report.splitlines()[0] if report else "", expanded=self.verbose)
            return report

        auth_res = self.permissions.authorize_tool_call(
            tool_name=name,
            args=args,
            workspace_dir=Path(self.state.workspace_dir),
            model_name=model_name,
            why_needed=thought,
        )
        reverted = self._find_reverted_edit(name, args, ts.edits)
        if reverted:
            out = (
                f"Refused: this Edit would undo the change you already made to '{reverted}' earlier in "
                "this turn. The file already contains that change. If the task is complete, give your final "
                "answer; otherwise make a different change."
            )
            self._render_tool(name, args, success=False, output=out, expanded=self.verbose)
            self.escalation.record_tool_error("self-reverting edit")
            return out
        if not auth_res.allowed:
            ts.denied_actions += 1
            out = (
                f"Permission denied: {auth_res.reason} Do not retry this action. Continue with what "
                "you can do, or give a final answer explaining what needs the user's approval."
            )
            self._render_tool(name, args, success=False, output=out, expanded=self.verbose)
            self.escalation.record_tool_error()
            return out

        from ijachi_router.agent.hooks import run_hooks

        ws = Path(self.state.workspace_dir)
        pre = run_hooks(self.settings, "PreToolUse", name, args, ws)
        if pre.blocked:
            out = f"Blocked: {pre.message}"
            self._render_tool(name, args, success=False, output=out, expanded=self.verbose)
            return out
        exec_res = self._execute_tool(name, args)
        post = run_hooks(self.settings, "PostToolUse", name, args, ws,
                         output=exec_res.output if exec_res.success else (exec_res.error or ""))
        if post.message:
            if exec_res.success:
                exec_res.output += f"\n\n[hook] {post.message}"
            else:
                exec_res.error = f"{exec_res.error}\n[hook] {post.message}"
        is_test_cmd = name in ("Bash", "run_command") and any(h in str(args.get("command", "")) for h in _TEST_COMMAND_HINTS)
        if name in _WRITE_TOOLS and exec_res.success:
            ts.edited_since_last_test = True
        if is_test_cmd and ts.edited_since_last_test:
            ts.edited_since_last_test = False
            if not exec_res.success:
                esc = self.escalation.record_test_failure_after_edit()
                if esc.escalate:
                    self._say(f"[bold yellow]⚠️ Escalating model: {esc.reason}[/bold yellow]")

        if exec_res.success:
            out = exec_res.output
            if exec_res.diff:
                out += f"\n\nDiff applied:\n{exec_res.diff}"
            if name in _EDIT_TOOLS:
                ts.edits.append((str(args.get("path", "")), str(args.get("target_content", "")), str(args.get("replacement_content", ""))))
            self._render_tool(name, args, success=True, output=exec_res.output, diff=exec_res.diff or "", expanded=self.verbose)
            return out + _NEXT_STEP_HINT
        out = f"Error: {exec_res.error}"
        self._render_tool(name, args, success=False, output=out, expanded=self.verbose)
        esc = self.escalation.record_tool_error()
        if esc.escalate:
            self._say(f"[bold yellow]⚠️ Escalating model: {esc.reason}[/bold yellow]")
        return out

    def _execute_tool(self, name: str, args: dict):
        """Built-in tools, plus MCP tools that live outside ToolRuntime."""
        if self.mcp is not None and self.mcp.handles(name):
            from ijachi_router.agent.tools import ToolExecutionResult
            from ijachi_router.agent.web import wrap_untrusted

            ok, text = self.mcp.call(name, args)
            wrapped = wrap_untrusted(name, text)
            return ToolExecutionResult(success=ok, output=wrapped if ok else "", error=None if ok else wrapped)
        return self.tools.execute(name, args)

    # ── Turn ─────────────────────────────────────────────────────────────────

    def execute_turn(
        self,
        user_message: str,
        on_stream_chunk: Callable[[str], None] | None = None,
        images: list[str | Path] | None = None,
    ) -> TurnResult:
        """Run one conversational turn or agentic multi-step sequence.

        ``images``: paths of image files to attach to this message (routed to vision models).
        """
        from ijachi_router.ui.activity import render_routing_badge, render_thought_stream

        self.state.turn_count += 1
        turn_num = self.state.turn_count
        from ijachi_router.context.images import load_image_parts
        image_parts = load_image_parts(images or [])
        self.store.append_event(CanonicalEvent(
            type="user_message", turn=turn_num,
            content=[{"kind": "text", "text": user_message}, *image_parts], committed=True,
        ))

        if self.state.is_budget_exceeded():
            limit_msg = f"Session budget limit (${self.state.budget_usd:.4f}) reached. Pausing."
            return TurnResult(
                text=limit_msg,
                model_used=self.state.current_model or "none",
                provider_used=self.state.current_provider or "none",
                input_tokens=0, output_tokens=0, cost_usd=0.0, latency_sec=0.0,
                completed=False, limit_hit=limit_msg,
            )

        ts = _TurnState(turn_num=turn_num, original_message=user_message,
                        files_at_start=_count_workspace_files(self.state.workspace_dir))
        build_request = self._is_build_request(user_message)
        turn_cost = 0.0
        turn_in_tokens = 0
        turn_out_tokens = 0
        final_answer = ""
        final_streamed = False
        last_model_used = ""
        last_provider_used = ""
        start_time = time.monotonic()
        deadline = start_time + self.limits.timeout_sec if self.limits.timeout_sec else None
        limit_hit: str | None = None
        finished = False
        pending_user_message = user_message
        self.tools.begin_turn(user_message)  # all file changes in this turn form one /undo set

        # Classify the user's actual request once; continuation prompts are internal.
        cat, conf = predict_category(user_message)
        cx = complexity_score(user_message)

        from ijachi_router.routing.architect import detect_and_determine_tech_stack
        rec = detect_and_determine_tech_stack(prompt=user_message, workspace_dir=self.state.workspace_dir, session_state=self.state)
        if rec:
            from rich.panel import Panel
            self._say(Panel(rec.format_terminal_card(), border_style="cyan"))
            self._say()

        iteration = 0
        while iteration < self.limits.max_turns:
            iteration += 1

            # Limits are enforced before every model request (FR-07).
            if self.state.is_budget_exceeded():
                limit_hit = f"Session budget limit (${self.state.budget_usd:.4f}) reached. Pausing."
                break
            if self.limits.max_cost_per_turn_usd is not None and turn_cost + ts.extra_cost >= self.limits.max_cost_per_turn_usd:
                limit_hit = f"Per-turn cost cap (${self.limits.max_cost_per_turn_usd:.4f}) reached. Pausing."
                break
            if deadline is not None and time.monotonic() > deadline:
                limit_hit = f"Turn time limit ({self.limits.timeout_sec}s) reached. Pausing."
                break

            need = extract_session_need(user_message, self.state, cat, conf, cx, has_images=bool(image_parts))
            priority = "quality" if self.escalation.is_escalated else (self.state.priority or self.config.priority)
            ranking = self._rank(need, priority, turn_in_tokens or 1000)
            winner = ranking.ranked[0]
            winning_model = winner.model
            chosen_reason = "best fit; sticky bonus applied" if winning_model.model_id == self.state.current_model else "highest score"
            if self.state.current_model and self.state.current_model != winning_model.model_id:
                self._say(f"[dim]switched {self.state.current_model} to {winning_model.model_id} ({chosen_reason})[/dim]")
            if not self.quiet:
                render_routing_badge(
                model_id=winning_model.model_id,
                provider=winning_model.provider,
                cost=winner.est_cost,
                reason=chosen_reason,
                quality_tier=winning_model.quality_tier,
            )
            self.last_explanation = RoutingExplanation(
                category=need.category,
                confidence=need.confidence,
                complexity=need.complexity,
                requires_tools=need.requires_tools,
                session_files_count=len(need.files_in_play),
                current_model=self.state.current_model,
                filtered_out=ranking.filtered_reasons,
                ranked=[
                    CandidateEvaluation(model_id=c.model.model_id, provider=c.model.provider, score=c.score,
                                        estimated_cost_usd=round(c.est_cost, 6))
                    for c in ranking.ranked
                ],
                chosen_model=winning_model.model_id,
                chosen_provider=winning_model.provider,
                decision_reason=chosen_reason,
                tip="/priority cost would choose cheaper alternative" if priority != "cost" else "",
            )

            events = self.store.read_events(committed_only=True)
            generation_res, used_model, ctx, native = self._call_candidates(
                ranking.ranked, events, pending_user_message, deadline
            )
            self.last_context = ctx
            pending_user_message = ""
            last_model_used = used_model.model_id
            last_provider_used = used_model.provider
            self.state.current_model = used_model.model_id
            self.state.current_provider = used_model.provider
            model_name = f"{last_provider_used}/{last_model_used}"

            turn_cost += generation_res.cost_usd
            turn_in_tokens += generation_res.input_tokens
            turn_out_tokens += generation_res.output_tokens
            self.state.record_usage(model=model_name, cost=generation_res.cost_usd,
                                    in_tokens=generation_res.input_tokens, out_tokens=generation_res.output_tokens)
            self.state.tokens_cached_estimate += generation_res.input_tokens
            self.state.cache_read_tokens += generation_res.cache_read_tokens
            self.state.cache_saved_usd += generation_res.cache_saved_usd

            resp_text = clean_reply(generation_res.text)

            # Tool calls: native ones first; otherwise parse the JSON-in-text protocol.
            calls: list[dict[str, Any]] = []
            thought = ""
            parsed = None
            if generation_res.tool_calls:
                calls = generation_res.tool_calls
                thought = resp_text
            else:
                text_calls = self._extract_json_calls(resp_text, self._known_tool_names())
                if len(text_calls) > 1:
                    # Several calls written into one reply: run them all, in order.
                    calls = [{"id": new_call_id(), "name": c.get("tool") or c.get("name"),
                              "args": c.get("args") or c.get("arguments") or {}} for c in text_calls]
                    thought = text_calls[0].get("thought", "")
                else:
                    parsed = self._extract_json_call(resp_text)
                    if parsed and "final_answer" not in parsed and (parsed.get("tool") or parsed.get("name")):
                        calls = [{
                            "id": new_call_id(),
                            "name": parsed.get("tool") or parsed.get("name"),
                            "args": parsed.get("args") or parsed.get("arguments") or {},
                        }]
                        thought = parsed.get("thought", "")
                if calls and native:
                    # The model was offered native tools but wrote its calls as text. Its chat
                    # template mishandles native tool messages (empty replies, leaked control
                    # tokens), so use the text protocol it is actually following from now on.
                    _TEXT_ONLY_MODELS.add(f"{used_model.provider}/{used_model.model_id}")
                    native = False

            if not calls:
                final_answer = parsed.get("final_answer", resp_text) if parsed else resp_text
                printed = getattr(self, "_last_printed", "").strip()
                final_streamed = bool(printed) and printed == final_answer.strip()

                # The model just finished whatever plan step it was working on.
                for s_done in self.state.plan_steps:
                    if s_done.status == "in_progress":
                        s_done.status = "completed"
                pending_steps = [s for s in self.state.plan_steps if s.status == "pending"]
                room = iteration < self.limits.max_turns - 1
                read_only = self.permissions.mode == "plan"

                cont_prompt = None
                if pending_steps and room and not read_only:
                    next_step = pending_steps[0]
                    next_step.status = "in_progress"  # completed only when the model reports back
                    self._say(f"[bold cyan]⚡ Autonomous Multi-Step Progress:[/bold cyan] [dim]Advancing to step {next_step.id}: '{next_step.title}'...[/dim]")
                    cont_prompt = (
                        f"Proceed directly to execute plan step {next_step.id}: '{next_step.title}'. "
                        "Use the tools (Write, Edit, or Bash) now to create or run the code directly."
                    )
                elif room and not read_only and ts.continuations < _MAX_CONTINUATIONS:
                    # The reply ended the turn but the work is not done: cut off, a broken
                    # tool call, or the model announced a step / asked to continue.
                    files_changed = len(self.tools.turn_checkpoints_created) + max(
                        0, _count_workspace_files(self.state.workspace_dir) - ts.files_at_start)
                    cont_prompt = continuation_prompt(
                        final_answer, resp_text, truncated=generation_res.truncated,
                        native=native, parsed=parsed, check_intent=ts.denied_actions == 0,
                        build_request=build_request and not ts.asked_for_files, files_changed=files_changed,
                    )
                    if cont_prompt == NO_CHANGES_PROMPT:
                        ts.asked_for_files = True
                    if cont_prompt:
                        ts.continuations += 1
                        self._say("[dim]↻ reply ended before the task was done; continuing…[/dim]")

                if cont_prompt:
                    self.store.append_event(CanonicalEvent(
                        type="assistant_message", turn=turn_num,
                        model={"provider": last_provider_used, "id": last_model_used},
                        content=[{"kind": "text", "text": resp_text}], committed=True,
                    ))
                    self.store.append_event(CanonicalEvent(
                        type="user_message", turn=turn_num, content=[{"kind": "text", "text": cont_prompt}], committed=True,
                    ))
                    pending_user_message = cont_prompt
                    continue

                self.store.append_event(CanonicalEvent(
                    type="assistant_message", turn=turn_num,
                    model={"provider": last_provider_used, "id": last_model_used},
                    content=[{"kind": "text", "text": final_answer}],
                    usage={"input_tokens": turn_in_tokens, "output_tokens": turn_out_tokens, "cost_usd": turn_cost},
                    committed=True,
                ))
                self.escalation.record_success(cx)
                finished = True
                break

            if thought:
                self.last_thought = thought
                if not getattr(self, "_last_printed", "").strip():
                    if not self.quiet:
                        render_thought_stream(thought, expanded=self.verbose)

            stop = False
            self._prefetch_explores(calls, ts)
            for call in calls:
                tool_name = call["name"]
                tool_args = call.get("args") or {}
                self.store.append_event(CanonicalEvent(
                    type="tool_call", turn=turn_num,
                    model={"provider": last_provider_used, "id": last_model_used},
                    tool_call={"id": call["id"], "name": tool_name, "args": tool_args, "thought": thought, "native": native},
                    committed=True,
                ))
                key = json.dumps([tool_name, tool_args], sort_keys=True, default=str)
                tool_output = self._run_tool(ts, tool_name, tool_args, thought, model_name, call["id"])
                failed = tool_output.startswith(("Error:", "Permission denied", "Refused", "Blocked"))
                if failed and key in ts.failed_calls:
                    tool_output += ("\n\nYou already made this exact call and it failed the same way. Do not repeat "
                                    "it: re-read the relevant file or change approach.")
                if failed:
                    ts.failed_calls.add(key)

                if len(tool_output) > 2000:
                    self.store.store_tool_result(tool_name, tool_output)  # full output kept on disk (FR-05)
                self.store.append_event(CanonicalEvent(
                    type="tool_result", turn=turn_num, content=[{"kind": "text", "text": tool_output}],
                    tool_call={"id": call["id"]}, committed=True,
                ))

                if self.repetition.record_call_and_result(tool_name, tool_args, tool_output):
                    self._say(f"[bold red]🛑 Loop detected: repeated call to '{tool_name}' 3 times. Stopping.[/bold red]")
                    final_answer = f"Agent stopped due to detected repetitive loop with {tool_name}."
                    limit_hit = "repetition"
                    self.store.append_event(CanonicalEvent(
                        type="assistant_message", turn=turn_num,
                        model={"provider": last_provider_used, "id": last_model_used},
                        content=[{"kind": "text", "text": final_answer}], committed=True,
                    ))
                    stop = True
                    break
            if stop:
                break

        turn_cost += ts.extra_cost
        turn_in_tokens += ts.extra_in
        turn_out_tokens += ts.extra_out

        if not finished and limit_hit is None:
            limit_hit = f"Reached the maximum of {self.limits.max_turns} model calls for one message."
        if limit_hit and limit_hit != "repetition":
            final_answer = (final_answer + "\n\n" if final_answer else "") + limit_hit
            final_streamed = False
            self._say(f"[bold yellow]⏸ {limit_hit}[/bold yellow]")

        self.store.save_state()

        # Weak live signal for learned routing (evaluation runs record ground truth instead).
        if last_model_used and self.depth == 0 and self.record_outcomes:
            from ijachi_router.routing.outcomes import record as record_outcome
            ok = finished and limit_hit is None and not self.escalation.is_escalated
            try:
                record_outcome(f"{last_provider_used}/{last_model_used}", cat, ok, weight=0.25)
            except OSError:
                pass

        if on_stream_chunk and final_answer and not final_streamed:
            on_stream_chunk(final_answer)

        if last_model_used:
            log_result(GenerationResult(
                text=final_answer, provider=last_provider_used, model=last_model_used,
                input_tokens=turn_in_tokens, output_tokens=turn_out_tokens, cost_usd=turn_cost,
                latency_s=time.monotonic() - start_time,
            ))

        return TurnResult(
            text=final_answer,
            model_used=last_model_used,
            provider_used=last_provider_used,
            input_tokens=turn_in_tokens,
            output_tokens=turn_out_tokens,
            cost_usd=turn_cost,
            latency_sec=time.monotonic() - start_time,
            explanation=self.last_explanation,
            completed=finished,
            limit_hit=limit_hit,
            denied_actions=ts.denied_actions,
            streamed=final_streamed,
        )

    @staticmethod
    def _find_reverted_edit(tool_name: str, args: dict[str, Any], turn_edits: list[tuple[str, str, str]]) -> str | None:
        """Return the path if this Edit exactly reverses an earlier successful Edit in the turn."""
        if tool_name not in _EDIT_TOOLS:
            return None
        path = str(args.get("path", ""))
        target = str(args.get("target_content", "")).strip()
        replacement = str(args.get("replacement_content", "")).strip()
        for prev_path, prev_target, prev_replacement in turn_edits:
            if prev_path == path and prev_replacement.strip() == target and prev_target.strip() == replacement:
                return path
        return None

    def _is_build_request(self, user_message: str) -> bool:
        """This message asks for something to be built, or briefly follows up on such a request."""
        if is_build_request(user_message):
            return True
        if len(user_message.split()) > 8:
            return False
        recent = [e for e in self.store.read_events(committed_only=True) if e.type == "user_message"][-4:-1]
        return any(is_build_request(" ".join(c.get("text", "") for c in e.content if isinstance(c, dict)))
                   for e in recent)

    def _known_tool_names(self) -> set[str]:
        from ijachi_router.agent.tools import TOOL_SCHEMAS
        names = set(TOOL_SCHEMAS) | {"Explore"}
        mcp = getattr(self, "mcp", None)
        if mcp is not None:
            try:
                names |= {t["name"] for t in mcp.specs()}
            except Exception:  # noqa: BLE001
                pass
        return names

    @staticmethod
    def _extract_json_calls(text: str, known: set[str]) -> list[dict[str, Any]]:
        """All tool-call objects written in the text, in order (only names of real tools)."""
        decoder = json.JSONDecoder()
        found: list[dict[str, Any]] = []
        i = 0
        while True:
            i = text.find("{", i)
            if i < 0:
                return found
            try:
                obj, end = decoder.raw_decode(text, i)
            except ValueError:
                i += 1
                continue
            name = obj.get("tool") or obj.get("name") if isinstance(obj, dict) else None
            if isinstance(name, str) and name in known and isinstance(obj.get("args", obj.get("arguments", {})), dict):
                found.append(obj)
                i = end
            else:
                i += 1

    @staticmethod
    def _extract_json_call(text: str) -> dict[str, Any] | None:
        """Extract JSON code block or function call from response text."""
        # Preprocess text: convert Python triple quotes `"""..."""` or `'''...'''` into valid JSON string escapes
        def _replace_triple(match: re.Match) -> str:
            return json.dumps(match.group(1))

        sanitized = re.sub(r'"""([\s\S]*?)"""', _replace_triple, text)
        sanitized = re.sub(r"'''([\s\S]*?)'''", _replace_triple, sanitized)

        # 1. Standard markdown ```json code block
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", sanitized, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass

        # 2. Robust raw JSON extraction using standard JSONDecoder on sanitized text
        decoder = json.JSONDecoder()
        for i, char in enumerate(sanitized):
            if char == "{":
                try:
                    obj, _ = decoder.raw_decode(sanitized[i:])
                    if isinstance(obj, dict) and any(k in obj for k in ("tool", "thought", "final_answer", "name")):
                        return obj
                except Exception:
                    continue

        # 3. Fallback: Parse inline function calls like ListDir(".") or Bash("ls")
        fn_match = re.search(r"\b(ListDir|Read|Write|Edit|Glob|Grep|Bash)\s*\(\s*[\"']([^\"']+)[\"']\s*\)", text)
        if fn_match:
            t_name = fn_match.group(1)
            arg_val = fn_match.group(2)
            arg_map = {
                "ListDir": {"path": arg_val},
                "Bash": {"command": arg_val},
                "Read": {"path": arg_val},
                "Glob": {"pattern": arg_val},
                "Grep": {"query": arg_val},
            }
            if t_name in arg_map:
                return {
                    "thought": f"Calling {t_name}",
                    "tool": t_name,
                    "args": arg_map[t_name],
                }

        # 4. Fallback: Direct regex extraction for malformed JSON with code
        t_match = re.search(r'"tool"\s*:\s*"(\w+)"', text)
        if t_match:
            t_name = t_match.group(1)
            p_match = re.search(r'"path"\s*:\s*"([^"]+)"', text)
            path_val = p_match.group(1) if p_match else ""

            c_match = re.search(r'"(?:replacement_content|content)"\s*:\s*(?:"""|")([\s\S]*?)(?:"""|"[\s,]*\})', text)
            content_val = c_match.group(1) if c_match else ""

            tc_match = re.search(r'"target_content"\s*:\s*(?:"""|")([\s\S]*?)(?:"""|"[\s,]*\})', text)
            target_val = tc_match.group(1) if tc_match else ""

            th_match = re.search(r'"thought"\s*:\s*"([^"]+)"', text)
            thought_val = th_match.group(1) if th_match else f"Executing {t_name}"

            if t_name in ("Write", "Edit") and path_val and content_val:
                args = {"path": path_val, "content": content_val, "replacement_content": content_val}
                if target_val:
                    args["target_content"] = target_val
                return {
                    "thought": thought_val,
                    "tool": t_name,
                    "args": args,
                }

        return None
