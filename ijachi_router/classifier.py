"""Prompt classifier: predicts category + confidence, plus a complexity score.

v1 strategy
-----------
1. Try to load a cached scikit-learn model from ~/.ijachi-llmr/classifier.pkl.
2. If the cache is missing, train a TfidfVectorizer + LogisticRegression from
   data/train_data.csv (bundled with the package) and persist it.
3. If sklearn or the CSV are unavailable, fall back to lightweight keyword
   heuristics so the router still works in minimal installs.

Caching uses stdlib ``pickle`` (not joblib) to avoid numpy_pickle DeprecationWarnings
that arise from the joblib ↔ NumPy 2.5 incompatibility.
"""

from __future__ import annotations

import csv
import os
import pickle
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
    total_kw = sum(len(kws) for _, kws in _KEYWORD_RULES)
    confidence = min(0.5 + best_count * 0.1, 0.85)
    return best_cat, round(confidence, 2)


# ---------------------------------------------------------------------------
# Sklearn classifier
# ---------------------------------------------------------------------------

def _load_training_data() -> tuple[list[str], list[str]]:
    """Load prompts and labels from the bundled CSV."""
    prompts, labels = [], []
    with open(_DATA_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            prompts.append(row["prompt"])
            labels.append(row["category"])
    return prompts, labels


def _train_and_cache() -> object:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    prompts, labels = _load_training_data()
    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1)),
        ("clf", LogisticRegression(max_iter=500, C=5.0)),
    ])
    pipeline.fit(prompts, labels)

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with _MODEL_PATH.open("wb") as f:
        pickle.dump(pipeline, f, protocol=pickle.HIGHEST_PROTOCOL)
    return pipeline


def _load_model() -> object | None:
    """Return cached model, training if needed. Returns None if sklearn absent."""
    try:
        import sklearn  # noqa: F401 – just checking availability
    except ImportError:
        return None

    if _MODEL_PATH.exists():
        try:
            with _MODEL_PATH.open("rb") as f:
                return pickle.load(f)  # noqa: S301 – trusted local cache
        except Exception:  # corrupt/stale cache → retrain
            pass

    if not _DATA_PATH.exists():
        return None

    return _train_and_cache()


_model = None  # lazy-loaded on first call


def _get_model() -> object | None:
    global _model
    if _model is None:
        _model = _load_model()
    return _model


import functools


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=4096)
def predict_category(prompt: str) -> tuple[str, float]:
    """Return (category, confidence) for *prompt*.

    Categories: code | math | creative | summarization | reasoning |
                long-context | simple-qa
    Confidence is a float in [0, 1].
    """
    model = _get_model()
    if model is not None:
        import numpy as np
        proba = model.predict_proba([prompt])[0]
        classes = model.classes_
        idx = int(np.argmax(proba))
        # sklearn classes_ may be numpy str_ — coerce to plain str
        return str(classes[idx]), round(float(proba[idx]), 3)
    return _keyword_classify(prompt)


@functools.lru_cache(maxsize=4096)
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
    """Force-retrain the classifier from data/train_data.csv and update cache."""
    global _model
    try:
        import sklearn  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "scikit-learn is required for training. "
            "Run: pip install scikit-learn"
        ) from e
    # Delete stale cache so _train_and_cache writes a fresh one
    if _MODEL_PATH.exists():
        _MODEL_PATH.unlink()
    _model = _train_and_cache()
