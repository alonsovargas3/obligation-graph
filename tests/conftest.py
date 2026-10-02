import httpx
import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests run offline. Any real HTTP transport call fails loudly."""

    def refuse(self, request):
        raise RuntimeError(f"network access in tests: {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path, monkeypatch):
    """Wave 4: og.paths resolves every data asset from OG_WORKSPACE.

    Point it at the test's own tmp dir so no test reads or writes the repository's
    eval/recorded/ or data/ by default, and start from the default replay mode.
    Tests that need another workspace set OG_WORKSPACE themselves.
    """
    monkeypatch.setenv("OG_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("OG_REPLAY", raising=False)
