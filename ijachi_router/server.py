"""REST API Gateway & Web Telemetry Dashboard Server for ijachi-llm-router.

Uses Python standard library http.server for zero external web framework dependencies.
Local endpoints are ungated so the open-source CLI and SDKs work out of the box.
"""

from __future__ import annotations

import json
import socketserver
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ijachi_router.core import route
from ijachi_router.license import is_pro_active, validate_license_key
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
        async function fetchStats() {
            try {
                const res = await fetch('/v1/stats');
                const data = await res.json();
                document.getElementById('total-calls').innerText = data.total_calls || 0;
                document.getElementById('total-cost').innerText = '$' + (data.total_cost_usd || 0).toFixed(4);
                document.getElementById('avg-latency').innerText = (data.avg_latency_sec || 0).toFixed(2) + 's';

                const rowsHtml = Object.entries(data.models || {}).map(([model, m]) => `
                    <tr>
                        <td><strong>${model}</strong></td>
                        <td>${m.provider}</td>
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


class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP server."""

    daemon_threads = True


class RouterRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Pro API gateway & dashboard."""

    def _send_json(self, status_code: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status_code: int, html_str: str):
        body = html_str.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _verify_auth(self) -> bool:
        """Verify API key in request header or server Pro license state."""
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            valid, _ = validate_license_key(token)
            if valid:
                return True
        return is_pro_active()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(200, _DASHBOARD_HTML)
            return

        if parsed.path == "/v1/stats":
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
            content_length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_length)
            try:
                payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
            except Exception:
                self._send_json(400, {"error": "Invalid JSON payload"})
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
                        "model": res.model,
                        "provider": res.provider,
                        "cost_usd": res.cost_usd,
                        "latency_sec": res.latency_s,
                    },
                )
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        if parsed.path == "/v1/agent/run":
            content_length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_length)
            try:
                payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
            except Exception:
                self._send_json(400, {"error": "Invalid JSON payload"})
                return

            task = payload.get("task")
            if not task:
                self._send_json(400, {"error": "Missing 'task' in request body"})
                return

            priority = payload.get("priority", "balanced")
            max_steps = int(payload.get("max_steps", 10))

            try:
                from ijachi_router.agent import AgenticRouter

                agent = AgenticRouter(priority=priority, require_approval=False)
                result = agent.run(task, max_steps=max_steps)
                self._send_json(
                    200,
                    {
                        "status": "success",
                        "final_text": result.final_text,
                        "steps": [
                            {
                                "step": s.step_number,
                                "thought": s.thought,
                                "tool": s.tool_name,
                                "model": s.model_used,
                                "cost_usd": s.cost_usd,
                            }
                            for s in result.steps
                        ],
                        "total_cost_usd": result.total_cost_usd,
                        "completed": result.completed,
                    },
                )
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        self._send_json(404, {"error": "Endpoint not found"})


def start_server(host: str = "127.0.0.1", port: int = 8000) -> HTTPServer:
    """Start the REST API Gateway & Web Dashboard server."""
    server_address = (host, port)
    httpd = ThreadedHTTPServer(server_address, RouterRequestHandler)
    print(f"🚀 ijachi-llm-router Server running on http://{host}:{port}")
    print(f"📊 Web Telemetry Dashboard: http://{host}:{port}/")
    print(f"⚡ REST API Endpoint: POST http://{host}:{port}/v1/route")
    return httpd
