"""Control-plane shutdown interrupts retries and joins owned workers."""

import sys
from pathlib import Path

import threading
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ros_packages/dispatcher"))

from dispatcher.utils.control_plane import ToolControlPlane


def test_close_interrupts_start_retry_and_joins_workers(monkeypatch):
    monkeypatch.setenv('LX_STACK_ID', 'test/lifecycle')
    host = SimpleNamespace(bind_tool_middleware=lambda middleware: None)
    plane = ToolControlPlane(host)
    attempted = threading.Event()
    closed = []
    def unavailable():
        attempted.set()
        raise RuntimeError('isolated transport unavailable')
    plane.middleware.start = unavailable
    plane.middleware.close = lambda: closed.append(True)
    plane.start()
    threads = list(plane._threads)
    try:
        assert attempted.wait(2)
    finally:
        started = time.monotonic()
        plane.close()
    assert time.monotonic() - started < 2
    assert all(not thread.is_alive() for thread in threads)
    assert plane._threads == [] and closed
