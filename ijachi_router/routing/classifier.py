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
        "website", "app", "application", "software", "html", "css", "javascript",
        "frontend", "backend", "full-stack", "component", "scaffold", "build",
        "develop", "newsletter", "pipeline",
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
    length_score = min(word_count / 150, 1.0) * 0.4

    multi_step_markers = [
        "first", "then", "next", "finally", "also", "additionally",
        "step 1", "step 2", "make sure", "ensure", "consider",
    ]
    lower = prompt.lower()
    marker_hits = sum(1 for m in multi_step_markers if m in lower)
    step_score = min(marker_hits / 4, 1.0) * 0.25

    technical_chars = len(re.findall(r"[(){}\[\]<>]", prompt))
    tech_score = min(technical_chars / 20, 1.0) * 0.15

    # Architectural scope markers (building full apps, websites, platforms)
    scope_markers = [
        "website", "application", "platform", "pipeline", "system", "full-stack",
        "newsletter", "automated", "database", "backend", "frontend", "architecture",
        "integrate", "crawler", "production", "academic journals",
    ]
    scope_hits = sum(1 for s in scope_markers if s in lower)
    scope_score = min(scope_hits / 3, 1.0) * 0.4

    score = length_score + step_score + tech_score + scope_score
    # Asking to build a whole app/website/platform is a long multi-file agent task even when the
    # prompt is short: small models usually fail it, which costs more than a capable model.
    if scope_hits and re.search(r"\b(build|create|make|develop|implement|scaffold|set up)\b", lower):
        score = max(score, 0.75)
    return round(min(max(score, 0.0), 1.0), 3)


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


# ---------------------------------------------------------------------------
# Learned model (TF-IDF + multinomial logistic regression), stored as plain JSON
# ---------------------------------------------------------------------------
#
# Featurization is implemented here so inference needs no scikit-learn and never unpickles
# anything. It mirrors sklearn's TfidfVectorizer(ngram_range=(1, 2)) defaults exactly
# (lowercase, token pattern \b\w\w+\b, smooth idf, l2 norm), which training relies on, plus
# a few pseudo-tokens so that maths notation is visible to the model.

_BUNDLED_MODEL_PATH = Path(__file__).parent.parent / "data" / "classifier_model.json"
_TOKEN_RE = re.compile(r"(?u)\b\w\w+\b")
_MODEL_FORMAT = "tfidf_logreg_v2"


def preprocess(text: str) -> str:
    """Lowercase and append pseudo-tokens for numbers / operators / code-ish punctuation."""
    lower = text.lower()
    extra: list[str] = []
    if re.search(r"\d", lower):
        extra.append("zznum")
    if re.search(r"\d\s*[-+*/^=<>]\s*[\dx(]|[a-z]\^\d|\b\d+x\b|sqrt|∫|√", lower):
        extra.append("zzmathop")
    if re.search(r"[{}();]|=>|::|\.\w+\(|\b\w+\.(py|js|ts|go|rs|java|cpp|rb|sql)\b", lower):
        extra.append("zzcodechar")
    if len(lower.split()) <= 6:
        extra.append("zzshort")
    return lower + (" " + " ".join(extra) if extra else "")


def _ngrams(text: str) -> list[str]:
    toks = _TOKEN_RE.findall(text)
    return toks + [f"{a} {b}" for a, b in zip(toks, toks[1:])]


class SafeModel:
    """Non-executable linear model: vocabulary, idf, weights and intercepts in JSON."""

    def __init__(self, vocab: dict[str, int], idf: list[float], classes: list[str],
                 weights: list[list[float]], intercepts: list[float], checksum: str, meta: dict | None = None):
        self.vocab = vocab
        self.idf = idf
        self.classes = classes
        self.weights = weights
        self.intercepts = intercepts
        self.checksum = checksum
        self.meta = meta or {}

    @staticmethod
    def _checksum(data: dict) -> str:
        body = json.dumps([data["weights"], data["intercepts"], data["idf"]]).encode()
        return hashlib.sha256(body).hexdigest()[:16]

    @classmethod
    def load(cls, path: Path) -> "SafeModel | None":
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("format") != _MODEL_FORMAT:
                return None
            if data.get("checksum") != cls._checksum(data):
                return None  # tampered or corrupt artifact (SEC-14)
            return cls(data["vocab"], data["idf"], data["classes"], data["weights"], data["intercepts"],
                       data["checksum"], data.get("meta"))
        except Exception:
            return None

    def features(self, text: str) -> dict[int, float]:
        counts: dict[int, float] = {}
        for g in _ngrams(preprocess(text)):
            idx = self.vocab.get(g)
            if idx is not None:
                counts[idx] = counts.get(idx, 0.0) + 1.0
        vec = {i: c * self.idf[i] for i, c in counts.items()}
        norm = math.sqrt(sum(v * v for v in vec.values()))
        return {i: v / norm for i, v in vec.items()} if norm else {}

    def predict_proba(self, text: str) -> list[float]:
        vec = self.features(text)
        scores = [
            self.intercepts[c] + sum(self.weights[c][i] * v for i, v in vec.items())
            for c in range(len(self.classes))
        ]
        top = max(scores)
        exp = [math.exp(s - top) for s in scores]
        total = sum(exp)
        return [e / total for e in exp]

    def predict(self, text: str) -> tuple[str, float]:
        probs = self.predict_proba(text)
        best = max(range(len(probs)), key=lambda i: probs[i])
        return self.classes[best], round(probs[best], 3)


_safe_model: SafeModel | None = None


def _data_sha256(path: Path = _DATA_PATH) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def get_safe_model() -> SafeModel | None:
    """User-retrained model if it matches the current training data, else the bundled one."""
    global _safe_model
    if _safe_model is None:
        user = SafeModel.load(_SAFE_MODEL_PATH)
        if user is not None and user.meta.get("data_sha256") == _data_sha256():
            _safe_model = user
        else:
            _safe_model = SafeModel.load(_BUNDLED_MODEL_PATH)
    return _safe_model


_SUBCATEGORY_RULES = [r for r in _KEYWORD_RULES if r[0] in ("debugging", "code-edit/refactor")]


def predict_base_category(prompt: str) -> tuple[str, float]:
    """One of the trained categories: code | math | creative | summarization | reasoning |
    long-context | simple-qa."""
    model = get_safe_model()
    if model is not None:
        cat, conf = model.predict(prompt)
        if conf >= 0.30:
            return cat, conf
    cat, conf = _keyword_classify(prompt)
    if cat in ("debugging", "code-edit/refactor"):
        cat = "code"
    if model is not None and cat == "simple-qa":
        return model.predict(prompt)
    return cat, conf


def predict_category(prompt: str) -> tuple[str, float]:
    """Predict task category and confidence for *prompt* (adds debugging / refactor subtypes)."""
    cat, conf = predict_base_category(prompt)
    if cat == "code":
        lower = prompt.lower()
        for sub, keywords in _SUBCATEGORY_RULES:
            if any(kw in lower for kw in keywords):
                return sub, conf
    return cat, conf


# ---------------------------------------------------------------------------
# Training (requires scikit-learn; used by `ijachi-router train` and scripts/)
# ---------------------------------------------------------------------------

def _read_csv(path: Path) -> tuple[list[str], list[str]]:
    prompts, labels = [], []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("prompt") and row.get("category"):
                prompts.append(row["prompt"])
                labels.append(row["category"].strip())
    return prompts, labels


def train_model(data_path: Path = _DATA_PATH, eval_path: Path | None = None) -> dict[str, Any]:
    """Train, pick C by stratified 5-fold CV, and return the JSON-serialisable model."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from sklearn.pipeline import make_pipeline

    prompts, labels = _read_csv(data_path)
    docs = [preprocess(p) for p in prompts]

    def pipeline(c: float):
        # lowercase=False: preprocess() already lowercased; token pattern = sklearn default.
        return make_pipeline(
            TfidfVectorizer(ngram_range=(1, 2), lowercase=False),
            LogisticRegression(C=c, max_iter=2000, class_weight="balanced"),
        )

    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)
    cv_scores = {c: float(cross_val_score(pipeline(c), docs, labels, cv=folds).mean()) for c in (1.0, 3.0, 10.0, 30.0)}
    best_c = max(cv_scores, key=lambda c: cv_scores[c])
    final = pipeline(best_c).fit(docs, labels)
    vec, clf = final.steps[0][1], final.steps[1][1]

    data: dict[str, Any] = {
        "format": _MODEL_FORMAT,
        "classes": [str(c) for c in clf.classes_],
        "vocab": {k: int(v) for k, v in vec.vocabulary_.items()},
        "idf": [float(x) for x in vec.idf_],
        "weights": clf.coef_.tolist(),
        "intercepts": clf.intercept_.tolist(),
        "meta": {
            "data_sha256": _data_sha256(data_path),
            "n_examples": len(prompts),
            "C": best_c,
            "cv_accuracy": round(cv_scores[best_c], 4),
        },
    }
    data["checksum"] = SafeModel._checksum(data)
    if eval_path and eval_path.exists():
        model = SafeModel(data["vocab"], data["idf"], data["classes"], data["weights"], data["intercepts"], data["checksum"])
        ep, el = _read_csv(eval_path)
        data["meta"]["eval_accuracy"] = round(sum(model.predict(p)[0] == l for p, l in zip(ep, el)) / len(ep), 4)
    return data


def retrain_safe_model(target: Path = _SAFE_MODEL_PATH) -> dict[str, Any]:
    """Retrain from data/train_data.csv into the user cache; returns training metadata."""
    global _safe_model
    eval_path = _DATA_PATH.parent / "eval_prompts.csv"
    data = train_model(_DATA_PATH, eval_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data), encoding="utf-8")
    _safe_model = None
    return data["meta"]
