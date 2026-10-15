"""Prompt Classifier for category, confidence, and complexity prediction.

Document 2.4 (FR-21, FR-25) & Document 5.10 (SEC-14):
- Categories: code, code-edit/refactor, debugging, math, reasoning, creative, summarization, long-context, simple-qa
- Complexity in [0.0, 1.0]
- Confidence threshold: if < 0.6, routing falls back to balanced default model (FR-25)
- Non-executable safe storage (JSON-serialized vocabulary, coefficients, and checksum) to avoid unsafe deserialization.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any

_CACHE_DIR = Path.home() / ".ijachi-llmr"
_SAFE_MODEL_PATH = _CACHE_DIR / "classifier_model.json"
_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "train_data.csv"

# Keyword rules for fast inference and fallback
_KEYWORD_RULES: list[tuple[str, list[str]]] = [
    ("debugging", ["debug", "error", "exception", "traceback", "crash", "segfault", "broken", "why does this fail"]),
    ("code-edit/refactor", ["refactor", "rename", "clean up", "restructure", "convert this code", "extract method", "rewrite this function"]),
    ("code", [
        "def ", "function ", "class ", "import ", "```", "sql", "api",
        "test", "regex", "algorithm", "script", "async", "await", "loop",
        "array", "variable", "compile", "runtime", "syntax", "git",
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
]


def complexity_score(prompt: str) -> float:
    """Return a complexity score in [0.0, 1.0]."""
    words = prompt.split()
    word_count = len(words)
    length_score = min(word_count / 200, 1.0) * 0.5

    multi_step_markers = [
        "first", "then", "next", "finally", "also", "additionally",
        "step 1", "step 2", "make sure", "ensure", "consider",
    ]
    lower = prompt.lower()
    marker_hits = sum(1 for m in multi_step_markers if m in lower)
    step_score = min(marker_hits / 4, 1.0) * 0.3

    technical_chars = len(re.findall(r"[(){}\[\]<>]", prompt))
    tech_score = min(technical_chars / 20, 1.0) * 0.2

    return round(length_score + step_score + tech_score, 3)


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
        return "simple-qa", 0.65
    confidence = min(0.65 + best_count * 0.1, 0.95)
    return best_cat, round(confidence, 2)


class SafeModel:
    """Non-executable linear model storing vocabulary and weights in JSON."""

    def __init__(self, vocab: dict[str, int], classes: list[str], weights: list[list[float]], intercepts: list[float], checksum: str):
        self.vocab = vocab
        self.classes = classes
        self.weights = weights
        self.intercepts = intercepts
        self.checksum = checksum

    @classmethod
    def load(cls, path: Path) -> SafeModel | None:
        if not path.exists():
            return None
        try:
            content = path.read_text(encoding="utf-8")
            data = json.loads(content)
            expected_checksum = data.get("checksum")
            actual_checksum = hashlib.sha256(json.dumps(data["weights"]).encode()).hexdigest()[:16]
            if expected_checksum and expected_checksum != actual_checksum:
                # Checksum mismatch! Refuse to load tampered artifact (SEC-14)
                return None
            return cls(
                vocab=data["vocab"],
                classes=data["classes"],
                weights=data["weights"],
                intercepts=data["intercepts"],
                checksum=actual_checksum,
            )
        except Exception:
            return None

    def predict(self, text: str) -> tuple[str, float]:
        tokens = re.findall(r"\b\w+\b", text.lower())
        vec: dict[int, float] = {}
        for t in tokens:
            idx = self.vocab.get(t)
            if idx is not None:
                vec[idx] = vec.get(idx, 0.0) + 1.0

        scores = list(self.intercepts)
        for class_idx in range(len(self.classes)):
            w_class = self.weights[class_idx]
            for feat_idx, val in vec.items():
                if feat_idx < len(w_class):
                    scores[class_idx] += w_class[feat_idx] * val

        # Softmax
        max_s = max(scores)
        exp_s = [math.exp(s - max_s) for s in scores]
        sum_exp = sum(exp_s)
        probs = [e / sum_exp for e in exp_s]

        best_idx = max(range(len(probs)), key=lambda i: probs[i])
        return self.classes[best_idx], round(probs[best_idx], 3)


_safe_model: SafeModel | None = None


def get_safe_model() -> SafeModel | None:
    global _safe_model
    if _safe_model is None and _SAFE_MODEL_PATH.exists():
        _safe_model = SafeModel.load(_SAFE_MODEL_PATH)
    return _safe_model


def predict_category(prompt: str) -> tuple[str, float]:
    """Predict task category and confidence for *prompt*."""
    # Check keyword heuristics for specific developer tasks (debugging, code-edit)
    cat, conf = _keyword_classify(prompt)
    if cat in ("debugging", "code-edit/refactor"):
        return cat, conf

    # If safe model exists, use it
    model = get_safe_model()
    if model:
        pred_cat, pred_conf = model.predict(prompt)
        # If model has strong confidence, use it
        if pred_conf > 0.4:
            return pred_cat, pred_conf

    # Fallback to existing sklearn or keyword
    try:
        from ijachi_router.classifier import _get_model
        sk_model = _get_model()
        if sk_model:
            import numpy as np
            proba = sk_model.predict_proba([prompt])[0]
            classes = sk_model.classes_
            idx = int(np.argmax(proba))
            return str(classes[idx]), round(float(proba[idx]), 3)
    except Exception:
        pass

    return cat, conf


def retrain_safe_model() -> None:
    """Train linear classifier and save into non-executable JSON format with checksum."""
    global _safe_model
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression

    prompts, labels = [], []
    with open(_DATA_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            prompts.append(row["prompt"])
            labels.append(row["category"])

    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
    X = vec.fit_transform(prompts)
    clf = LogisticRegression(max_iter=500, C=5.0)
    clf.fit(X, labels)

    vocab = {k: int(v) for k, v in vec.vocabulary_.items()}
    classes = [str(c) for c in clf.classes_]
    weights = clf.coef_.tolist()
    intercepts = clf.intercept_.tolist()
    checksum = hashlib.sha256(json.dumps(weights).encode()).hexdigest()[:16]

    data = {
        "format": "json_safe_weights_v1",
        "checksum": checksum,
        "classes": classes,
        "vocab": vocab,
        "weights": weights,
        "intercepts": intercepts,
    }
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _SAFE_MODEL_PATH.write_text(json.dumps(data), encoding="utf-8")
    _safe_model = SafeModel.load(_SAFE_MODEL_PATH)
