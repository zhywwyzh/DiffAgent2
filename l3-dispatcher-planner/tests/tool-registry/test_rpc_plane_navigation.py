# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest"]
# ///
"""navigation.* legacy RPC 别名归一化测试。

l4 仍发送旧导航工具名（`navigation.vla_nav {object, bearing}` /
`navigation.scene_graph_nav {object}`），l3 RpcPlane 侧把它们归一化到
canonical 注册表（`navigation.vla_reach` / `scene.navigate`），其中
scene_graph_nav 需要本地场景图对象解析。纯 headless：无 ROS、无真实 zenoh。
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


SCENE_OBJECTS = [
    {"id": 3, "label": "门", "pos": [1.0, 2.0, 0.0]},
    {"id": 7, "label": "桌子", "pos": [4.0, 5.0, 0.0]},
]


def stub_scene_graph(monkeypatch) -> None:
    monkeypatch.setattr(
        "dispatcher.tools.scene_nav.graph_source.load_objects_summary",
        lambda: ("g1", [dict(obj) for obj in SCENE_OBJECTS]),
    )


# ---------------------------------------------------------------------------
# navigation.vla_nav → navigation.vla_reach（参数变换）
# ---------------------------------------------------------------------------


def test_vla_nav_aliases_to_vla_reach(monkeypatch) -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    plane = make_plane(runtime)

    result = plane._execution_call(
        "navigation.vla_nav",
        params("call_1", identity, object="电视机", bearing="left"),
    )

    assert result == {
        "type": "rpc_result",
        "method": "navigation.vla_nav",
        "result": {"accepted": True, "call_id": "call_1"},
    }
    command = runtime._commands.get_nowait()
    assert command.kind == "call"
    assert command.call.name == "navigation.vla_reach"
    assert command.call.arguments == {
        "object": "电视机",
        "prompt": "电视机",
        "side": "left",
    }
    assert runtime._commands.empty()
    # outcome 回链用 wire 名，便于 l4 按原始调用匹配。
    assert plane._method_by_call["call_1"] == "navigation.vla_nav"


@pytest.mark.parametrize(
    "bearing,expected_side",
    [
        ("front", "front"),
        ("right", "right"),
        ("above", "above"),
        ("none", None),  # 不支持的方向不注入 side
        ("behind", None),
        ("below", None),
    ],
)
def test_vla_nav_bearing_mapping(monkeypatch, bearing, expected_side) -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    plane = make_plane(runtime)

    plane._execution_call(
        "navigation.vla_nav",
        params("call_1", identity, object="椅子", bearing=bearing),
    )

    command = runtime._commands.get_nowait()
    assert command.call.name == "navigation.vla_reach"
    expected = {"object": "椅子", "prompt": "椅子"}
    if expected_side:
        expected["side"] = expected_side
    assert command.call.arguments == expected


def test_vla_nav_passes_distance_m(monkeypatch) -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    plane = make_plane(runtime)

    plane._execution_call(
        "navigation.vla_nav",
        params("call_1", identity, object="桌子", bearing="none", distance_m=1.5),
    )

    command = runtime._commands.get_nowait()
    assert command.call.arguments == {
        "object": "桌子",
        "prompt": "桌子",
        "distance_m": 1.5,
    }


# ---------------------------------------------------------------------------
# navigation.scene_graph_nav → scene.navigate（本地 object_id 解析）
# ---------------------------------------------------------------------------


def test_scene_graph_nav_resolves_object_id(monkeypatch) -> None:
    stub_scene_graph(monkeypatch)
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    plane = make_plane(runtime)

    result = plane._execution_call(
        "navigation.scene_graph_nav",
        params("call_1", identity, object="门"),
    )

    assert result == {
        "type": "rpc_result",
        "method": "navigation.scene_graph_nav",
        "result": {"accepted": True, "call_id": "call_1"},
    }
    command = runtime._commands.get_nowait()
    assert command.kind == "call"
    assert command.call.name == "scene.navigate"
    assert command.call.arguments == {"object_id": 3}
    # mission prompt 对齐两步流程 map_search 的 user_prompt 语义。
    assert command.call.display_text == "门"
    assert runtime._commands.empty()
    assert plane._method_by_call["call_1"] == "navigation.scene_graph_nav"


def test_scene_graph_nav_substring_match(monkeypatch) -> None:
    stub_scene_graph(monkeypatch)
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    plane = make_plane(runtime)

    # label ⊇ query：l4 的“门”命中 label “门”全等覆盖；用“桌”验证子串命中。
    plane._execution_call(
        "navigation.scene_graph_nav",
        params("call_1", identity, object="桌"),
    )
    command = runtime._commands.get_nowait()
    assert command.call.arguments == {"object_id": 7}


def test_scene_graph_nav_ambiguous_match_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        "dispatcher.tools.scene_nav.graph_source.load_objects_summary",
        lambda: ("g1", [{"id": 1, "label": "红桌子"}, {"id": 2, "label": "蓝桌子"}]),
    )
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    plane = make_plane(runtime)

    with pytest.raises(ToolProtocolError) as caught:
        plane._execution_call(
            "navigation.scene_graph_nav",
            params("call_1", identity, object="桌子"),
        )
    assert caught.value.code == -32602
    assert caught.value.data["reason"] == "object_not_resolved"
    assert _admission_reason(caught.value) == "invalid_arguments"
    assert runtime._commands.empty()


def test_scene_graph_nav_unresolved_rejected(monkeypatch) -> None:
    stub_scene_graph(monkeypatch)
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    plane = make_plane(runtime)

    with pytest.raises(ToolProtocolError) as caught:
        plane._execution_call(
            "navigation.scene_graph_nav",
            params("call_1", identity, object="不存在的目标"),
        )
    assert caught.value.code == -32602
    assert caught.value.data["reason"] == "object_not_resolved"
    assert _admission_reason(caught.value) == "invalid_arguments"
    assert runtime._commands.empty()


# ---------------------------------------------------------------------------
# 端到端：从 `_on_rpc` 查询入口喂入 l4 真实会发的 JSON 字节流。
# ---------------------------------------------------------------------------


def test_on_rpc_vla_nav_end_to_end(monkeypatch) -> None:
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    plane = make_plane(runtime)

    query = rpc_query(
        "navigation.vla_nav",
        call_id="call_1",
        context=identity,
        object="空调",
        bearing="right",
    )
    plane._on_rpc(query)

    assert query.replied == [
        {
            "type": "rpc_result",
            "method": "navigation.vla_nav",
            "result": {"accepted": True, "call_id": "call_1"},
        }
    ]
    command = runtime._commands.get_nowait()
    assert command.kind == "call"
    assert command.call.name == "navigation.vla_reach"
    assert command.call.arguments == {"object": "空调", "prompt": "空调", "side": "right"}
    assert runtime._commands.empty()


def test_on_rpc_scene_graph_nav_end_to_end(monkeypatch) -> None:
    stub_scene_graph(monkeypatch)
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    plane = make_plane(runtime)

    query = rpc_query(
        "navigation.scene_graph_nav",
        call_id="call_1",
        context=identity,
        object="桌子",
    )
    plane._on_rpc(query)

    assert query.replied == [
        {
            "type": "rpc_result",
            "method": "navigation.scene_graph_nav",
            "result": {"accepted": True, "call_id": "call_1"},
        }
    ]
    command = runtime._commands.get_nowait()
    assert command.call.name == "scene.navigate"
    assert command.call.arguments == {"object_id": 7}
    assert runtime._commands.empty()


def test_on_rpc_scene_graph_nav_unresolved_replies_invalid_arguments(monkeypatch) -> None:
    stub_scene_graph(monkeypatch)
    runtime, manager, _ = make_runtime()
    identity = acquire(manager)
    plane = make_plane(runtime)

    query = rpc_query(
        "navigation.scene_graph_nav",
        call_id="call_1",
        context=identity,
        object="未知目标",
    )
    plane._on_rpc(query)

    assert query.replied == [
        {
            "type": "rpc_error",
            "method": "navigation.scene_graph_nav",
            "reason": "invalid_arguments",
            "message": "scene graph object not resolved: '未知目标'",
        }
    ]
    assert runtime._commands.empty()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
