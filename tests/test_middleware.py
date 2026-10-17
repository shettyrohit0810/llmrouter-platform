from fastapi.testclient import TestClient

from backend.app import create_app


def test_response_has_request_id_and_timing_headers():
    client = TestClient(create_app())
    response = client.get("/health")
    assert "X-Request-ID" in response.headers
    assert "X-Execution-Time" in response.headers


def test_cors_headers_present_on_options_preflight():
    client = TestClient(create_app())
    response = client.options(
        "/api/v1/routers",
        headers={"Origin": "http://example.com", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code in (200, 204)
    assert "access-control-allow-origin" in {k.lower() for k in response.headers.keys()}


def test_lifespan_logs_startup_and_shutdown(capsys):
    # configure_logging() replaces the root logger's handlers with our own
    # JSON stream handler, which means pytest's `caplog` (attached to the
    # root logger separately) can't see these records -- capture the actual
    # stderr stream our handler writes to instead.
    with TestClient(create_app()) as client:
        client.get("/health")

    captured = capsys.readouterr()
    assert "Backend starting up" in captured.err
    assert "Backend shutting down" in captured.err


def test_cors_origins_come_from_config(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app import create_app

    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://console.example.com")
    client = TestClient(create_app())
    allowed = client.get("/health", headers={"Origin": "https://console.example.com"})
    other = client.get("/health", headers={"Origin": "https://evil.example.com"})
    assert allowed.headers.get("access-control-allow-origin") == "https://console.example.com"
    assert "access-control-allow-origin" not in other.headers
