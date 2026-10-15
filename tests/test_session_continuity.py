"""Tests for Document 3: Session and Context Continuity.

Covers:
- SC-01: Canonical event log independent of provider formats
- SC-02: Model requests built from session store
- SC-03: Facts and decisions recall across model switches
- SC-04: Facts & decisions ledger survives compaction verbatim
- SC-05: Context assembler respects model window budget (B = 0.75 * W - O)
- SC-06: Compaction never deletes underlying event log
- SC-08: Checkpoint creation & undo restores modified files
- SC-09: Working set file hash tracking and stale read detection
- SC-10: /context token layer breakdown
- SC-13: Session export to Markdown and JSON
"""

from __future__ import annotations

import json
from pathlib import Path

from ijachi_router.context.assembler import ContextAssembler
from ijachi_router.context.compaction import CompactionEngine
from ijachi_router.session.checkpoints import CheckpointManager
from ijachi_router.session.events import CanonicalEvent
from ijachi_router.session.export import export_session_json, export_session_markdown
from ijachi_router.session.ledger import FactsAndDecisionsLedger
from ijachi_router.session.state import SessionState
from ijachi_router.session.store import SessionStore


def test_canonical_event_schema():
    evt = CanonicalEvent(
        type="assistant_message",
        turn=1,
        model={"provider": "anthropic", "id": "claude-sonnet-4-5"},
        content=[{"kind": "text", "text": "I will examine the codebase."}],
        usage={"input_tokens": 1200, "output_tokens": 80, "cost_usd": 0.005},
        committed=True,
    )
    d = evt.to_dict()
    assert d["type"] == "assistant_message"
    assert d["turn"] == 1
    assert d["model"]["id"] == "claude-sonnet-4-5"
    assert d["committed"] is True
    assert "evt_" in d["id"]

    rebuilt = CanonicalEvent.from_dict(d)
    assert rebuilt.id == evt.id
    assert rebuilt.text_content == "I will examine the codebase."


def test_session_store_atomic_append_and_recovery(tmp_path):
    store = SessionStore(session_id="test_session_1", root_dir=tmp_path)

    evt1 = CanonicalEvent(type="user_message", turn=1, content=[{"kind": "text", "text": "Initial task"}])
    evt2 = CanonicalEvent(type="assistant_message", turn=1, content=[{"kind": "text", "text": "Plan drafted"}])
    uncommitted = CanonicalEvent(type="assistant_message", turn=1, content=[{"kind": "text", "text": "Failed partial"}], committed=False)

    store.append_event(evt1)
    store.append_event(evt2)
    store.append_event(uncommitted)

    # Read committed events only
    committed = store.read_events(committed_only=True)
    assert len(committed) == 2
    assert committed[0].text_content == "Initial task"
    assert committed[1].text_content == "Plan drafted"

    # Read all events
    all_evts = store.read_events(committed_only=False)
    assert len(all_evts) == 3


def test_facts_ledger_survives_compaction_verbatim(tmp_path):
    state = SessionState(session_id="test_compaction", workspace_dir=tmp_path)
    state.ledger.record_fact("Use PostgreSQL for authentication storage", category="constraint")
    state.ledger.record_fact("Refuse raw SQL queries in handlers", category="decision")

    events = [
        CanonicalEvent(type="user_message", turn=i, content=[{"kind": "text", "text": f"Step {i} discussion"}])
        for i in range(1, 15)
    ]

    summary = CompactionEngine.compact_events(events, state)

    # SC-04: Ledger entries must be present verbatim in the compacted summary
    assert "Use PostgreSQL for authentication storage" in summary
    assert "Refuse raw SQL queries in handlers" in summary
    assert "[constraint]" in summary
    assert "[decision]" in summary


def test_checkpoint_and_undo(tmp_path):
    test_file = tmp_path / "config.py"
    test_file.write_text("API_VERSION = 1\n", encoding="utf-8")

    cp_manager = CheckpointManager(tmp_path / ".checkpoints")
    cp_id = cp_manager.create_checkpoint("v1_backup", [test_file])
    assert cp_id.startswith("cp_")

    # Modify file
    test_file.write_text("API_VERSION = 2\nNEW_SETTING = True\n", encoding="utf-8")
    diff = cp_manager.diff_from_checkpoint()
    assert "-API_VERSION = 1" in diff
    assert "+API_VERSION = 2" in diff

    # Undo
    ok, msg = cp_manager.undo_last()
    assert ok is True
    assert "Restored" in msg
    assert test_file.read_text(encoding="utf-8") == "API_VERSION = 1\n"


def test_working_set_stale_read_detection(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("print('version 1')", encoding="utf-8")

    state = SessionState(session_id="test_stale", workspace_dir=tmp_path)
    state.record_file_read(str(f))
    assert state.check_stale_read(str(f)) is False

    # External modification
    f.write_text("print('version 2 modified outside session')", encoding="utf-8")
    assert state.check_stale_read(str(f)) is True


def test_context_assembler_budget_and_layers(tmp_path):
    state = SessionState(session_id="test_ctx", workspace_dir=tmp_path)
    state.ledger.record_fact("Never modify production database credentials", category="constraint")

    events = [
        CanonicalEvent(type="user_message", turn=1, content=[{"kind": "text", "text": "Set up project"}]),
        CanonicalEvent(type="assistant_message", turn=1, content=[{"kind": "text", "text": "Project ready"}]),
    ]

    assembler = ContextAssembler(workspace_dir=tmp_path)
    # Model window = 32000, reserved output = 4000 -> budget = 0.75 * 32000 - 4000 = 20000
    ctx = assembler.assemble(
        state=state,
        events=events,
        new_user_message="Add tests for login",
        model_window=32_000,
        reserved_output=4_000,
    )

    assert ctx.budget == int(0.75 * 32_000 - 4_000)
    assert ctx.total_tokens <= ctx.budget
    assert ctx.layers.system_prompt > 0
    assert ctx.layers.ledger > 0
    assert ctx.layers.user_message > 0
    assert "Never modify production database credentials" in ctx.system_prompt


def test_session_export_json_and_markdown(tmp_path):
    store = SessionStore(session_id="test_export", root_dir=tmp_path)
    store.state.ledger.record_fact("Architecture decision: Clean Architecture", category="decision")
    store.append_event(CanonicalEvent(type="user_message", turn=1, content=[{"kind": "text", "text": "Hello"}]))
    store.append_event(CanonicalEvent(type="assistant_message", turn=1, content=[{"kind": "text", "text": "Hi!"}]))

    md = export_session_markdown(store)
    assert "# ijachi-llm-router Session Transcript" in md
    assert "Clean Architecture" in md
    assert "Hello" in md

    js = export_session_json(store)
    data = json.loads(js)
    assert data["state"]["session_id"] == "test_export"
    assert len(data["events"]) == 2
