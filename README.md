<p align="center">
  <img src="assets/logo.png" alt="ijachi-llm-router logo" width="160"/>
</p>

<h1 align="center">ijachi-llm-router</h1>

<p align="center">
  <strong>One prompt. Best model. Automatic fallback.</strong>
</p>

`ijachi-llm-router` classifies your prompt, picks the cheapest model that can handle it well, rewrites it for that model's quirks, and falls back automatically if a provider is down — all in one simple command.

```
$ ijachi-router route "What is the capital of France?"
Paris

[model=gpt-4o-mini  cost=$0.0001  latency=0.6s]

$ ijachi-router route "Write a Python function to sort a list"
def sort_list(lst):
    return sorted(lst)

[model=claude-haiku-4-5  cost=$0.0003  latency=0.8s]

$ ijachi-router stats

ijachi-llm-router usage  42 calls · $0.0127 total · 1.24s avg latency

╭────────────────────┬──────────┬───────┬───────────┬─────────────╮
│ Model              │ Provider │ Calls │ Cost (USD)│ Avg Latency │
├────────────────────┼──────────┼───────┼───────────┼─────────────┤
│ gpt-4o-mini        │ openai   │    18 │   $0.0014 │      0.62s  │
│ claude-haiku-4-5   │ anthropic│    14 │   $0.0028 │      0.84s  │
│ claude-sonnet-4-5  │ anthropic│     7 │   $0.0075 │      2.10s  │
│ llama3.2:3b        │ local    │     3 │   $0.0000 │      3.50s  │
╰────────────────────┴──────────┴───────┴───────────┴─────────────╯
```

---

## Why?

| Without ijachi-llm-router | With ijachi-llm-router |
|---|---|
| You hardcode one model for everything | Routes each prompt to the right model |
| Simple questions cost as much as hard ones | Trivial prompts → cheap/fast model |
| One provider outage = your app is down | Automatic fallback across 20 providers |
| No visibility into spend | `ijachi-router stats` & Web Dashboard show cost |

---

## 60-second quickstart

```bash
pip install ijachi-llm-router

# Set at least one provider key (or run Ollama locally — no key needed)
export ANTHROPIC_API_KEY=sk-ant-...
# and/or
export OPENAI_API_KEY=sk-...

# Route your first prompt (use ijachi-router or short alias ijr)
ijachi-router route "Explain quicksort in Python"
```

**Zero-cost test with Ollama (no API keys needed):**
```bash
# Install Ollama from https://ollama.com, then:
ollama pull llama3.2:3b
ijachi-router route "What is the speed of light?"
```

---

## Supported providers & models

`ijachi-llm-router` comes preconfigured out-of-the-box with **20 major LLM service providers** and **40+ top models** in [`models.yaml`](models.yaml).

| Provider | Model | Speed | Cost (in/out per 1K) | Best for |
|---|---|---|---|---|
| Cerebras Cloud | `llama3.1-70b` | ⚡⚡ ultra-fast (1800+ tok/s) | $0.0006 / $0.0006 | fast code, reasoning |
| SambaNova LPU | `Meta-Llama-3.1-405B` | ⚡ fast | $0.005 / $0.005 | frontier reasoning, math |
| Fireworks AI | `llama-v3p1-70b-instruct` | ⚡ fast | $0.0009 / $0.0009 | code, reasoning |
| AWS Bedrock | `claude-3-5-sonnet-v2` | 🔄 medium | $0.003 / $0.015 | enterprise code & reasoning |
| Azure OpenAI | `gpt-4o` | 🔄 medium | $0.0025 / $0.01 | enterprise code & math |
| Hugging Face | `Mistral-7B-Instruct-v0.3` | ⚡ fast | $0.0002 / $0.0002 | simple-qa, summarization |
| Custom / vLLM | `local-model` | ⚡ fast | **free / custom** | custom self-hosted server |
| Kimi (Moonshot) | `kimi-latest` | ⚡ fast | $0.0012 / $0.0012 | code, reasoning, long-context |
| Qwen (Alibaba) | `qwen-max` | 🔄 medium | $0.0028 / $0.0084 | reasoning, math, code |
| Perplexity AI | `sonar-pro` | ⚡ fast | $0.003 / $0.015 | simple-qa, web reasoning |
| Cohere AI | `command-r-plus` | 🔄 medium | $0.0025 / $0.01 | reasoning, long-context |
| DeepSeek Cloud | `deepseek-chat` (V3) | ⚡ fast | $0.00014 / $0.00028 | simple-qa, code, summarization |
| DeepSeek Cloud | `deepseek-reasoner` (R1) | 🔄 medium | $0.00055 / $0.00219 | reasoning, math, complex code |
| Google Gemini | `gemini-2.5-flash` | ⚡ fast | $0.000075 / $0.0003 | simple-qa, summarization |
| Google Gemini | `gemini-2.5-pro` | 🔄 medium | $0.00125 / $0.005 | code, reasoning, math |
| Groq LPU | `llama-3.3-70b-versatile` | ⚡ ultra-fast | $0.00059 / $0.00079 | fast code, reasoning |
| OpenAI | `gpt-4o-mini` | ⚡ fast | $0.00015 / $0.0006 | simple-qa, summarization |
| OpenAI | `gpt-4o` | 🔄 medium | $0.0025 / $0.01 | code, reasoning, math |
| Anthropic | `claude-3-7-sonnet` | ⚡ fast | $0.003 / $0.015 | code, reasoning, math |
| Mistral AI | `codestral-latest` | ⚡ fast | $0.0003 / $0.0009 | code, refactoring |
| Together AI | `Llama-3.3-70B-Turbo` | ⚡ fast | $0.00088 / $0.00088 | open source cloud |
| OpenRouter | `openrouter/auto` | 🔄 medium | $0.001 / $0.002 | model aggregation |
| Local (Ollama) | `llama3.2:3b` | ⚡ fast | **free** | simple-qa, summarization |

> **Zero Setup**: Export your key (e.g. `export CEREBRAS_API_KEY=...` or `export AWS_ACCESS_KEY_ID=...`) to activate any provider.
> **Auto-Updating Catalog**: Run `ijachi-router update-catalog` anytime to fetch dynamic pricing updates from remote model registries.

---

## CLI reference

```bash
# Route a prompt (auto-selects best model)
ijachi-router route "Your prompt here"
# or short alias:
ijr route "Your prompt here"

# Override routing priority for one call
ijachi-router route "Summarise this doc" --priority cost      # cheapest model wins
ijachi-router route "Prove P ≠ NP" --priority quality         # strongest model wins
ijachi-router route "What time is it?" --priority speed        # fastest model wins

# Cap cost per call (skips models above threshold)
ijachi-router route "Explain neural nets" --max-cost 0.01

# Dedicated coding assistant mode
ijachi-code "Write a Python script to sort a list"

# [AGENTIC] Autonomous multi-step workspace task (reads/edits files, runs commands)
ijachi-code agent "Refactor helper function in main.py and run pytest"

# [AGENTIC] Interactive REPL terminal session with file modification approval prompts
ijachi-code chat

# Show spend + latency table for all recorded calls
ijachi-router stats

# See which providers are active (which API keys detected)
ijachi-router providers

# Fetch dynamic pricing & new model updates from remote registry
ijachi-router update-catalog

# Retrain the prompt classifier after editing data/train_data.csv
ijachi-router train

# [PRO] Launch background REST API Server
ijachi-router serve --port 8000

# [PRO] Open Interactive Web Telemetry Dashboard in browser
ijachi-router dashboard --port 8000

# Manage Pro license key
ijachi-router license set IJPRO-YOUR-KEY-HERE
ijachi-router license status
```

---

## Library usage

```python
from ijachi_router import route, Router

# One-shot — auto-selects the best model
result = route("Explain quicksort in Python")
print(result.text)
print(f"Model: {result.model}  Cost: ${result.cost_usd:.4f}  Latency: {result.latency_s:.2f}s")

# Full control
router = Router()
router.config.priority = "cost"
router.config.max_cost_per_call = 0.005
result = router.route("Write a haiku about Python")
```

---

## 🐙 GitHub Action Integration

Save costs on automated PR summaries, test evaluation, and synthetic code checks by plugging `ijachi-llm-router` directly into your GitHub CI/CD workflows:

```yaml
- name: Route Prompt with ijachi-llm-router
  uses: ijachi/ijachi-llm-router@v1
  with:
    prompt: "Summarize recent commit changes and check for security flaws"
    priority: "cost"
    openai_api_key: ${{ secrets.OPENAI_API_KEY }}
    anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
```

**Step Outputs**: `${{ steps.router.outputs.response }}`, `${{ steps.router.outputs.model }}`, `${{ steps.router.outputs.cost_usd }}`, and `${{ steps.router.outputs.latency_sec }}`.

See [`.github/workflows/demo-ci.yml`](.github/workflows/demo-ci.yml) for a complete workflow example.

---

## 💻 GitHub CLI Extension (`gh router`)

Run `ijachi-llm-router` directly inside GitHub CLI:

```bash
# Install the GitHub CLI extension
gh extension install ijachi/ijachi-llm-router

# Route prompts from gh
gh router route "Explain this git diff"
gh router stats
```

---

## How routing works

```
Your prompt
    │
    ▼
┌─────────────┐      TF-IDF + LogReg classifier
│  Classifier │ ──►  category: "code"  confidence: 0.91
└─────────────┘      complexity: 0.42  (affects cheap vs strong model choice)
    │
    ▼
┌─────────────┐      Scores all available models on:
│   Scorer    │      • category match  • priority (cost/speed/quality/balanced)
└─────────────┘      • complexity      • cost cap
    │
    ▼
┌─────────────┐      Per-provider rewrites (no extra LLM call):
│  Optimizer  │      Anthropic → XML wrap + chain-of-thought
└─────────────┘      OpenAI/Gemini/DeepSeek → provider-tailored system prompts
    │
    ▼
┌───────────────────┐   Tries providers in ranked order
│ route_with_fallback│  Catches ProviderError → next candidate
└───────────────────┘   Circuit breaker auto-skips flaky providers
    │
    ▼
GenerationResult(text, model, cost_usd, latency_s, tokens…)
    │
    ▼
~/.ijachi-llmr/history.jsonl   (append-only cost/usage log)
```

---

## Add your own model

No code changes needed — just edit [`models.yaml`](models.yaml):

```yaml
- provider: openai           # matching REGISTRY provider key
  model_id: gpt-4o-mini      # exact string the API expects
  tags: [simple-qa, creative, summarization]
  input_per_1k: 0.00015     # USD per 1,000 input tokens
  output_per_1k: 0.0006      # USD per 1,000 output tokens
  max_context: 128000
  speed_tier: fast           # fast | medium | slow
```

Valid tags: `code` · `math` · `creative` · `summarization` · `reasoning` · `long-context` · `simple-qa`

Then run `ijachi-router providers` to confirm the provider key is set.

---

## Add a new provider

1. Create `ijachi_router/providers/your_provider.py` implementing the [`Provider`](ijachi_router/providers/base.py) ABC
2. Register it in [`ijachi_router/providers/__init__.py`](ijachi_router/providers/__init__.py)
3. Add its env key to `_PROVIDER_ENV_KEYS` in [`ijachi_router/config.py`](ijachi_router/config.py)
4. Add a rewrite strategy in [`ijachi_router/optimizer.py`](ijachi_router/optimizer.py)
5. Add at least one model entry in [`models.yaml`](models.yaml)

---

## Project structure

```
ijachi-llm-router/
├── action.yml               # GitHub Action definition
├── gh-router                # GitHub CLI extension executable
├── cli.py                  # CLI entry point (click)
├── models.yaml             # Model catalog — preconfigured matrix
├── pyproject.toml           # Package config + dependencies
├── PRICING.md              # Monetization tier comparison & Paystack link
├── COMMERCIAL_LICENSE.md   # Enterprise commercial license terms
├── data/
│   └── train_data.csv       # Classifier training data (~140 rows)
├── ijachi_router/
│   ├── __init__.py          # Public API: route(), Router
│   ├── catalog_updater.py   # Dynamic remote pricing & catalog updater
│   ├── classifier.py        # TF-IDF + LogReg prompt classifier
│   ├── config.py            # Config loader (models.yaml + user prefs)
│   ├── core.py              # Main routing orchestrator
│   ├── fallback.py          # Circuit breaker + fallback logic
│   ├── license.py           # Pro license key validation & paywall gating
│   ├── metrics.py           # Usage logging + stats table
│   ├── optimizer.py         # Per-provider prompt rewrites
│   ├── server.py            # REST API Gateway & Web Telemetry Dashboard
│   └── providers/
│       ├── __init__.py      # Provider registry (20 providers)
│       ├── base.py          # Provider ABC + GenerationResult
│       ├── anthropic_provider.py
│       ├── openai_provider.py
│       ├── deepseek_provider.py
│       ├── gemini_provider.py
│       ├── groq_provider.py
│       ├── mistral_provider.py
│       ├── moonshot_provider.py
│       ├── qwen_provider.py
│       ├── perplexity_provider.py
│       ├── cohere_provider.py
│       ├── cerebras_provider.py
│       ├── sambanova_provider.py
│       ├── fireworks_provider.py
│       ├── huggingface_provider.py
│       ├── bedrock_provider.py
│       ├── azure_provider.py
│       ├── custom_provider.py
│       ├── together_provider.py
│       ├── openrouter_provider.py
│       └── local_provider.py
└── tests/
    ├── test_catalog_updater.py
    ├── test_classifier.py
    ├── test_core.py
    ├── test_fallback.py
    ├── test_license.py
    ├── test_providers.py
    └── test_server.py
```

---

## 🚀 Pro, Enterprise & Commercial Licensing

`ijachi-llm-router` is available under an **Open Core** dual-licensing model:

- 🟢 **Community Edition (Free / MIT)**: Self-hosted CLI & Python SDK for individuals and open-source projects.
- 🔵 **Pro Edition ($19 / month)**: Hosted REST API Gateway, Web Telemetry Dashboard, and webhook budget alerts.
- 🟣 **Enterprise Commercial License**: Proprietary closed-source embedding, custom SLAs, white-labeling, and dedicated support.

See [**PRICING.md**](PRICING.md) for full tier details and plan comparisons.  
For proprietary commercial licensing, see [**COMMERCIAL_LICENSE.md**](COMMERCIAL_LICENSE.md).

👉 **Subscribe to Pro or Buy a License**: [**Paystack Payment Portal**](https://paystack.shop/pay/enlqpvzflw)

---

## 💖 Support & Sponsorship

If `ijachi-llm-router` saved you money or time, consider supporting its ongoing development! Every contribution helps maintain and improve the project.

[![Paystack](https://img.shields.io/badge/Support-Paystack-09A5DB?style=for-the-badge&logo=paystack&logoColor=white)](https://paystack.shop/pay/enlqpvzflw)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-Donate-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/ijachi)
[![GitHub Sponsors](https://img.shields.io/badge/Sponsor-GitHub-ea4aaa?style=for-the-badge&logo=github&logoColor=white)](https://github.com/sponsors/ijachi)

---

## License

Core library is licensed under [MIT](LICENSE). For commercial proprietary usage without open-source requirements, see [COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md).
