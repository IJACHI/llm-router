"""IDE Language Server & VS Code Extension Bridge for ijachi-code.

Provides a lightweight JSON-RPC / REST endpoint for real-time inline code completion
and LSP integration in VS Code, Cursor, and Antigravity IDE.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from ijachi_router.core import route


class LSPRequestHandler(BaseHTTPRequestHandler):
    """Handles HTTP completion requests from IDE extensions."""

    def _send_json(self, status_code: int, data: dict):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length)
        try:
            payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception:
            self._send_json(400, {"error": "Invalid JSON payload"})
            return

        prompt = payload.get("prompt") or payload.get("prefix")
        if not prompt:
            self._send_json(400, {"error": "Missing 'prompt' or 'prefix'"})
            return

        priority = payload.get("priority", "speed")

        try:
            res = route(prompt=prompt, priority=priority)
            self._send_json(
                200,
                {
                    "completion": res.text,
                    "model": res.model,
                    "provider": res.provider,
                    "cost_usd": res.cost_usd,
                },
            )
        except Exception as e:
            self._send_json(500, {"error": str(e)})


def start_lsp_server(host: str = "127.0.0.1", port: int = 8001) -> HTTPServer:
    """Start the LSP bridge server on the given host and port."""
    server = HTTPServer((host, port), LSPRequestHandler)
    return server
