"""Unit and integration tests for Pro REST API Server & Web Dashboard."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
import pytest

from ijachi_router.server import start_server


TOKEN = "test-token-123"


@pytest.fixture
def running_server(monkeypatch):
    """Fixture that starts a test server instance on a random port."""
    monkeypatch.setattr("ijachi_router.server.check_pro_access", lambda name: True)
    port = 8899
    server = start_server(host="127.0.0.1", port=port, token=TOKEN)
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
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "success"
        assert "total_calls" in data
        assert "models" in data


@pytest.mark.parametrize("auth", [None, "Bearer wrong-token", "Bearer IJPRO-DEMO-TEST-KEY-2026"])
def test_stats_endpoint_requires_the_server_token(running_server, auth):
    # A licensed server is NOT open: each request needs this server's token.
    headers = {"Authorization": auth} if auth else {}
    req = urllib.request.Request(f"{running_server}/v1/stats", headers=headers)
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req)
    assert err.value.code == 401
    assert json.loads(err.value.read().decode("utf-8"))["error"] == "Unauthorized"


def test_route_endpoint_returns_category(monkeypatch, running_server):
    from ijachi_router.providers.base import GenerationResult
    res = GenerationResult(text="4", provider="p", model="m", input_tokens=1, output_tokens=1,
                           cost_usd=0.0, latency_s=0.1, category="math")
    monkeypatch.setattr("ijachi_router.server.route", lambda **kw: res)
    req = urllib.request.Request(
        f"{running_server}/v1/route", data=json.dumps({"prompt": "2+2"}).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    assert data["text"] == "4" and data["category"] == "math"


def test_server_refuses_to_start_without_license(monkeypatch):
    monkeypatch.setattr("ijachi_router.server.check_pro_access", lambda name: False)
    assert start_server(port=8898) is None



def test_route_endpoint_auth_gating(monkeypatch, running_server):

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
        assert err.code == 401
        data = json.loads(err.read().decode("utf-8"))
        assert data["error"] == "Unauthorized"
