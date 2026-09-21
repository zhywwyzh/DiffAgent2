"""VLA 装配（execution/composition.py::install_vla）与发现面汇入回归。

覆盖验收要素（航点执行器形态，无感知/几何注入）：
- 正常装配：VlaWaypointExecution/VlaSkillHost/VlaSkill 构造、navigation.vla_nav
  注册可见（requires_perception=False）；
- 异常回滚：注册失败时异常上抛、技能不可见；
- disposer：注销后技能不可见、幂等、不误删替换实例（flight 同款语义）；
- 未注册名：core 口径 start_tool_workflow 上报 tool_not_registered fail 相位；
- 飞行独占：VLA 与飞行共享 engine 动作账务——owner 门双向拒绝；新调用
  抢占链（enter_global_stop）对 VLA 动作生效（取消出海保持 goal）。

发现面一致性（发现面 normalize 的合法 vla 调用经装配技能武装出海）在此
以生产注册面 ToolRegistry.default() 端到端验证。
"""

from __future__ import annotations

import json
import sys
import time
import types
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "l3-dispatcher-planner/ros_packages/dispatcher"
sys.path.insert(0, str(PACKAGE))

from dispatcher.engine import DispatcherEngine  # noqa: E402
from dispatcher.execution.composition import install_flight, install_vla  # noqa: E402
from dispatcher.execution.skill_host import VlaSkillHost  # noqa: E402
from dispatcher.execution.ports import FlightConfig, FlightState, Progress  # noqa: E402
from dispatcher.tool_plane.model import SkillCommand, ToolCall  # noqa: E402
from dispatcher.tool_plane.registry import ToolRegistry  # noqa: E402
from dispatcher.tools.vla.ports import VlaHostConfig  # noqa: E402
from dispatcher.support.state import DISPATCHER_STATE  # noqa: E402

WAYPOINT = {
    "object": "red marker",
    "prompt": "fly to the red marker",
    "waypoint_world": [2.2, 0.0, 1.0],
}


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
    """VlaWaypointExecution 的 FlightPorts 假件：记录 goal/stop，进度可注入。"""

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


def make_engine(tmp_path, monkeypatch, frame):
    monkeypatch.setattr("dispatcher.engine.time.sleep", lambda _: None)
    engine = DispatcherEngine(
        headless=True, telemetry_node_name="test", telemetry_level="error",
        telemetry_stdout_en=False, log_dir_root=tmp_path,
        channels=Channels(), clock=Clock(), log=Log(),
        get_frame_snapshot=lambda: frame,
        get_sensor_input_health=lambda: {},
    )
    engine.events = []
    engine.runlog.emit = lambda level, event, **fields: engine.events.append((event, fields))
    return engine


@pytest.fixture
def stack(tmp_path, monkeypatch):
    frame = SimpleNamespace(current_state=np.array([0.0, 0.0, 1.0, 0.0, 0.0, 0.0]))
    engine = make_engine(tmp_path, monkeypatch, frame)
    ports = FakePorts()
    modes = []
    host, dispose = install_vla(
        engine, ports,
        FlightConfig(min_height=0.0, max_height=1.8, state_timeout=1.0, action_timeout=60.0),
        VlaHostConfig(planner_mode_repeat=3, planner_mode_interval=0.0,
                      publish_planner_mode=modes.append),
    )
    return SimpleNamespace(
        engine=engine, frame=frame, ports=ports,
        host=host, dispose=dispose, modes=modes,
    )


def vla_call(arguments=None, name="navigation.vla_nav", step="step"):
    return ToolCall(
        call_id=step, name=name,
        arguments=dict(arguments if arguments is not None else WAYPOINT),
        flight_session_id="test", step_id=step,
    )


def dispatch_vla(stack, arguments=None):
    """以 waypoint 参数直发 DISPATCH（与 core 调用路径同源）。"""
    call = vla_call(arguments)
    assert stack.engine.skills.dispatch_plan(SkillCommand(call)) is True
    return call


# ---------------------------------------------------------------------------
# 正常装配 / 异常回滚 / disposer
# ---------------------------------------------------------------------------


def test_install_registers_skill_as_waypoint_executor(stack):
    """装配后 navigation.vla_nav 注册可见；航点执行器身份（无感知门）。"""
    engine, skill = stack.engine, stack.engine.skills.get("navigation.vla_nav")
    assert skill is not None
    assert skill.name == "navigation.vla_nav"
    assert skill.requires_perception is False
    assert skill.synchronous is False
    assert isinstance(stack.host, VlaSkillHost)
    # 宿主无几何/感知注入面（航点执行器端口集）
    assert not hasattr(stack.host, "geometry_source")
    assert not hasattr(stack.host, "get_fast_rgb")


def test_install_failure_rolls_back_registration(tmp_path, monkeypatch):
    """注册失败：异常上抛、技能不可见（回滚 dispose）。"""
    frame = SimpleNamespace(current_state=np.array([0.0, 0.0, 1.0, 0.0, 0.0, 0.0]))
    engine = make_engine(tmp_path, monkeypatch, frame)

    def failing_register(name, skill):
        raise RuntimeError("register_broken")

    monkeypatch.setattr(engine.skills, "register", failing_register)
    with pytest.raises(RuntimeError, match="register_broken"):
        install_vla(
            engine, FakePorts(),
            FlightConfig(min_height=0.0, max_height=1.8, state_timeout=1.0, action_timeout=60.0),
            VlaHostConfig(),
        )
    assert engine.skills.get("navigation.vla_nav") is None  # 回滚后不可见


def test_disposer_unregisters_skill(stack):
    """disposer：注销后技能不可见；幂等（重复调用无副作用）。"""
    stack.dispose()
    stack.dispose()
    assert stack.engine.skills.get("navigation.vla_nav") is None


def test_disposer_does_not_remove_replacement(stack):
    """旧 disposer 只撤销本次注册：dispose 后替换实例不受影响（flight 同款）。"""
    stack.dispose()
    replacement = SimpleNamespace(
        name="navigation.vla_nav", synchronous=False,
        on_cancel=lambda: None, plan_tick=lambda cmd: True,
    )
    stack.engine.skills.register(replacement.name, replacement)
    stack.dispose()  # 旧 disposer 二次调用不得误删替换实例
    assert stack.engine.skills.get("navigation.vla_nav") is replacement


def test_disposer_cancels_active_execution(stack):
    """disposer 先取消共享执行（保持 goal 出海）再注销技能。"""
    dispatch_vla(stack)
    held = len(stack.ports.goals)
    stack.dispose()
    assert len(stack.ports.goals) == held + 1  # cancel 发布保持意图
    assert stack.engine.skills.get("navigation.vla_nav") is None


# ---------------------------------------------------------------------------
# 未注册名（tool_not_registered）与发现面一致性
# ---------------------------------------------------------------------------


def test_unregistered_name_fails_tool_not_registered(stack):
    """core 口径：未注册名 start_tool_workflow 上报 tool_not_registered fail
    相位，不入队（发现面与技能装配无关的名字一律拒绝）。"""
    engine = stack.engine
    engine.tools.start_tool_workflow(
        vla_call(name="scene.map_search"),
        SkillCommand(vla_call(name="scene.map_search")),
    )
    last = engine.channels.phases[-1]
    assert last["phase"] == "fail"
    assert last["error"]["code"] == "tool_not_registered"
    assert engine.prompt_queue.head_command() is None


def test_registry_surface_call_dispatches_through_installed_skill(stack):
    """发现面与装配一致：生产注册面 normalize 的合法 waypoint 调用经装配
    技能武装出海（航点命中相位 → goal 出海 → WAIT_ACTION_FINISH）。"""
    engine = stack.engine
    call = ToolRegistry.default().normalize_call({
        "call_id": "c1",
        "name": "navigation.vla_nav",
        "arguments": dict(WAYPOINT),
        "context": {"flight_session_id": "flight_a", "step_id": "step_1"},
    })
    engine.tools.start_tool_workflow(call, SkillCommand(call))
    assert engine.prompt_queue.head_command() is not None  # 入队（无感知门）
    command = engine.prompt_queue.head_command()[1]
    assert engine.skills.dispatch_plan(command) is True
    assert stack.ports.goals, "waypoint 调用应武装并出海航点"
    assert stack.ports.goals[-1][1].position == (2.2, 0.0, 1.0)
    assert engine.dispatcher_state == DISPATCHER_STATE.WAIT_ACTION_FINISH
    assert stack.modes == [1, 1, 1]  # 模式脉冲经装配注入的出站回调出海


# ---------------------------------------------------------------------------
# 阈值配置面透传（install_vla 签名 + ~vla/* 参数读取）
# ---------------------------------------------------------------------------


def test_install_vla_passes_threshold_override(tmp_path, monkeypatch):
    """阈值透传：search_success_distance_thresh=0.5 的过近判定按 0.5 生效
    （0.4 m 航点被静默吞掉；默认 0.3 时照常出海）。"""
    frame = SimpleNamespace(current_state=np.array([0.0, 0.0, 1.0, 0.0, 0.0, 0.0]))
    engine = make_engine(tmp_path, monkeypatch, frame)
    ports = FakePorts()
    modes = []
    _, dispose = install_vla(
        engine, ports,
        FlightConfig(min_height=0.0, max_height=1.8, state_timeout=1.0, action_timeout=60.0),
        VlaHostConfig(planner_mode_repeat=3, planner_mode_interval=0.0,
                      publish_planner_mode=modes.append),
        search_success_distance_thresh=0.5,
    )
    skill = engine.skills.get("navigation.vla_nav")
    assert skill._search_success_distance_thresh == 0.5

    engine.tools._active_tool_name = skill.name
    # 0.4 < 0.5 → 过近静默成功（不出海）
    engine.skills.dispatch_plan(SkillCommand(vla_call(
        dict(WAYPOINT, waypoint_world=[0.4, 0.0, 1.0]))))
    assert ports.goals == []
    dispose()


def test_create_vla_runtime_reads_vla_private_params(tmp_path, monkeypatch):
    """~vla/* 私有参数逐字段读取（VlaHostConfig 全字段 + 技能层阈值），
    未覆盖字段保持默认值；create_vla_runtime 不再接收 perception。"""
    # dispatcher_node 顶部 import 链拖 tool_plane.control_plane → zenoh
    # （本环境无 zenoh，与全量门禁 ignore 的既有基线同源）；以 stub 顶替
    # 其模块级导入后加载。
    stub = types.ModuleType("dispatcher.tool_plane.control_plane")
    stub.ToolControlPlane = object
    monkeypatch.setitem(sys.modules, "dispatcher.tool_plane.control_plane", stub)
    import dispatcher_node

    overrides = {
        "vla/search_success_distance_thresh": 0.5,
        "vla/min_height": 0.2,
    }

    def fake_param(name, default=None):
        return overrides.get(name, default)

    monkeypatch.setattr(dispatcher_node.params_ros, "get_private_param", fake_param)

    frame = SimpleNamespace(current_state=np.array([0.0, 0.0, 1.0, 0.0, 0.0, 0.0]))
    engine = make_engine(tmp_path, monkeypatch, frame)
    ports = FakePorts()
    dispose = dispatcher_node.create_vla_runtime(
        engine, ports,
        FlightConfig(min_height=0.0, max_height=1.8, state_timeout=1.0, action_timeout=60.0),
    )
    try:
        skill = engine.skills.get("navigation.vla_nav")
        # 技能层阈值（~vla/* 覆盖生效）
        assert skill._search_success_distance_thresh == 0.5
        # VlaHostConfig 覆盖 / 未覆盖字段（默认值逐项核对）
        assert skill._host.min_height == 0.2
        assert skill._host.max_height == 1.8
        # 行为断言 1：过近阈值 0.5 生效（0.4 m 航点被吞）
        engine.tools._active_tool_name = skill.name
        engine.skills.dispatch_plan(SkillCommand(vla_call(
            dict(WAYPOINT, waypoint_world=[0.4, 0.0, 1.0]))))
        assert ports.goals == []
        # 行为断言 2：min_height=0.2 的 clamp 下界生效
        engine.skills.dispatch_plan(SkillCommand(vla_call(
            dict(WAYPOINT, waypoint_world=[2.2, 0.0, 0.05]))))
        assert ports.goals[-1][1].position == (2.2, 0.0, 0.2)
    finally:
        dispose()


# ---------------------------------------------------------------------------
# 飞行独占：VLA 与飞行共享 engine 动作账务 / runtime 单活动调用
# ---------------------------------------------------------------------------


def install_both(engine, ports):
    """飞行 + VLA 同 engine 装配（共享同一出站口与动作账务）。"""
    config = FlightConfig(min_height=0.0, max_height=1.8, state_timeout=1.0, action_timeout=60.0)
    flight_host, dispose_flight = install_flight(engine, ports, config)
    modes = []
    vla_host, dispose_vla = install_vla(
        engine, ports, config,
        VlaHostConfig(planner_mode_repeat=3, planner_mode_interval=0.0,
                      publish_planner_mode=modes.append),
    )
    return SimpleNamespace(
        flight_host=flight_host, dispose_flight=dispose_flight,
        vla_host=vla_host, dispose_vla=dispose_vla, modes=modes,
    )


def flight_call(call_id="f1", name="basic_flight.translate", arguments=None):
    if arguments is None:
        arguments = {"direction": "forward", "distance_m": 1.0}
    return ToolCall(
        call_id=call_id, name=name, arguments=arguments,
        flight_session_id="test", step_id=call_id,
    )


def test_flight_armed_rejects_vla_arm(tmp_path, monkeypatch):
    """动作归属唯一（owner 门）：飞行动作进行中，VLA 技能越权武装被拒——
    归属快照后 owner 与传入技能不一致，不推进动作账务。"""
    frame = SimpleNamespace(current_state=np.array([0.0, 0.0, 1.0, 0.0, 0.0, 0.0]))
    engine = make_engine(tmp_path, monkeypatch, frame)
    ports = FakePorts()
    both = install_both(engine, ports)
    # 飞行 translate 武装（owner=translate 技能，本轮 DISPATCH 命中者）
    engine.tools._active_tool_name = "basic_flight.translate"
    engine.skills.dispatch_plan(SkillCommand(flight_call()))
    assert engine.action_in_progress is True
    # VLA 技能越权武装：owner 快照不匹配 → 拒绝且不推进状态
    vla_skill = engine.skills.get("navigation.vla_nav")
    assert vla_skill._host.arm_action(
        action_name="search", prompt_raw="x", owner=vla_skill) is False
    assert "arm_action_owner_mismatch" in [event for event, _ in engine.events]
    both.dispose_vla()
    both.dispose_flight()


def test_new_call_preemption_path_cancels_active_vla_action(tmp_path, monkeypatch):
    """同源抢占链（core 新调用 enter_global_stop 路径）对 VLA 动作生效：
    活动调用被取消（保持 goal 出海）、技能状态清理，新调用接管。"""
    frame = SimpleNamespace(current_state=np.array([0.0, 0.0, 1.0, 0.0, 0.0, 0.0]))
    engine = make_engine(tmp_path, monkeypatch, frame)
    ports = FakePorts()
    both = install_both(engine, ports)
    # VLA 武装（活动调用）
    engine.tools._active_tool_name = "navigation.vla_nav"
    engine.skills.dispatch_plan(SkillCommand(vla_call()))
    assert engine.action_in_progress is True
    vla_skill = engine.skills.get("navigation.vla_nav")
    assert vla_skill._advance_after_result is True  # 终态腿已置会话态
    held = len(ports.goals)
    # 新调用准入（core start_tool_workflow 同款抢占链）：
    # enter_global_stop → owner.on_global_stop → VLA 取消 + 状态清理
    engine.tools.start_tool_workflow(flight_call(), SkillCommand(flight_call()))
    assert vla_skill._advance_after_result is False  # 会话状态随取消清理
    assert len(ports.goals) == held + 1  # 取消经共享执行发布保持意图
    assert engine.action_in_progress is False
    # 新调用（飞行）接管：入队并武装出海
    assert engine.prompt_queue.head_command() is not None
    command = engine.prompt_queue.head_command()[1]
    assert engine.skills.dispatch_plan(command) is True
    assert ports.goals[-1][1].position[:2] == (1.0, 0.0)  # forward 1m 无偏航
    both.dispose_vla()
    both.dispose_flight()


def test_same_owner_preemption_applies_to_vla_on_production_surface():
    """runtime 层（生产七工具发现面）：vla_nav 活动调用被同源新指令抢占——
    cancel(preempted_by_new_instruction) 先于新 call 命令入队（G27/G28 同款），
    飞行独占与同源抢占机制按工具面统一适用，navigation.vla_nav 无豁免。"""
    import queue

    from dispatcher.tool_plane.runtime import ToolRuntime
    from dispatcher.tool_plane.connection_lease import ConnectionLeaseManager

    commands = queue.Queue()
    manager = ConnectionLeaseManager("sim/dispatcher")
    runtime = ToolRuntime(ToolRegistry.default(), commands, manager)
    acquired = manager.acquire("station", "instance")
    identity = {key: acquired[key] for key in ("station_id", "station_instance_id", "lease_id")}

    def payload(call_id, name, arguments):
        return {
            "call_id": call_id, "name": name, "arguments": arguments,
            "context": {"flight_session_id": "flight_a", "step_id": "step_1", **identity},
        }

    runtime.admit(payload("vla_1", "navigation.vla_nav", dict(WAYPOINT)))
    assert commands.get_nowait().call.name == "navigation.vla_nav"
    runtime.admit(payload("land_1", "basic_flight.land", {}))
    cancel = commands.get_nowait()
    emergency = commands.get_nowait()
    assert (cancel.kind, cancel.call.call_id, cancel.reason) == (
        "cancel", "vla_1", "preempted_by_new_instruction",
    )
    assert (emergency.kind, emergency.call.name) == ("call", "basic_flight.land")
    assert runtime.can_execute("vla_1") is False  # 旧调用失去执行资格
    assert runtime.can_execute("land_1") is True  # 新调用接管飞行槽
