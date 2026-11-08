"""OS-level containment for shell commands run by the agent.

- macOS: ``sandbox-exec`` with a generated Seatbelt profile.
- Linux: ``bwrap`` (bubblewrap) with the filesystem read-only except the workspace.

Policy: writes only inside the workspace and temp/cache dirs; no reading of credential
stores (~/.ssh, cloud CLIs, this tool's own key files); outbound network denied unless
allowed (localhost always works, so dev servers and local databases are fine).
"""

from __future__ import annotations

import os
import platform
import shutil
import tempfile
from pathlib import Path

_HOME = Path.home()

# Credential stores a command never needs to read.
_SECRET_PATHS = [
    _HOME / ".ssh", _HOME / ".aws", _HOME / ".gnupg", _HOME / ".config" / "gcloud", _HOME / ".azure",
    _HOME / ".kube", _HOME / ".docker" / "config.json", _HOME / ".netrc", _HOME / ".npmrc", _HOME / ".pypirc",
    _HOME / ".ijachi-llmr" / "keys.env", _HOME / ".ijachi-llmr" / "license-signing", _HOME / ".ijachi-llmr" / "license.key",
]
# Writable besides the workspace: temp and package-manager caches.
_WRITABLE_EXTRA = [
    Path(tempfile.gettempdir()), Path("/tmp"), Path("/private/tmp"), Path("/private/var/folders"),
    _HOME / ".cache", _HOME / "Library" / "Caches", _HOME / ".npm", _HOME / ".cargo" / "registry",
    _HOME / "go" / "pkg", _HOME / ".gradle", _HOME / ".m2", _HOME / ".local" / "share" / "pnpm",
]


def available() -> str | None:
    """Name of the sandbox backend usable on this machine, or None."""
    system = platform.system()
    if system == "Darwin" and shutil.which("sandbox-exec"):
        return "seatbelt"
    if system == "Linux" and shutil.which("bwrap"):
        return "bubblewrap"
    return None


def _q(path: Path | str) -> str:
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def seatbelt_profile(workspace: Path, allow_network: bool) -> str:
    def real(p: Path) -> str:
        try:
            return str(p.resolve())
        except OSError:
            return str(p)

    writable = [workspace, *_WRITABLE_EXTRA]
    rules = [
        "(version 1)",
        "(allow default)",
        "(deny file-write*)",
        "(allow file-write* " + " ".join(f"(subpath {_q(real(p))})" for p in writable) + ")",
        '(allow file-write* (subpath "/dev") (literal "/dev/null") (literal "/dev/tty"))',
        # subpath matches the path itself and everything below it (files and directories).
        "(deny file-read* " + " ".join(f"(subpath {_q(real(p))})" for p in _SECRET_PATHS) + ")",
    ]
    if not allow_network:
        rules += [
            '(deny network-outbound (remote ip "*:*"))',
            '(allow network-outbound (remote ip "localhost:*"))',
            '(allow network-outbound (remote unix-socket))',
        ]
    return "\n".join(rules)


def wrap_command(command: str, workspace: Path, allow_network: bool = False) -> list[str] | None:
    """argv that runs *command* (a shell string) inside the sandbox, or None if unavailable."""
    backend = available()
    workspace = workspace.resolve()
    if backend == "seatbelt":
        return ["sandbox-exec", "-p", seatbelt_profile(workspace, allow_network), "/bin/sh", "-c", command]
    if backend == "bubblewrap":
        argv = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
                "--bind", str(workspace), str(workspace), "--die-with-parent", "--new-session"]
        for p in _WRITABLE_EXTRA:
            if p.exists():
                argv += ["--bind", str(p), str(p)]
        for p in _SECRET_PATHS:
            if p.is_dir():
                argv += ["--tmpfs", str(p)]
            elif p.exists():
                argv += ["--ro-bind", "/dev/null", str(p)]
        if not allow_network:
            argv.append("--unshare-net")
        argv += ["--chdir", str(workspace), "/bin/sh", "-c", command]
        return argv
    return None


def describe() -> str:
    backend = available()
    if backend:
        return f"{backend} ({platform.system()})"
    hint = "install bubblewrap (apt install bubblewrap)" if platform.system() == "Linux" else "not supported on this OS"
    return f"unavailable — {hint}"


def env_flag(name: str) -> bool | None:
    val = os.environ.get(name)
    if val is None:
        return None
    return val.strip().lower() in ("1", "true", "yes", "on")
