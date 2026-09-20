"""VlaSkillHost（execution/skill_host.py）单测：武装序列 / 代次 / 完成门 / 队列口。

覆盖 P1 验收三要素：
- 武装序列：snapshot_owner → 代次推进 → action_finish=False → WAIT_ACTION_FINISH；
- 代次失效：旧代次 action result 被拒（stale_generation）；
- action_finish 门：host.poll_result 消费 WaypointExecution 结果置完成标志。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "l3-dispatcher-planner/ros_packages/dispatcher"
sys.path.insert(0, str(PACKAGE))

from dispatcher.engine import DispatcherEngine  # noqa: E402
from dispatcher.execution.skill_host import VlaSkillHost  # noqa: E402
from dispatcher.execution.waypoint import WaypointExecution  # noqa: E402
from dispatcher.execution.ports import (  # noqa: E402
    FlightConfig,
    FlightState,
    Progress,
)
from dispatcher.tool_plane.model import SkillCommand, ToolCall  # noqa: E402
from dispatcher.tools.vla.ports import VlaHostConfig  # noqa: E402
from dispatcher.support.state import COMMAND_STATUS, DISPATCHER_STATE  # noqa: E402


class Channels:
    def __init__(self):
        self.phases = []
        self.commands = []
        self.stops = 0

    def publish_task_phase(self, payload):
        self.phases.append(json.loads(payload))

    def publish_command_content(self, payload):
        self.commands.append(json.loads(payload))

    def publish_emergency_stop(self):
        self.stops += 1

    def publish_if_handle_yaw(self, enabled):
        pass


class Log:
    def __init__(self):
        self.messages = []

    def info(self, message, *args):
        self.messages.append(message % args if args else message)

    warn = err = info

    def warn_throttle(self, period, message, *args):
        self.info(message, *args)


class Clock:
    def rate(self, hz):
        return self

    def sleep(self):
        pass

    def is_shutdown(self):
        return False

    def request_shutdown(self, reason):
        pass


class FakePorts:
    """WaypointExecution 的 FlightPorts 假件：记录 goal/stop，进度可注入。"""

    def __init__(self):
        self.goals = []
        self.stops = 0
        self.progress_messages = []
        self._state = FlightState((0.0, 0.0, 1.0), 0.0, 0.0, time.monotonic(), 0.0, "world")

    def snapshot(self):
        return self._state

    def progress(self):
        return tuple(self.progress_messages)

    def send_goal(self, batch, goal):
        self.goals.append((batch, goal))

    def takeoff(self):
        pass

    def land(self):
        pass

    def stop(self):
        self.stops += 1


class FakePerception:
    """geometry_source 端口假件（几何原语本体在 tests/perception 覆盖）。"""

    def get_fast_rgb(self):
        return ("image", 1.0)


def command(name="navigation.vla_nav", step="first"):
    return SkillCommand(ToolCall(
        call_id=step, name=name, arguments={}, flight_session_id="test", step_id=step,
    ))


class ArmingSkill:
    """dispatch 后立即经宿主武装的测试技能（owner=self）。"""

    synchronous = False
    requires_perception = False
    name = "navigation.vla_nav"

    def __init__(self, host):
        self.host = host
        self.armed = False

    def plan_tick(self, cmd):
        self.armed = self.host.arm_action(
            action_name="search",
            prompt_raw="go to the marker",
            replan_cmd="go to the marker",
            replan_reason="search",
            owner=self,
        )
        return True

    def action_done_gate(self):
        return None

    def on_action_result(self, result):
        raise AssertionError("本测试不进 POST_ACTION")


@pytest.fixture
def stack(tmp_path, monkeypatch):
    monkeypatch.setattr("dispatcher.engine.time.sleep", lambda _: None)
    engine = DispatcherEngine(
        headless=True, telemetry_node_name="test", telemetry_level="error",
        telemetry_stdout_en=False, log_dir_root=tmp_path,
        channels=Channels(), clock=Clock(), log=Log(),
        get_frame_snapshot=lambda: None,
        get_sensor_input_health=lambda: {},
    )
    engine.events = []
    engine.runlog.emit = lambda level, event, **fields: engine.events.append((event, fields))
    ports = FakePorts()
    execution = WaypointExecution(ports, FlightConfig(
        min_height=0.0, max_height=1.8, state_timeout=1.0, action_timeout=60.0))
    host = VlaSkillHost(engine, execution, FakePerception(), VlaHostConfig())
    return SimpleNamespace(engine=engine, ports=ports, execution=execution, host=host)


def dispatch_and_arm(stack):
    skill = ArmingSkill(stack.host)
    stack.engine.skills.register(skill.name, skill)
    stack.engine.tools._active_tool_name = skill.name
    stack.engine.skills.dispatch_plan(command())
    return skill


def test_arm_action_sequence(stack):
    """武装序列：归属快照→代次推进→finish=False→WAIT_ACTION_FINISH。"""
    generation = stack.engine.action_gate._action_generation
    skill = dispatch_and_arm(stack)
    assert skill.armed is True
    engine = stack.engine
    assert engine.skills.owner_skill() is skill
    assert engine.action_in_progress is True
    assert engine.action_finish is False
    assert engine.action_start_time > 0.0
    assert engine.dispatcher_state == DISPATCHER_STATE.WAIT_ACTION_FINISH
    assert engine.action_gate._action_generation == generation + 1
    pending = engine.action_gate.pending_action
    assert pending.replan_cmd == "go to the marker"
    assert pending.replan_reason == "search"
    assert pending.action_name == "search"
    assert pending.prompt_raw == "go to the marker"
    events = [event for event, _ in engine.events]
    assert "action_dispatch_prepared" in events
    transition = [f for e, f in engine.events
                  if e == "dispatcher_state_transition" and f["reason"] == "action:armed"]
    assert transition


def test_arm_action_rejects_owner_mismatch(stack):
    """owner 与本轮 DISPATCH 命中技能不一致 → 拒绝且不推进状态。"""
    stack.engine.skills.register("navigation.vla_nav", SimpleNamespace(
        synchronous=False, plan_tick=lambda cmd: True))
    stack.engine.tools._active_tool_name = "navigation.vla_nav"
    stack.engine.skills.dispatch_plan(command())
    other = object()
    assert stack.host.arm_action(action_name="x", owner=other) is False
    assert stack.engine.action_in_progress is False
    assert "arm_action_owner_mismatch" in [e for e, _ in stack.engine.events]


def test_arm_action_skipped_when_globally_stopped(stack):
    """急停/停止态拒绝新动作。"""
    stack.engine.global_stop_active = True
    assert dispatch_and_arm(stack).armed is False
    assert "arm_action_skipped_task_stopped" in [e for e, _ in stack.engine.events]


def test_stale_generation_result_is_rejected(stack):
    """代次失效：旧代次 action result 被完成门拒绝。"""
    dispatch_and_arm(stack)
    gate = stack.engine.action_gate
    stack.engine.action_finish = True
    gate._action_finish_generation = gate._action_generation - 1  # 旧代次结果
    assert gate.action_done() is False
    assert stack.engine.action_finish is False  # 被清并等待新结果
    assert "task_action_result_ignored" in [e for e, _ in stack.engine.events]


def test_poll_result_completes_action_through_gate(stack, monkeypatch):
    """完成门：send_task_goal 出海 → 进度 all_consumed → poll_result 置 finish。"""
    dispatch_and_arm(stack)
    host, ports = stack.host, stack.ports
    host.send_task_goal(2.2, 0.0, 1.0, None, yaw_source="current_odom")
    batch = ports.goals[-1][0]
    goal = ports.goals[-1][1]
    assert goal.position == (2.2, 0.0, 1.0) and goal.yaw == 0.0 and goal.look_forward
    ports.progress_messages.append(Progress(batch, True))
    assert host.poll_result() is not None
    engine = stack.engine
    assert engine.action_finish is True
    monkeypatch.setattr("dispatcher.core.action_gate.time.time",
                        lambda: engine.action_start_time + 1.0)
    assert engine.action_gate.action_done() is True


def test_send_task_goal_books_waypoint_and_rolls_back_on_failure(stack):
    """下发簿记 waypoint/nav_yaw/yaw_source；发送失败回滚执行态并上抛。"""
    dispatch_and_arm(stack)
    host, ports = stack.host, stack.ports
    host.send_task_goal(1.0, 2.0, 1.2, 0.5, yaw_source="image_bbox_center_ray")
    gate = stack.engine.action_gate
    assert stack.engine.waypoint == (1.0, 2.0, 1.2)
    assert stack.engine.last_published_waypoint == (1.0, 2.0, 1.2)
    assert gate.pending_action.waypoint == (1.0, 2.0, 1.2)
    assert gate.pending_action.nav_yaw == 0.5
    assert gate.pending_action.yaw_source == "image_bbox_center_ray"
    # 高度超界（> max_height 1.8）→ WaypointExecution 拒绝并上抛，回滚执行态。
    # 共享执行独占：先让上一动作完成（all_consumed）再下发新目标。
    batch = ports.goals[-1][0]
    ports.progress_messages.append(Progress(batch, True))
    host.poll_result()
    with pytest.raises(ValueError):
        host.send_task_goal(1.0, 2.0, 5.0, None)
    assert stack.engine.action_in_progress is False
    assert len(stack.ports.goals) == 1  # 失败 goal 未出海


def test_fail_sequence_carries_reason_as_error_code(stack):
    """fail 唯一写口：error.code=reason，回 WAIT_FOR_MISSION。"""
    dispatch_and_arm(stack)
    stack.host.send_task_goal(2.2, 0.0, 1.0, None)
    stack.host.fail_sequence("invalid_grounded_bbox")
    engine = stack.engine
    assert engine.ledger.failed
    assert engine.dispatcher_state == DISPATCHER_STATE.WAIT_FOR_MISSION
    last = engine.channels.phases[-1]
    assert last["phase"] == "fail"
    assert last["error"]["code"] == "invalid_grounded_bbox"
    assert engine.action_gate.pending_action.replan_cmd is None
    assert engine.action_in_progress is False
    # 取消经共享执行发布保持意图（动作 goal + 保持 goal 各一次）
    assert len(stack.ports.goals) == 2


def test_task_generation_guard(stack):
    """代次守卫：快照→失效→事件；关闭开关后恒有效。"""
    engine = stack.engine
    captured = stack.host.capture_task_generation()
    engine.ledger.bump_task_generation("switch_prompt")
    assert stack.host.task_generation_valid(captured, reason="test") is False
    assert "stale_task_result_discarded" in [e for e, _ in engine.events]
    assert stack.host.task_generation_valid(stack.host.capture_task_generation())
    engine.task_generation_guard_enabled = False
    assert stack.host.task_generation_valid(captured) is True


def test_consume_and_advance_prompt_ports(stack):
    """队列机械口：consume 弹队首+ADVANCE_READY；advance 推进下一条。"""
    engine = stack.engine
    first, second = command(step="first"), command(step="second")
    config = [(entry.call.name, entry) for entry in (first, second)]
    engine.prompt_queue.sync_task_buffers_from_prepare(config)
    engine.tools._activate_tool_call(first.call)
    engine.prompt_queue.pop_next_task()
    assert engine.prompt_queue.head_command()[1] is first

    stack.host.consume_head_prompt()
    assert engine.ledger.command_status == COMMAND_STATUS.ADVANCE_READY
    assert engine.prompt_queue.head_command() is None  # 队首已弹出

    engine.prompt_queue.command_content.append(config[0])
    stack.host.advance_prompt()
    assert engine.prompt_queue.head_command()[1] is second
    assert engine.ledger.command_status == COMMAND_STATUS.RUNNING


def test_mode_burst_wiring(stack):
    """模式脉冲：注入回调按重复次数出海；未接线直接失败（不静默降级）。"""
    seen = []
    stack.host.config = VlaHostConfig(
        planner_mode_repeat=3, planner_mode_interval=0.0, publish_planner_mode=seen.append
    )
    stack.host.publish_mode_burst(int(stack.host.planner_ego_mode_value))
    assert seen == [1, 1, 1]
    stack.host.publish_mode_burst(7, repeat=2, interval=0.0)
    assert seen[-2:] == [7, 7]
    unwired = VlaSkillHost(stack.engine, stack.execution, FakePerception(), VlaHostConfig())
    with pytest.raises(RuntimeError):
        unwired.publish_mode_burst(1, repeat=1, interval=0.0)


def test_frame_and_geometry_source_ports(stack, monkeypatch):
    """帧/几何源访问：latest_frame 走 engine 快照口，geometry_source 返回注入感知。"""
    sentinel = object()
    monkeypatch.setattr(stack.engine, "get_frame_snapshot", lambda: sentinel)
    assert stack.host.latest_frame() is sentinel
    assert stack.host.get_fast_rgb() == ("image", 1.0)
    assert isinstance(stack.host.geometry_source(), FakePerception)
    assert (stack.host.min_height, stack.host.max_height, stack.host.planner_ego_mode_value) == (0.0, 1.8, 1)
