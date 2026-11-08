"""Prompt classifier: predicts category + confidence, plus a complexity score.

Category prediction delegates to the single shared model in ``routing.classifier``
(JSON weights bundled with the package; no pickle, no scikit-learn needed at runtime).
The keyword rules below remain as a fallback.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_CACHE_DIR = Path.home() / ".ijachi-llmr"
_MODEL_PATH = _CACHE_DIR / "classifier.pkl"
_DATA_PATH = Path(__file__).parent.parent / "data" / "train_data.csv"

# ---------------------------------------------------------------------------
# Keyword heuristics fallback
# ---------------------------------------------------------------------------
_KEYWORD_RULES: list[tuple[str, list[str]]] = [
    ("code", [
        "def ", "function ", "class ", "import ", "```", "sql", "api",
        "bug", "error", "exception", "debug", "refactor", "test", "regex",
        "algorithm", "script", "async", "await", "loop", "array", "variable",
        "compile", "runtime", "syntax",
    ]),
    ("math", [
        "integral", "derivative", "equation", "solve", "calculate", "proof",
        "theorem", "matrix", "eigenvalue", "probability", "statistics",
        "formula", "polynomial", "factori", "prime", "geometry",
    ]),
    ("creative", [
        "poem", "story", "write a", "haiku", "limerick", "fiction", "novel",
        "dialogue", "character", "plot", "creative", "invent", "imagine",
        "tagline", "slogan", "name idea",
    ]),
    ("summarization", [
        "summarize", "summary", "tldr", "tl;dr", "condense", "brief",
        "key points", "main points", "distill", "overview", "outline",
        "takeaway",
    ]),
    ("reasoning", [
        "analyze", "evaluate", "compare", "tradeoff", "trade-off", "pros and cons",
        "implications", "consequences", "should i", "is it better",
        "design a system", "strategy", "ethical",
    ]),
    ("long-context", [
        "entire", "whole document", "all chapters", "50-page", "200-page",
        "full report", "meeting transcript", "entire codebase", "throughout",
        "across all",
    ]),
    # simple-qa is the catch-all — no strong keywords needed
]


def _keyword_classify(prompt: str) -> tuple[str, float]:
    lower = prompt.lower()
    scores: dict[str, int] = {cat: 0 for cat, _ in _KEYWORD_RULES}
    for cat, keywords in _KEYWORD_RULES:
        for kw in keywords:
            if kw in lower:
                scores[cat] += 1
    best_cat = max(scores, key=lambda c: scores[c])
    best_count = scores[best_cat]
    if best_count == 0:
        return "simple-qa", 0.5
    # rough confidence: fraction of top-scoring keywords triggered
    confidence = min(0.5 + best_count * 0.1, 0.85)
    return best_cat, round(confidence, 2)


# ---------------------------------------------------------------------------
# Public API — delegates to the single shared model in routing.classifier
# ---------------------------------------------------------------------------

def predict_category(prompt: str) -> tuple[str, float]:
    """Return (category, confidence) for *prompt*.

    Categories: code | math | creative | summarization | reasoning |
                long-context | simple-qa
    """
    from ijachi_router.routing.classifier import predict_base_category
    return predict_base_category(prompt)


def complexity_score(prompt: str) -> float:
    """Return a rough complexity score in [0, 1].

    Higher = more complex prompt (longer, multi-step, technical vocabulary).
    Used by the router to choose cheap-fast vs strong-slow model within a
    matched category.
    """
    words = prompt.split()
    word_count = len(words)

    # Length component (caps at 200 words → 0.5 contribution)
    length_score = min(word_count / 200, 1.0) * 0.5

    # Multi-step indicator words
    multi_step_markers = [
        "first", "then", "next", "finally", "also", "additionally",
        "step 1", "step 2", "make sure", "ensure", "consider",
    ]
    lower = prompt.lower()
    marker_hits = sum(1 for m in multi_step_markers if m in lower)
    step_score = min(marker_hits / 4, 1.0) * 0.3

    # Technical / domain vocabulary
    technical_chars = len(re.findall(r"[(){}\[\]<>]", prompt))
    tech_score = min(technical_chars / 20, 1.0) * 0.2

    return round(length_score + step_score + tech_score, 3)


def retrain() -> None:
    """Retrain the shared classifier from data/train_data.csv (requires scikit-learn)."""
    from ijachi_router.routing.classifier import retrain_safe_model
    try:
        retrain_safe_model()
    except ImportError as e:
        raise RuntimeError("scikit-learn is required for training. Run: pip install scikit-learn") from e
