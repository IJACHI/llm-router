# Privacy Policy and Data Flow Specification

Document 5.7 Data flows and privacy modes:

## Data Boundaries

| Data | Stays Local | Sent to Selected Provider | Sent to Remote Server |
|---|---|---|---|
| **Prompts & Assembled Context** | Stored in `~/.ijachi-llmr/sessions/` | Yes, for each request to that specific provider | No |
| **Workspace Files** | Yes | Yes, only when relevant file snippets are in context | No |
| **Command Output** | Yes | Yes, after secrets redaction | No |
| **Provider API Keys** | Yes (`~/.ijachi-llmr/keys.env`, keychain, or env) | Only to their own provider as an Authorization header | Never |
| **Usage Statistics** | Yes (`~/.ijachi-llmr/history.jsonl`) | No | Only if opted in or using Pro Dashboard |
| **Catalog Updates** | No user content | No user content | Fetches signed model pricing catalog |

## Privacy Modes

- **Default**: Sessions and metrics are stored strictly on your local disk in `~/.ijachi-llmr/`. Telemetry is disabled by default.
- **`--no-persist`**: Nothing is written to disk beyond session metrics totals. Sessions cannot be resumed.
- **`--local-only`**: Cloud providers are completely disabled. Only local models (Ollama / custom local servers) are queried. No prompt data ever leaves your computer.
