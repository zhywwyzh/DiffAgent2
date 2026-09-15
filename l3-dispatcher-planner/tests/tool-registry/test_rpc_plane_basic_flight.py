# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest"]
# ///
"""basic_flight.* -> flight.* RPC 别名归一化测试。

覆盖 l4 legacy wire 名在 l3 RpcPlane 侧的 name/argument 适配，
以及 admission / outcome 回链 / 负例。纯 headless：无 ROS、无真实 zenoh。
"""

from __future__ import annotations

import json
import queue
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "ros_packages" / "dispatcher"))

from dispatcher.utils.connection_lease import ConnectionLeaseManager  # noqa: E402
from dispatcher.utils.rpc_plane import RpcPlane, _admission_reason  # noqa: E402
from dispatcher.tools.protocol import ToolProtocolError  # noqa: E402
from dispatcher.tools.registry import ToolRegistry  # noqa: E402
from dispatcher.tools.runtime import ToolRuntime  # noqa: E402


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_runtime(clock: FakeClock | None = None):
    clock = clock or FakeClock()
    manager = ConnectionLeaseManager(
        "sim/test",
        clock=clock,
        wall_clock=lambda: 0.0,
        lease_id_factory=iter(f"lease_{n:03d}" for n in range(1000)).__next__,
    )
    runtime = ToolRuntime(ToolRegistry.default(), queue.Queue(), manager)
    return runtime, manager, clock


def acquire(manager: ConnectionLeaseManager, station: str = "station-a") -> dict:
    reply = manager.acquire(station, f"stn_{station[-1]}")
    return {k: reply[k] for k in ("station_id", "station_instance_id", "lease_id")}


class _FakeSession:
    """RpcPlane.__init__ 只要求非空 session；_execution_call 不触碰它。"""


class _FakeMw:
    def __init__(self, runtime: ToolRuntime) -> None:
        self.runtime = runtime
        self._zenoh_session = _FakeSession()


def make_plane(runtime: ToolRuntime) -> RpcPlane:
    return RpcPlane(_FakeMw(runtime))


def params(call_id: str, context: dict, **arguments) -> dict:
    """对齐 l4 RpcPlaneClient.execution 的扁平参数结构。"""
    return {"call_id": call_id, "context": context, **arguments}


class _Bytes:
    """仿 zenoh payload：`.to_bytes()` 返回序列化后的原始 RPC JSON 字节流。"""

    def __init__(self, obj: dict) -> None:
        self._obj = obj

    def to_bytes(self) -> bytes:
        return json.dumps(self._obj, ensure_ascii=False).encode()


class _FakeQuery:
    """仿 zenoh query：携带 wire JSON，并捕获 `reply()` 写回的字节流。"""

    def __init__(self, obj: dict) -> None:
        self.key_expr = "lx/sim/3dgs/rpc"
        self._payload = _Bytes(obj)
        self.replied: list[dict] = []

    @property
    def payload(self) -> _Bytes:
        return self._payload

    def reply(self, key_expr: str, data: bytes) -> None:
        self.replied.append(json.loads(data.decode()))


def rpc_query(method: str, **params_fields) -> _FakeQuery:
    """构造一个 l4 真实会发出的 RPC 请求（method + params 扁平对象）。"""
    return _FakeQuery({"method": method, "params": params_fields})


CASES = [
    ("basic_flight.takeoff", "flight.takeoff", {}, {}),
    ("basic_flight.land", "flight.land", {}, {}),
    (
        "basic_flight.translate",
        "flight.translate",
        {"direction": "forward", "distance_m": 1},
        {"direction": "forward", "distance_m": 1.0},
    ),
    (
        "basic_flight.rotate",
        "flight.rotate",
        {"yaw_delta_deg": 90},
        {"yaw_delta_deg": 90.0},
    ),
    ("basic_flight.emergency_stop", "flight.emergency_stop", {}, {}),
    # l4 空参，l3 注入 target=origin 后通过 canonical 校验。
    ("basic_flight.return", "flight.return", {}, {"target": "origin"}),
]


@pytest.mark.parametrize("wire,canonical,wire_args,expected_args", CASES)
def test_basic_flight_alias_admits(wire, canonical, wire_args, expected_args) -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    plane = make_plane(runtime)

    result = plane._execution_call(wire, params("call_1", identity, **wire_args))

    assert result == {
        "type": "rpc_result",
        "method": wire,
        "result": {"accepted": True, "call_id": "call_1"},
    }
    command = runtime._commands.get_nowait()
    assert command.kind == "call"
    assert command.call.name == canonical
    assert command.call.arguments == expected_args
    assert runtime._commands.empty()
    # outcome 回链用 wire 名，便于 l4 按原始调用匹配。
    assert plane._method_by_call["call_1"] == wire


def test_outcome_echoes_wire_method() -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    plane = make_plane(runtime)

    plane._execution_call(
        "basic_flight.translate",
        params("call_1", identity, direction="forward", distance_m=1),
    )

    published: list[dict] = []

    class _Pub:
        def put(self, data: bytes) -> None:
            published.append(json.loads(data.decode()))

    plane._outcome = _Pub()
    plane.on_event(
        {"status": "done", "call_id": "call_1", "structuredContent": {"completion": "done"}}
    )

    assert published[0]["method"] == "basic_flight.translate"
    assert published[0]["call_id"] == "call_1"
    assert published[0]["outcome"]["ok"] is True


def test_unknown_method_is_method_not_found() -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    plane = make_plane(runtime)

    with pytest.raises(ToolProtocolError) as caught:
        plane._execution_call("basic_flight.hover", params("call_1", identity))

    assert caught.value.code == -32601
    assert caught.value.data["reason"] == "tool_not_registered"
    assert _admission_reason(caught.value) == "method_not_found"


def test_execution_requires_call_id() -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    plane = make_plane(runtime)

    with pytest.raises(ToolProtocolError) as caught:
        plane._execution_call("basic_flight.takeoff", {"context": identity})

    assert caught.value.code == -32602
    assert _admission_reason(caught.value) == "invalid_arguments"


def test_execution_without_lease_is_connection_not_owner() -> None:
    runtime, _, _ = make_runtime()
    plane = make_plane(runtime)

    with pytest.raises(ToolProtocolError) as caught:
        plane._execution_call("basic_flight.takeoff", {"call_id": "call_1"})

    assert caught.value.code == -32000
    assert _admission_reason(caught.value) == "connection_not_owner"


def test_canonical_name_still_works_and_invalid_enum_rejected() -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    plane = make_plane(runtime)

    plane._execution_call(
        "flight.translate", params("call_1", identity, direction="forward", distance_m=2)
    )
    cmd = runtime._commands.get_nowait()
    assert cmd.call.name == "flight.translate"
    assert cmd.call.arguments == {"direction": "forward", "distance_m": 2.0}

    with pytest.raises(ToolProtocolError) as caught:
        plane._execution_call(
            "basic_flight.translate", params("call_2", identity, direction="back", distance_m=1)
        )
    assert caught.value.code == -32602
    assert _admission_reason(caught.value) == "invalid_arguments"


def test_missing_session_step_derives_nonempty_frame() -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    plane = make_plane(runtime)

    plane._execution_call("basic_flight.takeoff", {"call_id": "call_1", "context": identity})

    cmd = runtime._commands.get_nowait()
    assert cmd.call.flight_session_id == identity["lease_id"]
    assert cmd.call.step_id == "call_1"
    assert cmd.call.frame_id == f"copaw/{identity['lease_id']}/call_1"


# ---------------------------------------------------------------------------
# 端到端：从 `_on_rpc` 查询入口喂入 l4 真实会发的 JSON 字节流（走完整
# 解析 -> 分发 -> 异常映射），而非直接调 `_execution_call`。
# ---------------------------------------------------------------------------


def test_on_rpc_basic_flight_translate_end_to_end() -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    plane = make_plane(runtime)

    query = rpc_query(
        "basic_flight.translate",
        call_id="call_1",
        context=identity,
        direction="forward",
        distance_m=1,
    )
    plane._on_rpc(query)

    # 同步 reply：accepted，且 method 回显 legacy wire 名（l4 用它匹配调用）。
    assert query.replied == [
        {
            "type": "rpc_result",
            "method": "basic_flight.translate",
            "result": {"accepted": True, "call_id": "call_1"},
        }
    ]
    # 但内部 admit 的是 canonical 名 + 数值归一化参数。
    command = runtime._commands.get_nowait()
    assert command.kind == "call"
    assert command.call.name == "flight.translate"
    assert command.call.arguments == {"direction": "forward", "distance_m": 1.0}
    assert runtime._commands.empty()


def test_on_rpc_basic_flight_return_injects_target_default() -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    plane = make_plane(runtime)

    plane._on_rpc(rpc_query("basic_flight.return", call_id="call_1", context=identity))

    assert plane._method_by_call["call_1"] == "basic_flight.return"
    command = runtime._commands.get_nowait()
    assert command.call.name == "flight.return"
    assert command.call.arguments == {"target": "origin"}


def test_on_rpc_unknown_method_replies_method_not_found() -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    plane = make_plane(runtime)

    query = rpc_query("basic_flight.hover", call_id="call_1", context=identity)
    plane._on_rpc(query)

    assert query.replied == [
        {
            "type": "rpc_error",
            "method": "basic_flight.hover",
            "reason": "method_not_found",
            "message": "tool not registered: basic_flight.hover",
        }
    ]
    # 未产生任何准入命令。
    assert runtime._commands.empty()


def test_on_rpc_missing_call_id_replies_invalid_arguments() -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    plane = make_plane(runtime)

    query = rpc_query("basic_flight.takeoff", context=identity)
    plane._on_rpc(query)

    assert query.replied[0]["type"] == "rpc_error"
    assert query.replied[0]["reason"] == "invalid_arguments"


def test_on_rpc_non_object_params_replies_invalid_arguments() -> None:
    runtime, manager, _ = make_runtime()
    plane = make_plane(runtime)

    query = _FakeQuery({"method": "basic_flight.takeoff", "params": "not-a-dict"})
    plane._on_rpc(query)

    assert query.replied[0]["type"] == "rpc_error"
    assert query.replied[0]["reason"] == "invalid_arguments"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
