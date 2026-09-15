"""单入口连接、空生产发现面与通用调用回归。"""

import json
import queue
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "ros_packages/dispatcher"))

from dispatcher.tools.registry import ToolRegistry
from dispatcher.tools.runtime import ToolRuntime
from dispatcher.utils.connection_lease import ConnectionLeaseManager
from dispatcher.utils.rpc_plane import RpcPlane
from registry_support import test_registry


REMOVED_NAMES = (
    "navigation.vla_reach", "scene.map_search", "scene.navigate",
    "flight.takeoff", "flight.land", "flight.translate", "flight.rotate",
    "flight.return", "flight.emergency_stop", "scene_nav.graph.list",
    "scene_nav.graph.select", "scene_nav.graph.save", "scene_nav.graph.objects",
    "scene_nav.graph.object_pose", "navigation.vla_nav", "navigation.scene_graph_nav",
    "basic_flight.takeoff", "basic_flight.land", "basic_flight.translate",
    "basic_flight.rotate", "basic_flight.return", "basic_flight.emergency_stop",
)


def setup_plane(registry):
    manager = ConnectionLeaseManager("test/core")
    runtime = ToolRuntime(registry, queue.Queue(), manager)
    plane = RpcPlane(SimpleNamespace(runtime=runtime, leases=manager, _zenoh_session=object()))
    acquired = manager.acquire("station", "instance")
    identity = {key: acquired[key] for key in ("station_id", "station_instance_id", "lease_id")}
    return plane, runtime, identity


def query(plane, method, params):
    replies = []
    plane._on_rpc(SimpleNamespace(
        payload=json.dumps({"method": method, "params": params}).encode(),
        key_expr="lx/test/core/rpc", reply=lambda key, data: replies.append(json.loads(data)),
    ))
    assert len(replies) == 1
    return replies[0]


@pytest.mark.parametrize("name", REMOVED_NAMES)
def test_removed_entry_rejected_without_queueing(name):
    plane, runtime, identity = setup_plane(ToolRegistry.default())
    reply = query(plane, name, {"call_id": "removed", "context": identity})
    assert reply["type"] == "rpc_error" and reply["reason"] == "method_not_found"
    assert runtime._commands.empty() and not runtime.has_active_call()


def test_generic_rpc_admits_and_publishes_one_outcome():
    plane, runtime, identity = setup_plane(test_registry())
    replies = []
    plane._outcome = SimpleNamespace(put=lambda data: replies.append(json.loads(data)))
    runtime.event_sink = plane.on_event
    result = query(plane, "test.start", {"call_id": "generic", "context": identity})
    assert result["result"] == {"accepted": True, "call_id": "generic"}
    assert runtime._commands.get_nowait().call.name == "test.start"
    assert runtime.emit("generic", status="done", phase="done")
    assert not runtime.emit("generic", status="fail", phase="fail")
    assert len(replies) == 1 and replies[0]["outcome"]["ok"]


def test_connection_rpc_remains_available_with_no_tools():
    plane, runtime, identity = setup_plane(ToolRegistry.default())
    reply = query(plane, "connection.status", {})
    assert reply["type"] == "rpc_result" and reply["result"]["owned"]
    reply = query(plane, "connection.renew", identity)
    assert reply["type"] == "rpc_result"
    assert runtime.list_tools()["tools"] == []


def test_empty_discovery_revision_matches_spec():
    revision = ToolRegistry.default().list_tools()["revision"]
    spec = (REPO.parent / "specs/implemented/inner/l3-tool-plane.spec.md").read_text()
    assert revision == "sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
    assert revision in spec


def test_safety_stop_requires_real_port_and_creates_no_tool_call():
    _, runtime, _ = setup_plane(ToolRegistry.default())
    with pytest.raises(RuntimeError, match="safety stop port"):
        runtime.issue_safety_stop("lease_lost")
    stopped = []
    runtime._safety_stop = stopped.append
    runtime.issue_safety_stop("lease_lost")
    assert stopped == ["lease_lost"] and runtime._commands.empty()


def test_terminal_call_cannot_execute_after_immediate_safety_stop():
    plane, runtime, identity = setup_plane(test_registry())
    query(plane, "test.start", {"call_id": "queued", "context": identity})
    assert runtime.can_execute("queued")
    runtime.cancel_active_for_lease_loss("lease_lost")
    stopped = []
    runtime._safety_stop = stopped.append
    runtime.issue_safety_stop("lease_lost")
    assert not runtime.can_execute("queued") and stopped == ["lease_lost"]
