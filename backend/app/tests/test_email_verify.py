import httpx
import pytest

from app.services import email_verify as ev


class _FakeResponse:
    """Minimal stand-in for httpx.Response for unit tests."""

    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        """Return the canned JSON payload."""
        return self._payload


class _FakeClient:
    """Async context manager that returns a canned response from get()."""

    def __init__(self, response: _FakeResponse | None = None, raises: Exception | None = None):
        self._response = response
        self._raises = raises

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def get(self, _url):
        """Return the canned response or raise."""
        if self._raises:
            raise self._raises
        return self._response


def _patch(monkeypatch, **kwargs):
    """Install a fake AsyncClient on httpx for one test."""
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: _FakeClient(**kwargs))


@pytest.mark.asyncio
async def test_deliverable_when_valid_mx_and_not_disposable(monkeypatch):
    """A valid + mx + non-disposable response should mark the email deliverable."""
    _patch(monkeypatch, response=_FakeResponse(200, {"valid": True, "mx": True, "disposable": False, "reason": "Valid"}))
    out = await ev.verify_email("asha@gmail.com")
    assert out.deliverable is True
    assert out.mx is True
    assert out.disposable is False


@pytest.mark.asyncio
async def test_blocked_when_no_mx(monkeypatch):
    """An mx=false response should block the send."""
    _patch(monkeypatch, response=_FakeResponse(200, {"valid": True, "mx": False, "disposable": False}))
    out = await ev.verify_email("ghost@nodomain.fake")
    assert out.deliverable is False
    assert "no mx" in out.reason


@pytest.mark.asyncio
async def test_blocked_when_disposable(monkeypatch):
    """A disposable=true response should block the send."""
    _patch(monkeypatch, response=_FakeResponse(200, {"valid": True, "mx": True, "disposable": True}))
    out = await ev.verify_email("burner@mailinator.com")
    assert out.deliverable is False
    assert "disposable" in out.reason


@pytest.mark.asyncio
async def test_fail_open_on_network_error(monkeypatch):
    """When the verify API errors out, we let the send proceed (fail-open)."""
    _patch(monkeypatch, raises=httpx.ConnectError("boom"))
    out = await ev.verify_email("asha@example.com")
    assert out.deliverable is True
    assert out.fail_open is True
