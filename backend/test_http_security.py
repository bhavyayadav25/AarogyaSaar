"""FIX 8 — CORS, HTTP security and production-hardening regression tests."""

from fastapi.testclient import TestClient
import main


def test_security_headers_and_request_id_are_present():
    client = TestClient(main.app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert "default-src 'none'" in response.headers.get("Content-Security-Policy", "")
    assert "microphone=(self)" in response.headers.get("Permissions-Policy", "")
    assert response.headers.get("X-Request-ID")


def test_cors_is_explicit_and_does_not_allow_arbitrary_origin():
    client = TestClient(main.app)
    allowed = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert allowed.headers.get("access-control-allow-credentials") == "true"

    blocked = client.options(
        "/api/health",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert blocked.status_code == 400
    assert "access-control-allow-origin" not in blocked.headers


def test_request_body_limit_rejects_declared_oversized_body():
    client = TestClient(main.app)
    old_limit = main.MAX_REQUEST_BODY_BYTES
    main.MAX_REQUEST_BODY_BYTES = 10
    try:
        response = client.post("/api/auth/login", content=b"x" * 11, headers={"Content-Type": "application/json"})
        assert response.status_code == 413
        assert response.headers.get("X-Request-ID")
    finally:
        main.MAX_REQUEST_BODY_BYTES = old_limit


def test_production_defaults_are_safe_without_changing_demo_mode():
    assert main.IS_PRODUCTION is False
    assert "*" not in main.TRUSTED_HOSTS
    assert "/docs" in main.PUBLIC_PATHS
    assert main.REQUIRE_HTTPS is False
