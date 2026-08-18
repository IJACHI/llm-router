# Contributing to ijachi-llm-router

Thanks for your interest in contributing! Here's how to get started.

## Quick setup

```bash
git clone https://github.com/ijachi/ijachi-llm-router
cd ijachi-llm-router
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest  # should see 32 passed, 0 warnings
```

## Ways to contribute

### 🏷️ Add a model (no code needed)

The easiest contribution: edit [`models.yaml`](models.yaml) to add a new model.

```yaml
- provider: openai           # anthropic | openai | local
  model_id: gpt-4.1-nano     # exact string the API expects
  tags: [simple-qa, creative] # categories this model excels at
  input_per_1k: 0.0001       # USD per 1,000 input tokens
  output_per_1k: 0.0004      # USD per 1,000 output tokens
  max_context: 128000         # context window in tokens
  speed_tier: fast            # fast | medium | slow
```

Valid tags: `code` · `math` · `creative` · `summarization` · `reasoning` · `long-context` · `simple-qa`

Please include a link to the pricing page in your PR description so reviewers can verify the rates.

### 📊 Improve the classifier

The prompt classifier trains on `data/train_data.csv`. To improve accuracy:

1. Add rows to the CSV (format: `prompt text,category`)
2. Run `ijachi-router train` to retrain
3. Run `pytest tests/test_classifier.py` to verify known prompts still classify correctly
4. Submit a PR with both the CSV changes and updated test cases if you added new category patterns

### 🔌 Add a provider

1. Create `ijachi_router/providers/your_provider.py` implementing the `Provider` ABC:

```python
from ijachi_router.providers.base import Provider, ProviderError

class YourProvider(Provider):
    name = "your_provider"

    def _call(self, prompt: str, **kwargs) -> tuple[str, int, int]:
        # Call your API, return (text, input_tokens, output_tokens)
        # Raise ProviderError on any failure
        ...
```

2. Register it in `ijachi_router/providers/__init__.py`
3. Add at least one model entry in `models.yaml`
4. Add the env key detection in `ijachi_router/config.py` (`_PROVIDER_ENV_KEYS` dict)
5. Add a rewrite strategy in `ijachi_router/optimizer.py` (or fall through to passthrough)

### 🐛 Bug reports

Open an issue with:
- Your Python version (`python3 --version`)
- Your OS
- The full error traceback
- The command or code you ran

### 🧪 Tests

All code changes should include tests. Run the full suite with:

```bash
pytest               # all tests
pytest -x            # stop on first failure
pytest -k "keyword"  # run matching tests only
```

**No real API calls in tests.** Mock the `Provider._call` method — see `tests/test_core.py` for examples.

## Code style

- We use [ruff](https://github.com/astral-sh/ruff) for linting (config in `pyproject.toml`)
- Line length: 100
- Target: Python 3.10+
- Type hints encouraged but not enforced

## Pull request checklist

- [ ] All tests pass (`pytest`)
- [ ] No new warnings
- [ ] Added/updated tests for changed behavior
- [ ] Updated `README.md` if user-facing behavior changed
- [ ] Models added to `models.yaml` have verified pricing
