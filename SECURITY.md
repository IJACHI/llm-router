# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

Security is a core design principle of `ijachi-llm-router`. If you discover a vulnerability, security bypass, or unintended secret exposure, please report it privately:

1. **Email**: `security@ijachi.dev` (or open a GitHub Private Security Advisory)
2. **Response Timeline**:
   - Initial acknowledgement within **72 hours**
   - Severity triage within **5 business days**
   - Fix release and advisory notification according to severity

Please do **not** file public GitHub issues for security vulnerabilities or secret leaks.

## Security Principles and Controls

- **User in Control**: Destructive actions and out-of-workspace file changes require explicit approval.
- **Least Privilege**: Read-only by default (`R0`); commands run with a scrubbed environment stripped of API keys and credentials.
- **Data Minimization**: Sessions and metrics are stored locally in `~/.ijachi-llmr/`; prompts are sent only to the provider selected for that turn.
- **Sandboxed Execution**: Subprocess commands have timeouts, output caps, and path canonicalization.
