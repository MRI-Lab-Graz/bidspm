import pytest


@pytest.fixture(autouse=True)
def _docker_images_present(monkeypatch):
    """Readiness checks must not depend on which images this machine happens to have (image_missing is tested
    on lib.preflight.docker_image_present itself, in tests/test_preflight_image_atlas.py)."""
    import lib.preflight
    monkeypatch.setattr(lib.preflight, "_image_present", lambda image: True)
