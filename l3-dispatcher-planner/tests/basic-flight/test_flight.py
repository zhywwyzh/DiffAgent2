"""六技能通过真实六态 FSM 的领域测试，以及执行/原点故障边界。"""
from dataclasses import replace
import math
from pathlib import Path
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'ros_packages/dispatcher'), str(ROOT / 'tests/core-boundary')]
from test_core_boundary import engine
from dispatcher.execution.composition import install_flight
from dispatcher.execution.waypoint_execution import WaypointExecution
from dispatcher.services.flight_session import FlightSession
from dispatcher.tools.flight.ports import FlightConfig, FlightState, Goal, Progress
from dispatcher.tools.flight.catalog import flight_specs
from dispatcher.tools.registry import ToolRegistry
from dispatcher.tools.protocol import ToolProtocolError
from dispatcher.tools.model import ToolCall, SkillCommand
from dispatcher.utils.state import DISPATCHER_STATE


class Ports:
    def __init__(self):
        self.current = FlightState((0., 0., 1.), 0., 0., time.monotonic(), 10., 'world')
        self.sent = []
        self.results = []
        self.commands = []
        self.auto_finish = True

    def snapshot(self):
        return self.current

    def progress(self):
        return tuple(self.results)

    def send_goal(self, batch, goal):
        self.sent.append((batch, goal))
        if self.auto_finish:
            self.current = replace(self.current, position=goal.position, yaw=goal.yaw,
                                   received=time.monotonic(), source_stamp=self.current.source_stamp + .1)
            self.results.append(Progress(batch, True))

    def takeoff(self):
        self.commands.append('takeoff')

    def land(self):
        self.commands.append('land')

    def stop(self):
        self.commands.append('stop')


def run(engine, name, arguments):
    call = ToolCall('call', 'basic_flight.' + name, arguments, 'session', 'step')
    engine.tools.start_tool_workflow(call, SkillCommand(call))
    if not engine.skills.get(call.name).synchronous:
        engine.clock.polls = 0
        engine._run_inference_loop()
    return [phase for phase in engine.channels.phases if phase['phase'] in ('done', 'fail')]


@pytest.mark.parametrize('direction,expected', [('forward', (0, 2)), ('backward', (0, -2)),
                                              ('left', (-2, 0)), ('right', (2, 0))])
def test_body_translation_runs_real_fsm(engine, direction, expected):
    ports = Ports()
    ports.current = replace(ports.current, yaw=math.pi/2)
    _, dispose = install_flight(engine, ports, FlightConfig())
    terminals = run(engine, 'translate', {'direction': direction, 'distance_m': 2})
    assert [item['phase'] for item in terminals] == ['done']
    assert ports.sent[0][1].position[:2] == pytest.approx(expected)
    assert engine.dispatcher_state == DISPATCHER_STATE.WAIT_FOR_MISSION
    dispose()
    dispose()


def test_rotation_keeps_full_turns_and_one_terminal(engine):
    ports = Ports()
    install_flight(engine, ports, FlightConfig())
    terminals = run(engine, 'rotate', {'yaw_delta_deg': 450})
    assert len(ports.sent) == 5
    assert [goal.yaw for _, goal in ports.sent] == pytest.approx([math.pi/2*i for i in range(1, 6)])
    assert [item['phase'] for item in terminals] == ['done']


@pytest.mark.parametrize('name,command', [('takeoff', 'takeoff'), ('land', 'land'), ('emergency_stop', 'stop')])
def test_synchronous_commands_are_forwarded(engine, name, command):
    ports = Ports()
    ports.current = replace(ports.current, position=(1., 2., 0.))
    install_flight(engine, ports, FlightConfig(ground_z=0))
    terminals = run(engine, name, {})
    assert ports.commands == [command]
    assert [item['phase'] for item in terminals] == ['done']
    assert terminals[0]['result']['completion'] == 'forwarded'
    assert not engine.action_in_progress


def test_return_needs_confirmed_origin_and_preserves_current_height(engine):
    ports = Ports()
    host, _ = install_flight(engine, ports, FlightConfig(ground_z=0))
    ports.current = replace(ports.current, position=(2., 3., 0.))
    host.request_takeoff()
    ports.current = replace(ports.current, position=(2., 3., 1.), source_stamp=11.)
    host.state()
    ports.current = replace(ports.current, position=(5., 6., 1.5), source_stamp=12.)
    terminals = run(engine, 'return', {})
    assert ports.sent[-1][1].position == (2., 3., 1.5)
    assert [item['phase'] for item in terminals] == ['done']


def test_missing_origin_fails_without_goal(engine):
    ports = Ports()
    install_flight(engine, ports, FlightConfig())
    terminals = run(engine, 'return', {})
    assert not ports.sent
    assert [item['phase'] for item in terminals] == ['fail']


def test_timeout_and_old_progress_cannot_succeed():
    ports = Ports()
    ports.auto_finish = False
    now = [ports.current.received]
    execution = WaypointExecution(ports, FlightConfig(action_timeout=.2), clock=lambda: now[0], first_batch=10)
    batch = execution.start(Goal((1., 0., 1.), 0.))
    ports.results = [Progress(batch-1, True)]
    assert execution.poll() is None
    now[0] += .3
    result = execution.poll()
    assert not result.success and result.reason == 'planner_timeout'
    assert ports.sent[-1][0] != batch
    assert ports.sent[-1][1] == Goal(ports.current.position, ports.current.yaw, look_forward=False)
    ports.results.append(Progress(batch, True))
    assert execution.poll() is None


def test_skipped_waypoint_fails_and_cancels():
    ports = Ports()
    ports.auto_finish = False
    execution = WaypointExecution(ports, FlightConfig())
    batch = execution.start(Goal((1., 0., 1.), 0.))
    ports.results.append(Progress(batch, True, 1))
    assert not execution.poll().success
    assert ports.sent[-1][0] != batch
    assert ports.sent[-1][1] == Goal(ports.current.position, ports.current.yaw, look_forward=False)


def test_session_frame_reset_and_landing_invalidate_origin():
    session = FlightSession(FlightConfig(ground_z=0))
    state = FlightState((3, 4, 0), 0, 0, 0, 10, 'world')
    session.prepare_takeoff(state)
    with pytest.raises(RuntimeError):
        session.origin(state)
    flying = replace(state, position=(3, 4, 1), source_stamp=11)
    assert session.origin(flying) == (3, 4, 0)
    with pytest.raises(RuntimeError):
        session.prepare_takeoff(flying)
    with pytest.raises(RuntimeError):
        session.origin(replace(flying, frame='new-world'))
    session.prepare_takeoff(replace(state, source_stamp=12))
    assert session.origin(replace(flying, source_stamp=13)) == (3, 4, 0)
    with pytest.raises(RuntimeError):
        session.origin(replace(state, source_stamp=14))


def test_disposer_does_not_remove_replacement(engine):
    ports = Ports()
    _, dispose = install_flight(engine, ports, FlightConfig())
    replacement = engine.skills.get('basic_flight.translate').__class__(None)
    engine.skills.register(replacement.name, replacement)
    dispose()
    assert engine.skills.get(replacement.name) is replacement


def test_catalog_accepts_l4_parameters_and_rejects_legacy_return_target():
    registry = ToolRegistry(flight_specs())
    assert len(registry.list_tools()['tools']) == 6
    payload = {'call_id': 'schema', 'name': 'basic_flight.return', 'arguments': {'target': 'origin'},
               'context': {'flight_session_id': 'session', 'step_id': 'step'}}
    with pytest.raises(ToolProtocolError) as caught:
        registry.normalize_call(payload)
    assert caught.value.data['reason'] == 'unknown_argument'
    # P3 起生产发现面 = 飞行六工具 + navigation.vla_nav（vla 并入 default()）
    assert {tool['name'] for tool in ToolRegistry.default().list_tools()['tools']} \
        == {spec.name for spec in flight_specs()} | {'navigation.vla_nav'}


def test_cancel_and_new_call_ignore_late_result_while_fsm_runs(engine, monkeypatch):
    import threading
    # Event.wait supplies a real wait without relying on the fixture's patched sleep.
    monkeypatch.setattr('dispatcher.engine.time.sleep', lambda seconds: threading.Event().wait(seconds))
    ports = Ports()
    ports.auto_finish = False
    install_flight(engine, ports, FlightConfig())
    first = ToolCall('first', 'basic_flight.translate', {'direction': 'forward', 'distance_m': 1}, 'test', 'first')
    second = ToolCall('second', first.name, first.arguments, 'test', 'second')
    thread = threading.Thread(target=engine._run_inference_loop)
    thread.start()
    def until(predicate):
        for _ in range(100):
            if predicate():
                return
            threading.Event().wait(.005)
        assert predicate()
    try:
        engine.tools.start_tool_workflow(first, SkillCommand(first))
        until(lambda: len(ports.sent) == 1)
        old_batch = ports.sent[0][0]
        engine.tools.cancel_tool_call(first, 'test_cancel')
        assert len(ports.sent) == 2
        assert ports.sent[-1][0] != old_batch
        assert ports.sent[-1][1] == Goal(ports.current.position, ports.current.yaw, look_forward=False)
        engine.tools.start_tool_workflow(second, SkillCommand(second))
        until(lambda: len(ports.sent) == 3)
        ports.results.append(Progress(old_batch, True))
        threading.Event().wait(.1)
        assert not any(item['phase'] == 'done' for item in engine.channels.phases)
        assert engine.action_in_progress
    finally:
        engine.clock.stopped = True
        thread.join(timeout=2)
    assert not thread.is_alive()


def test_freshness_includes_age_before_receipt_and_requires_world_frame():
    ports = Ports()
    ports.current = replace(ports.current, source_age=.8)
    execution = WaypointExecution(ports, FlightConfig(), clock=lambda: ports.current.received + .3)
    with pytest.raises(RuntimeError, match='stale'):
        execution.state()
    ports.current = replace(ports.current, frame='camera', source_age=0.)
    with pytest.raises(RuntimeError, match='frame_mismatch'):
        execution.state()
