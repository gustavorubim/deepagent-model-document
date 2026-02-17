"""Run trace collection and persistence helpers."""

from __future__ import annotations

import csv
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class RunTraceCollector:
    """Thread-safe collector for structured runtime trace events."""

    _CSV_COLUMNS = [
        "seq",
        "timestamp",
        "event_type",
        "component",
        "action",
        "status",
        "section_id",
        "attempt",
        "payload_format",
        "duration_ms",
        "details",
    ]

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._next_seq = 1
        self._lock = threading.Lock()
        self._live_sink: Callable[[dict[str, Any]], None] | None = None

    def set_live_sink(self, sink: Callable[[dict[str, Any]], None] | None) -> None:
        """Set optional callback to stream trace events as they are recorded."""
        with self._lock:
            self._live_sink = sink

    def log(
        self,
        *,
        event_type: str,
        component: str,
        action: str,
        status: str = "ok",
        section_id: str | None = None,
        attempt: int | None = None,
        payload_format: str | None = None,
        duration_ms: int | None = None,
        details: dict[str, Any] | str | None = None,
    ) -> None:
        """Record a structured trace event."""
        sink: Callable[[dict[str, Any]], None] | None = None
        event_copy: dict[str, Any] | None = None
        with self._lock:
            event = {
                "seq": self._next_seq,
                "timestamp": datetime.now(UTC).isoformat(),
                "event_type": event_type,
                "component": component,
                "action": action,
                "status": status,
                "section_id": section_id or "",
                "attempt": "" if attempt is None else attempt,
                "payload_format": payload_format or "",
                "duration_ms": "" if duration_ms is None else duration_ms,
                "details": _serialize_details(details),
            }
            self._events.append(event)
            self._next_seq += 1
            sink = self._live_sink
            if sink is not None:
                event_copy = dict(event)
        if sink is not None and event_copy is not None:
            try:
                sink(event_copy)
            except Exception:
                # Trace streaming must never interfere with the main run flow.
                pass

    def events(self) -> list[dict[str, Any]]:
        """Return a shallow copy of collected events."""
        with self._lock:
            return list(self._events)

    def write_json(self, path: Path) -> None:
        """Write trace events as JSON array."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.events(), indent=2, sort_keys=False)
        path.write_text(payload + "\n", encoding="utf-8")

    def write_csv(self, path: Path) -> None:
        """Write trace events as CSV rows."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as file_obj:
            writer = csv.DictWriter(file_obj, fieldnames=self._CSV_COLUMNS)
            writer.writeheader()
            for event in self.events():
                writer.writerow({key: event.get(key, "") for key in self._CSV_COLUMNS})


def _serialize_details(details: dict[str, Any] | str | None) -> str:
    if details is None:
        return ""
    if isinstance(details, str):
        return details
    return json.dumps(details, sort_keys=True, default=str)
