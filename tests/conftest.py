import pytest


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset module-level singletons between tests."""
    import src.core.config as cfg_mod
    import src.core.container as cnt_mod
    import src.secrets.vault as vault_mod

    cfg_mod._settings = None
    cnt_mod._container = None
    vault_mod._vault = None

    yield

    cfg_mod._settings = None
    cnt_mod._container = None
    vault_mod._vault = None
