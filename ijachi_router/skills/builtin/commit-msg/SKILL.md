---
name: commit-msg
description: >
  Generate a Conventional Commit message from the current git diff,
  following the Conventional Commits specification (feat/fix/chore/docs/refactor/test).
trigger_keywords:
  - "commit"
  - "git commit"
  - "commit message"
  - "write commit"
  - "conventional commit"
  - "generate commit"
version: "1.0"
---

# Commit Message Generation Skill

## Objective
Generate a precise, informative Conventional Commit message from `git diff` output.

## Conventional Commits Format
```
<type>(<scope>): <short description>

[optional body]

[optional footer(s)]
```

## Types
| Type       | When to use |
|------------|-------------|
| `feat`     | New feature for the user |
| `fix`      | Bug fix for the user |
| `docs`     | Documentation changes only |
| `style`    | Formatting, no logic change |
| `refactor` | Refactoring production code |
| `test`     | Adding or updating tests |
| `chore`    | Build, deps, config changes |
| `perf`     | Performance improvement |
| `ci`       | CI/CD configuration |
| `revert`   | Reverting a previous commit |

## Rules
1. **Subject line** ≤ 72 characters, lowercase after type/scope, no trailing period.
2. **Scope** = the module or feature area changed (e.g. `agent`, `formatter`, `cli`).
3. **Body** (optional): explain *why*, not *what*. Wrap at 72 chars.
4. **Breaking changes**: add `BREAKING CHANGE:` footer if the public API changes.
5. Output ONLY the commit message — no extra prose.

## Example Output
```
feat(formatter): add language-aware code style enforcement

Introduces CodeFormatter with support for black/isort (Python),
prettier (JS/TS), and gofmt (Go). Auto-injects missing docstrings
and runs a lint gate after every file write.

BREAKING CHANGE: write_file now applies formatting by default.
```
