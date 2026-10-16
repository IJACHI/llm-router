"""Tests for User-Configurable Routing Preference Modes and Autonomy Levels.

Covers:
1. 4 Routing Preference Modes:
   - efficient (Default): Balances cost and best fit (cheapest adequate model)
   - cheapest: Preference for only cheapest/free models
   - best: Preference for best models/providers (high quality bias)
   - best-fit: Best fit models/providers for the task irrespective of cost
2. 3 Autonomy Levels:
   - auto (Fully automatic): No need for user approvals for safe actions
   - semi-auto (Semi-automatic): Approvals for some activities (auto-approves edits, asks for shell)
   - manual (Manual): Needs approval for every major activity
3. REPL commands and interactive toggling (/mode, /autonomy, /auto).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from ijachi_router.agent.permissions import PermissionManager, normalize_permission_mode
from ijachi_router.config import ModelConfig, normalize_mode
from ijachi_router.routing.features import extract_session_need
from ijachi_router.routing.policy import filter_candidates
from ijachi_router.routing.scorer import score_candidate
from ijachi_router.session.state import SessionState
from ijachi_router.session.store import SessionStore
from ijachi_router.ui.render import format_status_line
from ijachi_router.ui.repl import InteractiveREPL


def test_normalize_mode_aliases():
    assert normalize_mode(None) == "efficient"
    assert normalize_mode("") == "efficient"
    assert normalize_mode("efficient") == "efficient"
    assert normalize_mode("balanced") == "efficient"
    assert normalize_mode("1") == "efficient"

    assert normalize_mode("cheapest") == "cheapest"
    assert normalize_mode("cost") == "cheapest"
    assert normalize_mode("free") == "cheapest"
    assert normalize_mode("2") == "cheapest"

    assert normalize_mode("best") == "best"
    assert normalize_mode("quality") == "best"
    assert normalize_mode("pro") == "best"
    assert normalize_mode("3") == "best"

    assert normalize_mode("best-fit") == "best-fit"
    assert normalize_mode("unconstrained") == "best-fit"
    assert normalize_mode("max-quality") == "best-fit"
    assert normalize_mode("4") == "best-fit"


def test_four_routing_modes_scoring():
    free_adequate = ModelConfig(
        provider="local",
        model_id="qwen2.5-coder:7b",
        tags=["code"],
        input_per_1k=0.0,
        output_per_1k=0.0,
        max_context=32768,
        speed_tier="fast",
        quality_tier=2,
    )
    frontier_expensive = ModelConfig(
        provider="anthropic",
        model_id="claude-sonnet-4-5",
        tags=["code", "reasoning"],
        input_per_1k=0.010,
        output_per_1k=0.050,
        max_context=200000,
        speed_tier="medium",
        quality_tier=4,
    )
    state = SessionState(session_id="test_modes")
    need = extract_session_need("refactor database layer", state, "code", 0.9, 0.5)

    # 1. Cheapest mode: Free model wins overwhelmingly
    s_free_cheap = score_candidate(free_adequate, need, priority="cheapest")
    s_front_cheap = score_candidate(frontier_expensive, need, priority="cheapest")
    assert s_free_cheap > s_front_cheap

    # 2. Best mode: Frontier quality model wins despite price
    s_free_best = score_candidate(free_adequate, need, priority="best")
    s_front_best = score_candidate(frontier_expensive, need, priority="best")
    assert s_front_best > s_free_best

    # 3. Best-Fit mode: Irrespective of cost (pure quality + capability fit)
    s_free_fit = score_candidate(free_adequate, need, priority="best-fit")
    s_front_fit = score_candidate(frontier_expensive, need, priority="best-fit")
    assert s_front_fit > s_free_fit

    # 4. Efficient mode (Default): For moderate complexity (0.5), free adequate model wins
    s_free_eff = score_candidate(free_adequate, need, priority="efficient")
    s_front_eff = score_candidate(frontier_expensive, need, priority="efficient")
    assert s_free_eff > s_front_eff


def test_best_fit_mode_bypasses_cost_cap():
    expensive_model = ModelConfig(
        provider="anthropic",
        model_id="claude-sonnet-4-5",
        tags=["code"],
        input_per_1k=0.01,
        output_per_1k=0.05,
        max_context=200000,
        speed_tier="medium",
        quality_tier=4,
    )
    state = SessionState(session_id="test_cap")
    need = extract_session_need("complex refactor", state, "code", 0.9, 0.7)

    # In efficient mode with $0.0001 cap: filtered out
    eligible_eff, reasons_eff = filter_candidates(
        candidates=[expensive_model],
        need=need,
        max_cost_per_turn=0.0001,
        priority="efficient",
    )
    assert len(eligible_eff) == 0

    # In best-fit mode: cost cap is bypassed irrespective of cost
    eligible_fit, reasons_fit = filter_candidates(
        candidates=[expensive_model],
        need=need,
        max_cost_per_turn=0.0001,
        priority="best-fit",
    )
    assert len(eligible_fit) == 1
    assert eligible_fit[0].model_id == "claude-sonnet-4-5"


def test_autonomy_modes_authorization(tmp_path):
    # 1. Fully Automatic mode: File edits and safe bash commands run without approval
    pm_auto = PermissionManager(mode="auto", is_tty=True)
    res_edit = pm_auto.authorize_tool_call("Edit", {"path": "main.py"}, workspace_dir=tmp_path)
    assert res_edit.allowed is True

    res_bash = pm_auto.authorize_tool_call("Bash", {"command": "pytest"}, workspace_dir=tmp_path)
    assert res_bash.allowed is True

    # 2. Semi-Automatic mode: File edits auto-approved, but shell execution prompts
    pm_semi = PermissionManager(mode="semi-auto", is_tty=False)
    res_semi_edit = pm_semi.authorize_tool_call("Edit", {"path": "main.py"}, workspace_dir=tmp_path)
    assert res_semi_edit.allowed is True

    # Non-interactive without TTY, shell execution is denied (prompts in TTY)
    res_semi_bash = pm_semi.authorize_tool_call("Bash", {"command": "pytest"}, workspace_dir=tmp_path)
    assert res_semi_bash.allowed is False

    # 3. Manual mode: Needs approval for every major activity
    pm_manual = PermissionManager(mode="manual", is_tty=False)
    res_man_edit = pm_manual.authorize_tool_call("Edit", {"path": "main.py"}, workspace_dir=tmp_path)
    assert res_man_edit.allowed is False


def test_repl_mode_and_autonomy_toggle(tmp_path):
    store = SessionStore(workspace_dir=tmp_path)
    repl = InteractiveREPL(store=store, priority="efficient", permission_mode="manual")

    # Initial state
    assert repl.state.priority == "efficient"
    assert repl.loop.permissions.mode == "manual"

    # Toggle autonomy via /auto
    repl.handle_slash_command("/auto")
    assert repl.loop.permissions.mode == "semi-auto"

    repl.handle_slash_command("/auto")
    assert repl.loop.permissions.mode == "auto"

    repl.handle_slash_command("/auto")
    assert repl.loop.permissions.mode == "manual"

    # Switch mode via /mode
    repl.handle_slash_command("/mode cheapest")
    assert repl.state.priority == "cheapest"

    repl.handle_slash_command("/mode best-fit")
    assert repl.state.priority == "best-fit"

    # Switch autonomy explicitly via /autonomy
    repl.handle_slash_command("/autonomy auto")
    assert repl.loop.permissions.mode == "auto"

    # Verify status line displays both modes
    status = repl._toolbar_fn()
    assert "best-fit" in status
    assert "auto" in status


def test_automatic_tech_stack_determination(tmp_path):
    from ijachi_router.routing.architect import detect_and_determine_tech_stack
    state = SessionState(session_id="test_stack", workspace_dir=tmp_path)

    # 1. Unspecified stack on medical newsletter creation
    prompt = "build me an automated weekly medical newsletter website that aggregates and summarizes new medical papers from pubmed"
    rec = detect_and_determine_tech_stack(prompt, tmp_path, state)
    assert rec is not None
    assert "FastAPI" in rec.name
    assert "SQLite" in rec.name
    assert "APScheduler" in rec.name

    # Decision is committed to session ledger
    assert any("tech stack" in e.fact.lower() for e in state.ledger.entries)

    # 2. Subsequent check skips because already determined in ledger
    rec_second = detect_and_determine_tech_stack(prompt, tmp_path, state)
    assert rec_second is None

    # 3. User explicitly specifies stack ("in Flask") -> should skip determination
    state2 = SessionState(session_id="test_stack_explicit", workspace_dir=tmp_path)
    rec_explicit = detect_and_determine_tech_stack("build this app in Flask", tmp_path, state2)
    assert rec_explicit is None

    # 4. Project already has package.json -> should skip determination
    (tmp_path / "package.json").write_text("{}")
    state3 = SessionState(session_id="test_stack_pkg", workspace_dir=tmp_path)
    rec_existing = detect_and_determine_tech_stack("build user dashboard", tmp_path, state3)
    assert rec_existing is None


def test_catchy_spinner_and_activity():
    from ijachi_router.ui.activity import CatchyStatusSpinner, render_routing_badge, render_thought_stream, render_tool_activity

    # Catchy spinner context manager
    with CatchyStatusSpinner(initial_phrase="Thinking...") as spinner:
        assert spinner is not None

    # Transparent rendering functions - collapsed by default
    render_routing_badge("qwen2.5-coder:7b", "local", 0.0, "highest score", quality_tier=2)
    render_thought_stream("Analyzing PubMed API query to design clean schemas...", expanded=False)
    render_thought_stream("Detailed thought process with full reasoning...", expanded=True)

    # Intelligently collapsed tool activities
    render_tool_activity("Read", {"path": "src/app.py"}, success=True, output="line1\nline2\nline3")
    render_tool_activity("Write", {"path": "main.py", "content": "import fastapi\napp = fastapi.FastAPI()"}, success=True)
    render_tool_activity("Edit", {"path": "main.py"}, success=True, diff="+line1\n-line2")
    render_tool_activity("Bash", {"command": "pytest"}, success=True, output="147 passed in 4.26s")
    render_tool_activity("Bash", {"command": "pytest"}, success=False, output="FAILED test_bad.py:10")
    render_tool_activity("Grep", {"query": "FastAPI"}, success=True, output="main.py:1\nmain.py:2")
    render_tool_activity("Glob", {"pattern": "*.py"}, success=True, output="main.py\nutils.py")
    render_tool_activity("ListDir", {"path": "."}, success=True, output="main.py\nrequirements.txt")


def test_verbose_and_thoughts_slash_commands(tmp_path):
    store = SessionStore(workspace_dir=tmp_path)
    repl = InteractiveREPL(store=store)

    # Test /verbose toggle
    assert repl.loop.verbose is False
    repl.handle_slash_command("/verbose")
    assert repl.loop.verbose is True
    repl.handle_slash_command("/verbose")
    assert repl.loop.verbose is False

    # Test /thoughts
    repl.loop.last_thought = "Designing modular router components"
    assert repl.handle_slash_command("/thoughts") is False


def test_bold_ascii_banner_art():
    from ijachi_router.ui import _BANNER_ART, get_neon_banner
    assert _BANNER_ART is not None
    # Verify solid block characters and non-empty lines
    lines = [l for l in _BANNER_ART.splitlines() if l.strip()]
    assert len(lines) == 5
    for line in lines:
        assert "██" in line

    panel = get_neon_banner()
    assert panel is not None


def test_extract_json_call_fallback():
    from ijachi_router.agent.loop import AgentSessionLoop

    # 1. JSON code block
    t1 = '```json\n{"tool": "ListDir", "args": {"path": "."}}\n```'
    assert AgentSessionLoop._extract_json_call(t1)["tool"] == "ListDir"

    # 2. Raw JSON
    t2 = '{"tool": "Bash", "args": {"command": "pytest"}}'
    assert AgentSessionLoop._extract_json_call(t2)["tool"] == "Bash"

    # 3. Inline function call fallback
    t3 = 'Step 2: List files\nListDir(".")\nPlease provide output.'
    res = AgentSessionLoop._extract_json_call(t3)
    assert res is not None
    assert res["tool"] == "ListDir"
    assert res["args"] == {"path": "."}

    # 4. Bash inline function call fallback
    t4 = 'Run server:\nBash("uvicorn main:app --reload")'
    res4 = AgentSessionLoop._extract_json_call(t4)
    assert res4 is not None
    assert res4["tool"] == "Bash"
    assert res4["args"] == {"command": "uvicorn main:app --reload"}


    # 5. Model output with Python triple quotes (""")
    t5 = '''
    {
      "thought": "Creating a basic FastAPI application to fetch research articles.",
      "tool": "Edit",
      "args": {
        "path": "./main.py",
        "target_content": "",
        "replacement_content": """
from fastapi import FastAPI, HTTPException
import requests

app = FastAPI()
"""
      }
    }
    '''
    res5 = AgentSessionLoop._extract_json_call(t5)
    assert res5 is not None
    assert res5["tool"] == "Edit"
    assert res5["args"]["path"] == "./main.py"
    assert "FastAPI" in res5["args"]["replacement_content"]


def test_tool_edit_auto_creates_nonexistent_file(tmp_path):
    from ijachi_router.agent.sandbox import WorkspaceSandbox
    from ijachi_router.agent.tools import ToolRuntime
    from ijachi_router.session.checkpoints import CheckpointManager

    state = SessionState(session_id="test_edit_create", workspace_dir=tmp_path)
    sandbox = WorkspaceSandbox(tmp_path)
    cp = CheckpointManager(checkpoints_dir=tmp_path / "checkpoints")
    tools = ToolRuntime(sandbox, state, cp)

    target_file = tmp_path / "main.py"
    assert not target_file.exists()

    # Model calls Edit with replacement_content on non-existent file
    res = tools.tool_edit({
        "path": "main.py",
        "target_content": "",
        "replacement_content": "from fastapi import FastAPI\napp = FastAPI()\n",
    })

    assert res.success is True
    assert target_file.exists()
    assert "FastAPI" in target_file.read_text()


def test_architect_skips_run_and_execution_commands(tmp_path):
    from ijachi_router.routing.architect import detect_and_determine_tech_stack
    state = SessionState(session_id="test_run_skip", workspace_dir=tmp_path)

    # "run the application in this directory" should NOT trigger architecture determination
    assert detect_and_determine_tech_stack("run the application in this directory", tmp_path, state) is None
    assert detect_and_determine_tech_stack("start the server", tmp_path, state) is None
    assert detect_and_determine_tech_stack("test the app", tmp_path, state) is None


def test_permission_prompt_natural_responses(tmp_path, monkeypatch):
    from ijachi_router.agent.permissions import PermissionManager, _sanitize_terminal_input

    # Test "yes" natural response
    pm = PermissionManager(mode="manual", is_tty=True)
    pm.is_tty = True  # force interactive for test
    monkeypatch.setattr(pm, "_prompt_approval", lambda *args, **kwargs: "yes")
    res_yes = pm.authorize_tool_call("Write", {"path": "test.txt", "content": "hi"}, workspace_dir=tmp_path)
    assert res_yes.allowed is True

    # Test "yep"
    monkeypatch.setattr(pm, "_prompt_approval", lambda *args, **kwargs: "yep")
    res_yep = pm.authorize_tool_call("Write", {"path": "test.txt", "content": "hi"}, workspace_dir=tmp_path)
    assert res_yep.allowed is True

    # Test "always"
    monkeypatch.setattr(pm, "_prompt_approval", lambda *args, **kwargs: "always")
    res_always = pm.authorize_tool_call("Write", {"path": "test.txt", "content": "hi"}, workspace_dir=tmp_path)
    assert res_always.allowed is True

    # Test "session"
    monkeypatch.setattr(pm, "_prompt_approval", lambda *args, **kwargs: "session")
    res_session = pm.authorize_tool_call("Write", {"path": "test.txt", "content": "hi"}, workspace_dir=tmp_path)
    assert res_session.allowed is True

    # Test "no" and default deny
    monkeypatch.setattr(pm, "_prompt_approval", lambda *args, **kwargs: "no")
    res_no = pm.authorize_tool_call("Bash", {"command": "rm -rf /tmp/foo"}, workspace_dir=tmp_path)
    assert res_no.allowed is False


def test_permission_prompt_explain_and_reprompt(tmp_path, monkeypatch):
    from ijachi_router.agent.permissions import PermissionManager

    pm = PermissionManager(mode="manual", is_tty=True)
    pm.is_tty = True

    # Simulate user typing "e" first, then "yes"
    inputs = iter(["explain", "yes"])
    monkeypatch.setattr(pm, "_prompt_approval", lambda *args, **kwargs: next(inputs))

    res = pm.authorize_tool_call(
        tool_name="Bash",
        args={"command": "npm install"},
        workspace_dir=tmp_path,
        why_needed="Need packages for server",
    )
    assert res.allowed is True


def test_terminal_sanitization_and_spinner_cleanup():
    from ijachi_router.agent.permissions import _sanitize_terminal_input
    from ijachi_router.ui.activity import CatchyStatusSpinner, ensure_spinners_stopped, _ACTIVE_SPINNERS

    # Test terminal sanitization runs safely without raising
    _sanitize_terminal_input()

    # Test active spinner registration and cleanup
    spinner = CatchyStatusSpinner(initial_phrase="Thinking...")
    spinner.start()
    assert spinner in _ACTIVE_SPINNERS
    assert spinner._thread.is_alive()

    ensure_spinners_stopped()
    assert len(_ACTIVE_SPINNERS) == 0
    assert not spinner._thread.is_alive()




