"""Small slog-compatible JSONL emitter for Python ROS nodes.

Dual sink: stdout (fluent-bit ingest path, live ops) and an append-only
local trace file (the authoritative decision trace for replay/attribution).
Both sinks share one monotonic ``seq`` per node; stdout records keep the
legacy fields (ts_ns/level/event/node) plus additive ``seq``/``layer`` —
the ground-station ingest reads known keys and passes extra keys through.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


_LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40, "fatal": 50}

_TRACE_FORMAT = 1

# Events on the l3-l4 command boundary: their provenance is the comm layer,
# not a mission decision. Unknown events default to "mission".
_COMM_EVENTS = frozenset(
    {
        "agent_prompt_received",
        "agent_prompt_rejected",
        "task_phase_published",
    }
)


def infer_layer(event: str) -> str:
    """Map one event name to its provenance layer (comm vs default mission)."""
    return "comm" if event in _COMM_EVENTS else "mission"


class StructuredLogger:
    """Flat structured telemetry to stdout plus an optional local trace file.

    The trace file is opened once in append mode and never rewritten; each
    event is one JSON line. A header line is written when the file is fresh,
    so a per-session file stays self-describing. ``emit`` is the stdout path
    (level-gated); ``trace_append`` records trace-only events and leaves
    stdout bytes untouched.
    """

    def __init__(
        self,
        node: str,
        level: str = "info",
        stdout_en: bool = True,
        trace_path: str | Path | None = None,
        session_tag: str = "",
    ):
        self.node = str(node or "dispatcher_node").lstrip("/")
        self.threshold = _LEVELS.get(str(level).lower(), _LEVELS["info"])
        self.stdout_en = bool(stdout_en)
        self._seq = 0
        self._trace_fh = None
        self._trace_path: str | None = None
        if trace_path is not None:
            self.attach_trace(trace_path, session_tag=session_tag)

    def attach_trace(self, trace_path: str | Path, session_tag: str = "") -> None:
        """Open (or reuse) the append-only trace file and stamp a fresh header.

        Idempotent per path; attaching a different path closes the previous
        sink first.
        """
        trace_path = Path(trace_path)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        fresh = not trace_path.exists() or trace_path.stat().st_size == 0
        if self._trace_fh is not None:
            self.close()
        self._trace_fh = open(trace_path, "a", encoding="utf-8")
        self._trace_path = str(trace_path)
        if fresh:
            self._write_line(
                {
                    "trace_format": _TRACE_FORMAT,
                    "node": self.node,
                    "session_tag": str(session_tag or ""),
                }
            )

    @property
    def trace_path(self) -> str | None:
        """Absolute path of the trace sink, or None when stdout-only."""
        return self._trace_path

    def emit(self, level: str, event: str, layer: str | None = None, **fields) -> None:
        """Emit one event to both sinks; seq increments even when suppressed.

        Level suppression gates stdout only: the trace file records every
        event so replay never loses a decision.
        @param level - severity (debug/info/warning/error/fatal)
        @param event - lowercase snake_case event name
        @param layer - provenance layer override (default: inferred)
        """
        record = self._record(level, event, layer, fields)
        if (
            self.stdout_en
            and _LEVELS.get(record["level"], _LEVELS["info"]) >= self.threshold
        ):
            print(
                json.dumps(
                    record, ensure_ascii=False, separators=(",", ":"), default=str
                ),
                file=sys.stdout,
                flush=True,
            )
        self._write_line(record)

    def trace_append(self, event: str, layer: str | None = None, **fields) -> None:
        """Record one trace-only event (no stdout output, never level-gated).

        @param event - lowercase snake_case event name
        @param layer - provenance layer override (default: inferred)
        """
        self._write_line(self._record("info", event, layer, fields))

    def _record(self, level: str, event: str, layer: str | None, fields: dict) -> dict:
        """Assemble one numbered event record; seq advances monotonically."""
        self._seq += 1
        record = {
            "seq": self._seq,
            "ts_ns": time.time_ns(),
            "level": str(level).lower(),
            "event": str(event),
            "node": self.node,
            "layer": layer if layer is not None else infer_layer(event),
        }
        record.update(fields)
        return record

    def _write_line(self, record: dict) -> None:
        if self._trace_fh is None:
            return
        try:
            self._trace_fh.write(
                json.dumps(
                    record, ensure_ascii=False, separators=(",", ":"), default=str
                )
                + "\n"
            )
            self._trace_fh.flush()
        except Exception as exc:  # the trace sink must never break the node
            print(f"trace write failed: {exc}", file=sys.stderr, flush=True)

    def close(self) -> None:
        """Close the trace sink (idempotent)."""
        if self._trace_fh is not None:
            try:
                self._trace_fh.close()
            finally:
                self._trace_fh = None
