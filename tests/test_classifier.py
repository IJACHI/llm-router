"""Tests for ijachi_router/classifier.py."""
import pytest
from ijachi_router.classifier import predict_category, complexity_score


# ---------------------------------------------------------------------------
# predict_category
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prompt,expected", [
    ("Write a Python function to sort a list", "code"),
    ("Solve the integral of x squared", "math"),
    ("Write a poem about the ocean", "creative"),
    ("Summarize the key points of the article", "summarization"),
    ("What is the capital of France?", "simple-qa"),
    ("Analyze the trade-offs between SQL and NoSQL for a social network", "reasoning"),
])
def test_known_prompts(prompt, expected):
    category, confidence = predict_category(prompt)
    assert category == expected, (
        f"Expected '{expected}' for prompt: {prompt!r}, got '{category}' "
        f"(confidence={confidence})"
    )
    assert 0.0 <= confidence <= 1.0


def test_predict_returns_tuple():
    result = predict_category("Hello world")
    assert isinstance(result, tuple)
    assert len(result) == 2
    cat, conf = result
    assert isinstance(cat, str)
    assert isinstance(conf, float)


def test_predict_valid_category():
    valid = {"code", "math", "creative", "summarization", "reasoning",
             "long-context", "simple-qa"}
    for prompt in [
        "def foo(): pass",
        "What is 2+2?",
        "Write a short story",
    ]:
        cat, _ = predict_category(prompt)
        assert cat in valid, f"Unexpected category '{cat}'"


# ---------------------------------------------------------------------------
# complexity_score
# ---------------------------------------------------------------------------

def test_short_prompt_lower_complexity():
    short = "What is Python?"
    long = (
        "First, explain the history of Python. Then describe its type system. "
        "Next, compare it to Go. Also show an example of async code with error "
        "handling. Finally, discuss the GIL and its implications for performance."
    )
    assert complexity_score(short) < complexity_score(long)


def test_complexity_in_range():
    for prompt in ["Hi", "Explain quantum computing in detail with examples"]:
        score = complexity_score(prompt)
        assert 0.0 <= score <= 1.0, f"Score out of range: {score}"


def test_complexity_returns_float():
    result = complexity_score("test prompt")
    assert isinstance(result, float)
