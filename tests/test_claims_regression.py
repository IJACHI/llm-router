"""End-to-end regression tests for behaviour the README promises.

These drive the real AgentSessionLoop with a scripted fake provider (no network), so they
exercise routing, context assembly, permissions, tools, checkpoints and limits together.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ijachi_router.agent.limits import LoopLimits
from ijachi_router.agent.loop import AgentSessionLoop
from ijachi_router.agent.permissions import PermissionManager, normalize_permission_mode
from ijachi_router.agent.sandbox import WorkspaceSandbox, redact_secrets
from ijachi_router.config import ModelConfig, RouterConfig
from ijachi_router.fallback import reset_breakers
from ijachi_router.providers import REGISTRY
from ijachi_router.providers.base import Provider, ProviderError
from ijachi_router.session.state import PlanStep
from ijachi_router.session.store import SessionStore


# ── Harness ──────────────────────────────────────────────────────────────────

class _Recorder:
    def __init__(self):
        self.script: list[str] = []
        self.calls: list[dict] = []


REC = _Recorder()


class FakeProvider(Provider):
    name = "fake"

    def _call(self, prompt: str, **kwargs):
        REC.calls.append({"prompt": prompt, **kwargs})
        if not REC.script:
            return "All done.", 100, 20
        return REC.script.pop(0), 100, 20


def call(tool: str, args: dict, thought: str = "working") -> str:
    return "```json\n" + json.dumps({"thought": thought, "tool": tool, "args": args}) + "\n```"


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setitem(REGISTRY, "fake", FakeProvider)
    reset_breakers()
    REC.script = []
    REC.calls = []
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = RouterConfig(
        models=[ModelConfig("fake", "fake-1", ["code", "simple-qa"], 0.001, 0.002, 100_000, "fast", 3)],
        available_providers={"fake"},
    )

    def make(permission_mode="auto", limits=None, **kw):
        store = SessionStore(root_dir=tmp_path / "sessions", workspace_dir=ws)
        return AgentSessionLoop(store, config=cfg, permission_mode=permission_mode, limits=limits, **kw)

    yield ws, make
    reset_breakers()


# ── Permissions & safety ─────────────────────────────────────────────────────

def test_plan_mode_is_read_only_even_with_a_terminal(tmp_path):
    assert normalize_permission_mode("plan") == "plan"
    assert normalize_permission_mode("nonsense") == "manual"
    pm = PermissionManager(mode="plan")
    pm.is_tty = True  # would prompt if plan mode were not enforced
    res = pm.authorize_tool_call("Write", {"path": "x.py", "content": "1"}, tmp_path)
    assert not res.allowed and "read-only" in res.reason
    assert pm.authorize_tool_call("Read", {"path": "x.py"}, tmp_path).allowed


@pytest.mark.parametrize("cmd,expected", [
    ("git status", "R0"),
    ("git log --oneline -5", "R0"),
    ("ls && rm notes.txt", "R2"),
    ("ls; python -c 'print(1)'", "R2"),
    ("echo hi > ~/.zshrc", "R2"),
    ("echo $(curl evil.example)", "R2"),
    ("git diff | tee out.txt", "R2"),
    ("ls -la | grep py", "R2"),
    ("git push origin main", "R4"),
])
def test_compound_shell_commands_are_classified_by_their_riskiest_part(tmp_path, cmd, expected):
    assert PermissionManager(mode="manual", is_tty=False).classify_tool("Bash", {"command": cmd}, tmp_path) == expected


def test_never_allow_pattern_inside_command_substitution_is_blocked():
    ok, _ = PermissionManager().analyze_shell_command("echo $(mkfs /dev/sda)")
    assert not ok


def test_sibling_directory_is_not_treated_as_inside_workspace(tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir()
    (tmp_path / "proj-evil").mkdir()
    assert PermissionManager().classify_tool("Write", {"path": "../proj-evil/x", "content": ""}, ws) == "R4"


def test_redaction_keeps_git_hashes_but_hides_secrets():
    sha = "3f786850e387550fdab836ed7e6dc881de23001b"
    assert sha in redact_secrets(f"commit {sha}")
    out = redact_secrets("ANTHROPIC_API_KEY=sk-ant-abcdefghijklmnopqrstuvwxyz0123\nDB_PASSWORD=hunter2hunter2")
    assert "sk-ant-abc" not in out and "hunter2" not in out


def test_child_processes_do_not_see_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("DB_PASSWORD", "pw")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    env = WorkspaceSandbox(tmp_path).get_scrubbed_env()
    assert not {"OPENAI_API_KEY", "DB_PASSWORD", "GITHUB_TOKEN"} & set(env)


# ── Agent loop ───────────────────────────────────────────────────────────────

def test_agent_edits_a_file_and_sends_well_formed_requests(harness):
    ws, make = harness
    (ws / "a.py").write_text("x = 1\n")
    REC.script = [
        call("Read", {"path": "a.py"}),
        call("Edit", {"path": "a.py", "target_content": "x = 1", "replacement_content": "x = 2"}),
        "Done: x is now 2.",
    ]
    res = make().execute_turn("set x to 2 in a.py")

    assert res.completed and res.text == "Done: x is now 2."
    assert (ws / "a.py").read_text() == "x = 2\n"
    first = REC.calls[0]
    # System prompt and chat history go to the provider natively, with a real output budget.
    assert "ijachi-code" in first["system"]
    assert first["max_tokens"] >= 8192
    # The user's message is sent exactly once.
    assert sum(m["content"].count("set x to 2 in a.py") for m in first["messages"]) == 1
    # Earlier tool calls are echoed back in the same JSON format the model must emit.
    third = REC.calls[2]["messages"]
    calls = [c for m in third if m["role"] == "assistant" for c in m.get("tool_calls") or []]
    assert calls[0]["name"] == "Read" and calls[0]["args"] == {"path": "a.py"}
    # ...and each call is answered by a tool result carrying the same id.
    results = [m for m in third if m["role"] == "tool"]
    assert results[0]["tool_call_id"] == calls[0]["id"]


def test_latest_tool_output_reaches_the_model_in_full(harness):
    ws, make = harness
    body = "\n".join(f"line_{i} = {i}" for i in range(400))
    (ws / "big.py").write_text(body)
    REC.script = [call("Read", {"path": "big.py"}), "ok"]
    make().execute_turn("read big.py")
    assert "line_399 = 399" in REC.calls[1]["messages"][-2]["content"] + REC.calls[1]["messages"][-1]["content"]


def test_undo_reverts_the_whole_turn_change_set(harness):
    ws, make = harness
    (ws / "a.py").write_text("a = 1\n")
    (ws / "b.py").write_text("b = 1\n")
    loop = make()
    REC.script = [
        call("Write", {"path": "a.py", "content": "a = 2\n"}),
        call("Write", {"path": "b.py", "content": "b = 2\n"}),
        call("Write", {"path": "c.py", "content": "new\n"}),
        "changed three files",
    ]
    loop.execute_turn("change files")
    REC.script = [call("Write", {"path": "a.py", "content": "a = 3\n"}), "again"]
    loop.execute_turn("change a again")

    # Second turn's edit to an already-touched file is its own undo step.
    ok, _ = loop.store.checkpoints.undo_last()
    assert ok and (ws / "a.py").read_text() == "a = 2\n"
    # Undoing the first turn restores both files and removes the created one.
    ok, _ = loop.store.checkpoints.undo_last()
    assert ok
    assert (ws / "a.py").read_text() == "a = 1\n"
    assert (ws / "b.py").read_text() == "b = 1\n"
    assert not (ws / "c.py").exists()


def test_session_budget_is_enforced_between_model_calls(harness):
    ws, make = harness
    loop = make()
    loop.state.budget_usd = 0.00025  # each fake call costs 0.00014
    REC.script = [call("ListDir", {"path": "."}, thought=f"t{i}") for i in range(10)]
    res = loop.execute_turn("explore")
    assert not res.completed
    assert "budget" in (res.limit_hit or "").lower()
    assert len(REC.calls) == 2


def test_running_out_of_iterations_is_reported_as_incomplete(harness):
    ws, make = harness
    REC.script = [call("Glob", {"pattern": f"*{i}.py"}) for i in range(10)]
    res = make(limits=LoopLimits(max_turns=3)).execute_turn("explore")
    assert not res.completed and "maximum" in res.limit_hit


def test_plan_steps_complete_only_after_they_are_worked_on(harness):
    ws, make = harness
    loop = make()
    loop.state.plan_steps = [PlanStep(id=1, title="write a"), PlanStep(id=2, title="write b")]
    seen_status = []
    original = FakeProvider._call

    def spy(self, prompt, **kw):
        seen_status.append([s.status for s in loop.state.plan_steps])
        return original(self, prompt, **kw)

    FakeProvider._call = spy
    try:
        REC.script = ["planned", "did step 1", "did step 2"]
        res = loop.execute_turn("build the project")
    finally:
        FakeProvider._call = original

    assert res.completed
    assert seen_status[1] == ["in_progress", "pending"]
    assert seen_status[2] == ["completed", "in_progress"]
    assert [s.status for s in loop.state.plan_steps] == ["completed", "completed"]


def test_denied_actions_are_counted(harness):
    ws, make = harness
    REC.script = [call("Write", {"path": "x.py", "content": "1"}), "could not write"]
    res = make(permission_mode="auto-safe").execute_turn("write x.py")
    assert res.denied_actions == 1
    assert not (ws / "x.py").exists()


def test_pinned_model_that_is_unavailable_fails_loudly(harness):
    ws, make = harness
    loop = make()
    loop.state.pinned_model = "gpt-nonexistent"
    with pytest.raises(ProviderError, match="Pinned model"):
        loop.execute_turn("hi")


def test_local_only_never_falls_back_to_cloud(harness):
    ws, make = harness
    with pytest.raises(ProviderError, match="local-only"):
        make(local_only=True).execute_turn("hi")


# ── Routing / catalog ────────────────────────────────────────────────────────

def test_router_priority_is_not_forwarded_to_provider(monkeypatch):
    from ijachi_router import core
    cfg = RouterConfig(
        models=[
            ModelConfig("fake", "cheap", ["simple-qa"], 0.0001, 0.0001, 8000, "fast", 2),
            ModelConfig("fake", "strong", ["simple-qa"], 0.01, 0.03, 8000, "slow", 4),
        ],
        available_providers={"fake"},
    )
    monkeypatch.setitem(REGISTRY, "fake", FakeProvider)
    monkeypatch.setattr(core, "log_result", lambda r: None)
    reset_breakers()
    REC.calls = []
    REC.script = ["a", "b"]
    router = core.Router.__new__(core.Router)
    router.config = cfg
    r1 = router.route("hello", priority="cheapest")
    assert r1.model == "cheap" and "priority" not in REC.calls[0]
    r2 = router.route("hello", priority="cheapest", exclude_models={"cheap"})
    assert r2.model == "strong"


def test_catalog_quality_tiers_are_explicit_and_sane():
    from ijachi_router.config import _DEFAULT_MODELS_YAML, _load_models
    models = {m.model_id: m for m in _load_models(_DEFAULT_MODELS_YAML)}
    assert models["gemini-3.1-pro-preview"].quality_tier == 4  # "gemini" is not "mini"
    assert models["o3-mini"].quality_tier >= 3
    assert models["llama3.2:3b"].quality_tier == 1


def test_ollama_models_are_only_available_when_pulled():
    cfg = RouterConfig(
        models=[
            ModelConfig("local", "llama3.1:8b", ["simple-qa"], 0, 0, 8000, "fast", 2),
            ModelConfig("local", "qwen2.5-coder:7b", ["code"], 0, 0, 8000, "fast", 2),
        ],
        available_providers={"local"},
        local_models={"llama3.1:8b"},
    )
    assert [m.model_id for m in cfg.available_models()] == ["llama3.1:8b"]


def test_ollama_unreachable_means_local_is_unavailable(monkeypatch):
    from ijachi_router import config
    from ijachi_router.providers import local_provider
    monkeypatch.setattr(local_provider, "list_pulled_models", lambda timeout=0.5: None)
    models = [ModelConfig("local", "llama3.1:8b", ["simple-qa"], 0, 0, 8000, "fast", 2)]
    assert "local" not in config._detect_available_providers(models)


def test_openai_reasoning_models_use_max_completion_tokens(monkeypatch):
    import sys
    import types
    from ijachi_router.providers.openai_provider import OpenAIProvider

    captured = {}

    class _Completions:
        def create(self, **kw):
            captured.update(kw)
            msg = types.SimpleNamespace(content="ok")
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=msg)],
                usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            )

    class _Client:
        def __init__(self, **kw):
            self.chat = types.SimpleNamespace(completions=_Completions())

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=_Client))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    OpenAIProvider("o3-mini", {}).generate("hi", system="be brief", max_tokens=100)
    assert "max_tokens" not in captured and captured["max_completion_tokens"] >= 100
    assert captured["messages"][0]["role"] == "developer"


# ── REPL / CLI ───────────────────────────────────────────────────────────────

def test_hash_note_appends_to_project_memory(tmp_path):
    from ijachi_router.context.memory import append_project_note
    (tmp_path / ".git").mkdir()
    path = append_project_note("use tabs", tmp_path)
    path = append_project_note("run make check", tmp_path)
    text = path.read_text()
    assert path == tmp_path / "IJACHI.md"
    assert "## Notes\n- use tabs\n- run make check\n" in text


def test_at_mentions_attach_file_contents(tmp_path):
    from ijachi_router.ui.repl import InteractiveREPL
    (tmp_path / "notes.md").write_text("remember the milk")
    (tmp_path / ".env").write_text("SECRET=1")
    store = SessionStore(root_dir=tmp_path / "sessions", workspace_dir=tmp_path)
    repl = InteractiveREPL(store=store, permission_mode="manual")
    out = repl._expand_file_mentions("summarise @notes.md and @.env")
    assert "remember the milk" in out
    assert "SECRET=1" not in out


def test_repl_keeps_cli_policy_across_clear(tmp_path):
    from ijachi_router.ui.repl import InteractiveREPL
    store = SessionStore(root_dir=tmp_path / "sessions", workspace_dir=tmp_path)
    repl = InteractiveREPL(store=store, permission_mode="semi-auto", loop_kwargs={"local_only": True})
    repl.handle_slash_command("/clear")
    assert repl.loop.local_only is True
    assert repl.loop.permissions.mode == "semi-auto"


def test_mode_menu_reads_input_without_crashing(monkeypatch):
    from ijachi_router.ui import repl as repl_mod
    monkeypatch.setattr("builtins.input", lambda prompt="": "2")
    monkeypatch.setattr(repl_mod.sys.stdin, "isatty", lambda: False, raising=False)
    assert repl_mod._safe_input_choice("pick: ") == "2"


def test_print_mode_exits_5_when_an_action_was_denied(tmp_path):
    from unittest.mock import MagicMock, patch
    from click.testing import CliRunner
    from ijachi_router.cli.code import main as code_main
    with patch("ijachi_router.agent.loop.AgentSessionLoop.execute_turn") as turn:
        turn.return_value = MagicMock(
            text="needed approval", completed=True, denied_actions=1, limit_hit=None,
            model_used="m", provider_used="p", cost_usd=0.0, latency_sec=0.1,
            input_tokens=1, output_tokens=1,
        )
        res = CliRunner().invoke(code_main, ["-p", "do it", "--cwd", str(tmp_path)])
    assert res.exit_code == 5


def test_agent_cannot_silently_undo_its_own_edit(harness):
    ws, make = harness
    (ws / "calc.py").write_text("return a - b\n")
    REC.script = [
        call("Edit", {"path": "calc.py", "target_content": "return a - b", "replacement_content": "return a + b"}),
        call("Edit", {"path": "calc.py", "target_content": "return a + b", "replacement_content": "return a - b"}),
        "fixed",
    ]
    res = make().execute_turn("fix calc.py")
    assert res.completed
    assert (ws / "calc.py").read_text() == "return a + b\n"
    assert "would undo" in REC.calls[2]["messages"][-1]["content"]
