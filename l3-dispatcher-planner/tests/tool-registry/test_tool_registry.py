# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest"]
# ///
"""Public contract tests for the executable tool registry."""

from __future__ import annotations

import queue
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "ros_packages" / "dispatcher"))

from dispatcher.tool_plane.connection_lease import ConnectionLeaseManager  # noqa: E402
from dispatcher.tool_plane.intake import ToolIntake  # noqa: E402
from dispatcher.tool_plane.protocol import ToolProtocolError  # noqa: E402
from dispatcher.tool_plane.registry import ToolRegistry  # noqa: E402
from registry_support import test_registry
from types import SimpleNamespace
from dispatcher.tool_plane.runtime import ToolRuntime  # noqa: E402

EXPECTED_TOOLS = {'basic_flight.' + name for name in ('takeoff', 'land', 'translate', 'rotate', 'return', 'emergency_stop')} | {'navigation.vla_nav'}


class FakeClock:
    """Injected monotonic clock (fleet-spec test seam)."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_runtime(clock: FakeClock | None = None):
    """Runtime + manager + clock bound to one unowned stack."""
    clock = clock or FakeClock()
    manager = ConnectionLeaseManager(
        "sim/test",
        clock=clock,
        wall_clock=lambda: 0.0,
        lease_id_factory=iter(f"lease_{n:03d}" for n in range(1000)).__next__,
    )
    runtime = ToolRuntime(test_registry(), queue.Queue(), manager)
    return runtime, manager, clock


def acquire(manager: ConnectionLeaseManager, station: str = "station-a") -> dict:
    reply = manager.acquire(station, f"stn_{station[-1]}")
    return {field: reply[field] for field in ("station_id", "station_instance_id", "lease_id")}


def call_payload(call_id: str, name: str, arguments: dict, identity: dict) -> dict:
    return {
        "call_id": call_id,
        "name": name,
        "arguments": arguments,
        "context": {
            "flight_session_id": "flight_a",
            "step_id": "step_1",
            **identity,
        },
    }


def owner_events(runtime: ToolRuntime, identity: dict, **kwargs) -> dict:
    return runtime.events({"after_seq": 0, "limit": 100, **identity, **kwargs})


def test_list_exposes_only_executable_tools() -> None:
    first = ToolRegistry.default().list_tools()
    second = ToolRegistry.default().list_tools()

    listed = {tool["name"] for tool in first["tools"]}
    assert listed == EXPECTED_TOOLS
    assert first["type"] == "tool_list"
    assert first["revision"] == second["revision"]
    assert len(first["revision"]) == 71  # "sha256:" + 64 hex characters


def test_call_identity_and_arguments_are_normalized_once() -> None:
    call = test_registry().normalize_call(
        {
            "call_id": "call_1",
            "name": "test.move",
            "arguments": {"direction": "forward", "distance_m": 2},
            "context": {
                "flight_session_id": "flight_a",
                "step_id": "step_1",
                "display_text": "Forward 2 metres",
            },
        }
    )

    assert call.name == "test.move"
    assert call.arguments == {"direction": "forward", "distance_m": 2.0}
    assert call.frame_id == "copaw/flight_a/step_1"


def test_runtime_admission_is_idempotent_and_replayable() -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    payload = call_payload("call_1", "test.start", {}, identity)
    commands = runtime._commands

    first = runtime.admit(payload)
    second = runtime.admit(payload)
    command = commands.get_nowait()
    events = owner_events(runtime, identity)

    assert first == second
    assert first["type"] == "tool_call_ack"
    for field in ("station_id", "station_instance_id", "lease_id"):
        assert first[field] == identity[field]
    assert command.kind == "call"
    assert command.call.call_id == "call_1"
    assert commands.empty()
    assert [event["phase"] for event in events["events"]] == ["accepted"]


def test_runtime_accepts_exactly_one_terminal_event() -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    runtime.admit(call_payload("call_1", "test.start", {}, identity))

    assert runtime.emit("call_1", status="done", phase="done", message="forwarded")
    assert not runtime.emit("call_1", status="fail", phase="fail", message="late failure")
    events = owner_events(runtime, identity)["events"]

    assert [event["status"] for event in events] == ["running", "done"]
    for event in events:
        for field in ("station_id", "station_instance_id", "lease_id"):
            assert event[field] == identity[field]


def test_runtime_cancel_is_idempotent_and_terminal() -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    runtime.admit(call_payload("call_1", "test.rotate", {"yaw_delta_deg": 90}, identity))
    commands = runtime._commands
    commands.get_nowait()

    cancel = {"call_id": "call_1", "reason": "operator_cancel", **identity}
    first = runtime.cancel(cancel)
    second = runtime.cancel(cancel)
    cancel_command = commands.get_nowait()
    runtime.mark_cancelled("call_1", cancel_command.reason)
    terminal = runtime.cancel({"call_id": "call_1", **identity})

    assert first["cancelled"] is True
    assert second["cancelled"] is True
    assert cancel_command.kind == "cancel"
    assert commands.empty()
    assert terminal["reason"] == "already_terminal"
    assert owner_events(runtime, identity)["events"][-1]["error"]["code"] == "cancelled"


def test_executor_routes_translate_into_skill_workflow() -> None:
    """P3.8：test.move 经注册表元数据构造携带原生 ToolCall 的
    SkillCommand 进入工作流（requires_perception 来自 ToolSpec）。"""

    class Host:
        def __init__(self) -> None:
            self.started = []

        def start_tool_workflow(self, call, command) -> None:
            self.started.append((call, command))




    registry = test_registry()
    host = Host()
    executor = ToolIntake(registry, host)
    call = registry.normalize_call(
        {
            "call_id": "call_1",
            "name": "test.move",
            "arguments": {"direction": "left", "distance_m": 1.5},
            "context": {"flight_session_id": "flight_a", "step_id": "step_1"},
        }
    )

    executor.start(call)

    assert host.started[0][0] is call
    assert host.started[0][1].call is call  # SkillCommand 携带原生 ToolCall
    assert host.started[0][1].requires_perception is False


def test_intake_routes_perception_requirement() -> None:
    """P3.8：test.sense 的 requires_perception=True 由注册表
    ToolSpec 声明驱动（原 vla adapter 硬编码下沉为元数据）。"""

    class Host:
        def __init__(self) -> None:
            self.started = []

        def start_tool_workflow(self, call, command) -> None:
            self.started.append((call, command))

    registry = test_registry()
    host = Host()
    executor = ToolIntake(registry, host)
    call = registry.normalize_call(
        {
            "call_id": "call_1",
            "name": "test.sense",
            "arguments": {},
            "context": {"flight_session_id": "flight_a", "step_id": "step_1"},
        }
    )

    executor.start(call)

    assert host.started[0][1].call is call
    assert host.started[0][1].requires_perception is True


def test_same_owner_preempts_before_new_execution():
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    commands = runtime._commands
    runtime.admit(
        call_payload("move_1", "test.move", {"direction": "forward", "distance_m": 2}, identity)
    )
    commands.get_nowait()

    runtime.admit(call_payload("stop_1", "test.replace", {}, identity))

    cancel = commands.get_nowait()
    emergency = commands.get_nowait()
    assert (cancel.kind, cancel.call.call_id, cancel.reason) == (
        "cancel",
        "move_1",
        "preempted_by_new_instruction",
    )
    assert (emergency.kind, emergency.call.call_id) == ("call", "stop_1")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
