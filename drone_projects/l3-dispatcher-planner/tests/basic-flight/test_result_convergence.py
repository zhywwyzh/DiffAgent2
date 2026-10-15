"""用独立时钟与连续观测验收原目标完成门及 VLA 多腿终态。"""
from dataclasses import replace
from pathlib import Path
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'ros_packages/dispatcher'), str(ROOT / 'tests/core-boundary')]
from dispatcher.execution.ports import FlightConfig, FlightState, Goal, Progress
from dispatcher.tools.flight.flight_waypoint import FlightWaypointExecution
from dispatcher.tools.vla.vla_waypoint import VlaWaypointExecution
from dispatcher.tools.skill_api import SkillVerdict
from test_vla_skill import stack, dispatch


class Observations:
    def __init__(self):
        self.now = 100.
        self.state = FlightState((0., 0., 1.), 0., 0., self.now, 100., 'world',
                                 velocity=(0., 0., 0.), yaw_rate_rad_s=0.)
        self.sent = []
        self.messages = []

    def snapshot(self):
        return self.state

    def progress(self):
        messages, self.messages = self.messages, []
        return messages

    def send_goal(self, batch, goal):
        self.sent.append((batch, goal))

    def sample(self, **changes):
        self.now += .125
        self.state = replace(self.state, received=self.now,
                             source_stamp=self.state.source_stamp + .125, **changes)


@pytest.fixture(params=[FlightWaypointExecution, VlaWaypointExecution])
def motion(request):
    ports = Observations()
    execution = request.param(ports, FlightConfig(action_timeout=2.), clock=lambda: ports.now)
    batch = execution.start(Goal((2., 0., 1.), .5))
    ports.messages.append(Progress(batch, True))
    return ports, execution


def test_progress_alone_and_duplicate_samples_never_complete(motion):
    ports, execution = motion
    assert execution.poll() is None
    for _ in range(4):
        ports.sample()
        assert execution.poll() is None
    ports.sample(position=(2., 0., 1.), yaw=.5)
    assert execution.poll() is None
    for _ in range(10):
        assert execution.poll() is None
    ports.sample()
    assert execution.poll() is None
    ports.sample()
    assert execution.poll().success
    assert execution.poll() is None


@pytest.mark.parametrize('changes', [
    {'speed': .2}, {'velocity': (.2, 0., 0.)},
    {'yaw_rate_rad_s': .3}, {'yaw': 1.}, {'velocity': None},
    {'yaw_rate_rad_s': None}, {'position': (1., 0., 1.)},
])
def test_each_unsettled_observation_resets_hold(motion, changes):
    ports, execution = motion
    ports.sample(position=(2., 0., 1.), yaw=.5)
    assert execution.poll() is None
    ports.sample(**changes)
    assert execution.poll() is None
    for _ in range(2):
        ports.sample(position=(2., 0., 1.), yaw=.5, speed=0.,
                     velocity=(0., 0., 0.), yaw_rate_rad_s=0.)
        assert execution.poll() is None
    result = None
    for _ in range(3):
        ports.sample()
        result = execution.poll()
        if result is not None:
            break
    assert result is not None and result.success


def test_settle_timeout_is_failure_and_late_progress_is_ignored(motion):
    ports, execution = motion
    batch = ports.sent[0][0]
    assert execution.poll() is None
    ports.now += 2.
    ports.state = replace(ports.state, received=ports.now, source_stamp=ports.now)
    result = execution.poll()
    assert not result.success and result.reason == 'goal_settle_timeout'
    assert ports.sent[-1][0] != batch
    ports.messages.append(Progress(batch, True))
    assert execution.poll() is None


def finish_leg(stack):
    ports = stack.ports
    batch, goal = ports.goals[-1]
    ports.progress_messages[:] = [Progress(batch, True)]
    assert stack.host.poll_result() is None
    for _ in range(4):
        ports._state = replace(ports._state, position=goal.position, yaw=goal.yaw,
                               velocity=(0., 0., 0.), yaw_rate_rad_s=0.,
                               received=time.monotonic(), source_stamp=ports._state.source_stamp + .125)
        result = stack.host.poll_result()
        if result is not None:
            assert result.success
            return result
    pytest.fail('连续停稳后未返回成功')


def test_vla_position_yaw_ground_complete_in_order(stack):
    stack.execution.config = replace(stack.execution.config, ground_z=0.)
    stack.host.execution_config = stack.execution.config
    dispatch(stack, {'waypoint_world': [2., 0., 1.], 'yaw': .5}, display_text='land here')
    assert stack.ports.goals[-1][1].look_forward
    assert stack.skill.on_action_result(finish_leg(stack)) is SkillVerdict.NEW_ACTION
    assert stack.ports.goals[-1][1].yaw_low_speed
    assert not any(p['phase'] == 'done' for p in stack.engine.channels.phases)
    assert stack.skill.on_action_result(finish_leg(stack)) is SkillVerdict.NEW_ACTION
    assert stack.ports.goals[-1][1].ground_approach
    assert stack.ports.goals[-1][1].position[2] == pytest.approx(.1)
    assert not any(p['phase'] == 'done' for p in stack.engine.channels.phases)
    assert stack.skill.on_action_result(finish_leg(stack)) is SkillVerdict.ADVANCE
    assert len(stack.ports.goals) == 3


@pytest.mark.parametrize('failed_leg', [0, 1, 2])
def test_vla_skipped_leg_never_advances_or_sends_next_leg(stack, failed_leg):
    stack.execution.config = replace(stack.execution.config, ground_z=0.)
    stack.host.execution_config = stack.execution.config
    dispatch(stack, {'waypoint_world': [2., 0., 1.], 'yaw': .5}, display_text='land here')
    for _ in range(failed_leg):
        assert stack.skill.on_action_result(finish_leg(stack)) is SkillVerdict.NEW_ACTION
    count = len(stack.ports.goals)
    batch = stack.ports.goals[-1][0]
    stack.ports.progress_messages[:] = [Progress(batch, True, 1)]
    result = stack.host.poll_result()
    assert result is not None and not result.success
    assert stack.skill.on_action_result(result) is SkillVerdict.IDLE
    assert len(stack.ports.goals) == count + 1  # 只有取消保持目标
    assert [p['phase'] for p in stack.engine.channels.phases if p['phase'] in ('done', 'fail')] == ['fail']


@pytest.mark.parametrize('name,arguments,legs', [
    ('basic_flight.translate', {'direction': 'forward', 'distance_m': 2.}, 1),
    ('basic_flight.rotate', {'yaw_delta_deg': 450.}, 5),
    ('basic_flight.rotate', {'yaw_delta_deg': -450.}, 5),
    ('navigation.vla_nav', {'waypoint_world': [2., 0., 1.], 'yaw': .5}, 2),
])
def test_real_engine_loop_with_continuous_motion(stack, name, arguments, legs):
    import math
    from dispatcher.execution.composition import install_flight
    from dispatcher.tool_plane.model import ToolCall, SkillCommand

    engine, ports = stack.engine, stack.ports
    engine._min_action_wait = 0.
    ports._state = replace(ports._state, velocity=(0., 0., 0.), yaw_rate_rad_s=0.)
    if name.startswith('basic_flight.'):
        install_flight(engine, ports, FlightConfig())
    ticks = [0]

    def tick():
        ticks[0] += 1
        if ticks[0] > 500 or any(p['phase'] in ('done', 'fail') for p in engine.channels.phases):
            return True
        state = ports._state
        if ports.goals:
            batch, goal = ports.goals[-1]
            delta = tuple(b-a for a, b in zip(state.position, goal.position))
            distance = math.sqrt(sum(v*v for v in delta))
            scale = min(1., .1 / distance) if distance else 0.
            position = tuple(a + scale*d for a, d in zip(state.position, delta))
            velocity = tuple(scale*d/.125 for d in delta)
            error = math.atan2(math.sin(goal.yaw-state.yaw), math.cos(goal.yaw-state.yaw))
            turn = max(-.1, min(.1, error))
            yaw = math.atan2(math.sin(state.yaw+turn), math.cos(state.yaw+turn))
            ports._state = replace(state, position=position, velocity=velocity,
                                   speed=math.sqrt(sum(v*v for v in velocity)),
                                   yaw=yaw, yaw_rate_rad_s=turn/.125)
            # 提前反馈刻意先于到达：完成仍须等待物理观测。
            ports.progress_messages[:] = [Progress(batch, True)]
        ports._state = replace(ports._state, received=time.monotonic(),
                               source_stamp=state.source_stamp+.125)
        return False

    engine.clock.is_shutdown = tick
    call = ToolCall('continuous', name, arguments, 'test', 'continuous')
    engine.tools.start_tool_workflow(call, SkillCommand(call))
    engine._run_inference_loop()
    assert ticks[0] < 500
    assert len(ports.goals) == legs
    assert [p['phase'] for p in engine.channels.phases if p['phase'] in ('done', 'fail')] == ['done']
