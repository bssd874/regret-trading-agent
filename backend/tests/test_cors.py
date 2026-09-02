from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def test_dashboard_origin_is_allowed() -> None:
    response = client.options(
        "/api/regret/metrics",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "http://127.0.0.1:3000"
    )


def test_untrusted_origin_is_not_allowed() -> None:
    response = client.options(
        "/api/regret/metrics",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "access-control-allow-origin" not in response.headers
