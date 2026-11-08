"""Native tool calling, text-mode fallback, streaming, and the shared routing engine."""

from __future__ import annotations

import json
import types

import pytest

from ijachi_router.agent import loop as loop_mod
from ijachi_router.agent.loop import AgentSessionLoop
from ijachi_router.config import ModelConfig, RouterConfig
from ijachi_router.context.assembler import ContextAssembler
from ijachi_router.fallback import reset_breakers
from ijachi_router.providers import REGISTRY
from ijachi_router.providers.anthropic_provider import AnthropicProvider
from ijachi_router.providers.base import Provider
from ijachi_router.providers.openai_compat import OpenAICompatibleProvider
from ijachi_router.session.events import CanonicalEvent
from ijachi_router.session.state import SessionState
from ijachi_router.session.store import SessionStore
from ijachi_router.ui.activity import StreamPrinter

CALLS: list[dict] = []
SCRIPT: list = []


class NativeFake(Provider):
    name = "nfake"
    native_tools = True
    supports_streaming = True

    def _call(self, prompt, **kw):
        CALLS.append(kw)
        step = SCRIPT.pop(0) if SCRIPT else "done"
        if isinstance(step, Exception):
            raise step
        if isinstance(step, tuple):  # (text, [tool calls])
            return step[0], 50, 10, step[1]
        cb = kw.get("on_text_delta")
        if cb:
            for word in step.split(" "):
                cb(word + " ")
        return step, 50, 10


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setitem(REGISTRY, "nfake", NativeFake)
    loop_mod._TEXT_ONLY_MODELS.clear()
    reset_breakers()
    CALLS.clear()
    SCRIPT.clear()
    w = tmp_path / "ws"
    w.mkdir()
    cfg = RouterConfig(models=[ModelConfig("nfake", "n1", ["code", "simple-qa"], 0.001, 0.002, 100_000, "fast", 3)],
                       available_providers={"nfake"})

    def make(mode="auto"):
        store = SessionStore(root_dir=tmp_path / "s", workspace_dir=w)
        return AgentSessionLoop(store, config=cfg, permission_mode=mode)

    yield w, make
    reset_breakers()


def test_native_tool_calls_round_trip_with_matching_ids(ws):
    w, make = ws
    (w / "a.py").write_text("x = 1\n")
    SCRIPT[:] = [("Let me look.", [{"id": "toolu_1", "name": "Read", "args": {"path": "a.py"}}]), "x is 1."]
    res = make().execute_turn("what is x in a.py?")
    assert res.completed and res.text == "x is 1."
    assert CALLS[0]["tools"] and {t["name"] for t in CALLS[0]["tools"]} >= {"Read", "Edit", "Bash"}
    # The native system prompt does not teach the JSON-in-text protocol.
    assert "single JSON code block" not in CALLS[0]["system"]
    msgs = CALLS[1]["messages"]
    asst = next(m for m in msgs if m.get("tool_calls"))
    tool = next(m for m in msgs if m["role"] == "tool")
    assert asst["tool_calls"][0] == {"id": "toolu_1", "name": "Read", "args": {"path": "a.py"}, "thought": "Let me look."}
    assert tool["tool_call_id"] == "toolu_1" and "x = 1" in tool["content"]


def test_parallel_native_calls_all_execute(ws):
    w, make = ws
    (w / "a.py").write_text("a\n")
    (w / "b.py").write_text("b\n")
    SCRIPT[:] = [("", [{"id": "c1", "name": "Read", "args": {"path": "a.py"}},
                       {"id": "c2", "name": "Read", "args": {"path": "b.py"}}]), "both read"]
    make().execute_turn("read both")
    ids = [m["tool_call_id"] for m in CALLS[1]["messages"] if m["role"] == "tool"]
    assert ids == ["c1", "c2"]


def test_model_rejecting_tools_falls_back_to_text_mode(ws):
    w, make = ws
    SCRIPT[:] = [RuntimeError("400: this model does not support tools"), "plain answer"]
    res = make().execute_turn("hello")
    assert res.text == "plain answer"
    assert "tools" in CALLS[0] and "tools" not in CALLS[1]
    assert "single JSON code block" in CALLS[1]["system"]
    assert "nfake/n1" in loop_mod._TEXT_ONLY_MODELS


def test_streamed_final_answer_is_printed_once(ws):
    w, make = ws
    out: list[str] = []
    loop = make()
    loop.stream_printer = StreamPrinter(write=out.append)
    SCRIPT[:] = ["The answer is 42."]
    res = loop.execute_turn("what is the answer?")
    assert res.streamed is True
    assert "".join(out).strip() == "The answer is 42."


def test_stream_printer_suppresses_tool_call_json():
    out: list[str] = []
    p = StreamPrinter(write=out.append)
    p.start(json_guard=True)
    for piece in ['{"too', 'l": "Read", "args": {}}']:
        p.feed(piece)
    assert p.end() == "" and out == []
    p.start(json_guard=True)
    for piece in ["Fi", "xed it", " now."]:
        p.feed(piece)
    assert p.end() == "Fixed it now." and "".join(out) == "Fixed it now.\n"


# ── Wire-format conversion ────────────────────────────────────────────────────

NEUTRAL = [
    {"role": "user", "content": "fix it"},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "name": "Read", "args": {"path": "a.py"}}]},
    {"role": "tool", "tool_call_id": "c1", "name": "Read", "content": "x = 1"},
    {"role": "user", "content": "go on"},
]
TOOLS = [{"name": "Read", "description": "read", "parameters": {"type": "object", "properties": {}}}]


def test_openai_wire_format():
    p = OpenAICompatibleProvider("m", {})
    msgs = p._chat_messages("", {"messages": NEUTRAL, "tools": TOOLS, "system": "sys"})
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert msgs[2]["tool_calls"][0]["function"] == {"name": "Read", "arguments": '{"path": "a.py"}'}
    assert msgs[3] == {"role": "tool", "tool_call_id": "c1", "content": "x = 1"}
    # Without native tools the same history is rendered as text.
    text = p._chat_messages("", {"messages": NEUTRAL, "system": "sys"})
    assert all("tool_calls" not in m for m in text) and '"tool": "Read"' in text[2]["content"]


def test_anthropic_wire_format():
    msgs = AnthropicProvider("m", {})._messages("", {"messages": NEUTRAL, "tools": TOOLS})
    assert msgs[1]["content"][0] == {"type": "tool_use", "id": "c1", "name": "Read", "input": {"path": "a.py"}}
    assert msgs[2]["role"] == "user"
    assert msgs[2]["content"][0] == {"type": "tool_result", "tool_use_id": "c1", "content": "x = 1"}
    assert msgs[2]["content"][1] == {"type": "text", "text": "go on"}


def test_openai_stream_accumulates_tool_call_deltas():
    def chunk(content=None, tcs=None, usage=None):
        delta = types.SimpleNamespace(content=content, tool_calls=tcs)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta)] if (content or tcs) else [], usage=usage)

    def tc(index, id=None, name=None, args=None):
        return types.SimpleNamespace(index=index, id=id, function=types.SimpleNamespace(name=name, arguments=args))

    chunks = [
        chunk(content="Reading "), chunk(tcs=[tc(0, "call_9", "Read", '{"pa')]), chunk(tcs=[tc(0, args='th": "a.py"}')]),
        chunk(usage=types.SimpleNamespace(prompt_tokens=11, completion_tokens=7)),
    ]

    class Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    assert kw["stream"] is True
                    return iter(chunks)

    seen: list[str] = []
    p = OpenAICompatibleProvider("m", {})
    text, i, o, calls, _usage = p._stream(Client, {"messages": []}, seen.append)
    assert text == "Reading " and seen == ["Reading "]
    assert (i, o) == (11, 7)
    assert calls == [{"id": "call_9", "name": "Read", "args": '{"path": "a.py"}'}]


def test_history_trimming_never_orphans_tool_results(tmp_path):
    state = SessionState("s", workspace_dir=tmp_path)
    events = []
    for i in range(30):
        events.append(CanonicalEvent(type="tool_call", tool_call={"id": f"c{i}", "name": "Read", "args": {"path": "x" * 400}}))
        events.append(CanonicalEvent(type="tool_result", content=[{"kind": "text", "text": "y" * 3000}], tool_call={"id": f"c{i}"}))
    events.append(CanonicalEvent(type="tool_call", tool_call={"id": "dangling", "name": "Bash", "args": {"command": "ls"}}))
    ctx = ContextAssembler(tmp_path).assemble(state, events, "", model_window=12_000, reserved_output=1000, native_tools=True)
    msgs = ctx.messages
    assert msgs and msgs[0]["role"] == "assistant" and msgs[0].get("tool_calls")  # trimmed at a group boundary
    call_ids = [c["id"] for m in msgs for c in m.get("tool_calls") or []]
    result_ids = [m["tool_call_id"] for m in msgs if m["role"] == "tool"]
    assert call_ids == result_ids and "dangling" in call_ids  # unanswered call gets a placeholder result


# ── Shared routing engine ─────────────────────────────────────────────────────

def test_one_shot_router_and_agent_use_the_same_engine(monkeypatch):
    from ijachi_router import core
    from ijachi_router.routing.engine import rank_models, simple_need

    cfg = RouterConfig(
        models=[
            ModelConfig("p", "cheap", ["code", "simple-qa"], 0.0001, 0.0002, 100_000, "fast", 2),
            ModelConfig("p", "mid", ["code", "simple-qa"], 0.001, 0.004, 100_000, "medium", 3),
            ModelConfig("p", "top", ["code", "simple-qa"], 0.004, 0.02, 100_000, "slow", 4),
        ],
        available_providers={"p"},
    )
    for priority in ("cheapest", "best", "efficient"):
        one_shot = [m.model_id for m in core._rank_models(cfg, "code", 0.3, priority=priority)]
        engine = [c.model.model_id for c in rank_models(cfg, simple_need("code", 1.0, 0.3), priority,
                                                        quality_floor=0, input_tokens=500).ranked]
        assert one_shot == engine
    assert core._rank_models(cfg, "code", 0.3, priority="cheapest")[0] == cfg.models[0]
    assert core._rank_models(cfg, "code", 0.9, priority="best")[0].model_id == "top"


def test_stickiness_does_not_override_a_clearly_cheaper_model():
    from ijachi_router.routing.engine import rank_models, simple_need

    cfg = RouterConfig(
        models=[
            ModelConfig("p", "free", ["simple-qa"], 0.0, 0.0, 100_000, "fast", 2),
            ModelConfig("p", "pricey", ["simple-qa"], 0.01, 0.03, 100_000, "medium", 3),
        ],
        available_providers={"p"},
    )
    need = simple_need("simple-qa", 1.0, 0.1)
    ranked = rank_models(cfg, need, "cheapest", current_model="pricey", cached_tokens=50_000, quality_floor=0).ranked
    assert ranked[0].model.model_id == "free"
    # ...but it still breaks near-ties in favour of the current model.
    tie = RouterConfig(models=[ModelConfig("p", "a", ["simple-qa"], 0.001, 0.001, 1000, "fast", 2),
                               ModelConfig("p", "b", ["simple-qa"], 0.001, 0.001, 1000, "fast", 2)],
                       available_providers={"p"})
    assert rank_models(tie, need, "efficient", current_model="b", quality_floor=0).ranked[0].model.model_id == "b"
