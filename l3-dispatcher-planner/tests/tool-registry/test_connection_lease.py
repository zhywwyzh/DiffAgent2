# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest"]
# ///
"""Connection-lease + owner-scoped tool plane tests (fleet spec v1).

Pure headless: injected monotonic clock, no ROS, no zenoh session. The
middleware-level tests cover only the testable key-registration surface.
"""

from __future__ import annotations

import queue
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "ros_packages" / "dispatcher"))

from dispatcher.tool_plane import zenoh_transport  # noqa: E402
from dispatcher.tool_plane.connection_lease import (  # noqa: E402
    CANCELLING,
    SAFETY_REQUESTED,
    ConnectionLeaseManager,
)
from dispatcher.tool_plane.protocol import ToolProtocolError  # noqa: E402
from dispatcher.tool_plane.registry import ToolRegistry  # noqa: E402
from registry_support import test_registry
from types import SimpleNamespace
from dispatcher.tool_plane.runtime import ToolRuntime  # noqa: E402

STACK = "sim/0"
TTL_S = 15.0


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class LeaseIds:
    """Deterministic opaque lease ids."""

    def __init__(self) -> None:
        self._n = 0

    def __call__(self) -> str:
        self._n += 1
        return f"lease_{self._n:03d}"


def make_manager(clock: FakeClock | None = None, **kwargs) -> ConnectionLeaseManager:
    clock = clock or FakeClock()
    kwargs.setdefault("lease_id_factory", LeaseIds())
    kwargs.setdefault("wall_clock", lambda: 0.0)
    return ConnectionLeaseManager(STACK, clock=clock, **kwargs)


def make_runtime(clock: FakeClock | None = None):
    clock = clock or FakeClock()
    manager = make_manager(clock)
    commands = queue.Queue()
    runtime = ToolRuntime(test_registry(), commands, manager,
                          safety_stop=lambda reason: commands.put(SimpleNamespace(kind="safety_stop", reason=reason)))
    manager.set_active_call_probe(runtime.has_active_call)
    manager.bind_loss_handlers(
        runtime.cancel_active_for_lease_loss,
        runtime.issue_safety_stop,
        lambda station_id, lease_id: None,
    )
    return runtime, manager, clock


def acquire(manager: ConnectionLeaseManager, station: str = "station-a") -> dict:
    reply = manager.acquire(station, f"inst_{station}")
    return {k: reply[k] for k in ("station_id", "station_instance_id", "lease_id")}


def payload(call_id: str, name: str, identity: dict, arguments: dict | None = None) -> dict:
    return {
        "call_id": call_id,
        "name": name,
        "arguments": arguments or {},
        "context": {"flight_session_id": "fs", "step_id": "s1", **identity},
    }


def reason_of(exc: ToolProtocolError) -> str:
    return exc.data.get("reason", "")


# ---------------------------------------------------------------------------
# acquire
# ---------------------------------------------------------------------------


def test_acquire_returns_the_fleet_lease_reply() -> None:
    clock = FakeClock()
    manager = make_manager(clock)

    reply = manager.acquire("station-a", "inst_station-a")

    assert reply["type"] == "connection_lease"
    assert reply["accepted"] is True
    assert reply["stack_id"] == STACK
    assert reply["station_id"] == "station-a"
    assert reply["station_instance_id"] == "inst_station-a"
    assert reply["lease_id"] == "lease_001"
    assert reply["ttl_ms"] == int(TTL_S * 1000)
    assert "expires_at" in reply
    assert manager.status()["owned"] is True


def test_acquire_is_idempotent_for_the_same_station_instance() -> None:
    manager = make_manager()
    first = manager.acquire("station-a", "inst_station-a")
    second = manager.acquire("station-a", "inst_station-a")

    assert second["lease_id"] == first["lease_id"]


def test_acquire_conflicts_are_deterministic() -> None:
    manager = make_manager()
    manager.acquire("station-a", "inst_station-a")

    with pytest.raises(ToolProtocolError) as caught:
        manager.acquire("station-b", "inst_station-b")
    assert caught.value.code == -32000
    assert reason_of(caught.value) == "connection_busy"
    assert caught.value.data["owner_station_id"] == "station-a"
    assert "expires_at" in caught.value.data

    with pytest.raises(ToolProtocolError) as caught:
        manager.acquire("station-a", "inst_station-a-DUPLICATE")
    assert reason_of(caught.value) == "connection_busy"


# ---------------------------------------------------------------------------
# renew / release ownership
# ---------------------------------------------------------------------------


def test_renew_extends_expiry_for_the_current_owner_only() -> None:
    clock = FakeClock()
    manager = make_manager(clock)
    identity = acquire(manager)

    clock.advance(10.0)
    reply = manager.renew(**identity)
    assert reply["accepted"] is True

    clock.advance(14.0)  # < renewed ttl from the renewal point
    assert manager.require_owner(identity)["lease_id"] == identity["lease_id"]

    with pytest.raises(ToolProtocolError) as caught:
        manager.renew(station_id="station-b", **{k: v for k, v in identity.items() if k != "station_id"})
    assert reason_of(caught.value) == "connection_not_owner"

    with pytest.raises(ToolProtocolError) as caught:
        manager.renew(**{**identity, "lease_id": "lease_999"})
    assert reason_of(caught.value) == "connection_not_owner"


def test_release_is_owner_only_and_frees_the_stack() -> None:
    manager = make_manager()
    identity = acquire(manager)

    with pytest.raises(ToolProtocolError) as caught:
        manager.release(**{**identity, "lease_id": "lease_999"})
    assert reason_of(caught.value) == "connection_not_owner"

    reply = manager.release(**identity)
    assert reply["released"] is True
    assert manager.status()["owned"] is False

    other = acquire(manager, "station-b")
    assert other["lease_id"] != identity["lease_id"]


def test_release_with_active_call_is_connection_active() -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    runtime.admit(payload("call_1", "test.start", identity))

    with pytest.raises(ToolProtocolError) as caught:
        manager.release(**identity)
    assert caught.value.code == -32000
    assert reason_of(caught.value) == "connection_active"

    runtime.emit("call_1", status="done", phase="done")
    assert manager.release(**identity)["released"] is True


# ---------------------------------------------------------------------------
# owner-only tool plane
# ---------------------------------------------------------------------------


def test_tool_plane_is_owner_only_including_emergency_stop() -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    foreign = {**identity, "lease_id": "lease_999"}

    for index, bad in enumerate(
        (
            {},
            {k: identity[k] for k in ("station_id", "station_instance_id")},
            foreign,
        )
    ):
        with pytest.raises(ToolProtocolError) as caught:
            runtime.admit(payload(f"reject_{index}", "test.replace", bad))
        assert caught.value.code == -32000
        assert reason_of(caught.value) == "connection_not_owner"

    runtime.admit(payload("call_1", "test.start", identity))
    with pytest.raises(ToolProtocolError) as caught:
        runtime.cancel({"call_id": "call_1"})
    assert reason_of(caught.value) == "connection_not_owner"

    ack = runtime.admit(payload("call_es", "test.replace", identity))
    assert [ack[f] for f in ("station_id", "station_instance_id", "lease_id")] == [
        identity[f] for f in ("station_id", "station_instance_id", "lease_id")
    ]


def test_events_request_requires_the_lease_identity() -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)

    for request in ({}, {k: identity[k] for k in ("station_id", "station_instance_id")}):
        with pytest.raises(ToolProtocolError) as caught:
            runtime.events(request)
        assert caught.value.code == -32000
        assert reason_of(caught.value) == "connection_not_owner"

    with pytest.raises(ToolProtocolError) as caught:
        runtime.events({"after_seq": 0, "limit": 10, **identity, "lease_id": "lease_999"})
    assert reason_of(caught.value) == "connection_not_owner"


# ---------------------------------------------------------------------------
# event filtering + cursor progress
# ---------------------------------------------------------------------------


def test_events_filter_by_lease_and_advance_over_foreign_events() -> None:
    runtime, manager, clock = make_runtime()
    first = acquire(manager, "station-a")
    runtime.admit(payload("a_1", "test.start", first))

    # Lease A expires mid-call (terminal connection_lost is a foreign event
    # for station B); station B takes over and admits its own call.
    clock.advance(TTL_S + 1.0)
    assert manager.expire_if_due() is True
    second = acquire(manager, "station-b")
    runtime.admit(payload("b_1", "test.finish", second))

    reply = runtime.events({"after_seq": 0, "limit": 100, **second})

    assert [event["call_id"] for event in reply["events"]] == ["b_1"]
    # next_seq advanced past both foreign lease-A events.
    assert reply["events"][0]["seq"] == 3
    assert reply["next_seq"] == 3
    assert reply["has_more"] is False

    # An expired lease is no longer an owner: no event drain after loss.
    with pytest.raises(ToolProtocolError) as caught:
        runtime.events({"after_seq": 0, "limit": 100, **first})
    assert reason_of(caught.value) == "connection_not_owner"


def test_truncated_matching_page_keeps_the_cursor_retrievable() -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    runtime.admit(payload("call_1", "test.start", identity))
    runtime.emit("call_1", status="running", phase="executing")
    runtime.emit("call_1", status="running", phase="executing")
    runtime.emit("call_1", status="done", phase="done")

    page_one = runtime.events({"after_seq": 0, "limit": 2, **identity})
    assert [e["seq"] for e in page_one["events"]] == [1, 2]
    assert page_one["next_seq"] == 2
    assert page_one["has_more"] is True

    page_two = runtime.events({"after_seq": page_one["next_seq"], "limit": 2, **identity})
    assert [e["seq"] for e in page_two["events"]] == [3, 4]
    assert page_two["has_more"] is False


# ---------------------------------------------------------------------------
# expiry / token-loss safety behavior
# ---------------------------------------------------------------------------


def test_expiry_stops_admission_cancels_and_requests_safety() -> None:
    runtime, manager, clock = make_runtime()
    identity = acquire(manager)
    commands = runtime._commands
    runtime.admit(
        payload("call_1", "test.move", identity, {"direction": "forward", "distance_m": 1.0})
    )
    commands.get_nowait()

    clock.advance(TTL_S + 0.1)

    # Admission is stopped by the expired lease.
    with pytest.raises(ToolProtocolError) as caught:
        runtime.admit(payload("call_2", "test.start", identity))
    assert reason_of(caught.value) == "connection_not_owner"

    # Exactly one terminal with connection_lost semantics was emitted for
    # the active call (the dead lease can no longer poll; white-box read).
    terminal = list(runtime._event_history)[-1]
    assert terminal["call_id"] == "call_1"
    assert terminal["status"] == "fail"
    assert terminal["error"]["code"] == "connection_lost"

    cancel = commands.get_nowait()
    safety = commands.get_nowait()
    assert (cancel.kind, cancel.call.call_id) == ("cancel", "call_1")
    assert safety.kind == "safety_stop"
    assert commands.empty()

    # Safety request issued: the stack is free for a new station.
    assert manager.state == "unowned"
    assert manager.acquire("station-b", "inst_station-b")["accepted"] is True


def test_lease_loss_rejects_acquire_until_safety_request_is_issued() -> None:
    manager = make_manager()
    identity = acquire(manager)
    observed: list[str] = []

    def cancel_active(reason: str) -> None:
        observed.append(f"cancel:{manager.state}")
        with pytest.raises(ToolProtocolError) as caught:
            manager.acquire("station-b", "inst_station-b")
        assert reason_of(caught.value) == "connection_busy"

    def issue_safety(reason: str) -> None:
        observed.append(f"safety:{manager.state}")
        with pytest.raises(ToolProtocolError) as caught:
            manager.acquire("station-b", "inst_station-b")
        assert reason_of(caught.value) == "connection_busy"

    def on_released(station_id: str, lease_id: str) -> None:
        observed.append(f"released:{manager.state}:{station_id}:{lease_id}")

    manager.bind_loss_handlers(cancel_active, issue_safety, on_released)

    assert manager.notify_owner_lost("station_connection_token_lost") is True

    # Spec order: the state is entered BEFORE its side effect runs.
    assert observed == [
        f"cancel:{CANCELLING}",
        f"safety:{SAFETY_REQUESTED}",
        f"released:{SAFETY_REQUESTED}:{identity['station_id']}:{identity['lease_id']}",
    ]
    assert manager.state == "unowned"
    assert manager.acquire("station-b", "inst_station-b")["accepted"] is True


def test_safety_dispatch_failure_is_fail_closed_and_resumable() -> None:
    manager = make_manager()
    acquire(manager)
    attempts = {"n": 0}

    def flaky_safety(reason: str) -> None:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("safety dispatch unavailable")

    manager.bind_loss_handlers(lambda reason: None, flaky_safety, lambda station_id, lease_id: None)

    with pytest.raises(RuntimeError):
        manager.notify_owner_lost("station_connection_token_lost")

    # Fail closed: safety was NOT issued, so the stack is not releasable.
    assert manager.state == CANCELLING
    with pytest.raises(ToolProtocolError) as caught:
        manager.acquire("station-b", "inst_station-b")
    assert reason_of(caught.value) == "connection_busy"

    # The retry lands the safety request and only then frees the stack.
    assert manager.resume_pending_loss() is True
    assert attempts["n"] == 2
    assert manager.state == "unowned"
    assert manager.acquire("station-b", "inst_station-b")["accepted"] is True


def test_owner_token_loss_before_expiry_triggers_the_same_sequence() -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    commands = runtime._commands
    runtime.admit(payload("call_1", "test.start", identity))
    commands.get_nowait()

    assert manager.notify_owner_lost("station_connection_token_lost") is True

    terminal = list(runtime._event_history)[-1]
    assert terminal["error"]["code"] == "connection_lost"
    kinds = [(commands.get_nowait().kind,) for _ in range(2)]
    assert kinds == [("cancel",), ("safety_stop",)]  # 取消后直接调用安全停止端口
    assert manager.status()["owned"] is False


# ---------------------------------------------------------------------------
# claim-free status + key registration surface
# ---------------------------------------------------------------------------


def test_status_is_claim_free() -> None:
    manager = make_manager()
    unowned = manager.status()
    assert unowned["type"] == "connection_status"
    assert unowned["owned"] is False

    identity = acquire(manager)
    owned = manager.status()
    assert owned["owned"] is True
    assert owned["station_id"] == identity["station_id"]
    assert "expires_at" in owned


def test_middleware_requires_explicit_stack_id(monkeypatch) -> None:
    monkeypatch.delenv("LX_STACK_ID", raising=False)
    with pytest.raises(RuntimeError, match="LX_STACK_ID"):
        zenoh_transport.ZenohTaskMiddleware(queue.Queue())


def test_middleware_declares_fleet_keys() -> None:
    middleware = zenoh_transport.ZenohTaskMiddleware(queue.Queue(), stack_id=STACK)

    suffixes = middleware.queryable_suffixes()
    assert suffixes == ("sim/reset", "health")
    assert middleware.presence_token_key.startswith(f"lx/{STACK}/presence/task/")
    assert middleware.owner_watch_key("station-a", "lease_007") == (
        f"lx/stations/station-a/connection/lease_007/{STACK}"
    )
    # The runtime gate is wired to the middleware's own lease ledger.
    assert middleware.runtime._leases is middleware.leases


# ---------------------------------------------------------------------------
# lease watchdog: silent TTL expiry is reaped without any incoming request
# ---------------------------------------------------------------------------


class _FakeHandle:
    def __init__(self) -> None:
        self.undeclared = False

    def undeclare(self) -> None:
        self.undeclared = True


class _FakeLiveliness:
    def __init__(self) -> None:
        self.tokens: list = []
        self.subs: list = []

    def declare_token(self, key: str) -> _FakeHandle:
        self.tokens.append(str(key))
        return _FakeHandle()

    def declare_subscriber(self, key: str, handler, **kwargs) -> _FakeHandle:
        handle = _FakeHandle()
        self.subs.append((str(key), handler, handle))
        return handle


class _FakeZenohSession:
    def __init__(self) -> None:
        self._liveliness = _FakeLiveliness()

    def liveliness(self) -> _FakeLiveliness:
        return self._liveliness

    def declare_queryable(self, key: str, handler, **kwargs) -> _FakeHandle:
        return _FakeHandle()

    def declare_publisher(self, key: str, **kwargs) -> _FakeHandle:
        return _FakeHandle()

    def close(self) -> None:
        pass


class _FakeConf:
    def insert_json5(self, *args) -> None:
        pass


def test_watchdog_reaps_silent_expiry_without_incoming_request(monkeypatch) -> None:
    monkeypatch.setattr(zenoh_transport.zenoh, "open", lambda conf: _FakeZenohSession())
    monkeypatch.setattr(zenoh_transport.zenoh, "Config", _FakeConf)

    commands = queue.Queue()
    middleware = zenoh_transport.ZenohTaskMiddleware(
        commands,
        stack_id=STACK,
        lease_ttl_s=0.15,
        lease_watchdog_interval_s=0.02,
    )
    middleware.registry = test_registry()
    middleware.runtime.registry = middleware.registry
    middleware.runtime._safety_stop = lambda reason: commands.put(SimpleNamespace(kind="safety_stop", reason=reason))
    middleware.start()
    watchdog = middleware._watchdog_thread
    assert watchdog is not None and watchdog.is_alive()
    try:
        reply = middleware.leases.acquire("station-w", "inst_station-w")
        identity = {k: reply[k] for k in ("station_id", "station_instance_id", "lease_id")}
        middleware.runtime.admit(payload("watch_1", "test.start", identity))
        assert middleware.leases.state == "owned"

        # SILENT: no query, no runtime touch — only the watchdog runs.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and middleware.leases.state != "unowned":
            time.sleep(0.01)

        assert middleware.leases.state == "unowned"
        terminal = list(middleware.runtime._event_history)[-1]
        assert terminal["call_id"] == "watch_1"
        assert terminal["error"]["code"] == "connection_lost"
        reaped = list(commands.queue)
        # [0] is the still-queued admission command (no consumer thread here).
        assert (reaped[0].kind, reaped[0].call.call_id) == ("call", "watch_1")
        assert (reaped[1].kind, reaped[1].call.call_id) == ("cancel", "watch_1")
        safety = reaped[2]
        assert safety.kind == "safety_stop"
    finally:
        middleware.close()

    # Lifecycle: the watchdog is joined on close — no thread leak.
    assert not watchdog.is_alive()
    assert middleware._watchdog_thread is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_rpc_acquire_watches_owner_and_ignores_stale_delete():
    from types import SimpleNamespace
    from dispatcher.tool_plane.methods import RpcMethods
    middleware = zenoh_transport.ZenohTaskMiddleware(queue.Queue(), stack_id=STACK,
                                               safety_stop=lambda reason: None)
    session = _FakeZenohSession()
    middleware._zenoh_session = session
    plane = RpcMethods(middleware)
    params = {'station_id': 'station-a', 'station_instance_id': 'instance-a'}
    first = plane._connection_call('connection.acquire', params)['result']
    plane._connection_call('connection.acquire', params)
    assert len(session._liveliness.subs) == 1
    key, callback, handle = session._liveliness.subs[0]
    assert first['lease_id'] in key
    identity = {k: first[k] for k in ('station_id', 'station_instance_id', 'lease_id')}
    plane._connection_call('connection.release', identity)
    assert handle.undeclared
    second = plane._connection_call('connection.acquire', params)['result']
    callback(SimpleNamespace(kind=zenoh_transport.zenoh.SampleKind.DELETE))
    assert middleware.leases.is_current_owner('station-a', second['lease_id'])
    session._liveliness.subs[-1][1](SimpleNamespace(kind=zenoh_transport.zenoh.SampleKind.DELETE))
    assert not middleware.leases.status()['owned']
    middleware.close()


def test_partial_start_failure_releases_all_acquired_resources(monkeypatch):
    session = _FakeZenohSession()
    handles = []
    def queryable(*args, **kwargs):
        handle = _FakeHandle()
        handles.append(handle)
        return handle
    session.declare_queryable = queryable
    def broken_publisher(*args, **kwargs):
        raise RuntimeError('publisher unavailable')
    session.declare_publisher = broken_publisher
    closed = []
    session.close = lambda: closed.append(True)
    monkeypatch.setattr(zenoh_transport.zenoh, 'open', lambda conf: session)
    middleware = zenoh_transport.ZenohTaskMiddleware(queue.Queue(), stack_id=STACK)
    with pytest.raises(RuntimeError, match='publisher unavailable'):
        middleware.start()
    assert closed == [True]
    assert handles and all(handle.undeclared for handle in handles)
    assert middleware._zenoh_session is None
    assert middleware._presence_token is None
    middleware.close()
