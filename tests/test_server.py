"""Unit and integration tests for Pro REST API Server & Web Dashboard."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
import pytest

from ijachi_router.server import start_server


@pytest.fixture
def running_server(monkeypatch):
    """Fixture that starts a test server instance on a random port."""
    monkeypatch.setattr("ijachi_router.license.is_pro_active", lambda: True)
    port = 8899
    server = start_server(host="127.0.0.1", port=port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


def test_dashboard_html_endpoint(running_server):
    req = urllib.request.Request(f"{running_server}/")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        html = resp.read().decode("utf-8")
        assert "ijachi-llm-router" in html
        assert "PRO" in html


def test_stats_json_endpoint(running_server):
    req = urllib.request.Request(
        f"{running_server}/v1/stats",
        headers={"Authorization": "Bearer IJPRO-DEMO-TEST-KEY-2026"},
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "success"
        assert "total_calls" in data
        assert "models" in data


def test_stats_endpoint_auth_gating(monkeypatch, running_server):
    monkeypatch.setattr("ijachi_router.license.is_pro_active", lambda: False)
    req = urllib.request.Request(f"{running_server}/v1/stats")
    try:
        urllib.request.urlopen(req)
        pytest.fail("Expected 403 Forbidden")
    except urllib.error.HTTPError as err:
        assert err.code == 403
        data = json.loads(err.read().decode("utf-8"))
        assert "Pro License Required" in data["error"]



def test_route_endpoint_auth_gating(monkeypatch, running_server):
    monkeypatch.setattr("ijachi_router.license.is_pro_active", lambda: False)

    body = json.dumps({"prompt": "Hello world"}).encode("utf-8")
    req = urllib.request.Request(
        f"{running_server}/v1/route",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        urllib.request.urlopen(req)
        pytest.fail("Expected 403 Forbidden")
    except urllib.error.HTTPError as err:
        assert err.code == 403
        data = json.loads(err.read().decode("utf-8"))
        assert "Pro License Required" in data["error"]
        assert "paystack_url" in data
