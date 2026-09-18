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
    "scene_nav.graph.object_pose", "navigation.scene_graph_nav",
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
    runtime.registry = ToolRegistry(())
    reply = query(plane, "connection.status", {})
    assert reply["type"] == "rpc_result" and reply["result"]["owned"]
    reply = query(plane, "connection.renew", identity)
    assert reply["type"] == "rpc_result"
    assert runtime.list_tools()["tools"] == []


def test_production_discovery_revision_matches_spec():
    """G24：生产发现面 == 七工具（六 basic_flight.* + navigation.vla_nav），
    revision 与 l3-tool-plane.spec.md §1 记录的现行值一致。"""
    listing = ToolRegistry.default().list_tools()
    revision = listing["revision"]
    spec = (REPO.parent / "specs/implemented/inner/l3-tool-plane.spec.md").read_text()
    assert len(listing["tools"]) == 7
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


@pytest.mark.parametrize('payload', [b'[]', b'null', b'1', b'"text"', b'{', b'\xff',
    b'{}', b'{"method": 5, "params": {}}', b'{"method":"", "params":{}}',
    b'{"method":"connection.status", "params":[]}'])
def test_malformed_request_always_replies(payload):
    plane, _, _ = setup_plane(test_registry())
    replies = []
    plane._on_rpc(SimpleNamespace(payload=payload, key_expr='lx/test/core/rpc',
        reply=lambda key, data: replies.append(json.loads(data))))
    assert len(replies) == 1
    assert replies[0]['type'] == 'rpc_error'
    assert replies[0]['reason'] == 'invalid_arguments'


def test_terminal_before_admit_returns_is_delivered_and_replay_does_not_execute():
    plane, runtime, identity = setup_plane(test_registry())
    outcomes = []
    plane._outcome = SimpleNamespace(put=lambda data: outcomes.append(json.loads(data)))
    runtime.event_sink = plane.on_event
    admit = runtime.admit

    def immediate(payload):
        ack = admit(payload)
        runtime.emit(payload['call_id'], status='done', phase='done')
        return ack

    runtime.admit = immediate
    params = {'call_id': 'instant', 'context': identity}
    assert query(plane, 'test.start', params)['result']['accepted']
    assert query(plane, 'test.start', params)['result']['accepted']
    assert len(outcomes) == 1
    assert outcomes[0]['method'] == 'test.start'
    assert outcomes[0]['outcome']['result']['completion'] == 'workflow_result'
    assert runtime._commands.qsize() == 1


def test_replay_after_lease_loss_is_rejected():
    plane, runtime, identity = setup_plane(test_registry())
    params = {'call_id': 'lost', 'context': identity}
    query(plane, 'test.start', params)
    runtime._leases.mark_lost('test')
    reply = query(plane, 'test.start', params)
    assert reply['reason'] == 'connection_not_owner'
    assert runtime._commands.qsize() == 1


def test_failed_outcome_publish_does_not_repeat_execution(capsys):
    plane, runtime, identity = setup_plane(test_registry())
    def unavailable(data):
        raise RuntimeError('disconnected')
    plane._outcome = SimpleNamespace(put=unavailable)
    runtime.event_sink = plane.on_event
    params = {'call_id': 'publish-failure', 'context': identity}
    query(plane, 'test.start', params)
    assert runtime.emit('publish-failure', status='done', phase='done')
    assert not runtime.emit('publish-failure', status='done', phase='done')
    query(plane, 'test.start', params)
    assert runtime._commands.qsize() == 1
    assert 'outcome publish FAILED' in capsys.readouterr().out


def test_call_id_is_not_silently_rewritten():
    plane, runtime, identity = setup_plane(test_registry())
    reply = query(plane, 'test.start', {'call_id': ' padded ', 'context': identity})
    assert reply['reason'] == 'invalid_arguments'
    assert runtime._commands.empty()
