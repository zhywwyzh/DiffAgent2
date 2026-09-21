"""VLA 技能（tools/vla/vla_skill.py）回归：plan_tick 语义链 / 三裁决 / 门禁。

期望值推导依据（航点执行器形态，station 解算 waypoint 后下发）：
- 语义预检（_consume_station_waypoint）：waypoint_world 恰 3 项且有限、
  yaw 有限 → 6-D 航点；预检失败 → invalid_station_waypoint（唯一结构原因，
  事件名 vla_invalid_station_waypoint）。
- 距离过近：‖waypoint-pos‖ < search_success_distance_thresh=0.3 →
  vla_waypoint_too_close + advance_prompt（不 dispatch）；载荷带 yaw 时
  豁免（terminal yaw 到达后转向）；位姿不可用（headless）跳过判定。
- 高度 clamp（_dispatch_waypoint）：z ∈ [min_height=0, max_height=1.8]。
- yaw/look_forward 派生：yaw 有限 → look_forward=False、
  yaw_source=station_geometry；缺省 look_forward=true、yaw_source=unspecified。
- 贴地腿：waypoint=(x, y, 0.1, 0, 0, yaw)，look_forward=False →
  dispatched_yaw=yaw，NEW_ACTION；headless 无帧时不发贴地腿（IDLE 收敛）。

动作账务走真实 VlaSkillHost + VlaWaypointExecution + DispatcherEngine。
"""

from __future__ import annotations

import ast
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "l3-dispatcher-planner/ros_packages/dispatcher"
sys.path.insert(0, str(PACKAGE))

from dispatcher.engine import DispatcherEngine  # noqa: E402
from dispatcher.execution.skill_host import VlaSkillHost  # noqa: E402
from dispatcher.tools.vla.vla_waypoint import VlaWaypointExecution  # noqa: E402
from dispatcher.execution.ports import (  # noqa: E402
    FlightConfig,
    FlightState,
    Progress,
)
from dispatcher.tool_plane.model import SkillCommand, ToolCall  # noqa: E402
from dispatcher.tools.skill_api import SkillVerdict  # noqa: E402
from dispatcher.tools.vla.ports import VlaHostConfig  # noqa: E402
from dispatcher.tools.vla.vla_skill import VlaSkill  # noqa: E402
from dispatcher.support.state import COMMAND_STATUS, DISPATCHER_STATE  # noqa: E402

# ---------------------------------------------------------------------------
# 合成环境：原点上方 1m、朝 +x（yaw=0）的机体；station 下发世界系航点
# ---------------------------------------------------------------------------

FRAME_STATE = np.array([0.0, 0.0, 1.0, 0.0, 0.0, 0.0])
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
    frame = SimpleNamespace(current_state=FRAME_STATE.copy())
    engine.get_frame_snapshot = lambda: frame  # 距离过近判定消费
    ports = FakePorts()
    execution = VlaWaypointExecution(ports, FlightConfig(
        min_height=0.0, max_height=1.8, state_timeout=1.0, action_timeout=60.0))
    modes = []
    host = VlaSkillHost(engine, execution, VlaHostConfig(
        planner_mode_repeat=3, planner_mode_interval=0.0, publish_planner_mode=modes.append))
    slog = []
    skill = VlaSkill(host, emit=lambda level, event, **fields: slog.append((level, event, fields)))
    engine.skills.register(skill.name, skill)
    engine.tools._active_tool_name = skill.name
    return SimpleNamespace(
        engine=engine, frame=frame, ports=ports,
        execution=execution, host=host, skill=skill, modes=modes, slog=slog,
    )


def dispatch(stack, arguments=None, display_text=""):
    """以 waypoint 参数直发 DISPATCH（绕 FSM 节拍；与 core 调用路径同源）。"""
    call = ToolCall(
        call_id="step", name="navigation.vla_nav",
        arguments=dict(arguments if arguments is not None else WAYPOINT),
        flight_session_id="test", step_id="step", display_text=display_text,
    )
    assert stack.engine.skills.dispatch_plan(SkillCommand(call)) is True
    return call


def finish_active(stack):
    """注入 all_consumed 进度并轮询到动作结果（True 视为成功到达）。"""
    batch = stack.ports.goals[-1][0]
    stack.ports.progress_messages.append(Progress(batch, True))
    result = stack.host.poll_result()
    assert result is not None and result.success
    return result


def last_goal(stack):
    return stack.ports.goals[-1][1]


# ---------------------------------------------------------------------------
# 身份与协议钩子
# ---------------------------------------------------------------------------


def test_identity_and_protocol_hooks(stack):
    """身份三项声明（l3-skill-contract §2/§10）；wait 钩驱动共享执行轮询
    （无活动执行时 poll 返回 None）、无技能完成门。"""
    skill = stack.skill
    assert skill.name == "navigation.vla_nav"
    assert skill.requires_perception is False
    assert skill.synchronous is False
    assert skill.wait_action_tick() is None
    assert skill.action_done_gate() is None


# ---------------------------------------------------------------------------
# station waypoint 消费（_consume_station_waypoint）
# ---------------------------------------------------------------------------


def waypoint_from(stack, arguments):
    call = ToolCall(
        call_id="step", name="navigation.vla_nav", arguments=dict(arguments),
        flight_session_id="test", step_id="step",
    )
    return stack.skill._consume_station_waypoint(call)


def test_consume_builds_six_dim_waypoint(stack):
    """合法载荷：恰 3 项有限 → [x, y, z, 0, 0, yaw]（缺省 yaw=0）。"""
    waypoint = waypoint_from(stack, WAYPOINT)
    assert waypoint.tolist() == [2.2, 0.0, 1.0, 0.0, 0.0, 0.0]


def test_consume_honors_terminal_yaw(stack):
    waypoint = waypoint_from(stack, dict(WAYPOINT, yaw=0.6))
    assert waypoint.tolist() == [2.2, 0.0, 1.0, 0.0, 0.0, 0.6]


@pytest.mark.parametrize("overrides", [
    {"waypoint_world": None},              # waypoint_world 缺失/空
    {"waypoint_world": [1.0, 2.0]},        # 2 项
    {"waypoint_world": [1.0, 2.0, 3.0, 4.0]},  # 4 项
    {"waypoint_world": [1.0, 2.0, float("inf")]},  # 非有限
    {"waypoint_world": [1.0, 2.0, float("nan")]},  # 非有限
    {"waypoint_world": "1,2,3"},           # 类型不符
    {"yaw": float("nan")},                 # yaw 非有限
])
def test_consume_rejects_invalid_payloads(stack, overrides):
    assert waypoint_from(stack, dict(WAYPOINT, **overrides)) is None


# ---------------------------------------------------------------------------
# plan_tick fail-closed（唯一结构原因 invalid_station_waypoint）
# ---------------------------------------------------------------------------


def test_fail_closed_invalid_station_waypoint(stack):
    dispatch(stack, dict(WAYPOINT, waypoint_world=[500.0, 500.0]))
    engine = stack.engine
    assert engine.ledger.failed
    assert engine.dispatcher_state == DISPATCHER_STATE.WAIT_FOR_MISSION
    assert engine.channels.phases[-1]["error"]["code"] == "invalid_station_waypoint"
    assert stack.ports.goals == []  # 未武装、未出海
    events = [event for _, event, _ in stack.slog]
    assert "vla_invalid_station_waypoint" in events
    fields = next(f for _, e, f in stack.slog if e == "vla_invalid_station_waypoint")
    assert fields["target"] == "fly to the red marker"


def test_fail_closed_missing_waypoint(stack):
    arguments = dict(WAYPOINT)
    del arguments["waypoint_world"]
    dispatch(stack, arguments)
    assert stack.engine.channels.phases[-1]["error"]["code"] == "invalid_station_waypoint"
    assert stack.ports.goals == []


# ---------------------------------------------------------------------------
# plan_tick 正常链：航点出海 / yaw 派生 / 接近判定 / clamp
# ---------------------------------------------------------------------------


def test_normal_leg_dispatches_waypoint(stack):
    """正常路径：航点命中相位（携带 waypoint）→ goal (2.2,0,1) look_forward。"""
    dispatch(stack)
    engine, goal = stack.engine, last_goal(stack)
    assert goal.position == (2.2, 0.0, 1.0)
    assert goal.yaw == 0.0 and goal.look_forward is True
    # 簿记与武装（宿主机械写）：waypoint / 代次 / WAIT_ACTION_FINISH
    assert engine.waypoint == (2.2, 0.0, 1.0)
    assert engine.last_published_waypoint == (2.2, 0.0, 1.0)
    assert engine.dispatcher_state == DISPATCHER_STATE.WAIT_ACTION_FINISH
    pending = engine.action_gate.pending_action  # 宿主侧记账（技能不读，见静态断言）
    assert pending.action_name == "search"
    assert pending.nav_yaw is None  # look_forward → nav_yaw 簿记 None
    assert pending.yaw_source == "unspecified"
    # 模式脉冲经受控回调出海（repeat=3）
    assert stack.modes == [1, 1, 1]
    assert "vla_waypoint_published" in [event for _, event, _ in stack.slog]
    # 航点命中相位（携带站端航点，前端呈现目标位置）
    searching = [p for p in engine.channels.phases if p["phase"] == "searching"]
    assert searching and searching[-1]["result"]["waypoint"] == [2.2, 0.0, 1.0]
    # 单一终态路径：consume_head_prompt 弹队首 + ADVANCE_READY
    assert engine.ledger.command_status == COMMAND_STATUS.ADVANCE_READY


def test_terminal_yaw_leg_turns_to_target(stack):
    """载荷带 yaw：look_forward=False、nav_yaw=yaw、yaw_source=station_geometry。"""
    dispatch(stack, dict(WAYPOINT, yaw=0.6))
    goal = last_goal(stack)
    assert goal.position == (2.2, 0.0, 1.0)
    assert goal.yaw == 0.6 and goal.look_forward is False
    pending = stack.engine.action_gate.pending_action
    assert pending.nav_yaw == 0.6
    assert pending.yaw_source == "station_geometry"


def test_explicit_look_forward_false_uses_waypoint_yaw(stack):
    """仅 look_forward=false（无 yaw）：dispatched_yaw 取 6-D 航点 yaw（0.0）。"""
    dispatch(stack, dict(WAYPOINT, look_forward=False))
    goal = last_goal(stack)
    assert goal.yaw == 0.0 and goal.look_forward is False


@pytest.mark.parametrize("waypoint,expected_goal", [
    ([0.1, 0.0, 1.0], None),    # 距离 0.1 < 0.3 → 不 dispatch，推进 prompt
    ([0.35, 0.0, 1.0], (0.35, 0.0, 1.0)),  # 距离 0.35 ≥ 0.3 → 正常出海
    ([0.3, 0.0, 1.0], (0.3, 0.0, 1.0)),    # 边界：恰 0.3 不算接近（< 严格）
])
def test_close_distance_threshold(stack, waypoint, expected_goal):
    dispatch(stack, dict(WAYPOINT, waypoint_world=waypoint))
    if expected_goal is None:
        assert stack.ports.goals == []
        assert "vla_waypoint_too_close" in [event for _, event, _ in stack.slog]
        assert stack.engine.ledger.command_status == COMMAND_STATUS.MISSION_DONE
    else:
        assert last_goal(stack).position == expected_goal


def test_terminal_yaw_exempt_from_too_close_skip(stack):
    """terminal yaw 豁免：距离过近（0.1 < 0.3）但载荷带 yaw → 照常发腿。"""
    dispatch(stack, dict(WAYPOINT, waypoint_world=[0.1, 0.0, 1.0], yaw=0.4))
    goal = last_goal(stack)
    assert goal.position == (0.1, 0.0, 1.0)
    assert goal.yaw == 0.4 and goal.look_forward is False


def test_no_frame_skips_too_close_check(stack):
    """headless（latest_frame None）：跳过接近判定，按正常航点执行。"""
    stack.engine.get_frame_snapshot = lambda: None
    dispatch(stack, dict(WAYPOINT, waypoint_world=[0.1, 0.0, 1.0]))
    assert last_goal(stack).position == (0.1, 0.0, 1.0)


@pytest.mark.parametrize("z,clamped", [(2.5, 1.8), (-0.5, 0.0), (1.0, 1.0)])
def test_height_clamp_inline_shaping(stack, z, clamped):
    """内联塑形：航点高度 clamp 到 [min_height=0, max_height=1.8]。"""
    dispatch(stack, dict(WAYPOINT, waypoint_world=[2.2, 0.0, z]))
    assert last_goal(stack).position == (2.2, 0.0, clamped)


def test_too_close_stashes_action_result_and_advances(stack):
    """过近静默成功：advance_prompt 队空即发 done，结果携带 action_result。"""
    dispatch(stack, dict(WAYPOINT, waypoint_world=[0.1, 0.0, 1.0]))
    engine = stack.engine
    assert stack.ports.goals == []
    assert engine.ledger.command_status == COMMAND_STATUS.MISSION_DONE
    done = [p for p in engine.channels.phases if p["phase"] == "done"]
    assert done and done[-1]["result"] == {"completion": "action_result"}


# ---------------------------------------------------------------------------
# 三裁决（on_action_result；无 REPLAN——单次消费即终态腿）
# ---------------------------------------------------------------------------


def test_advance_verdict_stashes_action_result(stack):
    """正常腿到达 → ADVANCE，stash completion=action_result。"""
    dispatch(stack)
    verdict = stack.skill.on_action_result(finish_active(stack))
    assert verdict is SkillVerdict.ADVANCE
    assert stack.engine.skills.pop_task_result() == {"completion": "action_result"}
    assert stack.skill.on_action_result(None) is SkillVerdict.IDLE  # 会话状态已清


def test_stale_generation_result_rejected_after_rearm(stack):
    """重新武装后旧代次结果被拒（代次门）：完成门不放行、finish 标志被清。"""
    engine = stack.engine
    dispatch(stack)
    finish_active(stack)  # 第一腿结果（代次 N）
    stack.skill.on_action_result(engine.action_gate._last_action_result)  # ADVANCE
    # 下一腿重新武装（代次 N+1）后，旧代次结果迟到
    dispatch(stack, dict(WAYPOINT, waypoint_world=[3.0, 0.0, 1.0]))
    gate = engine.action_gate
    engine.action_finish = True
    gate._action_finish_generation = gate._action_generation - 1
    assert gate.action_done() is False
    assert engine.action_finish is False
    assert "task_action_result_ignored" in [event for event, _ in engine.events]


def test_cancel_clears_session_state_and_holds(stack):
    """取消：停共享执行（保持 goal 出海）+ 会话状态清理 → 裁决不再 ADVANCE。"""
    dispatch(stack)
    held = len(stack.ports.goals)
    stack.skill.on_cancel()
    assert stack.skill._advance_after_result is False
    assert len(stack.ports.goals) == held + 1  # cancel 发布保持意图
    assert stack.skill.on_action_result(None) is SkillVerdict.IDLE


def test_new_prompt_task_and_global_stop_clear_session_state(stack):
    """新任务准入 / 全局停止：会话状态清理，不跨任务泄漏。"""
    dispatch(stack, display_text="land at the marker")
    assert stack.skill._if_landing is True
    stack.skill.on_new_prompt_task()
    assert stack.skill._advance_after_result is False
    assert stack.skill._if_landing is False

    # 旧动作收尾后再造会话态（共享执行独占：活动 goal 未完成不得二次出海）
    finish_active(stack)
    stack.skill.on_action_result(None)
    dispatch(stack)
    assert stack.skill._advance_after_result is True
    stack.skill.on_global_stop()
    assert stack.skill._advance_after_result is False
    assert stack.skill._if_landing is False


def test_landing_final_approach_returns_new_action(stack):
    """landing 贴地腿：主腿到达 → 先推进 prompt 序列，再补贴地航点 z=0.1。"""
    engine = stack.engine
    dispatch(stack, display_text="land at the marker")
    assert stack.skill._if_landing is True
    verdict = stack.skill.on_action_result(finish_active(stack))
    assert verdict is SkillVerdict.NEW_ACTION
    # 序列推进（advance_prompt 端口）：队空 → done 相位携带 action_result
    assert engine.ledger.command_status == COMMAND_STATUS.MISSION_DONE
    done = [p for p in engine.channels.phases if p["phase"] == "done"]
    assert done and done[-1]["result"] == {"completion": "action_result"}
    # 贴地航点：当前 xy、z=0.1、terminal yaw=当前 yaw（look_forward=False）
    goal = last_goal(stack)
    assert goal.position == (0.0, 0.0, 0.1)
    assert goal.yaw == 0.0 and goal.look_forward is False
    assert engine.action_gate.pending_action.action_name == "landing-final-approach"
    # 贴地腿到达 → 回落通用 IDLE（不循环 NEW_ACTION）
    assert stack.skill.on_action_result(finish_active(stack)) is SkillVerdict.IDLE


def test_landing_without_frame_converges_without_ground_leg(stack):
    """headless 无帧：贴地腿不可构造 → 不空武装，按队列推进收敛（IDLE）。"""
    engine = stack.engine
    dispatch(stack, display_text="land at the marker")
    held = len(stack.ports.goals)
    engine.get_frame_snapshot = lambda: None
    verdict = stack.skill.on_action_result(finish_active(stack))
    assert verdict is SkillVerdict.IDLE
    assert len(stack.ports.goals) == held  # 未再出海
    assert engine.ledger.command_status == COMMAND_STATUS.MISSION_DONE


# ---------------------------------------------------------------------------
# B1 端到端：引擎主循环逐 tick 驱动（不手动 poll_result）
# ---------------------------------------------------------------------------


def engine_tick(engine):
    """仿真 engine.run_inference 单节拍：DISPATCH / WAIT_ACTION_FINISH /
    POST_ACTION 三态分支与 engine.py 同源（B1 断链所在区域）。"""
    state = engine.dispatcher_state
    if state == DISPATCHER_STATE.WAIT_ACTION_FINISH:
        wait_skill = engine.skills.owner_skill()
        if wait_skill is not None:
            wait_skill.wait_action_tick()
            if engine.dispatcher_state != DISPATCHER_STATE.WAIT_ACTION_FINISH:
                return
        if engine.action_gate.action_done():
            engine.action_in_progress = False
            engine.action_finish = False
            engine.ledger.set_state(
                DISPATCHER_STATE.POST_ACTION, reason="action:done"
            )
        return
    if state == DISPATCHER_STATE.POST_ACTION:
        engine.action_gate.handle_post_action()
        return
    if state == DISPATCHER_STATE.DISPATCH:
        if engine.action_in_progress:
            engine.ledger.set_state(
                DISPATCHER_STATE.WAIT_ACTION_FINISH,
                reason="dispatch:action_in_progress",
            )
            return
        if engine.prompt_queue.is_command_empty():
            engine.ledger.set_state(
                DISPATCHER_STATE.WAIT_FOR_MISSION, reason="plan:command_content_empty"
            )
            return
        engine.prompt_queue.reset_plan_cycle_if_needed()
        _, skill_command = engine.prompt_queue.head_command()
        engine.skills.dispatch_plan(skill_command)
        return
    raise AssertionError(f"tick 仿真未覆盖的状态: {state}")


def run_ticks(engine, *, limit=64, until=None):
    """逐 tick 推进到 until 条件；超限即失败——B1 回归锚点：wait_action_tick
    若为空钩、action_finish 永不置位，此循环必然超限。"""
    for _ in range(limit):
        if until is not None and until(engine):
            return
        engine_tick(engine)
    assert until is not None and until(engine), "tick 推进超限：FSM 未达期望状态"


def test_engine_loop_ticks_drive_vla_to_done(stack):
    """B1 端到端：主循环逐 tick（wait_action_tick → poll_result →
    action_done）驱动「出海 → 完成 → ADVANCE → 队列耗尽 done」全链，
    全程不手动调用 poll_result（终态腿：单次消费、单次下发）。"""
    engine = stack.engine
    engine._min_action_wait = 0.0  # 绕最小等待窗口（poll 即完成的受控环境）
    # 队列装载（与生产 start_tool_workflow 同款机械：入队 + 弹队首装载）
    command = SkillCommand(ToolCall(
        call_id="loop", name="navigation.vla_nav", arguments=dict(WAYPOINT),
        flight_session_id="test", step_id="loop"))
    engine.prompt_queue.sync_task_buffers_from_prepare(
        [("fly to the red marker", command)])
    engine.tools._activate_tool_call(command.call)
    engine.prompt_queue.pop_next_task()
    engine.ledger.set_state(DISPATCHER_STATE.DISPATCH, reason="mission:ready")

    # 1) 出海：DISPATCH 消费 → 站端航点 (2.2,0,1) → WAIT_ACTION_FINISH
    engine_tick(engine)
    assert engine.dispatcher_state == DISPATCHER_STATE.WAIT_ACTION_FINISH
    assert last_goal(stack).position == (2.2, 0.0, 1.0)
    # 2) 空转节拍：wait_action_tick 内部 poll 无结果 → 完成门不放行（仍在等）
    engine_tick(engine)
    assert engine.dispatcher_state == DISPATCHER_STATE.WAIT_ACTION_FINISH
    assert engine.action_finish is False
    # 3) 下游到达：注入 all_consumed 进度 → 下一节拍 poll 置 action_finish →
    #    完成门放行 → POST_ACTION（B1 修复点：完成由 tick 轮询驱动）
    batch = stack.ports.goals[-1][0]
    stack.ports.progress_messages.append(Progress(batch, True))
    engine_tick(engine)
    assert engine.dispatcher_state == DISPATCHER_STATE.POST_ACTION
    # 4) POST_ACTION 裁决 ADVANCE → 队空即发 done（结果携带 action_result）
    #    并回落 WAIT_FOR_MISSION（终态，FSM 不卡死）
    engine_tick(engine)
    assert engine.dispatcher_state == DISPATCHER_STATE.WAIT_FOR_MISSION
    done = [p for p in engine.channels.phases if p["phase"] == "done"]
    assert done and done[-1]["result"] == {"completion": "action_result"}
    run_ticks(
        engine,
        until=lambda e: e.dispatcher_state == DISPATCHER_STATE.WAIT_FOR_MISSION,
    )
    assert engine.ledger.failed is False
    assert len(stack.ports.goals) == 1  # 终态腿只出海一次


def test_engine_loop_poll_failure_fails_sequence_with_reason(stack):
    """B1 异常路径：wait_action_tick 内 poll 抛异常 → fail_sequence 语义化
    终态（异常文本作 fail 相位 error.code，VLA 宿主口径），FSM 退出等待态
    不卡死。"""
    engine = stack.engine
    dispatch(stack)  # 出海 → WAIT_ACTION_FINISH
    assert engine.dispatcher_state == DISPATCHER_STATE.WAIT_ACTION_FINISH

    def broken_poll():
        raise RuntimeError("waypoint_lost")

    stack.host.execution.poll = broken_poll
    stack.skill.wait_action_tick()
    assert engine.ledger.failed is True
    assert engine.dispatcher_state == DISPATCHER_STATE.WAIT_FOR_MISSION
    fail = [p for p in engine.channels.phases if p["phase"] == "fail"]
    assert fail and fail[-1]["error"]["code"] == "waypoint_lost"
    assert engine.action_finish is False
    assert engine.if_plan is False


# ---------------------------------------------------------------------------
# requires_perception=false：分发前就绪门不再以感知帧为前置
# ---------------------------------------------------------------------------


def test_chain_admits_without_frame(stack, monkeypatch):
    """requires_perception=False + 帧缺失 → 照常入队（无 chain_not_ready 门）。"""
    engine = stack.engine
    monkeypatch.setattr(engine, "get_frame_snapshot", lambda: None)
    call = ToolCall(
        call_id="gate", name="navigation.vla_nav", arguments=dict(WAYPOINT),
        flight_session_id="test", step_id="gate")
    engine.tools.start_tool_workflow(call, SkillCommand(call))
    assert all(
        p["error"]["code"] != "chain_not_ready" for p in engine.channels.phases
        if "error" in p
    )
    assert engine.prompt_queue.head_command() is not None
    assert engine.ledger.command_status == COMMAND_STATUS.RUNNING


# ---------------------------------------------------------------------------
# 门禁 G14：技能源码不引用宿主私有（pending_action / ActionGate 等）
# ---------------------------------------------------------------------------


def test_skill_source_does_not_touch_host_privates():
    """静态断言：vla_skill.py 的代码标识符不含宿主私有成员（注释除外）。"""
    source = (PACKAGE / "dispatcher/tools/vla/vla_skill.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    identifiers = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
        elif isinstance(node, ast.Name):
            identifiers.add(node.id)
    banned = {
        "pending_action", "ActionGate", "action_gate", "_action_gate",
        "prompt_queue", "runlog", "telemetry", "ledger", "skills",
        "command_status",
    }
    assert not identifiers & banned, identifiers & banned
