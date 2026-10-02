import httpx
import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests run offline. Any real HTTP transport call fails loudly."""

    def refuse(self, request):
        raise RuntimeError(f"network access in tests: {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
