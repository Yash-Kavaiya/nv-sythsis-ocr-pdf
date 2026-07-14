"""The eval/LLM call sites must surface the provider's response body in the
raised error, so a bad NVIDIA key reads as `403 ... Authorization failed`
instead of a bare `403 Forbidden` that hides the actual reason."""
import httpx
import pytest

from app.pipeline.llm import raise_for_status_with_body


def _response(status: int, body: str) -> httpx.Response:
    request = httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")
    return httpx.Response(status_code=status, text=body, request=request)


def test_403_error_includes_body_reason():
    resp = _response(403, '{"status":403,"title":"Forbidden","detail":"Authorization failed"}')
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        raise_for_status_with_body(resp)
    message = str(exc_info.value)
    assert "403" in message
    assert "Authorization failed" in message  # the actionable part, previously discarded


def test_401_missing_auth_body_surfaced():
    resp = _response(401, "Header of type `authorization` was missing")
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        raise_for_status_with_body(resp)
    assert "authorization` was missing" in str(exc_info.value)


def test_success_does_not_raise():
    raise_for_status_with_body(_response(200, '{"choices":[]}'))


def test_error_body_is_truncated():
    resp = _response(500, "x" * 1000)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        raise_for_status_with_body(resp)
    # body clipped to 400 chars so a giant HTML error page can't flood the UI cell
    assert str(exc_info.value).count("x") == 400
