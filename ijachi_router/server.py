"""REST API Gateway & Web Telemetry Dashboard Server for ijachi-llm-router Pro.

Uses Python standard library http.server for zero external web framework dependencies.
Gated behind Pro tier license key verification.
"""

from __future__ import annotations

import contextlib
import hmac
import json
import os
import secrets
import socketserver
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ijachi_router.core import route
from ijachi_router.license import check_pro_access
from ijachi_router.metrics import _HISTORY_PATH, load_history

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ijachi-llm-router Pro Dashboard</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0f19;
            --card-bg: rgba(22, 30, 46, 0.7);
            --card-border: rgba(255, 255, 255, 0.08);
            --accent-cyan: #06b6d4;
            --accent-purple: #8b5cf6;
            --accent-green: #10b981;
            --text-primary: #f3f4f6;
            --text-secondary: #9ca3af;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }
        body { background: var(--bg-color); color: var(--text-primary); min-height: 100vh; padding: 2rem; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 2rem; }
        .logo { font-size: 1.5rem; font-weight: 700; background: linear-gradient(135deg, var(--accent-cyan), var(--accent-purple)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .badge { background: rgba(6, 182, 212, 0.15); color: var(--accent-cyan); border: 1px solid var(--accent-cyan); padding: 0.25rem 0.75rem; border-radius: 999px; font-size: 0.8rem; font-weight: 600; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1.5rem; margin-bottom: 2rem; }
        .card { background: var(--card-bg); backdrop-filter: blur(12px); border: 1px solid var(--card-border); border-radius: 12px; padding: 1.5rem; }
        .card-title { font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 0.5rem; font-weight: 500; }
        .card-value { font-size: 1.8rem; font-weight: 700; color: #ffffff; }
        .table-card { background: var(--card-bg); backdrop-filter: blur(12px); border: 1px solid var(--card-border); border-radius: 12px; padding: 1.5rem; }
        table { width: 100%; border-collapse: collapse; text-align: left; }
        th { color: var(--text-secondary); font-size: 0.8rem; text-transform: uppercase; padding: 0.75rem 1rem; border-bottom: 1px solid var(--card-border); }
        td { padding: 0.85rem 1rem; font-size: 0.9rem; border-bottom: 1px solid rgba(255,255,255,0.03); }
        tr:hover { background: rgba(255,255,255,0.02); }
        .btn { background: var(--accent-cyan); color: #000; border: none; padding: 0.6rem 1.2rem; border-radius: 8px; font-weight: 600; cursor: pointer; transition: opacity 0.2s; }
        .btn:hover { opacity: 0.9; }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">🚦 ijachi-llm-router <span class="badge">PRO</span></div>
        <button class="btn" onclick="fetchStats()">Refresh Telemetry</button>
    </div>

    <div class="grid">
        <div class="card">
            <div class="card-title">Total Requests</div>
            <div class="card-value" id="total-calls">0</div>
        </div>
        <div class="card">
            <div class="card-title">Total Spend (USD)</div>
            <div class="card-value" id="total-cost" style="color: var(--accent-green)">$0.0000</div>
        </div>
        <div class="card">
            <div class="card-title">Avg Latency</div>
            <div class="card-value" id="avg-latency" style="color: var(--accent-cyan)">0.00s</div>
        </div>
    </div>

    <div class="table-card">
        <h3 style="margin-bottom: 1rem;">Model Breakdown</h3>
        <table>
            <thead>
                <tr>
                    <th>Model</th>
                    <th>Provider</th>
                    <th>Calls</th>
                    <th>Cost (USD)</th>
                    <th>Avg Latency</th>
                </tr>
            </thead>
            <tbody id="model-rows">
                <tr><td colspan="5" style="text-align:center; color:var(--text-secondary)">Loading telemetry...</td></tr>
            </tbody>
        </table>
    </div>

    <script>
        // The API token arrives in the URL fragment (never sent to the server in logs) and is
        // remembered for this browser tab only.
        function apiToken() {
            const m = location.hash.match(/token=([^&]+)/);
            if (m) { sessionStorage.setItem('ijr_token', decodeURIComponent(m[1])); history.replaceState(null, '', location.pathname); }
            return sessionStorage.getItem('ijr_token') || '';
        }
        function esc(v) {
            return String(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
        }
        async function fetchStats() {
            try {
                const res = await fetch('/v1/stats', { headers: { 'Authorization': 'Bearer ' + apiToken() } });
                if (res.status === 401) {
                    document.getElementById('model-rows').innerHTML = '<tr><td colspan="5" style="text-align:center;">Open the dashboard with the link printed by <code>ijachi-router serve</code> (it includes the access token).</td></tr>';
                    return;
                }
                const data = await res.json();
                document.getElementById('total-calls').innerText = data.total_calls || 0;
                document.getElementById('total-cost').innerText = '$' + (data.total_cost_usd || 0).toFixed(4);
                document.getElementById('avg-latency').innerText = (data.avg_latency_sec || 0).toFixed(2) + 's';

                const rowsHtml = Object.entries(data.models || {}).map(([model, m]) => `
                    <tr>
                        <td><strong>${esc(model)}</strong></td>
                        <td>${esc(m.provider)}</td>
                        <td>${m.calls}</td>
                        <td>$${m.cost.toFixed(4)}</td>
                        <td>${(m.total_latency / (m.calls || 1)).toFixed(2)}s</td>
                    </tr>
                `).join('');
                document.getElementById('model-rows').innerHTML = rowsHtml || '<tr><td colspan="5" style="text-align:center;">No calls logged yet</td></tr>';
            } catch (err) {
                console.error('Failed to load stats:', err);
            }
        }
        fetchStats();
    </script>
</body>
</html>
"""


_MAX_BODY_BYTES = 2_000_000
_AGENT_MODES = {"auto-safe", "plan", "semi-auto", "auto"}


class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP server."""

    daemon_threads = True


class RouterRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Pro API gateway & dashboard."""

    def _send_json(self, status_code: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status_code: int, html_str: str):
        body = html_str.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com")
        self.end_headers()
        self.wfile.write(body)

    def _verify_auth(self) -> bool:
        """Every API request must carry this server's access token (constant-time compare)."""
        expected = getattr(self.server, "api_token", None)
        auth_header = self.headers.get("Authorization", "")
        if not expected or not auth_header.startswith("Bearer "):
            return False
        return hmac.compare_digest(auth_header[7:].strip().encode(), expected.encode())

    def _reject(self) -> None:
        self._send_json(401, {
            "error": "Unauthorized",
            "message": "Send the server access token: Authorization: Bearer <token> "
                       "(printed by `ijachi-router serve`, or set via IJACHI_SERVER_TOKEN).",
        })

    def _read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length > _MAX_BODY_BYTES:
            self._send_json(413, {"error": "Request body too large"})
            return None
        body = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            self._send_json(400, {"error": "Invalid JSON payload"})
            return None
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "JSON body must be an object"})
            return None
        return payload

    def log_message(self, format, *args):  # noqa: A002 - keep tokens out of stderr access logs
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(200, _DASHBOARD_HTML)
            return

        if parsed.path == "/v1/stats":
            if not self._verify_auth():
                self._reject()
                return

            records = load_history()
            total_calls = len(records)
            total_cost = sum(r.get("cost_usd", 0.0) for r in records)
            total_lat = sum(r.get("latency_sec", 0.0) for r in records)
            avg_lat = (total_lat / total_calls) if total_calls > 0 else 0.0

            models_summary: dict[str, dict] = {}
            for r in records:
                m = str(r.get("model", "unknown"))
                p = str(r.get("provider", "unknown"))
                c = float(r.get("cost_usd", 0.0))
                lat = float(r.get("latency_sec", 0.0))
                if m not in models_summary:
                    models_summary[m] = {"provider": p, "calls": 0, "cost": 0.0, "total_latency": 0.0}
                models_summary[m]["calls"] += 1
                models_summary[m]["cost"] += c
                models_summary[m]["total_latency"] += lat

            self._send_json(
                200,
                {
                    "status": "success",
                    "total_calls": total_calls,
                    "total_cost_usd": total_cost,
                    "avg_latency_sec": avg_lat,
                    "models": models_summary,
                },
            )
            return

        self._send_json(404, {"error": "Endpoint not found"})


    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/v1/route":
            if not self._verify_auth():
                self._reject()
                return

            payload = self._read_json()
            if payload is None:
                return

            prompt = payload.get("prompt")
            if not prompt:
                self._send_json(400, {"error": "Missing 'prompt' in request body"})
                return

            priority = payload.get("priority")
            max_cost = payload.get("max_cost")

            try:
                res = route(prompt=prompt, priority=priority, max_cost=max_cost)
                self._send_json(
                    200,
                    {
                        "status": "success",
                        "text": res.text,
                        "model": res.model_used,
                        "provider": res.provider,
                        "cost_usd": res.cost,
                        "latency_sec": res.latency_sec,
                        "category": getattr(res, "category", None),
                    },
                )
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        if parsed.path == "/v1/agent/run":
            if not self._verify_auth():
                self._reject()
                return

            payload = self._read_json()
            if payload is None:
                return

            task = payload.get("task")
            if not task:
                self._send_json(400, {"error": "Missing 'task' in request body"})
                return

            priority = payload.get("priority")
            max_steps = max(1, min(int(payload.get("max_steps", 10)), 50))
            mode = payload.get("permission_mode", "auto-safe")
            if mode not in _AGENT_MODES:
                self._send_json(400, {"error": f"permission_mode must be one of {sorted(_AGENT_MODES)}"})
                return

            try:
                from ijachi_router.agent.limits import LoopLimits
                from ijachi_router.agent.loop import AgentSessionLoop
                from ijachi_router.session.store import SessionStore

                store = SessionStore(workspace_dir=getattr(self.server, "workspace_dir", Path.cwd()))
                if priority:
                    store.state.priority = priority
                loop = AgentSessionLoop(store=store, permission_mode=mode, limits=LoopLimits(max_turns=max_steps))
                loop.permissions.is_tty = False  # HTTP callers can never answer an approval prompt
                with contextlib.redirect_stdout(sys.stderr):
                    result = loop.execute_turn(task)
                steps = [
                    {"tool": e.tool_call.get("name"), "args": e.tool_call.get("args"), "thought": e.tool_call.get("thought", "")}
                    for e in store.read_events() if e.type == "tool_call" and e.turn == store.state.turn_count
                ]
                self._send_json(
                    200,
                    {
                        "status": "success",
                        "final_text": result.text,
                        "session_id": store.session_id,
                        "model": f"{result.provider_used}/{result.model_used}",
                        "steps": steps,
                        "total_cost_usd": result.cost_usd,
                        "completed": result.completed,
                        "denied_actions": result.denied_actions,
                    },
                )
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        self._send_json(404, {"error": "Endpoint not found"})


def start_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    token: str | None = None,
    workspace_dir: Path | str | None = None,
) -> HTTPServer | None:
    """Start the Pro REST API Gateway & Web Dashboard server.

    The Pro license is checked once here. Every API request must then present this server's
    access token, so a licensed server is not open to anyone who can reach the port.
    """
    if not check_pro_access("REST API Gateway & Web Dashboard"):
        return None

    httpd = ThreadedHTTPServer((host, port), RouterRequestHandler)
    httpd.api_token = token or os.environ.get("IJACHI_SERVER_TOKEN") or secrets.token_urlsafe(24)
    httpd.workspace_dir = Path(workspace_dir or Path.cwd()).resolve()
    shown = "(from IJACHI_SERVER_TOKEN)" if not token and os.environ.get("IJACHI_SERVER_TOKEN") else httpd.api_token
    print(f"🚀 ijachi-llm-router Pro Server running on http://{host}:{port}")
    print(f"🔑 Access token: {shown}")
    print(f"📊 Web Telemetry Dashboard: http://{host}:{port}/#token={httpd.api_token}")
    print(f"⚡ REST API Endpoint: POST http://{host}:{port}/v1/route  (Authorization: Bearer <token>)")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("⚠️  Listening beyond localhost: traffic is plain HTTP. Put it behind a TLS proxy and keep the token secret.")
    return httpd
