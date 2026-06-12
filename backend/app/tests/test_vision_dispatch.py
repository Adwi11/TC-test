import json
import httpx
import pytest

from app.services import vision as vision_mod


class _FakeResponse:
    """Minimal stand-in for httpx.Response."""

    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or json.dumps(payload or {})

    def json(self):
        """Return the canned JSON payload."""
        return self._payload


class _FakeClient:
    """httpx.AsyncClient stand-in with a recording post()."""

    last_url: str | None = None
    last_body: dict | None = None
    last_headers: dict | None = None

    def __init__(self, *args, response: _FakeResponse | None = None, **kwargs):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def post(self, url, json=None, headers=None):
        """Record the request and return the canned response."""
        _FakeClient.last_url = url
        _FakeClient.last_body = json
        _FakeClient.last_headers = headers
        return self._response


def _install_fake(monkeypatch, response: _FakeResponse):
    """Patch httpx.AsyncClient to return the canned response."""
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: _FakeClient(response=response))


@pytest.mark.asyncio
async def test_dispatch_routes_to_gemini_when_provider_set(monkeypatch):
    """When VISION_PROVIDER=gemini and a key is set, the Gemini endpoint should be hit."""
    monkeypatch.setenv("VISION_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_VISION_MODEL", "gemini-2.5-flash")
    from app.config import get_settings
    get_settings.cache_clear()

    gemini_payload = {"candidates": [{"content": {"parts": [{"text": json.dumps({"name": "Asha", "email": "a@b.io"})}]}}]}
    _install_fake(monkeypatch, _FakeResponse(200, gemini_payload))

    result = await vision_mod._dispatch_vision([("image/png", "aGVsbG8=")])
    assert "generativelanguage.googleapis.com" in (_FakeClient.last_url or "")
    assert _FakeClient.last_headers.get("x-goog-api-key") == "test-key"
    assert result.fields.get("email") == "a@b.io"


@pytest.mark.asyncio
async def test_dispatch_falls_back_to_ollama_when_gemini_key_missing(monkeypatch):
    """If provider=gemini but the key is empty, dispatch should fall back to Ollama."""
    monkeypatch.setenv("VISION_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    from app.config import get_settings
    get_settings.cache_clear()

    ollama_payload = {"message": {"content": json.dumps({"name": "B"})}}
    _install_fake(monkeypatch, _FakeResponse(200, ollama_payload))

    await vision_mod._dispatch_vision([("image/png", "aGVsbG8=")])
    assert "/api/chat" in (_FakeClient.last_url or "")


@pytest.mark.asyncio
async def test_dispatch_routes_to_ollama_when_provider_set_to_ollama(monkeypatch):
    """Explicit VISION_PROVIDER=ollama should route to the Ollama endpoint."""
    monkeypatch.setenv("VISION_PROVIDER", "ollama")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    from app.config import get_settings
    get_settings.cache_clear()

    ollama_payload = {"message": {"content": json.dumps({"email": "x@y.io"})}}
    _install_fake(monkeypatch, _FakeResponse(200, ollama_payload))

    result = await vision_mod._dispatch_vision([("image/png", "aGVsbG8=")])
    assert "/api/chat" in (_FakeClient.last_url or "")
    assert result.fields.get("email") == "x@y.io"
