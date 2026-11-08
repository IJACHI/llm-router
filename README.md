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
[route] code-edit · complexity 0.62 · claude-sonnet-5-5

* Read src/auth/routes.py ok
* Grep 'limiter' in src/ 2 matches
* Edit src/auth/routes.py +14 -2 [awaiting approval]

Allow? [y] once [s] this session [a] always [n] no [e] explain: y
──────────────────────────────────────────────────────────────────
auto · claude-sonnet-5-5 · ctx 38% · turn $0.0042 · session $0.0187 / $2.00
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
| **Non-interactive / CI** | 🟢 Stable | `-p` print mode, stdin piping, machine-readable `--json` result, auto-safe exit codes (0 ok · 1 stopped by a limit · 3 error · 5 action needed approval) |
| **Test-Repair Loop (`fix`)** | 🟡 Beta | Automated test runner, failure diagnosis, and repair loop |
| **Symbol Indexer (`index`)** | 🟡 Beta | Workspace symbol cache in `.ijachi/symbols.json` |
| **Consensus Mode** | 🟡 Beta | Two-model peer review and synthesis (`ijachi-code consensus`) |
| **Commit Helper** | 🟡 Beta | Conventional commit generation from staged git diff (`ijachi-code commit`) |
| **OS Sandbox (`--sandbox`)**| 🟢 Stable | macOS Seatbelt / Linux bubblewrap: writes confined to the workspace, credential stores unreadable, network off except install/fetch commands. On by default in `auto` mode |
| **Native Tool Calling & Streaming** | 🟢 Stable | Structured (parallel) tool calls on OpenAI-compatible, Anthropic, Ollama and Bedrock models; automatic text-protocol fallback; streamed answers |
| **Evaluation Suite (`ijr eval`)** | 🟡 Beta | 15 graded tasks; solve rate, cost per solved task and time per routing mode; results feed learned routing |
| **MCP Client** | 🟡 Beta | stdio MCP servers from settings; tools exposed as `mcp__server__tool`, always approval-gated |
| **Web Search & Fetch** | 🟡 Beta | Brave / Tavily / DuckDuckGo search, SSRF-guarded fetch, content marked untrusted |
| **Explore Helpers** | 🟡 Beta | Read-only helper agents on cheap models, run in parallel, report back to the main model |
| **Git Workflow** | 🟡 Beta | `--worktree NAME` per task; `ijachi-code pr` commits, pushes and opens a draft PR via `gh` |
| **VS Code Extension** | 🟡 Beta | `editors/vscode`: open agent, ask about selection, fix file problems, task-in-worktree |

---

## 💡 What Makes It Different

### 1. Cost-Aware Multi-Model Routing
Each turn is classified by category (code, debugging, math, reasoning, creative, summarization, long-context, simple-qa) and complexity by a small bundled model (92.9% accuracy on a held-out set; retrain with `ijachi-router train`). One routing engine (`routing/engine.py`) — shared by `ijachi-code`, `ijr route`, the HTTP server and consensus mode — filters candidates by policy and capability, then scores them on expected cost, explicit quality tier, speed, and a small stickiness bonus that breaks near-ties without overriding a clearly better or cheaper model.

### Native tool calling & streaming
Models that support it (OpenAI-compatible APIs, Anthropic, Ollama, Bedrock) receive real tool definitions and return structured tool calls, including several in parallel; the session log stays provider-neutral, so you can still switch models mid-task. Models without tool support automatically fall back to a JSON-in-text protocol. Answers stream to the terminal as they are generated.

### Built to be measured
`ijachi-router eval` runs the agent on a suite of real tasks (`evals/tasks/`: a repo snapshot, a request and a pass/fail check) and reports **solve rate, cost per solved task and time** for each routing mode. Each task is checked to fail *before* the agent runs, so a broken task can never count as solved. Results are recorded per model and task category and gently adjust future routing (bounded to ±0.15 of the score; disable with `IJACHI_LEARNED_ROUTING=0`).

**Measured so far (2026-11-08):** with only a local 7B model (`qwen2.5-coder:7b` via Ollama, $0), the agent solved **3–4 of 15 tasks (20–27%)** across two runs; which tasks pass varies run to run at this model size. Frontier-model numbers have not been measured yet. Run them on your own keys (this spends credits):

```bash
ijachi-router eval --mode cheapest,efficient,best --repeat 3
ijachi-router eval --model claude-sonnet-5-5 --repeat 3
```

### Tools the agent has
Read · Edit (refuses ambiguous matches; `replace_all` opt-in) · MultiEdit (atomic) · Write · Glob · Grep (ripgrep when installed) · ListDir · RepoMap (classes/functions/signatures) · Bash (with background jobs: `run_in_background`, BashOutput, KillShell) · Explore (parallel read-only helpers) · WebSearch · WebFetch · Plan · any configured MCP tool. After every edit, fast checks (Python syntax and `ruff` if installed, `node --check`, JSON/YAML/TOML parsing) report errors straight back to the model.

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
- **Permission rules & hooks** in `.ijachi/settings.json` (project), `.ijachi/settings.local.json` (personal) or `~/.ijachi-llmr/settings.json`:
  ```json
  {
    "permissions": {"allow": ["Bash(npm test:*)", "Edit(src/**)"], "deny": ["Bash(git push:*)"], "ask": ["Edit(migrations/**)"]},
    "hooks": {"PostToolUse": [{"matcher": "Edit|Write|MultiEdit", "command": "ruff format --quiet ."}]},
    "mcpServers": {"github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]}},
    "sandbox": {"enabled": true, "network": false}
  }
  ```
  Answering **[s]** at an approval prompt allows only the suggested rule (e.g. `Bash(npm test:*)`) for the session; **[a]** saves it to `settings.local.json`. A compound command is allowed only if every part matches a rule. `PreToolUse` hooks that exit with code 2 block the call.
- **Untrusted content**: web pages, search results and MCP output are wrapped as untrusted data and the model is told never to follow instructions inside them.
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
| `/compact [focus]` | Summarize older history with a cheap model (keeps the latest turns verbatim) |
| `/clear` | Start a fresh session (old session remains saved and resumable) |
| `/resume [id]` | Browse and resume previous sessions |
| `/undo` | Revert the last file change set to its checkpoint |
| `/checkpoint [name]` | Create a named file checkpoint |
| `/diff` | Show every file change made in this session (vs. its first checkpoint) |
| `/memory` | View or edit the project memory file (`IJACHI.md`; `AGENTS.md` / `CLAUDE.md` are read too) |
| `/pr` | Commit, push and open a pull request for this task |
| `/bashes` | List background shells started by the agent |
| `/init` | Analyze repository and draft project memory file |
| `/providers` | Show detected providers, health, and circuit-breaker status |
| `/doctor` | Run full environment diagnostics (keys, network, permissions) |
| `/exit` | Leave session and print cost summary |

**Shortcuts:**
- `!command`: Runs a shell command through the permission sandbox.
- `#note`: Appends a fact or note to the project memory file.
- `@path`: Autocompletes and attaches file contents into context; `@screenshot.png` attaches an image (routed to vision models). From the CLI: `--image shot.png`.

---

## 🤖 Supported Providers (20 Backends)

Preconfigured in [`models.yaml`](models.yaml):

| Provider | Key / Auth | Speed Tier | Quality Tier | Default Models |
|---|---|---|---|---|
| **Anthropic** | `ANTHROPIC_API_KEY` | fast / slow | Tier 3-4 | `claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5` |
| **OpenAI** | `OPENAI_API_KEY` | fast / medium | Tier 4-5 | `gpt-4o`, `gpt-4o-mini`, `o3-mini` |
| **Local (Ollama)** | None (local) | fast | Tier 1-2 | `llama3.1:8b`, `llama3.2:3b`, `qwen2.5-coder` (only models you have pulled are routed to) |
| **DeepSeek** | `DEEPSEEK_API_KEY` | fast / medium | Tier 3-4 | `deepseek-chat`, `deepseek-reasoner` |
| **Google Gemini**| `GEMINI_API_KEY` | fast / medium | Tier 4-5 | `gemini-3.6-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-pro-preview` |
| **Groq** | `GROQ_API_KEY` | ultra-fast | Tier 3-4 | `llama-3.3-70b-versatile` |
| **Cerebras** | `CEREBRAS_API_KEY` | ultra-fast | Tier 3-4 | `llama3.1-70b`, `llama3.1-8b` |
| **SambaNova** | `SAMBANOVA_API_KEY` | fast / medium | Tier 4-5 | `Meta-Llama-3.1-405B`, `Meta-Llama-3.1-70B` |
| **Fireworks** | `FIREWORKS_API_KEY` | fast | Tier 3-4 | `llama-v3p1-70b-instruct` |
| **Mistral AI** | `MISTRAL_API_KEY` | fast | Tier 2-3 | `codestral-latest`, `mistral-small-latest` |
| **AWS Bedrock** | `AWS_ACCESS_KEY_ID` | medium | Tier 4-5 | `anthropic.claude-3-5-sonnet-v2:0` |
| **Azure OpenAI** | `AZURE_OPENAI_API_KEY`| medium | Tier 4-5 | `gpt-4o`, `gpt-4o-mini` |
| **Kimi (Moonshot)**| `MOONSHOT_API_KEY` (+ `MOONSHOT_BASE_URL=https://api.moonshot.cn/v1` for China-region keys) | fast / medium | Tier 3-4 | `kimi-k2.7-code`, `kimi-k3.1-pro` |
| **Qwen (Alibaba)**| `DASHSCOPE_API_KEY` | medium | Tier 2-3 | `qwen-max`, `qwen-plus`, `qwen2.5-coder-32b-instruct` |
| **Perplexity** | `PERPLEXITY_API_KEY`| fast | Tier 3-4 | `sonar-pro` |
| **Cohere** | `COHERE_API_KEY` | medium | Tier 3-4 | `command-r-plus` |
| **Together AI** | `TOGETHER_API_KEY` | fast | Tier 3 | `Llama-3.3-70B-Instruct-Turbo` |
| **OpenRouter** | `OPENROUTER_API_KEY`| fast / medium | Tier 2-5 | Any model aggregator |
| **Hugging Face**| `HF_TOKEN` | fast | Tier 2-3 | `Mistral-7B-Instruct-v0.3` |
| **Custom / vLLM**| `LOCAL_SERVER_URL` | fast | Custom | Self-hosted OpenAI-compatible endpoint |

Prices were last checked on 2026-11-08. Run `ijachi-router update-catalog` to refresh prices for catalog entries that declare an `openrouter_id`; refreshed prices are stored as an overlay and never add or rename models. Entries marked as unverified in `models.yaml` could not be checked without that provider's API key.

---

## 🔐 Pro License & REST Server

- **License keys are Ed25519-signed.** The package contains only the public key, so keys cannot be forged by guessing a format. Issue keys with `python scripts/license_admin.py issue --sub <customer> --days 365`; the private signing key lives outside the repository (`~/.ijachi-llmr/license-signing/` by default). Keys in the old unsigned `IJPRO-…` format are no longer accepted.
- **`ijachi-router serve` requires an access token on every request** (`Authorization: Bearer <token>`). Pass `--token`, set `IJACHI_SERVER_TOKEN`, or use the random token printed at startup; the dashboard link printed by `serve` includes it. A Pro license is needed to start the server, but a license key is not an API credential.
- `POST /v1/agent/run` uses the same agent loop as `ijachi-code`, defaulting to `permission_mode: "auto-safe"` (only read-only actions run without approval).

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
│   │   ├── memory.py          # Layered IJACHI.md / AGENTS.md / CLAUDE.md loader
│   │   ├── repomap.py         # Signature-level codebase outline
│   │   ├── images.py          # Image attachments
│   │   └── tokens.py          # Token estimators
│   ├── agent/
│   │   ├── loop.py            # Agent loop: routing, native tools, streaming, helpers, summaries
│   │   ├── permissions.py     # R0-R4 risk tiers, shell parser, rule-based approvals
│   │   ├── rules.py           # Bash(npm test:*) / Edit(src/**) permission rules
│   │   ├── hooks.py           # PreToolUse / PostToolUse hooks
│   │   ├── sandbox.py         # Workspace boundaries, env scrubbing, redaction
│   │   ├── os_sandbox.py      # Seatbelt (macOS) / bubblewrap (Linux) containment
│   │   ├── background.py      # Background shells
│   │   ├── diagnostics.py     # Post-edit checks
│   │   ├── web.py             # WebSearch / WebFetch
│   │   ├── mcp.py             # MCP stdio client
│   │   ├── tools.py           # Tool implementations & schemas
│   │   └── limits.py          # Turn caps & loop repetition detector
│   ├── routing/
│   │   ├── features.py        # Session-aware feature extractor
│   │   ├── classifier.py      # Non-executable safe classifier
│   │   ├── policy.py          # Candidate filters & quality floors
│   │   ├── engine.py          # Single ranking engine (agent, ijr, server, consensus)
│   │   ├── scorer.py          # Scoring: cost, quality tier, speed, stickiness, learned outcomes
│   │   ├── outcomes.py        # Learned routing from eval and session outcomes
│   │   ├── escalation.py      # Automatic frontier escalation
│   │   └── explain.py         # /why output builder
│   ├── ui/
│   │   ├── repl.py            # Rich + prompt_toolkit interactive REPL
│   │   ├── render.py          # Output streaming & terminal sanitization
│   │   └── prompts.py         # Multi-line input & autocompletion
│   ├── providers/             # 20 Provider backends + registry
│   ├── evals.py               # Evaluation harness (ijachi-router eval)
│   ├── gitflow.py             # Worktrees & pull requests
│   ├── settings.py            # Layered settings (permissions, hooks, MCP, sandbox)
│   ├── doctor.py              # Environment diagnostics runner
│   ├── fallback.py            # Circuit breakers
│   ├── metrics.py             # Usage statistics
│   └── server.py              # Pro REST gateway & telemetry dashboard
├── evals/tasks/               # Evaluation tasks (repo snapshot + prompt + check)
├── editors/vscode/            # VS Code extension
├── scripts/                   # license_admin.py, train_classifier.py
└── tests/                     # 209 unit, security, integration and acceptance tests
```

---

## ⚖️ Licensing & Commercial Editions

`ijachi-llm-router` is distributed under an Open Core model:
- **Community Edition (MIT)**: Free for all developers. Includes the full interactive assistant (`ijachi-code`), session continuity, agent tools, routing engine, and local diagnostics.
- **Pro Edition ($19 / month)**: Hosted REST API gateway, Web Telemetry Dashboard, and webhook budget alerts. See [PRICING.md](PRICING.md) and [Paystack Portal](https://paystack.shop/pay/enlqpvzflw).
- **Enterprise License**: Dedicated support, white-labeling, custom SLAs, and proprietary embedding. See [COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md).
