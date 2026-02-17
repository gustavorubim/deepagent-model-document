from __future__ import annotations

import os

import pytest

from mrm_deepagent.agent_runtime import build_agent
from mrm_deepagent.models import AppConfig


@pytest.mark.live
def test_live_gemini_smoke() -> None:
    if os.getenv("RUN_LIVE_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_TESTS=1 to enable live Gemini smoke tests.")
    if not os.getenv("GOOGLE_API_KEY"):
        pytest.skip("GOOGLE_API_KEY not set.")
    config = AppConfig()
    runtime = build_agent(config, tools=[])
    prompt = (
        'Return JSON: {"body":"ok","checkboxes":[],"attachments":[],'
        '"evidence":["x"],"missing_items":[]}'
    )
    result = runtime.invoke_with_retry(
        prompt,
        retries=1,
        timeout_s=30,
    )
    assert isinstance(result, str)
