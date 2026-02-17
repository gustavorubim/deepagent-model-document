from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from mrm_deepagent.tracing import RunTraceCollector


def test_run_trace_collector_writes_json_and_csv(tmp_path: Path) -> None:
    trace = RunTraceCollector()
    trace.log(
        event_type="llm_call",
        component="agent_runtime",
        action="attempt_start",
        status="start",
        section_id="exec_summary",
        attempt=1,
        details={"timeout_s": 90},
    )
    trace.log(
        event_type="tool_call",
        component="agent_tool",
        action="read_file",
        status="ok",
        section_id="exec_summary",
        duration_ms=12,
        details="read train.py",
    )

    json_path = tmp_path / "trace.json"
    csv_path = tmp_path / "trace.csv"
    trace.write_json(json_path)
    trace.write_csv(csv_path)

    assert json_path.exists()
    assert csv_path.exists()

    json_events = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(json_events) == 2
    assert json_events[0]["event_type"] == "llm_call"
    assert json_events[1]["event_type"] == "tool_call"
    assert "timeout_s" in json_events[0]["details"]

    with csv_path.open("r", encoding="utf-8", newline="") as file_obj:
        rows = list(csv.DictReader(file_obj))
    assert len(rows) == 2
    assert rows[0]["component"] == "agent_runtime"
    assert rows[1]["action"] == "read_file"


def test_run_trace_collector_streams_live_events() -> None:
    seen: list[dict[str, Any]] = []
    trace = RunTraceCollector()
    trace.set_live_sink(lambda event: seen.append(event))
    trace.log(
        event_type="run",
        component="cli",
        action="config_loaded",
        status="ok",
        details={"model": "gemini-3-flash-preview"},
    )

    assert len(seen) == 1
    assert seen[0]["event_type"] == "run"
    assert seen[0]["component"] == "cli"
