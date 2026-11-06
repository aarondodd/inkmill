import pytest


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    """Keep every test away from the real settings, state and plugins."""
    cfg = tmp_path / "config"
    state = tmp_path / "state"
    monkeypatch.setenv("INKMILL_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("INKMILL_STATE_DIR", str(state))
    # No test reaches GitHub for Inkmill updates; this folder does not exist.
    monkeypatch.setenv("INKMILL_UPDATE_URL", (tmp_path / "no-updates").as_uri() + "/")
    return cfg, state
