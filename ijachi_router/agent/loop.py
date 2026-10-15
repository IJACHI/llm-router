"""Agent Loop Orchestrator with session continuity and fallback execution.

Document 2.3 (Agent loop requirements) & Document 4.4 (Data flow for one turn):
1. Append user_message event to canonical session log.
2. Build session Need and assemble context.
3. Route turn using session-aware scoring, stickiness, and candidate filtering.
4. Execute model request with fallback across candidates from last committed event (SC-08).
5. Validate and authorize tool calls; execute with checkpoints before writes.
6. Commit events only upon successful completion.
7. Enforce repetition detection and limits.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from rich.console import Console

from ijachi_router.agent.limits import LoopLimits, RepetitionDetector
from ijachi_router.agent.permissions import PermissionManager
from ijachi_router.agent.sandbox import WorkspaceSandbox
from ijachi_router.agent.tools import ToolRuntime
from ijachi_router.config import ModelConfig, RouterConfig, load_config
from ijachi_router.context.assembler import ContextAssembler
from ijachi_router.fallback import get_circuit_breaker
from ijachi_router.metrics import log_result
from ijachi_router.providers import REGISTRY
from ijachi_router.providers.base import GenerationResult, ProviderError
from ijachi_router.routing.classifier import complexity_score, predict_category
from ijachi_router.routing.escalation import EscalationTracker
from ijachi_router.routing.explain import CandidateEvaluation, RoutingExplanation
from ijachi_router.routing.features import extract_session_need
from ijachi_router.routing.policy import filter_candidates
from ijachi_router.routing.scorer import score_candidate
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
    ):
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
        self.permissions = PermissionManager(mode=permission_mode)
        self.tools = ToolRuntime(self.sandbox, self.state, self.store.checkpoints)
        self.assembler = ContextAssembler(self.state.workspace_dir)
        self.escalation = EscalationTracker()
        self.repetition = RepetitionDetector(threshold=3)
        self.last_explanation: RoutingExplanation | None = None
        self.last_thought: str = ""
        self.verbose: bool = False

    def execute_turn(
        self,
        user_message: str,
        on_stream_chunk: Callable[[str], None] | None = None,
    ) -> TurnResult:
        """Run one conversational turn or agentic multi-step sequence."""
        self.state.turn_count += 1
        turn_num = self.state.turn_count

        # 1. Append user event to session log
        user_evt = CanonicalEvent(
            type="user_message",
            turn=turn_num,
            content=[{"kind": "text", "text": user_message}],
            committed=True,
        )
        self.store.append_event(user_evt)

        # Budget check before starting
        if self.state.is_budget_exceeded():
            limit_msg = f"Session budget limit (${self.state.budget_usd:.4f}) reached. Pausing."
            return TurnResult(
                text=limit_msg,
                model_used=self.state.current_model or "none",
                provider_used=self.state.current_provider or "none",
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                latency_sec=0.0,
                completed=False,
                limit_hit=limit_msg,
            )

        turn_cost = 0.0
        turn_in_tokens = 0
        turn_out_tokens = 0
        final_answer = ""
        last_model_used = ""
        last_provider_used = ""
        start_time = time.monotonic()

        # 1. Automatic tech stack determination on new projects if not specified
        from ijachi_router.routing.architect import detect_and_determine_tech_stack
        rec = detect_and_determine_tech_stack(
            prompt=user_message,
            workspace_dir=self.state.workspace_dir,
            session_state=self.state,
        )
        if rec:
            from rich.panel import Panel
            console.print(Panel(rec.format_terminal_card(), border_style="cyan"))
            console.print()

        iteration = 0
        while iteration < self.limits.max_turns:
            iteration += 1

            # 2. Extract routing Need from prompt + session state
            cat, conf = predict_category(user_message)
            cx = complexity_score(user_message)
            need = extract_session_need(user_message, self.state, cat, conf, cx)

            # Check escalation
            if self.escalation.is_escalated:
                priority = "quality"
            else:
                priority = self.state.priority or self.config.priority

            # 3. Filter candidates
            open_circuits = {
                p for p in self.config.available_providers if get_circuit_breaker(p).is_open
            }
            eligible, filtered_reasons = filter_candidates(
                candidates=self.config.available_models(),
                need=need,
                allow_providers=self.allow_providers,
                deny_providers=self.deny_providers,
                local_only=self.local_only,
                max_cost_per_turn=self.limits.max_cost_per_turn_usd,
                agent_quality_floor=2,
                open_circuit_providers=open_circuits,
                pinned_model=self.state.pinned_model,
            )

            if not eligible:
                # Fallback to all available models if everything was filtered out
                eligible = self.config.available_models()

            if not eligible:
                raise ProviderError(
                    "No providers available. Please configure an API key or start local Ollama."
                )

            # 4. Score candidates with stickiness bonus
            scored: list[tuple[float, ModelConfig, float]] = []
            for m in eligible:
                is_curr = (m.model_id == self.state.current_model)
                s = score_candidate(
                    model=m,
                    need=need,
                    priority=priority,
                    input_tokens=turn_in_tokens or 1000,
                    is_current_model=is_curr,
                    cached_tokens=self.state.tokens_cached_estimate,
                )
                est_cost = (1000 / 1000) * m.input_per_1k + (need.expected_output_tokens / 1000) * m.output_per_1k
                scored.append((s, m, est_cost))

            scored.sort(key=lambda t: -t[0])
            ranked_evals = [
                CandidateEvaluation(
                    model_id=m.model_id,
                    provider=m.provider,
                    score=s,
                    estimated_cost_usd=round(ec, 6),
                )
                for s, m, ec in scored
            ]

            winning_model = scored[0][1]
            chosen_reason = "best fit; sticky bonus applied" if winning_model.model_id == self.state.current_model else "highest score"

            # Check if model switched (Doc 3.6 User visibility)
            if self.state.current_model and self.state.current_model != winning_model.model_id:
                switch_msg = f"[dim]switched {self.state.current_model} to {winning_model.model_id} ({chosen_reason})[/dim]"
                console.print(switch_msg)

            self.state.current_model = winning_model.model_id
            self.state.current_provider = winning_model.provider

            # Transparent routing announcement (Doc 3.6 & user visibility)
            from ijachi_router.ui.activity import CatchyStatusSpinner, render_routing_badge, render_thought_stream, render_tool_activity
            render_routing_badge(
                model_id=winning_model.model_id,
                provider=winning_model.provider,
                cost=scored[0][2],
                reason=chosen_reason,
                quality_tier=getattr(winning_model, "quality_tier", 2),
            )

            # Save routing explanation (FR-29)
            self.last_explanation = RoutingExplanation(
                category=need.category,
                confidence=need.confidence,
                complexity=need.complexity,
                requires_tools=need.requires_tools,
                session_files_count=len(need.files_in_play),
                current_model=self.state.current_model,
                filtered_out=filtered_reasons,
                ranked=ranked_evals,
                chosen_model=winning_model.model_id,
                chosen_provider=winning_model.provider,
                decision_reason=chosen_reason,
                tip="/priority cost would choose cheaper alternative" if priority != "cost" else "",
            )

            # 5. Assemble context
            events = self.store.read_events(committed_only=True)
            ctx = self.assembler.assemble(
                state=self.state,
                events=events,
                new_user_message=user_message,
                model_window=winning_model.max_context,
                provider_name=winning_model.provider,
            )

            # 6. Execute model call with fallback and catchy animated spinner
            generation_res = None
            for _, candidate_model, _ in scored:
                breaker = get_circuit_breaker(candidate_model.provider)
                if not breaker.allow_request():
                    continue

                provider_cls = REGISTRY.get(candidate_model.provider)
                if not provider_cls:
                    continue

                try:
                    prov_inst = provider_cls(
                        model_id=candidate_model.model_id,
                        pricing=candidate_model.pricing,
                    )
                    # Flatten assembled messages for provider
                    full_prompt = f"{ctx.system_prompt}\n\n"
                    for msg in ctx.messages:
                        full_prompt += f"{msg['role'].title()}: {msg['content']}\n\n"
                    full_prompt += "Assistant: "

                    with CatchyStatusSpinner(initial_phrase="Thinking..."):
                        generation_res = prov_inst.generate(full_prompt, on_stream_chunk=on_stream_chunk)

                    breaker.record_success()
                    last_model_used = candidate_model.model_id
                    last_provider_used = candidate_model.provider
                    break
                except Exception as e:
                    breaker.record_failure()
                    console.print(f"[dim yellow]Provider {candidate_model.provider} failed: {e}. Falling back...[/dim yellow]")
                    continue

            if not generation_res:
                raise ProviderError("All candidate models failed to generate response.")

            # Record turn costs & tokens
            turn_cost += generation_res.cost_usd
            turn_in_tokens += generation_res.input_tokens
            turn_out_tokens += generation_res.output_tokens
            self.state.record_usage(
                model=f"{last_provider_used}/{last_model_used}",
                cost=generation_res.cost_usd,
                in_tokens=generation_res.input_tokens,
                out_tokens=generation_res.output_tokens,
            )
            self.state.tokens_cached_estimate += generation_res.input_tokens

            resp_text = generation_res.text.strip()
            if on_stream_chunk:
                on_stream_chunk(resp_text)

            # Parse tool calls
            parsed = self._extract_json_call(resp_text)

            # If no tool call or final answer
            if not parsed or "final_answer" in parsed or ("tool" not in parsed and "tool_call" not in parsed):
                final_answer = parsed.get("final_answer", resp_text) if parsed else resp_text
                # Commit assistant event
                ast_evt = CanonicalEvent(
                    type="assistant_message",
                    turn=turn_num,
                    model={"provider": last_provider_used, "id": last_model_used},
                    content=[{"kind": "text", "text": final_answer}],
                    usage={
                        "input_tokens": turn_in_tokens,
                        "output_tokens": turn_out_tokens,
                        "cost_usd": turn_cost,
                    },
                    committed=True,
                )
                self.store.append_event(ast_evt)
                self.escalation.record_success(cx)
                break

            # Handle Tool Call
            tool_name = parsed.get("tool") or parsed.get("name")
            tool_args = parsed.get("args") or parsed.get("arguments") or {}
            thought = parsed.get("thought", "")

            # Stream thought process if provided (collapsed by default, /thoughts to expand)
            if thought:
                self.last_thought = thought
                render_thought_stream(thought, expanded=self.verbose)

            # Commit tool_call event
            tc_evt = CanonicalEvent(
                type="tool_call",
                turn=turn_num,
                model={"provider": last_provider_used, "id": last_model_used},
                tool_call={"name": tool_name, "args": tool_args, "thought": thought},
                committed=True,
            )
            self.store.append_event(tc_evt)

            # Authorize tool call
            auth_res = self.permissions.authorize_tool_call(
                tool_name=tool_name,
                args=tool_args,
                workspace_dir=Path(self.state.workspace_dir),
                model_name=f"{last_provider_used}/{last_model_used}",
                why_needed=thought,
            )

            if not auth_res.allowed:
                tool_output = f"Permission denied: {auth_res.reason}"
                render_tool_activity(tool_name, tool_args, success=False, output=tool_output, expanded=self.verbose)
                self.escalation.record_tool_error()
            else:
                exec_res = self.tools.execute(tool_name, tool_args)
                if exec_res.success:
                    tool_output = exec_res.output
                    if exec_res.diff:
                        tool_output += f"\n\nDiff applied:\n{exec_res.diff}"
                    render_tool_activity(
                        tool_name,
                        tool_args,
                        success=True,
                        output=exec_res.output,
                        diff=exec_res.diff or "",
                        expanded=self.verbose,
                    )
                else:
                    tool_output = f"Error: {exec_res.error}"
                    render_tool_activity(
                        tool_name,
                        tool_args,
                        success=False,
                        output=tool_output,
                        expanded=self.verbose,
                    )
                    esc_dec = self.escalation.record_tool_error()
                    if esc_dec.escalate:
                        console.print(f"[bold yellow]⚠️ Escalating model: {esc_dec.reason}[/bold yellow]")

            # Repetition detection (FR-08)
            if self.repetition.record_call_and_result(tool_name, tool_args, tool_output):
                console.print(f"[bold red]🛑 Loop detected: repeated call to '{tool_name}' 3 times. Stopping.[/bold red]")
                final_answer = f"Agent stopped due to detected repetitive loop with {tool_name}."
                break

            # Store large tool output on disk (FR-05)
            if len(tool_output) > 2000:
                self.store.store_tool_result(tool_name, tool_output)

            # Commit tool_result event
            tr_evt = CanonicalEvent(
                type="tool_result",
                turn=turn_num,
                content=[{"kind": "text", "text": tool_output}],
                committed=True,
            )
            self.store.append_event(tr_evt)

        # Save session snapshot
        self.store.save_state()

        # Log metrics
        if last_model_used:
            total_sec = time.monotonic() - start_time
            gen_mock = GenerationResult(
                text=final_answer,
                provider=last_provider_used,
                model=last_model_used,
                input_tokens=turn_in_tokens,
                output_tokens=turn_out_tokens,
                cost_usd=turn_cost,
                latency_s=total_sec,
            )
            log_result(gen_mock)

        return TurnResult(
            text=final_answer,
            model_used=last_model_used,
            provider_used=last_provider_used,
            input_tokens=turn_in_tokens,
            output_tokens=turn_out_tokens,
            cost_usd=turn_cost,
            latency_sec=time.monotonic() - start_time,
            explanation=self.last_explanation,
            completed=True,
        )

    @staticmethod
    def _extract_json_call(text: str) -> dict[str, Any] | None:
        """Extract JSON code block or function call from response text."""
        # 1. Standard markdown ```json code block
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass

        # 2. Robust raw JSON extraction using standard JSONDecoder
        decoder = json.JSONDecoder()
        for i, char in enumerate(text):
            if char == "{":
                try:
                    obj, _ = decoder.raw_decode(text[i:])
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

        return None
