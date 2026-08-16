"""Force the test suite into deterministic offline mode.

If a developer has NVIDIA_API_KEY / OPENROUTER_API_KEY / SERP_API_KEY set
locally, pipeline tests would otherwise make real LLM and web calls (slow,
flaky, and token-burning). Clear them for every test so the suite exercises
the deterministic Faker fallback path.
"""
import pytest


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch):
    for var in (
        "NVIDIA_API_KEY",
        "NVIDIA_BASE_URL",
        "NVIDIA_MODEL",
        "NVIDIA_VISION_MODEL",
        "OPENROUTER_API_KEY",
        "SERP_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
