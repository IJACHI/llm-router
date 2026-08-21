---
name: test-repair
description: >
  Automatically diagnose failing tests, locate root-cause code, apply minimal
  targeted fixes, and re-run the test suite until 100% pass or max retries reached.
trigger_keywords:
  - "fix tests"
  - "failing tests"
  - "test failure"
  - "pytest failed"
  - "test suite"
  - "repair tests"
  - "make tests pass"
  - "broken test"
version: "1.0"
---

# Test Repair Skill

## Objective
You are operating in **Test Repair Mode**. Your goal is to make all tests pass with
minimal, surgical changes to production code. Do NOT modify tests themselves unless
the test has a clear bug (e.g. wrong expected value).

## Workflow

1. **Analyse the failure output** — identify which test(s) failed, the exact assertion
   or exception, and the file/line where the failure originates.
2. **Read the failing test** — use `read_file` to understand what the test expects.
3. **Read the production code** — use `read_file` on the module under test.
4. **Trace the root cause** — follow imports and function calls until you find the bug.
5. **Apply a minimal fix** — use `edit_file` with the smallest possible change.
6. **Verify** — use `run_command` to re-run only the failing test(s) first, then the
   full suite.

## Rules
- Do NOT rewrite entire files. Use `edit_file` with precise `target_content`.
- Do NOT change test expectations unless the test itself is clearly wrong.
- Add a `# FIX: <brief reason>` comment on every changed line.
- If the fix requires adding a new helper function, add a docstring to it.
- Report: which tests now pass, which still fail (if any), and why.

## Output Format
After each repair cycle, output a brief status:
```
✅ Fixed: test_module::test_name — root cause: <description>
🔧 Change: <file>:<line> — <what changed>
```
