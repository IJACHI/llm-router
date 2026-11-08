"""Background shell commands (dev servers, watchers, long test runs).

``Bash`` with ``run_in_background: true`` starts a command and returns a shell id at once;
``BashOutput`` returns new output since the last read plus status; ``KillShell`` stops it.
Every background process is killed when the session ends.
"""

from __future__ import annotations

import atexit
import os
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class _Job:
    id: str
    command: str
    proc: subprocess.Popen
    log_path: Path
    started: float = field(default_factory=time.time)
    read_offset: int = 0


class BackgroundShells:
    MAX_JOBS = 8

    def __init__(self) -> None:
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.Lock()
        self._dir = Path(tempfile.mkdtemp(prefix="ijachi-bg-"))
        atexit.register(self.kill_all)

    def start(self, argv_or_cmd, cwd: Path, env: dict[str, str], display: str) -> str:
        with self._lock:
            running = [j for j in self._jobs.values() if j.proc.poll() is None]
            if len(running) >= self.MAX_JOBS:
                raise RuntimeError(f"too many background shells running ({len(running)}); kill one with KillShell first")
            job_id = f"bash_{uuid.uuid4().hex[:6]}"
            log_path = self._dir / f"{job_id}.log"
            log = open(log_path, "wb")
            shell = isinstance(argv_or_cmd, str)
            proc = subprocess.Popen(
                argv_or_cmd, shell=shell, cwd=cwd, env=env,
                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                start_new_session=True,  # own process group so the whole tree can be killed
            )
            log.close()
            self._jobs[job_id] = _Job(job_id, display, proc, log_path)
            return job_id

    def output(self, job_id: str, max_chars: int = 20_000) -> tuple[str, str, int | None]:
        """(new_output, status, exit_code) — status is 'running' or 'exited'."""
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        with open(job.log_path, "rb") as f:
            f.seek(job.read_offset)
            data = f.read()
        job.read_offset += len(data)
        text = data.decode("utf-8", errors="replace")
        if len(text) > max_chars:
            text = f"...[{len(text) - max_chars} earlier chars omitted]...\n" + text[-max_chars:]
        code = job.proc.poll()
        return text, ("running" if code is None else "exited"), code

    def kill(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None:
            return False
        if job.proc.poll() is None:
            try:
                os.killpg(job.proc.pid, signal.SIGTERM)
                job.proc.wait(timeout=3)
            except (ProcessLookupError, PermissionError):
                pass
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(job.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        return True

    def kill_all(self) -> None:
        for job_id in list(self._jobs):
            self.kill(job_id)

    def list(self) -> list[dict]:
        return [
            {"id": j.id, "command": j.command, "status": "running" if j.proc.poll() is None else f"exited ({j.proc.returncode})",
             "age_s": int(time.time() - j.started)}
            for j in self._jobs.values()
        ]


SHELLS = BackgroundShells()
