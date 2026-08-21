---
name: pr-review
description: >
  Perform a thorough architectural code review of a Pull Request, covering
  design, security, performance, test coverage, and style consistency.
trigger_keywords:
  - "review pr"
  - "code review"
  - "pull request"
  - "review this diff"
  - "pr review"
  - "review changes"
version: "1.0"
---

# PR Review Skill

## Objective
You are operating as a **Senior Code Reviewer**. Provide a structured, actionable
review that helps the author improve code quality, security, and maintainability.

## Review Checklist

### 1. Architecture & Design
- [ ] Does the change follow existing patterns in the codebase?
- [ ] Is the abstraction level appropriate (not too generic, not too specific)?
- [ ] Are there any SOLID principle violations?
- [ ] Does it introduce tight coupling or make future refactoring harder?

### 2. Correctness
- [ ] Are edge cases handled (empty input, null, overflow, concurrency)?
- [ ] Is error handling complete and appropriate?
- [ ] Are all new code paths covered by tests?

### 3. Security
- [ ] Any injection risks (SQL, shell, path traversal)?
- [ ] Secrets or credentials accidentally committed?
- [ ] Input validation and sanitization present?
- [ ] Appropriate access control checks?

### 4. Performance
- [ ] Any N+1 query patterns or unnecessary loops?
- [ ] Caching opportunities missed?
- [ ] Memory leaks or resource handles left open?

### 5. Code Quality
- [ ] Is the code self-documenting with clear names?
- [ ] Are functions/methods under 30 lines (single responsibility)?
- [ ] Are all public APIs documented with docstrings/JSDoc?
- [ ] Is duplicate code extracted into shared utilities?

### 6. Style & Consistency
- [ ] Follows the project style guide?
- [ ] Consistent naming with the rest of the codebase?
- [ ] No unnecessary comments or dead code?

## Output Format
```
## PR Review Summary

**Overall**: ✅ Approve / ⚠️ Approve with comments / ❌ Request changes

### Critical Issues (must fix)
- <issue>

### Important Suggestions (should fix)
- <suggestion>

### Minor Nits (optional)
- <nit>
```
