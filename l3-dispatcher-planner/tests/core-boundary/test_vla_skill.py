"""VLA 技能（tools/vla/vla_skill.py）回归：plan_tick 语义链 / 四裁决 / 门禁。

期望值从旧链（DiffAgent2 旧版 tools/vla/vla_skill.py）逻辑推导：
- 像素换算（旧 _consume_grounded_detection L416-427）：scale=像素宽高/1000、
  int 取整、中心=两点均值取整；image_width/height 非正值回落 640x480。
- fail-closed 三态（旧 L111-122/L151-162/L397-414）：invalid_grounded_bbox /
  target_not_visible / odom_stamp_unavailable；事件名 vla_grounded_detection_failed /
  vla_odom_stamp_unavailable 与旧链一致。
- far_push（旧 L226-234）：depth_match_ok=False → 沿机头推进
  far_push_distance_m=5.0：[x+push*cos(yaw), y+push*sin(yaw), z]。
- 接近判定（旧 L176-190）：‖target-pos‖ < search_success_distance_thresh=0.3
  → vla_waypoint_too_close + advance_prompt（不 dispatch）。
- 高度 clamp（旧 _dispatch_waypoint L361）：z ∈ [min_height=0, max_height=1.8]。
- 贴地腿（旧 L274-295）：waypoint=(x, y, 0.1, 0, 0, yaw)，look_forward=False
  → dispatched_yaw=yaw，NEW_ACTION。

几何原语走假件（真值几何回归归 tests/perception/test_vla_geometry.py）；
动作账务走真实 VlaSkillHost + WaypointExecution + DispatcherEngine。
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
from dispatcher.execution.waypoint_execution import WaypointExecution  # noqa: E402
from dispatcher.tools.flight.ports import (  # noqa: E402
    FlightConfig,
    FlightState,
    Progress,
)
from dispatcher.tools.model import SkillCommand, ToolCall  # noqa: E402
from dispatcher.tools.skill_api import SkillVerdict  # noqa: E402
from dispatcher.tools.vla.ports import VlaHostConfig  # noqa: E402
from dispatcher.tools.vla.vla_skill import VlaSkill  # noqa: E402
from dispatcher.utils.state import COMMAND_STATUS, DISPATCHER_STATE  # noqa: E402

# ---------------------------------------------------------------------------
# 合成环境：原点上方 1m、朝 +x（yaw=0）的机体；station 下发 1000 空间 bbox
# ---------------------------------------------------------------------------

FRAME_STATE = np.array([0.0, 0.0, 1.0, 0.0, 0.0, 0.0])
GROUNDED = {
    "object": "red marker",
    "prompt": "fly to the red marker",
    "bbox_1000": [250.0, 250.0, 500.0, 500.0],
    "image_stamp": 100.25,
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
    """geometry_source 端口假件：几何原语按技能路径最小协同。

    - build_world_frame_for_image_stamp：恒返回预置 world_frame（None 注入
      复现 odom 对齐失败 → odom_stamp_unavailable）。
    - bbox basic 分支的增量候选经 bbox_candidate_to_body_incremental_waypoints
      返回受控 target_world（默认 (2.2,0,1)，P1 几何链 depth 单源同款期望）；
      depth_match_ok 经候选 match_ok 注入（far_push 判据）。
    """

    def __init__(self, world_frame=None, target_world=(2.2, 0.0, 1.0), match_ok=True):
        self.safe_dis_radius_m = 0.4
        self.if_safe_dis = True
        self.world_frame = world_frame if world_frame is not None else SimpleNamespace(
            current_state=np.array([0.0, 0.0, 1.0, 0.0, 0.0, 0.0]),
            depth_image=None,
            stamp=100.3,
        )
        self.target_world = np.asarray(target_world, dtype=np.float64)
        self.match_ok = bool(match_ok)

    def get_fast_rgb(self):
        return ("image", 1.0)

    def build_world_frame_for_image_stamp(self, frame, stamp):
        return self.world_frame

    def _build_region_from_bbox(self, detection, frame):
        return SimpleNamespace(kind="bbox")

    def _estimate_waypoint_candidate_for_region(self, region, frame, **kwargs):
        # point_world：非 bbox/basic 分支（side/above/front）的 object_pose
        # 构造与 _finalize_waypoint_candidate 假件的输入基准
        return SimpleNamespace(
            source="depth",
            raw_depth=3.0,
            match_ok=self.match_ok,
            point_world=np.array([3.0, 0.0, 1.0]),
        )

    def _finalize_waypoint_candidate(
        self, candidate, frame, *, pose_yaw, direction="", **kwargs
    ):
        """finalize 假件：按 d_side 组合侧偏目标（left 正向），其余回落
        轴向目标——d_side 经 config 透传到此（R1 参数覆盖验证点）。"""
        base = np.asarray(candidate.point_world, dtype=np.float64)
        lateral = float(kwargs.get("d_side", 0.5))
        if direction in ("left", "right"):
            sign = 1.0 if direction == "left" else -1.0
            return np.array([base[0] - 0.8, sign * lateral, base[2]])
        return np.array([base[0] - 0.8, base[1], base[2]])

    def _planar_axes_from_bearing(self, origin_xyz, target_xyz, fallback_yaw):
        # yaw=0 机体系：forward=+x、left=+y、up=+z
        return (
            np.array([1.0, 0.0, 0.0]),
            np.array([0.0, 1.0, 0.0]),
            np.array([0.0, 0.0, 1.0]),
        )

    def _geometry_safe_distance(self, cloud_depth_mismatch):
        return 0.8

    def _candidate_with_safe_distance(self, candidate, frame, **kwargs):
        return candidate

    def bbox_candidate_to_body_incremental_waypoints(self, region, candidate, frame, **kwargs):
        origin = np.array([0.0, 0.0, 1.0])
        return {
            "object_world": np.array([3.0, 0.0, 1.0]),
            "target_world": self.target_world.copy(),
            "object_increment": np.array([3.0, 0.0, 0.0]),
            "target_increment": self.target_world - origin,
            "incremental_yaw": 0.0,
            "target_yaw": 0.0,
            "yaw_source": "image_bbox_center_ray",
        }

    def _publish_candidate_debug_points(self, candidate, frame):
        pass

    def _publish_p2w_marker(self, P_w, stamp):
        pass


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
    engine.get_frame_snapshot = lambda: frame  # 技能 latest_frame / 就绪门共用
    perception = FakePerception()
    ports = FakePorts()
    execution = WaypointExecution(ports, FlightConfig(
        min_height=0.0, max_height=1.8, state_timeout=1.0, action_timeout=60.0))
    modes = []
    host = VlaSkillHost(engine, execution, perception, VlaHostConfig(
        planner_mode_repeat=3, planner_mode_interval=0.0, publish_planner_mode=modes.append))
    slog = []
    skill = VlaSkill(host, emit=lambda level, event, **fields: slog.append((level, event, fields)))
    engine.skills.register(skill.name, skill)
    engine.tools._active_tool_name = skill.name
    return SimpleNamespace(
        engine=engine, frame=frame, perception=perception, ports=ports,
        execution=execution, host=host, skill=skill, modes=modes, slog=slog,
    )


def dispatch(stack, arguments=None, display_text=""):
    """以 grounded 参数直发 DISPATCH（绕 FSM 节拍；与 core 调用路径同源）。"""
    call = ToolCall(
        call_id="step", name="navigation.vla_nav",
        arguments=dict(arguments if arguments is not None else GROUNDED),
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
    assert skill.requires_perception is True
    assert skill.synchronous is False
    assert skill.wait_action_tick() is None
    assert skill.action_done_gate() is None


# ---------------------------------------------------------------------------
# grounded detection 消费（旧 _consume_grounded_detection L383-443）
# ---------------------------------------------------------------------------


def detection_from(stack, arguments):
    call = ToolCall(
        call_id="step", name="navigation.vla_nav", arguments=dict(arguments),
        flight_session_id="test", step_id="step",
    )
    return stack.skill._consume_grounded_detection(call)


def test_pixel_conversion_defaults_to_640x480(stack):
    """缺省换算：scale=0.64/0.48 → pt1=(160,120)、pt2=(320,240)、中心=(240,180)。"""
    detection = detection_from(stack, GROUNDED)
    assert detection["visible"] is True
    assert detection["bbox"] == [160, 120, 320, 240]
    assert detection["result"]["pos"] == [240, 180]
    assert detection["result"]["llm_stamp"] == 100.25
    assert detection["result"]["provider"] == "station"
    assert detection["finish"] is False


def test_pixel_conversion_honors_explicit_resolution(stack):
    """显式声明 1280x960：scale=1.28/0.96 → pt1=(320,240)、pt2=(640,480)。"""
    detection = detection_from(stack, dict(GROUNDED, image_width=1280, image_height=960))
    assert detection["bbox"] == [320, 240, 640, 480]
    assert detection["result"]["pos"] == [480, 360]


def test_nonpositive_resolution_falls_back_to_default(stack):
    """image_width/height 非正值（0/负数）回落 640x480 缺省约定。"""
    detection = detection_from(stack, dict(GROUNDED, image_width=0, image_height=-5))
    assert detection["bbox"] == [160, 120, 320, 240]


def test_visible_false_short_circuits_before_bbox(stack):
    """station 明示不可见：bbox 无论形态均不消费 → target_not_visible。"""
    detection = detection_from(stack, dict(GROUNDED, visible=False, bbox_1000=[0, 0, 0, 0]))
    assert detection == {"visible": False, "reason": "target_not_visible"}


@pytest.mark.parametrize("bbox", [
    [500.0, 250.0, 400.0, 500.0],   # x2 <= x1
    [250.0, 500.0, 500.0, 400.0],   # y2 <= y1
    [250.0, 250.0, 1000.5, 500.0],  # 值域越界（>1000）
    [-0.5, 250.0, 500.0, 500.0],    # 值域越界（<0）
    [250.0, 250.0, float("inf"), 500.0],  # 非有限值
    [250.0, 250.0, 500.0],          # 元数不符（registry 已拒；此处防御同判）
])
def test_invalid_bbox_semantics_fail_closed(stack, bbox):
    assert detection_from(stack, dict(GROUNDED, bbox_1000=bbox)) == {
        "visible": False, "reason": "invalid_grounded_bbox",
    }


def test_nonfinite_stamp_fails_closed(stack):
    assert detection_from(stack, dict(GROUNDED, image_stamp=float("nan"))) == {
        "visible": False, "reason": "invalid_grounded_bbox",
    }


# ---------------------------------------------------------------------------
# plan_tick fail-closed 三态（唯一 fail 终态原因；事件名与旧链一致）
# ---------------------------------------------------------------------------


def test_fail_closed_invalid_grounded_bbox(stack):
    dispatch(stack, dict(GROUNDED, bbox_1000=[500.0, 500.0, 400.0, 600.0]))
    engine = stack.engine
    assert engine.ledger.failed
    assert engine.dispatcher_state == DISPATCHER_STATE.WAIT_FOR_MISSION
    assert engine.channels.phases[-1]["error"]["code"] == "invalid_grounded_bbox"
    assert stack.ports.goals == []  # 未武装、未出海
    events = [event for _, event, _ in stack.slog]
    assert "vla_grounded_detection_failed" in events
    fields = next(f for _, e, f in stack.slog if e == "vla_grounded_detection_failed")
    assert fields["reason"] == "invalid_grounded_bbox"


def test_fail_closed_target_not_visible(stack):
    dispatch(stack, dict(GROUNDED, visible=False))
    assert stack.engine.channels.phases[-1]["error"]["code"] == "target_not_visible"
    assert stack.ports.goals == []


def test_fail_closed_odom_stamp_unavailable(stack):
    """bracket/odom buffer 对齐失败（world_frame=None）→ odom_stamp_unavailable。"""
    stack.perception.world_frame = None
    dispatch(stack)
    engine = stack.engine
    assert engine.channels.phases[-1]["error"]["code"] == "odom_stamp_unavailable"
    assert "vla_odom_stamp_unavailable" in [event for _, event, _ in stack.slog]
    assert stack.ports.goals == []


def test_fail_closed_when_frame_missing(stack):
    """当前帧缺失（latest_frame None）同样 odom_stamp_unavailable，不静默回落。"""
    stack.engine.get_frame_snapshot = lambda: None
    dispatch(stack)
    assert stack.engine.channels.phases[-1]["error"]["code"] == "odom_stamp_unavailable"


# ---------------------------------------------------------------------------
# plan_tick 正常链：航点出海 / far_push / 接近判定 / clamp / finish 腿
# ---------------------------------------------------------------------------


def test_normal_leg_dispatches_waypoint(stack):
    """正常路径（depth_match_ok=True）：bbox 命中 → 搜索相位 → 航点 (2.2,0,1)。"""
    dispatch(stack, dict(GROUNDED, prompt="fly to the red marker"))
    engine, goal = stack.engine, last_goal(stack)
    # 航点 = 几何 target_pose (2.2,0,1)；look_forward → yaw 以 0.0 占位下发
    assert goal.position == (2.2, 0.0, 1.0)
    assert goal.yaw == 0.0 and goal.look_forward is True
    # 簿记与武装（宿主机械写）：waypoint / 代次 / replan 记账 / WAIT_ACTION_FINISH
    assert engine.waypoint == (2.2, 0.0, 1.0)
    assert engine.last_published_waypoint == (2.2, 0.0, 1.0)
    assert engine.dispatcher_state == DISPATCHER_STATE.WAIT_ACTION_FINISH
    pending = engine.action_gate.pending_action  # 宿主侧记账（技能不读，见静态断言）
    assert pending.replan_cmd == "fly to the red marker"
    assert pending.replan_reason == "search"
    assert pending.action_name == "search"
    assert pending.nav_yaw is None  # look_forward → nav_yaw 簿记 None
    assert pending.yaw_source == "current_odom"
    # 模式脉冲经受控回调出海（repeat=3）；slog 事件与旧链一致
    assert stack.modes == [1, 1, 1]
    assert "vla_waypoint_published" in [event for _, event, _ in stack.slog]
    # bbox 命中相位（携带像素坐标，前端呈现检测框）
    searching = [p for p in engine.channels.phases if p["phase"] == "searching"]
    assert searching and searching[-1]["result"]["bbox"] == [160, 120, 320, 240]


def test_far_push_along_body_heading(stack):
    """depth_match_ok=False → 不飞不可信 bbox 航点，沿机头推进 5m（yaw=0）。"""
    stack.perception.match_ok = False
    dispatch(stack)
    assert last_goal(stack).position == (5.0, 0.0, 1.0)
    assert stack.engine.action_gate.pending_action.replan_cmd == "fly to the red marker"


def test_far_push_follows_current_yaw(stack):
    """yaw=π/2：推进航点 = (0, 5, 1)（[x+5cos, y+5sin, z] 旧公式）。"""
    stack.perception.match_ok = False
    stack.frame.current_state[5] = np.pi / 2
    dispatch(stack)
    assert last_goal(stack).position == pytest.approx((0.0, 5.0, 1.0))


def test_far_push_overrides_finish_flag(stack):
    """远推进不算到达：finish=True 也被覆盖回 replan 腿（旧链置回 RUNNING）。"""
    stack.perception.match_ok = False
    call = dispatch(stack, dict(GROUNDED, finish=True))
    assert stack.engine.action_gate.pending_action.replan_cmd == call.arguments["prompt"]
    assert stack.engine.ledger.command_status == COMMAND_STATUS.RUNNING


@pytest.mark.parametrize("side", ["left", "above", "front"])
def test_far_push_on_directional_legs_when_candidate_untrusted(stack, side):
    """R2：side/above/front 腿候选不可信（match_ok=False）同样触发 far_push
    （沿机头 5m）——旧链经 _finalize_waypoint_candidate 写引擎级
    depth_match_ok（候选可信度语义），新链由返回 dict 携带该键，
    三个方向分支不再恒 False。"""
    stack.perception.match_ok = False
    dispatch(stack, dict(GROUNDED, side=side))
    # 不飞向不可信的方向偏移航点，统一沿机头推进 5m（yaw=0 → +x）
    assert last_goal(stack).position == (5.0, 0.0, 1.0)
    assert stack.engine.action_gate.pending_action.replan_cmd == "fly to the red marker"


@pytest.mark.parametrize("side", ["left", "above", "front"])
def test_directional_legs_dispatch_when_candidate_trusted(stack, side):
    """R2 对照：候选可信（match_ok=True）时方向腿正常飞组合航点
    （非 far_push），side 腿按 finalize 假件的 d_side 侧偏。"""
    dispatch(stack, dict(GROUNDED, side=side))
    goal = last_goal(stack)
    if side == "left":
        # object(3,0,1) + lateral(d_side=0.7)*left + default_forward(-0.8)*forward
        assert goal.position == pytest.approx((2.2, 0.7, 1.0))
    else:
        # above/front：finalize 无方向假件回落轴向目标 (2.2,0,1) 后组合
        assert goal.position[:2] == pytest.approx((2.2, 0.0))


@pytest.mark.parametrize("target,expected_goal", [
    ((0.1, 0.0, 1.0), None),    # 距离 0.1 < 0.3 → 不 dispatch，推进 prompt
    ((0.35, 0.0, 1.0), (0.35, 0.0, 1.0)),  # 距离 0.35 ≥ 0.3 → 正常出海
    ((0.3, 0.0, 1.0), (0.3, 0.0, 1.0)),    # 边界：恰 0.3 不算接近（旧链 < 严格）
])
def test_close_distance_threshold(stack, target, expected_goal):
    stack.perception.target_world = np.asarray(target, dtype=np.float64)
    dispatch(stack)
    if expected_goal is None:
        assert stack.ports.goals == []
        assert "vla_waypoint_too_close" in [event for _, event, _ in stack.slog]
        assert stack.engine.ledger.command_status == COMMAND_STATUS.MISSION_DONE
    else:
        assert last_goal(stack).position == expected_goal


@pytest.mark.parametrize("z,clamped", [(2.5, 1.8), (-0.5, 0.0), (1.0, 1.0)])
def test_height_clamp_inline_shaping(stack, z, clamped):
    """内联塑形：航点高度 clamp 到 [min_height=0, max_height=1.8]。"""
    stack.perception.target_world = np.array([2.2, 0.0, z])
    dispatch(stack)
    assert last_goal(stack).position == (2.2, 0.0, clamped)


def test_finish_leg_consumes_prompt_and_dispatches_without_replan(stack):
    """finish=True：弹出队首（ADVANCE_READY）+ 无 replan 下发 → 到达后 ADVANCE。"""
    engine = stack.engine
    first = SkillCommand(ToolCall(
        call_id="first", name="navigation.vla_nav", arguments=dict(GROUNDED, finish=True),
        flight_session_id="test", step_id="first"))
    second = SkillCommand(ToolCall(
        call_id="second", name="navigation.vla_nav", arguments=dict(GROUNDED),
        flight_session_id="test", step_id="second"))
    engine.prompt_queue.sync_task_buffers_from_prepare(
        [(first.call.name, first), (second.call.name, second)])
    engine.tools._activate_tool_call(first.call)
    engine.prompt_queue.pop_next_task()

    engine.skills.dispatch_plan(first)
    assert engine.ledger.command_status == COMMAND_STATUS.ADVANCE_READY
    assert engine.prompt_queue.head_command() is None  # 队首已弹出
    assert engine.action_gate.pending_action.replan_cmd is None  # finish 腿无 replan

    verdict = stack.skill.on_action_result(finish_active(stack))
    assert verdict is SkillVerdict.ADVANCE
    assert engine.skills.pop_task_result() == {"completion": "workflow_result"}


# ---------------------------------------------------------------------------
# 四裁决（on_action_result；REPLAN 由技能自有状态判定，不读宿主私有）
# ---------------------------------------------------------------------------


def test_replan_verdict_does_not_finish_early(stack):
    """临时动作（replan 腿）完成只进 REPLAN 且不提前 done；状态随 verdict 自清。"""
    dispatch(stack)
    verdict = stack.skill.on_action_result(finish_active(stack))
    assert verdict is SkillVerdict.REPLAN
    # 技能自有 replan 状态已清（旧链由壳清 pending 记账；core REPLAN 分支同款）
    assert stack.skill._replan_cmd is None and stack.skill._replan_reason is None
    # 无 done 相位（提前完成被拒绝）；再次裁决回落通用分支
    assert all(p["phase"] != "done" for p in stack.engine.channels.phases)
    assert stack.skill.on_action_result(None) is SkillVerdict.IDLE


def test_replan_loop_converges_on_next_dispatch(stack):
    """REPLAN 回 DISPATCH 围绕同一条命令再消费：近距 → advance + workflow done。"""
    dispatch(stack)
    assert stack.skill.on_action_result(finish_active(stack)) is SkillVerdict.REPLAN
    # station 同参数重发；几何候选此时已在阈值内（逼近完成）
    stack.perception.target_world = np.array([0.1, 0.0, 1.0])
    dispatch(stack)
    engine = stack.engine
    assert stack.ports.goals and len(stack.ports.goals) == 1  # 第二轮未再出海
    assert engine.ledger.command_status == COMMAND_STATUS.MISSION_DONE
    done = [p for p in engine.channels.phases if p["phase"] == "done"]
    assert done and done[-1]["result"] == {"completion": "workflow_result"}


def test_stale_generation_result_rejected_after_rearm(stack):
    """重新武装后旧代次结果被拒（代次门）：完成门不放行、finish 标志被清。"""
    engine = stack.engine
    dispatch(stack)
    finish_active(stack)  # 第一腿结果（代次 N）
    # REPLAN 回 DISPATCH，第二轮重新武装（代次 N+1）
    stack.skill.on_action_result(engine.action_gate._last_action_result)
    dispatch(stack)
    gate = engine.action_gate
    # 旧代次结果迟到：finish 代次 != 当前代次 → 拒绝并清 finish 标志
    engine.action_finish = True
    gate._action_finish_generation = gate._action_generation - 1
    assert gate.action_done() is False
    assert engine.action_finish is False
    assert "task_action_result_ignored" in [event for event, _ in engine.events]


def test_cancel_clears_replan_state_and_holds(stack):
    """取消：停共享执行（保持 goal 出海）+ REPLAN 状态清理 → 裁决不再 REPLAN。"""
    dispatch(stack)
    held = len(stack.ports.goals)
    stack.skill.on_cancel()
    assert stack.skill._replan_cmd is None
    assert len(stack.ports.goals) == held + 1  # cancel 发布保持意图
    assert stack.skill.on_action_result(None) is SkillVerdict.IDLE


def test_new_prompt_task_and_global_stop_clear_session_state(stack):
    """新任务准入 / 全局停止：REPLAN 与会话状态清理，不跨任务泄漏。"""
    dispatch(stack, dict(GROUNDED, finish=True))
    stack.skill.on_new_prompt_task()
    assert stack.skill._replan_cmd is None
    assert stack.skill._advance_after_result is False
    assert stack.skill._if_landing is False

    # 旧动作收尾后再造 replan 腿（共享执行独占：活动 goal 未完成不得二次出海）
    finish_active(stack)
    dispatch(stack)
    assert stack.skill._replan_cmd is not None
    stack.skill.on_global_stop()
    assert stack.skill._replan_cmd is None
    assert stack.skill._advance_after_result is False


def test_landing_final_approach_returns_new_action(stack):
    """landing 贴地腿：finish 腿到达 → 先推进 prompt 序列，再补贴地航点 z=0.1。"""
    engine = stack.engine
    dispatch(stack, dict(GROUNDED, finish=True), display_text="land at the marker")
    assert stack.skill._if_landing is True
    verdict = stack.skill.on_action_result(finish_active(stack))
    assert verdict is SkillVerdict.NEW_ACTION
    # 序列推进（旧链 _load_next_prompt 经 advance_prompt 端口等价）：队空 →
    # done 相位携带 workflow_result（stash 由 load_next_prompt 随 done 消费）
    assert engine.ledger.command_status == COMMAND_STATUS.MISSION_DONE
    done = [p for p in engine.channels.phases if p["phase"] == "done"]
    assert done and done[-1]["result"] == {"completion": "workflow_result"}
    # 贴地航点：当前 xy、z=0.1、terminal yaw=当前 yaw（look_forward=False）
    goal = last_goal(stack)
    assert goal.position == (0.0, 0.0, 0.1)
    assert goal.yaw == 0.0 and goal.look_forward is False
    assert engine.action_gate.pending_action.action_name == "landing-final-approach"
    # 贴地腿到达 → 回落通用 IDLE（不循环 NEW_ACTION）
    assert stack.skill.on_action_result(finish_active(stack)) is SkillVerdict.IDLE


# ---------------------------------------------------------------------------
# B1 端到端：引擎主循环逐 tick 驱动（不手动 poll_result）
# ---------------------------------------------------------------------------


def engine_tick(engine):
    """仿真 engine.run_inference 单节拍：DISPATCH / WAIT_ACTION_FINISH /
    POST_ACTION 三态分支与 engine.py 同源（B1 断链所在区域）；INIT /
    WAIT_FOR_MISSION 空闲转移与本修复无关，由测试直接置 DISPATCH 起步。"""
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
    """逐 tick 推进到 until 条件；超限即失败——B1 回归锚点：修复前
    wait_action_tick 为空钩、action_finish 永不置位，此循环必然超限。"""
    for _ in range(limit):
        if until is not None and until(engine):
            return
        engine_tick(engine)
    assert until is not None and until(engine), "tick 推进超限：FSM 未达期望状态"


def test_engine_loop_ticks_drive_vla_to_done(stack):
    """B1 端到端：主循环逐 tick（wait_action_tick → poll_result →
    action_done）驱动「首腿出海 → 完成 → REPLAN → 再 DISPATCH →
    阈值内收敛 advance → 队列耗尽 done」全链，全程不手动调用 poll_result。"""
    engine = stack.engine
    engine._min_action_wait = 0.0  # 绕最小等待窗口（poll 即完成的受控环境）
    # 队列装载（与生产 start_tool_workflow 同款机械：入队 + 弹队首装载）
    command = SkillCommand(ToolCall(
        call_id="loop", name="navigation.vla_nav", arguments=dict(GROUNDED),
        flight_session_id="test", step_id="loop"))
    engine.prompt_queue.sync_task_buffers_from_prepare(
        [("fly to the red marker", command)])
    engine.tools._activate_tool_call(command.call)
    engine.prompt_queue.pop_next_task()
    engine.ledger.set_state(DISPATCHER_STATE.DISPATCH, reason="mission:ready")

    # 1) 首腿出海：DISPATCH 消费 → bbox 航点 (2.2,0,1) → WAIT_ACTION_FINISH
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
    # 4) POST_ACTION 裁决 REPLAN（远逼近临时动作）→ 回 DISPATCH 围绕同一 prompt
    engine_tick(engine)
    assert engine.dispatcher_state == DISPATCHER_STATE.DISPATCH
    # 5) 再 DISPATCH：几何候选收敛到阈值内 → stash + advance → 队列耗尽发
    #    done（MISSION_DONE），不再出海
    stack.perception.target_world = np.array([0.1, 0.0, 1.0])
    engine_tick(engine)
    assert engine.ledger.command_status == COMMAND_STATUS.MISSION_DONE
    done = [p for p in engine.channels.phases if p["phase"] == "done"]
    assert done and done[-1]["result"] == {"completion": "workflow_result"}
    # 6) 队列空 → 主循环回落 WAIT_FOR_MISSION（终态，FSM 不卡死）
    run_ticks(
        engine,
        until=lambda e: e.dispatcher_state == DISPATCHER_STATE.WAIT_FOR_MISSION,
    )
    assert engine.ledger.failed is False
    assert len(stack.ports.goals) == 1  # 阈值内收敛腿未再出海


def test_engine_loop_poll_failure_fails_sequence_with_reason(stack):
    """B1 异常路径：wait_action_tick 内 poll 抛异常 → fail_sequence 语义化
    终态（异常文本作 fail 相位 error.code，VLA 宿主口径），FSM 退出等待态
    不卡死。"""
    engine = stack.engine
    dispatch(stack)  # 首腿出海 → WAIT_ACTION_FINISH
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
# requires_perception 就绪门（core/tool_workflow.py 既有门）
# ---------------------------------------------------------------------------


def test_chain_not_ready_when_frame_missing(stack, monkeypatch):
    """requires_perception=True + input_ready=False → 准入即 fail chain_not_ready。"""
    engine = stack.engine
    monkeypatch.setattr(engine, "get_frame_snapshot", lambda: None)
    call = ToolCall(
        call_id="gate", name="navigation.vla_nav", arguments=dict(GROUNDED),
        flight_session_id="test", step_id="gate")
    engine.tools.start_tool_workflow(call, SkillCommand(call))
    assert engine.channels.phases[-1]["error"]["code"] == "chain_not_ready"
    assert engine.prompt_queue.head_command() is None  # 未入队


def test_chain_gate_passes_with_fresh_input(stack):
    """帧可用且输入新鲜 → 过就绪门入队（planning 相位 + RUNNING）。"""
    engine = stack.engine
    call = ToolCall(
        call_id="gate", name="navigation.vla_nav", arguments=dict(GROUNDED),
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
