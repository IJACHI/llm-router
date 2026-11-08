"""The agent must not end a turn early: narrated-but-not-done steps, permission questions,
truncated output and unparseable tool calls all continue the turn automatically."""

from __future__ import annotations

import pytest

from ijachi_router.agent.completion import continuation_prompt, looks_unfinished
from tests.test_claims_regression import REC, FakeProvider, call, harness  # noqa: F401


@pytest.mark.parametrize("text", [
    "I found the bug in utils.py. Now I'll update the tests to cover it.",
    "The parser is fixed. Next, I will run the test suite.",
    "Let me check the config file next.",
    "I've created the models. Shall I continue with the API routes?",
    "Step 1 is done. Would you like me to proceed with step 2?",
    "Here is the updated version of main.py:",
    "Done with the backend. I still need to wire up the frontend.",
    "Let's run the tests to verify.",
])
def test_unfinished_replies_are_detected(text):
    assert looks_unfinished(text)


@pytest.mark.parametrize("text", [
    "Fixed the off-by-one error in paginate(); all 12 tests pass.",
    "Done. Let me know if you need anything else!",
    "The function returns the sum of the list. Let me know if you'd like more detail.",
    "I've added the endpoint and tests. Would you like me to also add rate limiting?",
    "Yes, `sqlite3` is part of the standard library.",
    "I'll be happy to help with anything else.",
    "",
])
def test_finished_replies_are_accepted(text):
    assert not looks_unfinished(text)


def test_truncation_and_broken_calls_always_continue():
    assert continuation_prompt("partial", "partial", truncated=True)
    assert continuation_prompt("", '{"tool": "Write", "args": {"path": "a.py", "content": "x', native=False)
    assert continuation_prompt("", "", native=False, parsed={"thought": "thinking"})
    assert continuation_prompt("ok", "ok", native=False, parsed={"final_answer": "All tests pass."}) is None


def test_intent_check_can_be_disabled_after_a_denial():
    assert continuation_prompt("I need to write the file.", "", check_intent=False) is None


def test_turn_continues_after_announcing_a_step(harness):  # noqa: F811
    ws, make = harness
    REC.script = [
        call("Write", {"path": "a.py", "content": "a = 1\n"}),
        "Created a.py. Now I'll create b.py.",           # used to end the turn here
        call("Write", {"path": "b.py", "content": "b = 1\n"}),
        "Created a.py and b.py.",
    ]
    res = make().execute_turn("create a.py and b.py")
    assert res.completed
    assert (ws / "b.py").exists()
    assert res.text == "Created a.py and b.py."
    assert any("did not perform it" in str(c["prompt"]) or "did not perform it" in str(c.get("messages"))
               for c in REC.calls[3:4])


def test_truncated_reply_is_continued(harness):  # noqa: F811
    ws, make = harness
    replies = [("def f():\n    return", True), ("Finished writing f.", False)]
    original = FakeProvider._call

    def fake(self, prompt, **kw):
        REC.calls.append({"prompt": prompt, **kw})
        text, cut = replies.pop(0)
        return text, 100, 20, [], {"truncated": cut}

    FakeProvider._call = fake
    try:
        res = make().execute_turn("write f")
    finally:
        FakeProvider._call = original
    assert res.completed and res.text == "Finished writing f."
    assert len(REC.calls) == 2


def test_continuations_are_bounded(harness):  # noqa: F811
    ws, make = harness
    REC.script = ["Now I'll start."] * 10
    res = make().execute_turn("do the thing")
    assert res.completed  # gives up nudging after the cap and returns the answer
    assert len(REC.calls) == 4  # 1 reply + 3 continuations


def test_plan_mode_does_not_push_for_changes(harness):  # noqa: F811
    ws, make = harness
    REC.script = ["Plan: first I'll edit a.py, then I'll run the tests."]
    res = make(permission_mode="plan").execute_turn("plan the refactor")
    assert res.completed and len(REC.calls) == 1


# ── Failure modes seen in a real session with a local 7B model ──────────────

def test_empty_or_control_token_reply_continues():
    from ijachi_router.agent.completion import EMPTY_PROMPT
    assert continuation_prompt("", "") == EMPTY_PROMPT
    assert continuation_prompt("<|im_start|>", "<|im_start|>") == EMPTY_PROMPT


def test_pasted_file_contents_are_not_accepted():
    from ijachi_router.agent.completion import PASTED_CODE_PROMPT
    reply = "Here is the backend.\n\n```python\n# medfrontier/src/main.py\nfrom fastapi import FastAPI\n```\nDone."
    assert continuation_prompt(reply, reply) == PASTED_CODE_PROMPT
    assert continuation_prompt(reply, reply, files_changed=2) is None


def test_build_request_without_any_files_is_not_done():
    from ijachi_router.agent.completion import NO_CHANGES_PROMPT, is_build_request
    assert is_build_request("build me a automated weekly medical newsletter website")
    assert is_build_request("create a REST api for todos")
    assert not is_build_request("what does this function return?")
    assert continuation_prompt("The website is ready.", "x", build_request=True) == NO_CHANGES_PROMPT
    assert continuation_prompt("The website is ready.", "x", build_request=True, files_changed=3) is None


def test_build_prompts_route_as_complex():
    from ijachi_router.routing.classifier import complexity_score
    assert complexity_score("build me a newsletter website") >= 0.75
    assert complexity_score("fix the typo in README.md") < 0.4


def test_all_text_written_tool_calls_run(harness):  # noqa: F811
    ws, make = harness
    reply = (
        "Creating the structure:\n```json\n"
        '{"name": "Bash", "arguments": {"command": "mkdir src"}}\n'
        '{"name": "Write", "arguments": {"path": "src/app.py", "content": "print(1)\\n"}}\n'
        '{"name": "Write", "arguments": {"path": "README.md", "content": "# app\\n"}}\n```'
    )
    REC.script = [reply, "Created src/app.py and README.md."]
    res = make().execute_turn("build me a small app")
    assert (ws / "src" / "app.py").read_text() == "print(1)\n"
    assert (ws / "README.md").exists()
    assert res.completed and res.text == "Created src/app.py and README.md."


def test_claimed_done_build_with_no_files_is_pushed_once(harness):  # noqa: F811
    ws, make = harness
    REC.script = ["Your website is complete!", call("Write", {"path": "index.html", "content": "<h1>hi</h1>"}), "Created index.html."]
    res = make().execute_turn("build me a website")
    assert (ws / "index.html").exists() and res.text == "Created index.html."


def test_follow_up_question_inherits_the_build_request(harness):  # noqa: F811
    ws, make = harness
    loop = make()
    REC.script = ["Plan made.", "Still planning."]
    loop.execute_turn("build me a website")
    REC.script = ["Yes, I am done.", call("Write", {"path": "index.html", "content": "x"}), "Now it is done."]
    res = loop.execute_turn("are you done?")
    assert (ws / "index.html").exists() and res.text == "Now it is done."
