"""The localhost guard: DNS rebinding (bad Host) and cross-origin browser
requests (bad Origin) get 403; local traffic and the ngrok tunnel Twilio
posts through (PUBLIC_BASE_URL) pass."""

from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)


def test_rebound_host_rejected():
    assert client.get("/health", headers={"Host": "evil.example.com:5060"}).status_code == 403


def test_cross_origin_rejected():
    assert client.get("/health", headers={"Origin": "https://evil.example.com"}).status_code == 403


def test_no_origin_passes():
    assert client.get("/health").status_code == 200


def test_public_base_url_host_passes(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://abc123.ngrok.app")
    assert client.get("/health", headers={"Host": "abc123.ngrok.app"}).status_code == 200
