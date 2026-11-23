"""Every kind of error must come back in the standard shape:
{"error": {"code": ..., "message": ..., "details": ...}}
"""

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from api.errors import (
    ConflictError,
    NotFoundError,
    RateLimitedError,
    UnauthorizedError,
)
from api.schemas import CreateJobRequest, ErrorResponse

FRONTEND_ORIGIN = "http://localhost:3001"


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    """The real app plus a few routes that fail on purpose."""

    @app.get("/_test/not-found")
    async def not_found() -> None:
        raise NotFoundError("Job not found")

    @app.get("/_test/unauthorized")
    async def unauthorized() -> None:
        raise UnauthorizedError()

    @app.get("/_test/conflict")
    async def conflict() -> None:
        raise ConflictError("Job already finished", details={"status": "completed"})

    @app.get("/_test/rate-limited")
    async def rate_limited() -> None:
        raise RateLimitedError("Too many jobs", retry_after_seconds=120)

    @app.get("/_test/crash")
    async def crash() -> None:
        raise RuntimeError("secret internal detail: password=hunter2")

    @app.post("/_test/jobs")
    async def create(body: CreateJobRequest) -> dict[str, str]:
        return {"query": body.query}

    return app


def assert_error_shape(body: dict, code: str) -> dict:
    """Checks the body matches ErrorResponse exactly and has the expected code."""
    ErrorResponse.model_validate(body)  # raises if the shape is wrong
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    return body["error"]


async def test_app_error_not_found(client: AsyncClient) -> None:
    r = await client.get("/_test/not-found")
    assert r.status_code == 404
    err = assert_error_shape(r.json(), "not_found")
    assert err["message"] == "Job not found"
    assert err["details"] is None


async def test_app_error_with_details(client: AsyncClient) -> None:
    r = await client.get("/_test/conflict")
    assert r.status_code == 409
    err = assert_error_shape(r.json(), "conflict")
    assert err["details"] == {"status": "completed"}


async def test_unauthorized_sets_www_authenticate(client: AsyncClient) -> None:
    r = await client.get("/_test/unauthorized")
    assert r.status_code == 401
    assert_error_shape(r.json(), "unauthorized")
    assert r.headers["www-authenticate"] == "Bearer"


async def test_rate_limited_sets_retry_after(client: AsyncClient) -> None:
    r = await client.get("/_test/rate-limited")
    assert r.status_code == 429
    err = assert_error_shape(r.json(), "rate_limited")
    assert r.headers["retry-after"] == "120"
    assert err["details"] == {"retry_after_seconds": 120}


async def test_validation_error_lists_fields(client: AsyncClient) -> None:
    r = await client.post("/_test/jobs", json={"query": "  a "})  # 1 char after stripping
    assert r.status_code == 422
    err = assert_error_shape(r.json(), "validation_error")
    assert err["details"] == [
        {
            "location": "body",
            "field": "query",
            "message": "String should have at least 3 characters",
            "type": "string_too_short",
        }
    ]


async def test_validation_error_missing_and_unknown_fields(client: AsyncClient) -> None:
    r = await client.post("/_test/jobs", json={"qeury": "typo in field name"})
    assert r.status_code == 422
    err = assert_error_shape(r.json(), "validation_error")
    problems = {(d["field"], d["type"]) for d in err["details"]}
    assert problems == {("query", "missing"), ("qeury", "extra_forbidden")}


async def test_validation_error_does_not_echo_input(client: AsyncClient) -> None:
    r = await client.post("/_test/jobs", json={"query": "ok", "password": "hunter2"})
    assert r.status_code == 422
    assert "hunter2" not in r.text


async def test_malformed_json(client: AsyncClient) -> None:
    r = await client.post(
        "/_test/jobs", content="{not json", headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 422
    assert_error_shape(r.json(), "validation_error")


async def test_valid_request_passes_and_is_stripped(client: AsyncClient) -> None:
    r = await client.post("/_test/jobs", json={"query": "  intermittent fasting  "})
    assert r.status_code == 200
    assert r.json() == {"query": "intermittent fasting"}


async def test_unknown_url(client: AsyncClient) -> None:
    r = await client.get("/does-not-exist")
    assert r.status_code == 404
    assert_error_shape(r.json(), "not_found")


async def test_wrong_method_keeps_allow_header(client: AsyncClient) -> None:
    r = await client.delete("/_test/jobs")
    assert r.status_code == 405
    assert_error_shape(r.json(), "method_not_allowed")
    assert "POST" in r.headers["allow"]


async def test_unexpected_crash_is_generic_500(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    r = await client.get("/_test/crash")
    assert r.status_code == 500
    err = assert_error_shape(r.json(), "internal_error")
    assert err["message"] == "Something went wrong"
    # The client never sees internals...
    assert "hunter2" not in r.text
    assert "RuntimeError" not in r.text
    # ...but our logs have the full error.
    assert "secret internal detail" in caplog.text


async def test_crash_response_still_has_cors_headers(client: AsyncClient) -> None:
    """Without CORS headers the browser hides the 500 from the frontend entirely."""
    r = await client.get("/_test/crash", headers={"Origin": FRONTEND_ORIGIN})
    assert r.status_code == 500
    assert r.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


async def test_app_error_has_cors_headers(client: AsyncClient) -> None:
    r = await client.get("/_test/not-found", headers={"Origin": FRONTEND_ORIGIN})
    assert r.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
