"""Agent evaluation harness: solve rate, cost per solved task and time, per routing setup.

A task is a directory with ``task.yaml`` and a ``repo/`` snapshot:

    id: py-off-by-one
    category: debugging          # used for learned routing
    difficulty: easy
    prompt: "The pagination tests fail. Fix the bug."
    check: "python3 -m unittest -q"      # exit 0 = solved (optional)
    answer_contains: ["shipping_cost"]   # final answer must mention these (optional)
    forbid_changes: true                 # no file may change (optional)
    timeout: 600

Each run copies the repo to a temp dir, verifies the task is NOT already solved (an invalid
task can't inflate scores), runs the agent unattended (auto mode, OS sandbox), checks the
result, and records ground-truth outcomes for learned routing.

    ijachi-router eval --local-only
    ijachi-router eval --mode cheapest,efficient --repeat 2
"""

from __future__ import annotations

import contextlib
import datetime
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

TASKS_DIR = Path(__file__).resolve().parent.parent / "evals" / "tasks"
RESULTS_DIR = Path.home() / ".ijachi-llmr" / "evals"


@dataclass
class EvalTask:
    id: str
    path: Path
    prompt: str
    category: str = "code"
    difficulty: str = "medium"
    check: str | None = None
    answer_contains: list[str] = field(default_factory=list)
    forbid_changes: bool = False
    timeout: int = 600


@dataclass
class EvalResult:
    task: str
    mode: str
    solved: bool
    reason: str
    cost_usd: float
    seconds: float
    model: str
    tokens_in: int
    tokens_out: int
    category: str
    difficulty: str
    valid: bool = True


def load_tasks(tasks_dir: Path = TASKS_DIR, only: list[str] | None = None) -> list[EvalTask]:
    tasks = []
    for d in sorted(p for p in tasks_dir.iterdir() if (p / "task.yaml").exists()):
        meta = yaml.safe_load((d / "task.yaml").read_text())
        if only and not any(o in meta["id"] for o in only):
            continue
        tasks.append(EvalTask(
            id=meta["id"], path=d, prompt=meta["prompt"], category=meta.get("category", "code"),
            difficulty=meta.get("difficulty", "medium"), check=meta.get("check"),
            answer_contains=list(meta.get("answer_contains") or []),
            forbid_changes=bool(meta.get("forbid_changes")), timeout=int(meta.get("timeout", 600)),
        ))
    return tasks


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts and ".ijachi" not in p.parts:
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def _run_check(cmd: str, cwd: Path) -> tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=120,
                              stdin=subprocess.DEVNULL, executable="/bin/bash")
    except subprocess.TimeoutExpired:
        return False, "check timed out"
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()[-400:]


def _grade(task: EvalTask, ws: Path, answer: str, before_hash: str) -> tuple[bool, str]:
    if task.check:
        ok, out = _run_check(task.check, ws)
        if not ok:
            return False, f"check failed: {out[-200:]}"
    lower = answer.lower()
    missing = [w for w in task.answer_contains if w.lower() not in lower]
    if missing:
        return False, f"answer missing {missing}"
    if task.forbid_changes and _tree_hash(ws) != before_hash:
        return False, "files were changed but the task forbids changes"
    return True, "solved"


def run_task(task: EvalTask, mode: str, *, local_only: bool = False, model: str | None = None,
             allow_providers: set[str] | None = None, max_turns: int = 30, sandbox: bool = True,
             record: bool = True) -> EvalResult:
    from ijachi_router.agent.limits import LoopLimits
    from ijachi_router.agent.loop import AgentSessionLoop
    from ijachi_router.session.store import SessionStore

    tmp = Path(tempfile.mkdtemp(prefix=f"ijachi-eval-{task.id}-"))
    ws = tmp / "ws"
    shutil.copytree(task.path / "repo", ws)
    subprocess.run("git init -q && git add -A && git -c user.email=eval@ijachi -c user.name=eval commit -qm task",
                   shell=True, cwd=ws, capture_output=True)
    before = _tree_hash(ws)
    base = dict(task=task.id, mode=mode, cost_usd=0.0, seconds=0.0, model="", tokens_in=0, tokens_out=0,
                category=task.category, difficulty=task.difficulty)
    try:
        if task.check:
            already, _ = _run_check(task.check, ws)
            if already:
                return EvalResult(solved=False, reason="invalid task: check passes before the agent runs", valid=False, **base)

        store = SessionStore(root_dir=tmp / "sessions", workspace_dir=ws)
        store.state.priority = mode
        if model:
            store.state.pinned_model = model
        loop = AgentSessionLoop(
            store, permission_mode="auto", local_only=local_only, allow_providers=allow_providers,
            limits=LoopLimits(max_turns=max_turns, timeout_sec=task.timeout), sandbox=sandbox, quiet=True,
        )
        loop.permissions.is_tty = False
        loop.record_outcomes = False
        start = time.monotonic()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                res = loop.execute_turn(task.prompt)
        except Exception as e:  # noqa: BLE001
            return EvalResult(solved=False, reason=f"agent error: {e}", **{**base, "seconds": time.monotonic() - start})
        solved, reason = _grade(task, ws, res.text, before)
        model_key = f"{res.provider_used}/{res.model_used}"
        if record and res.model_used:
            from ijachi_router.routing.outcomes import record as record_outcome
            record_outcome(model_key, task.category, solved, weight=1.0)
        return EvalResult(
            solved=solved, reason=reason if solved or not res.limit_hit else f"{reason} (limit: {res.limit_hit})",
            **{**base, "cost_usd": round(res.cost_usd, 6), "seconds": round(time.monotonic() - start, 1),
               "model": model_key, "tokens_in": res.input_tokens, "tokens_out": res.output_tokens},
        )
    finally:
        if os.environ.get("IJACHI_EVAL_KEEP"):
            print(f"[kept {tmp}]")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


def summarize(results: list[EvalResult]) -> dict[str, dict]:
    by_mode: dict[str, list[EvalResult]] = {}
    for r in results:
        if r.valid:
            by_mode.setdefault(r.mode, []).append(r)
    out = {}
    for mode, rs in by_mode.items():
        solved = [r for r in rs if r.solved]
        cost = sum(r.cost_usd for r in rs)
        out[mode] = {
            "tasks": len(rs),
            "solved": len(solved),
            "solve_rate": round(len(solved) / len(rs), 3) if rs else 0.0,
            "total_cost_usd": round(cost, 4),
            "cost_per_solved_usd": round(cost / len(solved), 4) if solved else None,
            "avg_seconds": round(sum(r.seconds for r in rs) / len(rs), 1) if rs else 0.0,
            "models": sorted({r.model for r in rs if r.model}),
        }
    return out


def save_results(results: list[EvalResult], meta: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = RESULTS_DIR / f"eval-{stamp}.json"
    path.write_text(json.dumps({"meta": meta, "summary": summarize(results), "results": [asdict(r) for r in results]}, indent=2))
    return path
