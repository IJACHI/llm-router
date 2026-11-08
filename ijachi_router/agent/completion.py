"""Detect replies that end a turn before the task is actually finished.

A reply with no tool call normally ends the turn. Models (especially cheaper routed ones)
often stop early in recognisable ways:

* they narrate the next action instead of performing it ("Now I'll update the tests:"),
* they ask permission to keep going on a task they were already told to do,
* the output was cut off by the token limit,
* (text protocol) they emitted a tool call that could not be parsed.

``continuation_prompt`` returns an instruction to send back so the loop keeps working, or
``None`` when the reply looks like a genuine final answer. It is deliberately conservative
about ordinary closings ("Let me know if you need anything else", "Would you like me to also
add X?"), which are finished answers.
"""

from __future__ import annotations

import re

# First-person statement of an action about to be taken, at the end of the reply.
_INTENT_RE = re.compile(
    r"(?:^|[.!\n]\s*|\b(?:now|next|then|first|finally|so)\b,?\s+)"
    r"(?:i'?ll|i will|i'?m going to|i am going to|i need to|i'?m now going to|let me|let's|let us)\s+"
    r"(?!know\b|me know\b|be (?:happy|glad)\b|wait\b|stop\b|leave it\b)"
    r"(\w+)",
    re.IGNORECASE,
)
_ACTION_VERBS = {
    "add", "apply", "build", "change", "check", "create", "edit", "fix", "implement", "install",
    "look", "make", "modify", "move", "read", "refactor", "remove", "rename", "replace", "rerun",
    "re-run", "run", "search", "start", "test", "update", "verify", "write", "open", "inspect",
    "examine", "explore", "list", "view", "now", "proceed", "continue", "finish", "complete",
    "go", "do", "try", "debug", "investigate", "find", "set", "configure", "generate", "delete",
    "clean", "commit", "scaffold", "convert", "port", "migrate", "insert", "append", "adjust",
}
_PERMISSION_RE = re.compile(
    r"\b(?:shall|should|can|may) i (?:now )?(?:continue|proceed|go ahead|keep going|finish|complete|move on|carry on|start)"
    r"|\b(?:would|do) you (?:like|want) me to (?:now )?(?:continue|proceed|go ahead|keep going|finish|complete|move on|carry on)"
    r"|\blet me know (?:if|when|whether) (?:you(?:'d| would)? (?:like|want) me to )?(?:continue|proceed|go ahead|keep going)"
    r"|\bready (?:for me )?to (?:continue|proceed)\?",
    re.IGNORECASE,
)
_REMAINING_RE = re.compile(
    r"\b(?:i still need to|i(?:'ll| will) still need to|still (?:needs|need) to be (?:done|implemented|updated|fixed|written))\b"
    r"|\bremaining (?:steps|work|tasks|files|items) (?:are|is|will)\b",
    re.IGNORECASE,
)

TRUNCATED_PROMPT = (
    "Your previous reply was cut off by the output limit. Continue exactly where you stopped. "
    "If you were writing a large file, split the work: write a smaller part now and add the rest "
    "with further Edit/Write calls."
)
MALFORMED_PROMPT = (
    "Your last reply looked like a tool call but it was not valid, so nothing ran. Send the tool "
    "call again as a single valid JSON object."
)
EMPTY_PROMPT = (
    "Your last reply was empty, so nothing happened. Continue the task: call the next tool now, or "
    "give your final answer if everything is done."
)
PASTED_CODE_PROMPT = (
    "You put file contents in your reply instead of writing them, so no file was created. Use the "
    "Write tool to create each of those files now (one Write call per file)."
)
NO_CHANGES_PROMPT = (
    "No file has been created or changed yet, but the user asked you to build something. Create the "
    "files now with the Write tool, then run them to check they work. Only finish once the files exist."
)
UNFINISHED_PROMPT = (
    "You described the next step but did not perform it, so nothing happened. Do not stop or ask "
    "for permission: the user asked you to complete this task. Call the tool for that step now. "
    "Only give a final answer when the whole task is done (and verified where possible), or when "
    "you are blocked on something only the user can provide; then say exactly what is blocking you."
)


# Chat-template control tokens that small local models sometimes leak into replies.
_SPECIAL_TOKEN_RE = re.compile(r"<\|(?:im_start|im_end|endoftext|eot_id|end|start_header_id|end_header_id|assistant|user|system)\|>")

_BUILD_RE = re.compile(
    r"\b(?:build|create|make|scaffold|implement|develop|write|generate|set ?up|code)\b(?:\s+\w+){0,6}?\s+"
    r"(?:app|application|website|web ?site|site|page|api|server|backend|frontend|service|bot|script|program|"
    r"tool|game|dashboard|project|cli|library|module|file|files|newsletter|platform|component|extension)s?\b",
    re.IGNORECASE,
)
# A fenced block whose first line names a file path, e.g. "# src/main.py" or "<!-- index.html -->".
_PASTED_FILE_RE = re.compile(
    r"```[\w+-]*\n\s*(?:#|//|<!--|/\*|--)\s*[\w./-]+\.(?:py|js|ts|tsx|jsx|html|css|json|toml|yaml|yml|md|sh|go|rs|java|rb|php|sql)\b"
)


def clean_reply(text: str) -> str:
    """Strip leaked chat-template tokens."""
    return _SPECIAL_TOKEN_RE.sub("", text or "").strip()


def is_build_request(message: str) -> bool:
    return bool(_BUILD_RE.search(message or ""))


def _tail(text: str, chars: int = 400) -> str:
    text = text.strip()
    # Ignore trailing code fences: intent is expressed in prose.
    text = re.sub(r"```[\s\S]*?```\s*$", "", text).strip()
    return text[-chars:]


def looks_unfinished(answer: str) -> bool:
    """True when the reply ends by announcing work it did not do, or asks to continue."""
    if not answer or not answer.strip():
        return False
    tail = _tail(answer)
    if _PERMISSION_RE.search(tail) or _REMAINING_RE.search(tail):
        return True
    # Announcing the next action: check the last sentence or two only.
    last = re.split(r"(?<=[.!?])\s+(?=[A-Z])", tail)[-2:]
    window = " ".join(last)
    for m in _INTENT_RE.finditer(window):
        if m.group(1).lower() in _ACTION_VERBS:
            return True
    # "Here is the updated file:" / "Next steps:" with nothing after it.
    return tail.rstrip().endswith(":")


def looks_like_broken_tool_call(resp_text: str) -> bool:
    return bool(re.search(r'[{,]\s*"(?:tool|name)"\s*:\s*"\w+"', resp_text or ""))


def continuation_prompt(
    answer: str,
    resp_text: str,
    *,
    truncated: bool = False,
    native: bool = True,
    parsed: dict | None = None,
    check_intent: bool = True,
    build_request: bool = False,
    files_changed: int = 0,
) -> str | None:
    """Instruction to continue the turn, or None when the reply is a real final answer.

    ``build_request``: the user asked for something to be built; with ``files_changed == 0``
    a "done" answer is not accepted (once; the caller bounds how often it asks).
    """
    if truncated:
        return TRUNCATED_PROMPT
    if not clean_reply(resp_text) and not clean_reply(answer):
        return EMPTY_PROMPT
    if not native:
        if parsed is not None and "final_answer" not in parsed and not (parsed.get("tool") or parsed.get("name")):
            return MALFORMED_PROMPT  # e.g. {"thought": "..."} with no tool and no answer
        if parsed is None and looks_like_broken_tool_call(resp_text):
            return MALFORMED_PROMPT
        if parsed is not None and "final_answer" in parsed:
            answer = str(parsed.get("final_answer") or "")
    if not check_intent:
        return None
    if files_changed == 0 and _PASTED_FILE_RE.search(answer or resp_text or ""):
        return PASTED_CODE_PROMPT
    if looks_unfinished(answer):
        return UNFINISHED_PROMPT
    if build_request and files_changed == 0:
        return NO_CHANGES_PROMPT
    return None
