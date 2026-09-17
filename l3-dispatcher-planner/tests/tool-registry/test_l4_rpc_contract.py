"""Read-only station consumers against the real l3 RPC transport on loopback."""

import hashlib
import importlib.util
import json
import queue
import socket
import sys
import threading
import time
from pathlib import Path
from types import ModuleType

import pytest
import zenoh

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "l3-dispatcher-planner/ros_packages/dispatcher"))

from dispatcher.utils.zenoh_rpc import ZenohTaskMiddleware
from registry_support import test_registry


@pytest.fixture
def station(monkeypatch):
    # Load actual consumers without running CoPaw startup or accessing its config DB.
    monkeypatch.setattr(sys, 'dont_write_bytecode', True)
    base = ROOT / 'l4-agent/src/copaw'
    assert base.is_dir(), 'read-only l4 source is required for this contract test'
    prefix = '_station_contract'
    for suffix in ('', '.station_sidecar', '.station_sidecar.flight'):
        module = ModuleType(prefix + suffix)
        module.__path__ = []
        monkeypatch.setitem(sys.modules, module.__name__, module)
    kv = ModuleType(prefix + '.kv')
    kv.zenoh_router = lambda: ''
    kv.flight_publish_log = lambda: ''
    kv.flight_rpc_timeout_s = lambda: 2.0
    monkeypatch.setitem(sys.modules, kv.__name__, kv)
    sources = {}
    modules = {}
    for suffix in ('station_sidecar.rpc_plane', 'station_sidecar.fleet',
                   'station_sidecar.flight.models', 'station_sidecar.flight.rpc_bridge'):
        path = base / (suffix.replace('.', '/') + '.py')
        sources[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        spec = importlib.util.spec_from_file_location(prefix + '.' + suffix, path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, module)
        spec.loader.exec_module(module)
        modules[suffix.rsplit('.', 1)[-1]] = module
    yield modules
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest
               for path, digest in sources.items())


def eventually(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    assert predicate(), 'condition not reached before deadline'


def test_real_station_fleet_admission_outcome_and_owner_loss(station, monkeypatch):
    # No production router or robot: an isolated peer listens only on loopback.
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    endpoint = f'tcp/127.0.0.1:{port}'
    config = zenoh.Config()
    config.insert_json5('mode', '"peer"')
    config.insert_json5('listen/endpoints', f'["{endpoint}"]')
    config.insert_json5('scouting/multicast/enabled', 'false')
    server = zenoh.open(config)
    commands = queue.Queue()
    stops = []
    middleware = ZenohTaskMiddleware(commands, stack_id='test/contract',
                                    router=endpoint, safety_stop=stops.append)
    registry = test_registry()
    middleware.registry = registry
    middleware.runtime.registry = registry
    # Production start still declares its actual queryables, publisher and presence.
    with monkeypatch.context() as patch:
        patch.setattr(zenoh, 'open', lambda config: server)
        middleware.start()
    fleet = station['fleet'].FleetController(station_id='station-test', router=endpoint,
                                            renew_interval_s=1, query_timeout_s=2)
    received = []
    bridge = station['rpc_bridge'].RpcFlightBridge(lambda call_id, result: received.append((call_id, result)))
    bridge._router = endpoint
    worker_stop = threading.Event()
    def execute():
        while not worker_stop.is_set():
            try:
                command = commands.get(timeout=.05)
            except queue.Empty:
                continue
            if command.kind == 'call' and middleware.runtime.can_execute(command.call.call_id):
                middleware.runtime.emit(command.call.call_id, status='done', phase='done')
    worker = threading.Thread(target=execute)
    worker.start()
    try:
        fleet.start()
        eventually(lambda: 'test/contract' in fleet._inventory)
        lease = fleet.acquire('test/contract')
        assert lease['ttl_ms'] == 15000
        assert middleware._owner_watch is not None
        fleet._renew_once()
        bridge.bind_connection('test/contract', **{key: lease[key] for key in (
            'station_id', 'station_instance_id', 'lease_id')})
        record = station['models'].ExecutionRecord(call_id='wire-once', method='test.start', approved=True)
        bridge.register([record])
        assert bridge.publish_call('wire-once', chat_id='test-chat')
        eventually(lambda: bridge.record('wire-once').phase == 'done')
        assert received[0][1].ok
        assert received[0][1].result['completion'] == 'workflow_result'
        context = {key: lease[key] for key in ('station_id', 'station_instance_id', 'lease_id')}
        assert bridge._client.execution('test.start', {}, call_id='wire-once', context=context)['accepted']
        assert len(received) == 1
        # A real token DELETE reaches the server before the 15-second TTL.
        fleet._connection_token.undeclare()
        fleet._connection_token = None
        eventually(lambda: not middleware.leases.status()['owned'])
        assert stops == ['station_connection_token_lost']
        with pytest.raises(station['rpc_plane'].RpcPlaneError) as rejected:
            bridge._client.execution('test.start', {}, call_id='wire-once', context=context)
        assert rejected.value.reason == 'connection_not_owner'
    finally:
        worker_stop.set()
        worker.join(timeout=2)
        fleet.stop()
        bridge.stop()
        middleware.close()


def test_station_terminal_can_arrive_before_admission_reply(station):
    from types import SimpleNamespace
    from test_rpc_plane import setup_plane, query
    plane, runtime, identity = setup_plane(test_registry())
    bridge = station['rpc_bridge'].RpcFlightBridge(lambda *args: None)
    bridge.stack_id = 'test/contract'
    bridge._lease_identity = identity
    plane._outcome = SimpleNamespace(put=lambda data: bridge._apply_outcome(json.loads(data)))
    runtime.event_sink = plane.on_event
    def execution(method, arguments, *, call_id, context):
        reply = query(plane, method, {**arguments, 'call_id': call_id, 'context': context})
        runtime.emit(call_id, status='done', phase='done')
        assert bridge.record(call_id).phase == 'done'
        return reply['result']
    bridge._client = SimpleNamespace(execution=execution)
    record = station['models'].ExecutionRecord(call_id='early', method='test.start', approved=True)
    bridge.register([record])
    assert bridge.publish_call('early', chat_id='test')
    assert record.phase == 'done' and record.outcome.ok


def test_station_requires_task_presence_and_rejects_duplicate_instances(station):
    from types import SimpleNamespace
    fleet = station['fleet'].FleetController(station_id='station-test', router='tcp/127.0.0.1:1')
    with pytest.raises(station['fleet'].FleetError) as missing:
        fleet.acquire('test/contract')
    assert missing.value.reason == 'stack_not_discovered'
    for instance in ('one', 'two'):
        fleet._on_presence_sample(SimpleNamespace(
            key_expr=f'lx/test/contract/presence/task/{instance}', kind=zenoh.SampleKind.PUT))
    with pytest.raises(station['fleet'].FleetError) as duplicate:
        fleet.acquire('test/contract')
    assert duplicate.value.reason == 'identity_conflict'
    for instance in ('one', 'two'):
        fleet._on_presence_sample(SimpleNamespace(
            key_expr=f'lx/test/contract/presence/task/{instance}', kind=zenoh.SampleKind.DELETE))
    assert 'test/contract' not in fleet._inventory
