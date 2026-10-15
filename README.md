<p align="center">
  <img src="assets/logo.png" alt="ijachi-llm-router logo" width="160"/>
</p>

<h1 align="center">ijachi-llm-router</h1>

<p align="center">
  <strong>The terminal coding assistant that routes every turn to the cheapest adequate model without losing session context.</strong>
</p>

`ijachi-llm-router` combines Claude Code-style interactive terminal pair programming with cost-aware multi-model routing. Every turn is sent to the cheapest model that can handle the task, across 20 providers, with automatic fallback and seamless session continuity.

```bash
$ ijachi-code
```
```text
ijachi-code v1.0 ~/projects/api-server branch: feature/auth
──────────────────────────────────────────────────────────────────
> Add rate limiting to the login endpoint and write tests
[route] code-edit · complexity 0.62 · claude-sonnet-4-5

* Read src/auth/routes.py ok
* Grep 'limiter' in src/ 2 matches
* Edit src/auth/routes.py +14 -2 [awaiting approval]

Allow? [y] once [s] this session [a] always [n] no [e] explain: y
──────────────────────────────────────────────────────────────────
auto · claude-sonnet-4-5 · ctx 38% · turn $0.0042 · session $0.0187 / $2.00
> _
```

---

## 🧭 Command Surface & Naming

| Command | Role | Description |
|---|---|---|
| **`ijachi-code`** (alias **`ijachi`**) | Coding Assistant | Full interactive REPL pair programmer, agent loop, file editing, and test repair. |
| **`ijachi-router`** (alias **`ijr`**) | Admin & Routing | One-shot routing, stats, catalog updates, classifier training, server, and doctor. |
| **`gh router`** | GitHub CLI Extension | Wrapper executing `ijachi-router` from inside the GitHub CLI. |

---

## ⚡ 60-Second Quickstart

Install `ijachi` globally with a single command (no virtual environment activation required):

```bash
# 🚀 Universal One-Line Installer (macOS & Linux)
curl -fsSL https://raw.githubusercontent.com/IJACHI/llm-router/main/install.sh | bash

# Or via pipx / uv (isolated global CLI standard)
pipx install git+https://github.com/IJACHI/llm-router.git
# or: uv tool install git+https://github.com/IJACHI/llm-router.git

# Set at least one provider key (or run Ollama locally with no key)
export ANTHROPIC_API_KEY=sk-ant-...
# and/or
export OPENAI_API_KEY=sk-...

# Launch anywhere in any terminal window
ijachi-code
```

**Zero-cost local model path (Ollama):**
```bash
ollama pull llama3.1:8b
ijachi-code --local-only
```

---

## 📊 Feature Maturity

| Feature | Status | Description |
|---|---|---|
| **Multi-Model Routing** | 🟢 Stable | 20 providers, cost scoring, prompt optimization, automatic fallback |
| **Session Continuity** | 🟢 Stable | Append-only canonical event log, facts ledger, working set, crash recovery |
| **Permission Sandbox** | 🟢 Stable | R0-R4 risk tiers, compound command analyzer, env scrubbing, checkpoints & `/undo` |
| **Interactive REPL** | 🟢 Stable | Full slash commands (`/why`, `/context`, `/cost`, `/undo`, `/model`, etc.) |
| **Non-interactive / CI** | 🟢 Stable | `-p` print mode, stdin piping, machine-readable `--json` events, auto-safe exit codes |
| **Test-Repair Loop (`fix`)** | 🟡 Beta | Automated test runner, failure diagnosis, and repair loop |
| **Symbol Indexer (`index`)** | 🟡 Beta | Workspace symbol cache in `.ijachi/symbols.json` |
| **Consensus Mode** | 🟡 Beta | Two-model peer review and synthesis (`ijachi-code consensus`) |
| **Commit Helper** | 🟡 Beta | Conventional commit generation from staged git diff (`ijachi-code commit`) |
| **OS Sandbox (`--sandbox`)**| ⚪ Planned | Bubblewrap / Landlock container containment for commands (v1.1) |

---

## 💡 What Makes It Different

### 1. Cost-Aware Multi-Model Routing
Each turn is classified by category (code, debugging, math, reasoning, creative, summarization, long-context, simple-qa) and complexity. The router scores candidates considering expected input/output cost, speed tier, and current model stickiness.

### 2. Session Continuity Across Models (The Core Differentiator)
*The session owns the state, not the model.* Models are stateless workers. The session engine maintains:
- **Canonical Event Log** (`events.jsonl`): Provider-neutral history of every message, tool call, and result.
- **Facts & Decisions Ledger**: Pinned user constraints and architectural decisions that survive compaction verbatim.
- **Working Set**: Tracks file content hashes to detect external changes and stale reads.
- **File Checkpoints**: Automatic file snapshots before any edit, restored instantly with `/undo`.

### 3. Agent Safety & Sandboxing
- **Permission Modes**: `ask` (default), `plan` (read-only), `accept-edits`, and `auto-safe` (for CI).
- **Subprocess Environment Scrubbing**: Provider keys (`*_API_KEY`, `*_SECRET`, `AWS_*`) are stripped from child processes.
- **Path Traversal Protection**: Refuses edits or writes that escape the workspace roots.
- **Secrets Redaction**: Redacts API keys, tokens, and credentials from tool output before context injection.

---

## ⌨️ Slash Commands (Interactive REPL)

Inside `ijachi-code`, press `/` for autocomplete:

| Command | Function |
|---|---|
| `/help` | List available commands, shortcuts, and keybindings |
| `/model [id\|auto]` | Show, pin, or unpin the active model |
| `/priority [cost\|speed\|quality\|balanced]` | Change routing priority mid-session |
| `/budget [USD]` | Show or set session budget cap |
| `/cost` | Spend, tokens, cache savings, and per-model breakdown |
| `/why` | Explain the routing decision for the last turn (scores, filters, candidates) |
| `/context` | Show context window usage by layer (system, memory, ledger, summary, files) |
| `/compact` | Compact conversation into a structured summary |
| `/clear` | Start a fresh session (old session remains saved and resumable) |
| `/resume [id]` | Browse and resume previous sessions |
| `/undo` | Revert the last file change set to its checkpoint |
| `/checkpoint [name]` | Create a named file checkpoint |
| `/diff` | Show all uncommitted changes made in this session |
| `/memory` | View or edit the project memory file (`IJACHI.md`) |
| `/init` | Analyze repository and draft project memory file |
| `/providers` | Show detected providers, health, and circuit-breaker status |
| `/doctor` | Run full environment diagnostics (keys, network, permissions) |
| `/exit` | Leave session and print cost summary |

**Shortcuts:**
- `!command`: Runs a shell command through the permission sandbox.
- `#note`: Appends a fact or note to the project memory file.
- `@path`: Autocompletes and attaches file contents into context.

---

## 🤖 Supported Providers (20 Backends)

Preconfigured in [`models.yaml`](models.yaml):

| Provider | Key / Auth | Speed Tier | Quality Tier | Default Models |
|---|---|---|---|---|
| **Anthropic** | `ANTHROPIC_API_KEY` | fast / medium | Tier 4-5 | `claude-3-7-sonnet`, `claude-haiku-4-5`, `claude-sonnet-4-5` |
| **OpenAI** | `OPENAI_API_KEY` | fast / medium | Tier 4-5 | `gpt-4o`, `gpt-4o-mini`, `o3-mini` |
| **Local (Ollama)** | None (local) | fast | Tier 2-3 | `llama3.1:8b`, `llama3.2:3b`, `qwen2.5-coder` |
| **DeepSeek** | `DEEPSEEK_API_KEY` | fast / medium | Tier 4-5 | `deepseek-chat` (V3), `deepseek-reasoner` (R1) |
| **Google Gemini**| `GEMINI_API_KEY` | fast / medium | Tier 4-5 | `gemini-2.5-flash`, `gemini-2.5-pro` |
| **Groq** | `GROQ_API_KEY` | ultra-fast | Tier 3-4 | `llama-3.3-70b-versatile` |
| **Cerebras** | `CEREBRAS_API_KEY` | ultra-fast | Tier 3-4 | `llama3.1-70b`, `llama3.1-8b` |
| **SambaNova** | `SAMBANOVA_API_KEY` | fast / medium | Tier 4-5 | `Meta-Llama-3.1-405B`, `Meta-Llama-3.1-70B` |
| **Fireworks** | `FIREWORKS_API_KEY` | fast | Tier 3-4 | `llama-v3p1-70b-instruct` |
| **Mistral AI** | `MISTRAL_API_KEY` | fast | Tier 3-4 | `codestral-latest`, `mistral-large-latest` |
| **AWS Bedrock** | `AWS_ACCESS_KEY_ID` | medium | Tier 4-5 | `anthropic.claude-3-5-sonnet-v2:0` |
| **Azure OpenAI** | `AZURE_OPENAI_API_KEY`| medium | Tier 4-5 | `gpt-4o`, `gpt-4o-mini` |
| **Kimi (Moonshot)**| `MOONSHOT_API_KEY` | fast | Tier 3-4 | `kimi-latest` |
| **Qwen (Alibaba)**| `DASHSCOPE_API_KEY` | medium | Tier 4-5 | `qwen-max` |
| **Perplexity** | `PERPLEXITY_API_KEY`| fast | Tier 3-4 | `sonar-pro` |
| **Cohere** | `COHERE_API_KEY` | medium | Tier 3-4 | `command-r-plus` |
| **Together AI** | `TOGETHER_API_KEY` | fast | Tier 3-4 | `llama-3.1-70b-instruct` |
| **OpenRouter** | `OPENROUTER_API_KEY`| fast / medium | Tier 2-5 | Any model aggregator |
| **Hugging Face**| `HF_TOKEN` | fast | Tier 2-3 | `Mistral-7B-Instruct-v0.3` |
| **Custom / vLLM**| `LOCAL_SERVER_URL` | fast | Custom | Self-hosted OpenAI-compatible endpoint |

---

## 🐙 GitHub Action Integration

```yaml
- name: Route Prompt with ijachi-llm-router
  id: router
  uses: ijachi/ijachi-llm-router@v1
  with:
    prompt: "Summarize recent commit changes and check for security flaws"
    priority: "cost"
    openai_api_key: ${{ secrets.OPENAI_API_KEY }}
    anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}

- name: Display Output
  run: |
    echo "Model selected: ${{ steps.router.outputs.model }}"
    echo "Cost USD: ${{ steps.router.outputs.cost_usd }}"
    echo "Response: ${{ steps.router.outputs.response }}"
```

---

## 📁 Repository Structure

```
ijachi-llm-router/
├── cli.py                     # Root CLI proxy
├── models.yaml                # Model matrix & pricing specifications
├── pyproject.toml             # Package configuration & entry points
├── action.yml                 # GitHub Action definition
├── gh-router                  # GitHub CLI extension wrapper
├── SECURITY.md                # Vulnerability disclosure policy
├── PRIVACY.md                 # Data boundaries & privacy modes
├── data/
│   └── train_data.csv         # Classifier training dataset
├── ijachi_router/
│   ├── cli/
│   │   ├── code.py            # ijachi-code CLI implementation
│   │   └── router.py          # ijachi-router CLI implementation
│   ├── session/
│   │   ├── events.py          # Canonical event schema
│   │   ├── store.py           # Atomic append-only session store
│   │   ├── state.py           # Working set & cost ledger
│   │   ├── ledger.py          # Facts & decisions ledger
│   │   ├── checkpoints.py     # File snapshotting & /undo
│   │   └── export.py          # Markdown/JSON session exporter
│   ├── context/
│   │   ├── assembler.py       # Context layer budgeting (0.75*W - O)
│   │   ├── compaction.py      # Structured compaction engine
│   │   ├── memory.py          # Layered IJACHI.md loader
│   │   └── tokens.py          # Token estimators
│   ├── agent/
│   │   ├── loop.py            # Agentic orchestration & fallback replay
│   │   ├── permissions.py     # R0-R4 risk tiers & shell command parser
│   │   ├── sandbox.py         # Workspace boundaries & env scrubbing
│   │   ├── tools.py           # Read, Edit, Write, Glob, Grep, Bash, Plan
│   │   └── limits.py          # Turn caps & loop repetition detector
│   ├── routing/
│   │   ├── features.py        # Session-aware feature extractor
│   │   ├── classifier.py      # Non-executable safe classifier
│   │   ├── policy.py          # Candidate filters & quality floors
│   │   ├── scorer.py          # Scoring with stickiness bonuses
│   │   ├── escalation.py      # Automatic frontier escalation
│   │   └── explain.py         # /why output builder
│   ├── ui/
│   │   ├── repl.py            # Rich + prompt_toolkit interactive REPL
│   │   ├── render.py          # Output streaming & terminal sanitization
│   │   └── prompts.py         # Multi-line input & autocompletion
│   ├── providers/             # 20 Provider backends + registry
│   ├── doctor.py              # Environment diagnostics runner
│   ├── fallback.py            # Circuit breakers
│   ├── metrics.py             # Usage statistics
│   └── server.py              # Pro REST gateway & telemetry dashboard
└── tests/                     # 116 unit, security, and acceptance tests
```

---

## ⚖️ Licensing & Commercial Editions

`ijachi-llm-router` is distributed under an Open Core model:
- **Community Edition (MIT)**: Free for all developers. Includes the full interactive assistant (`ijachi-code`), session continuity, agent tools, routing engine, and local diagnostics.
- **Pro Edition ($19 / month)**: Hosted REST API gateway, Web Telemetry Dashboard, and webhook budget alerts. See [PRICING.md](PRICING.md) and [Paystack Portal](https://paystack.shop/pay/enlqpvzflw).
- **Enterprise License**: Dedicated support, white-labeling, custom SLAs, and proprietary embedding. See [COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md).
