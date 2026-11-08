"""Minimal Model Context Protocol client (stdio transport, tools only).

Configure servers in settings.json:

    "mcpServers": {
      "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
                 "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "..."}}
    }

Each server's tools are exposed to the model as ``mcp__<server>__<tool>``. MCP tools can have
side effects outside the workspace, so they always need approval unless a rule such as
``mcp__github__*`` allows them. Their output is treated as untrusted content.
"""

from __future__ import annotations

import atexit
import json
import os
import queue
import re
import subprocess
import threading
from typing import Any

PROTOCOL_VERSION = "2025-06-18"
_NAME_RE = re.compile(r"[^A-Za-z0-9_-]")


def _safe(name: str) -> str:
    return _NAME_RE.sub("_", name)


class MCPError(Exception):
    pass


class MCPServer:
    def __init__(self, name: str, command: str, args: list[str] | None = None, env: dict[str, str] | None = None,
                 cwd: str | None = None, timeout: float = 60.0):
        self.name = name
        self.timeout = timeout
        from ijachi_router.agent.sandbox import WorkspaceSandbox

        # Provider keys are scrubbed; the server gets only what its config passes explicitly.
        full_env = WorkspaceSandbox(cwd)._scrub_environment(dict(os.environ))
        full_env.update({k: str(v) for k, v in (env or {}).items()})
        self.proc = subprocess.Popen(
            [command, *(args or [])], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1, env=full_env, cwd=cwd,
        )
        self._next_id = 0
        self._pending: dict[int, queue.Queue] = {}
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self.tools: list[dict[str, Any]] = []

    def _read_loop(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg_id = msg.get("id")
            if msg_id is not None and ("result" in msg or "error" in msg):
                q = self._pending.pop(msg_id, None)
                if q:
                    q.put(msg)
        for q in list(self._pending.values()):
            q.put({"error": {"message": "server exited"}})

    def _send(self, payload: dict) -> None:
        if self.proc.poll() is not None or self.proc.stdin is None:
            raise MCPError(f"MCP server '{self.name}' is not running")
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict | None = None) -> dict:
        with self._lock:
            self._next_id += 1
            msg_id = self._next_id
            q: queue.Queue = queue.Queue()
            self._pending[msg_id] = q
            self._send({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}})
        try:
            msg = q.get(timeout=self.timeout)
        except queue.Empty as e:
            self._pending.pop(msg_id, None)
            raise MCPError(f"MCP server '{self.name}' did not answer {method} within {self.timeout:.0f}s") from e
        if "error" in msg:
            raise MCPError(f"{self.name}: {msg['error'].get('message', msg['error'])}")
        return msg.get("result", {})

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def initialize(self) -> None:
        self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "ijachi-code", "version": "1.0"},
        })
        self.notify("notifications/initialized")
        tools: list[dict] = []
        cursor = None
        for _ in range(20):
            res = self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(res.get("tools", []))
            cursor = res.get("nextCursor")
            if not cursor:
                break
        self.tools = tools

    def call(self, tool: str, arguments: dict) -> tuple[bool, str]:
        res = self.request("tools/call", {"name": tool, "arguments": arguments})
        parts = []
        for c in res.get("content", []) or []:
            if c.get("type") == "text":
                parts.append(c.get("text", ""))
            elif c.get("type") == "resource":
                parts.append(json.dumps(c.get("resource", {}))[:4000])
            else:
                parts.append(f"[{c.get('type')} content omitted]")
        if res.get("structuredContent") and not parts:
            parts.append(json.dumps(res["structuredContent"])[:20_000])
        return not res.get("isError", False), "\n".join(parts)

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                self.proc.kill()


class MCPManager:
    """Starts configured servers and routes ``mcp__server__tool`` calls."""

    def __init__(self, config: dict[str, dict], cwd: str | None = None):
        self.servers: dict[str, MCPServer] = {}
        self.errors: dict[str, str] = {}
        self._routes: dict[str, tuple[str, str]] = {}
        for name, conf in (config or {}).items():
            if not isinstance(conf, dict) or not conf.get("command"):
                continue
            try:
                srv = MCPServer(_safe(name), conf["command"], conf.get("args"), conf.get("env"), cwd,
                                float(conf.get("timeout", 60)))
                srv.initialize()
                self.servers[_safe(name)] = srv
            except Exception as e:  # noqa: BLE001
                self.errors[name] = str(e)
        for sname, srv in self.servers.items():
            for t in srv.tools:
                full = f"mcp__{sname}__{_safe(t.get('name', ''))}"[:64]
                self._routes[full] = (sname, t.get("name", ""))
        atexit.register(self.close)

    def specs(self) -> list[dict[str, Any]]:
        out = []
        for full, (sname, tname) in self._routes.items():
            t = next(x for x in self.servers[sname].tools if x.get("name") == tname)
            schema = t.get("inputSchema") or {"type": "object", "properties": {}}
            out.append({"name": full, "description": f"[MCP {sname}] {t.get('description', '')}"[:1000], "parameters": schema})
        return out

    def handles(self, tool: str) -> bool:
        return tool in self._routes

    def call(self, tool: str, args: dict) -> tuple[bool, str]:
        sname, tname = self._routes[tool]
        try:
            return self.servers[sname].call(tname, args)
        except MCPError as e:
            return False, str(e)

    def close(self) -> None:
        for srv in self.servers.values():
            srv.close()
