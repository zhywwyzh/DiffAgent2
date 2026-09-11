#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UAV 主策略节点（ROS1）。

主要职责：
1. 维护任务状态机（接收指令、规划、发布航点、等待执行完成）。
2. 调用统一 search 感知服务获取目标可见性与 bbox。
3. 将像素结果转换为世界系航点，并发布给规划器。
"""

from __future__ import annotations

import json
import time
import threading
from pathlib import Path
from dataclasses import dataclass
from typing import Any

import numpy as np

import rospy
from std_msgs.msg import String, Empty, Bool

from dispatcher.state import COMMAND_TYPE, COMMAND_STATUS, DISPATCHER_STATE
from dispatcher.config import (
    CONFIG_KEY_ALIASES,
    UAV_POLICY_DEFAULTS,
    load_yaml,
    set_ros_params,
    set_defaults,
    apply_config,
    merge_config_sections,
    get_nested_config,
    flatten_leaf_params,
    merge_pointcloud_mode_params,
)
from dispatcher.skill_api import SkillVerdict
from dispatcher.slog import StructuredLogger
from dispatcher.tools.model import SkillCommand, ToolCall

from dispatcher.perception.base_policy import BasePolicyNode


@dataclass
class PendingAction:
    """待发布动作上下文。"""

    waypoint: Any = None  # 待发布航点（xyz 或 xyzrpy）
    look_forward: bool = True  # 发布动作时是否朝向前进方向
    replan_cmd: Any = None  # 执行完成后用于重规划的命令
    replan_reason: Any = None  # 执行完成后用于重规划的原因
    action_name: str = ""  # 发布动作日志名称
    prompt_raw: str = ""  # 原始 prompt
    instruction_type: Any = None  # 动作发布类型，默认走 TURN_GOAL
    nav_yaw: Any = None  # 到达 waypoint 后执行的 terminal yaw
    yaw_source: str = "unspecified"  # 最终下发 yaw 的来源
    is_far_push: bool = False  # 是否为远/稀疏目标的推进动作（触发 reacquire 重搜）

    def clear(self) -> None:
        """重置待发布动作上下文。"""
        self.waypoint = None
        self.look_forward = True
        self.replan_cmd = None
        self.replan_reason = None
        self.action_name = ""
        self.prompt_raw = ""
        self.instruction_type = None
        self.nav_yaw = None
        self.yaw_source = "unspecified"
        self.is_far_push = False


# 主节点类初始化
class DispatcherEngine(
    BasePolicyNode,
):
    """任务编排与执行主节点。"""

    def __init__(self):
        """初始化节点状态、ROS 通信对象与后台线程。"""
        super().__init__()

        # 默认配置
        set_defaults(self, UAV_POLICY_DEFAULTS)  # 加载默认配置到节点属性

        # 核心任务状态
        self.first_image = None  # 任务起始图像缓存
        self.last_plan_time = None  # 上次规划时间戳
        self.first_rgb = None  # 当前任务的首帧 RGB
        self.command_content = []  # 当前待执行命令队列
        self.sync_task_buffers_from_prepare()  # 基于 prepare_content 初始化任务缓存
        self.replan_content = None  # 当前重规划参考命令
        self.command_type = COMMAND_TYPE.WAIT  # 外部命令类型状态
        self.command_status = COMMAND_STATUS.RUNNING  # 指令执行状态（RUNNING/MISSION_DONE/ADVANCE_READY）
        self.dispatcher_state = None  # 当前 dispatcher FSM 状态
        self.frame = None  # 当前传感器接收数据
        self.action_finish = False  # TaskAction result 完成标志（唯一完成信号源）
        self.last_state = None  # 保存上一次状态
        self.result = None  # 当前模型返回结果
        self.nav_mask = None  # 当前导航结果的 mask
        self.waypoint = None  # 当前导航目标点
        # first_plan 已随 VLA 搜索会话迁入 VlaSkill（P3.4，技能自有 _first_plan）
        self.first_frame = None  # 首次规划对应的帧快照

        # 动作发布状态
        self.action_in_progress = False  # 是否有动作正在执行
        self.pending_action = PendingAction()  # 待发布动作上下文
        self.action_start_time = 0.0  # 当前动作起始时间（墙钟）
        # 动作代次守卫：拒绝在途旧动作迟到的 action result（任务切换/preempt 场景必需）
        self._action_generation = 0  # 动作代次，每次发布自增
        self._action_finish_generation = -1  # TaskAction result 回调捕获时的动作代次
        self._last_action_result = None  # 最近一次 TaskAction result {success, reason, detail}
        # 任务级失败标志（canonical §3.3）：primitive 失败即终止整个
        # prompt 序列并发 phase=fail 终态，后续 _load_next_prompt 不得
        # 再发 done
        self._task_sequence_failed = False
        # 远/稀疏目标 reacquire 挂表已迁入 VlaSkill（P3.4，技能自有
        # _reacquire_publish_time；技能 _dispatch_waypoint 经 on_action_published
        # 挂表，壳急停经 disarm_reacquire 解除）
        # return(TURN_WAYPOINT_NAV) topo 返航的完成判定状态已随 FlightSkill 迁出（P3.2）
        # 目标搜索与重规划状态
        self.bbox = [0, 0, 0, 0]  # 当前观察结果的bbox
        self.first_bbox = []  # 给定起始bbox
        self.if_plan = False  # 是否进入规划状态
        # see_none/if_landing/cur_yaw_search/cur_z_search/search_left_deg/
        # search_right_deg/if_left/yaw_search_views 已随 VLA 搜索会话迁入
        # VlaSkill（P3.4，技能自有 _ 前缀副本，reset_search_state 全量重置）
        self._partial_bbox_recenter_attempts = 0  # 当前 search prompt 已执行的 bbox 居中次数

        self.global_stop_active = False  # 全局停止是否激活
        self.task_generation = 0  # 任务代次，用于丢弃急停/覆盖前的旧推理结果
        self.telemetry = StructuredLogger(
            rospy.get_name(),
            rospy.get_param("~telemetry/level", "info"),
            rospy.get_param("~telemetry/stdout_en", True),
        )

        # 过程记录与动作日志
        self.previous_return_record_cursor = None
        # Frame_id of the AgentPrompt that OWNS the currently active task. Set
        # in _start_prompt_task; every task-phase event (incl. terminals) must
        # use it instead of latest_agent_prompt_frame_id so a late fail is
        # correlated to the ORIGINAL step_id/request_id, not to a later
        # prompt's frame (L4 cancel "急停" overwrites the latest frame).
        self._active_task_frame_id = "Null"
        self._task_result_stash = None  # 技能暂存的任务级结果（stash/pop_task_result 端口背后字段）
        # lx patch: log root is ~log_dir (default ~/.ros/log/dispatcher) because the
        # install location (devel space) is mounted read-only at runtime.
        log_root = Path(rospy.get_param("~log_dir", str(Path.home() / ".ros" / "log" / "dispatcher")))
        log_dir = log_root / "dispatcher"
        log_dir.mkdir(parents=True, exist_ok=True)
        session_tag = time.strftime("%Y%m%d_%H%M%S")
        self.log_session_tag = session_tag
        # Decision trace sink (replay/attribution source of truth): one
        # append-only JSONL per session under ~log_dir/trace.
        self.telemetry.attach_trace(
            log_dir / "trace" / f"trace_{session_tag}.jsonl",
            session_tag=session_tag,
        )
        self._telemetry(
            "info",
            "dispatcher_started",
            headless=bool(rospy.get_param("~headless", False)),
            log_dir=str(log_root),
        )

        # 设为 None 可关闭调试落盘；设为目录路径则开启保存并在下一轮前清理上一轮。
        self.thinking_debug_dir = log_root / "debug" / "thinking_multi"
        self.last_thinking_debug_dir = None
        if self.thinking_debug_dir is not None:
            self.thinking_debug_dir.mkdir(parents=True, exist_ok=True)
            rospy.loginfo(f"[Thinking-Debug] 已开启，目录: {self.thinking_debug_dir}")

        # ROS Subscriber（保留句柄避免被回收）
        self._active_tool_name = ""
        self.zenoh_middleware = None

        # P3.4 动作归属绑定（patch 20/21 note b 修复）：完成门/verdict 挂到
        # 「发布该动作的技能实例」上，而非 _active_tool_name 字符串解析
        self._current_plan_skill = None  # 本轮 DISPATCH 分发命中的技能
        self._action_owner_skill = None  # 进入 WAIT_ACTION_FINISH 时的技能快照
        # P3 技能注册表（本轮迁入为空表：vla/flight/scene_nav/grasp 技能族
        # 未随本轮迁移，_handle_plan_tool/_action_done/_handle_post_action/
        # WAIT_ACTION_FINISH 的注册表查找按原 None 守卫走通用回退路径；
        # 后续轮次技能迁入时在此注册表恢复注册）。
        self._skills: dict = {}

        ## 点云环境订阅
        self.headless = bool(rospy.get_param("~headless", False))  # headless模式: 不订阅任何传感器

        # ROS Publisher
        ## 指令控制发布
        self.emergency_stop_topic = (
            str(rospy.get_param("~emergency_stop_topic", "/command/emergency_stop")).strip()
            or "/command/emergency_stop"
        )
        self.emergency_stop_pub = rospy.Publisher(  # 急停发布器
            self.emergency_stop_topic, Empty, queue_size=10
        )

        self.if_handle_yaw_pub = rospy.Publisher(  # 底层 ego planner yaw 处理开关发布器
            "if_handle_yaw", Bool, queue_size=10
        )

        ## 监控状态发布
        self.command_content_pub = rospy.Publisher(  # 监控：命令内容
            "monitor/command_content", String, queue_size=10
        )
        self.task_phase_pub = rospy.Publisher(  # 任务生命周期（l4 桥消费）
            rospy.get_param("~task_phase_topic", "/agent_task_phase"),
            String,
            queue_size=10,
        )
        self._task_phase_progress = 0  # 当前 prompt 已完成的原始动作计数

    # 任务编排与命令解析模块函数
    ## 任务缓存同步
    def sync_task_buffers_from_prepare(self):
        """将 prepare_content 同步到执行期的任务缓存。"""
        # 防误配守卫：配置面（real.yaml prepare_content）可注入字符串等非法
        # 元素——流到 DISPATCH 解包时，2 字符字符串会被静默拆成单字符、其他长度
        # 直接 ValueError 进异常自愈循环。恢复旧代码对误配的「跳过」容忍：
        # 只保留合法 (prompt, SkillCommand) 元组，非法元素丢弃并点名索引与内容。
        valid_entries = []
        for index, entry in enumerate(self.prepare_content):
            if isinstance(entry, tuple) and len(entry) == 2:
                valid_entries.append(entry)
            else:
                rospy.logerr(
                    "[PREPARE] 丢弃非法 prepare_content[%d]（期望 (prompt, SkillCommand) 元组）: %r",
                    index,
                    entry,
                )
        self.prepare_content = valid_entries
        # prepare_content 元素为 (prompt, SkillCommand) 元组；
        # content/pre_prompt/prompt_bf 是纯文本派生缓存，取元组中的 prompt。
        self.content = [entry[0] for entry in self.prepare_content]
        self.pre_prompt = [entry[0] for entry in self.prepare_content]
        self.pre_prompt.append("Finish the mission")
        self.prompt_bf = self.pre_prompt.copy()

    # 发布模块函数

    ## 指令与任务状态发布
    def _telemetry(self, level: str, event: str, **fields) -> None:
        """Emit a slog-compatible dispatcher decision event."""
        self.telemetry.emit(level, event, **fields)

    def publish_command_content(self, command_content):
        """发布当前指令内容（保持字符串列表 schema，从队列元组中取 prompt）"""
        content_msg = String()
        prompts = [entry[0] for entry in command_content]
        content_msg.data = json.dumps(prompts, ensure_ascii=False)
        self.command_content_pub.publish(content_msg)

    def _set_dispatcher_state(self, new_state, *, reason: str = ""):
        """统一设置状态，并在切回 WAIT_FOR_MISSION 时记录调用位置。"""

        def _state_name(state_value):
            for attr_name, attr_value in vars(DISPATCHER_STATE).items():
                if attr_name.startswith("_"):
                    continue
                if attr_value == state_value:
                    return attr_name
            return str(state_value)

        old_state = self.dispatcher_state
        self.dispatcher_state = new_state
        state_name = _state_name(new_state)
        old_state_name = _state_name(old_state)
        if old_state != new_state:
            self._telemetry(
                "info",
                "dispatcher_state_transition",
                from_state=old_state_name,
                to_state=state_name,
                reason=reason,
                task_generation=self.task_generation,
                action_generation=self._action_generation,
                action_in_progress=self.action_in_progress,
            )
        if new_state != DISPATCHER_STATE.WAIT_FOR_MISSION:
            return
        # rospy.logwarn(
        #     "[DISPATCHER_STATE] %s -> %s at %s:%d reason=%s "
        #     "action_in_progress=%s action_finish=%s command_status=%s cmd_head=%r",
        #     old_state_name,
        #     state_name,
        #     filename,
        #     lineno,
        #     reason or "-",
        #     self.action_in_progress,
        #     self.action_finish,
        #     self.command_status,
        #     self.command_content[0] if self.command_content else None,
        # )

    @staticmethod
    def _fmt_wait_age(age) -> str:
        """健康年龄格式化：None = 从未收到（区别于慢）。"""
        return "never" if age is None else f"{age:.1f}s"

    def _decision_chain_wait_diag(self) -> str:
        """决策链输入通道的诊断串：channel=topic:age 逐路点名。

        未启用的可选通道不进入健康表，也不在此
        显示——缺席即关闭，区别于“在但死”。
        """
        try:
            health = self.get_sensor_input_health()
        except Exception:
            return "input_health_unavailable"
        return " ".join(
            f"{channel}={topic}:{self._fmt_wait_age(age)}" for channel, (topic, age) in health.items()
        )

    def _publish_task_phase(
        self,
        phase: str,
        *,
        progress: int | None = None,
        detail: str = "",
        message: str | None = None,
        result: dict | None = None,
        error: dict | None = None,
        status: str | None = None,
        frame_id: str | None = None,
    ) -> None:
        """发布任务生命周期事件（std_msgs/String JSON）到 /agent_task_phase。

        frame_id 缺省用 _active_task_frame_id（发起当前任务的 AgentPrompt 快照），
        保证终态关联到原始 step_id/request_id；直接通道（起降/返回/急停/抓取/
        chain_not_ready）同步响应当前 prompt，显式传 latest_agent_prompt_frame_id。
        """
        effective_frame = (
            frame_id
            if frame_id is not None
            else str(getattr(self, "_active_task_frame_id", "Null") or "Null")
        )
        payload = {
            "frame_id": effective_frame,
            "phase": phase,
            "progress": progress,
            "detail": detail,
        }
        if message is not None:
            payload["message"] = message
        if result is not None:
            payload["result"] = result
        if error is not None:
            payload["error"] = error
        if status is not None:
            payload["status"] = status
        try:
            if self.zenoh_middleware is not None:
                self.zenoh_middleware.on_tool_phase(payload)
            self.task_phase_pub.publish(String(data=json.dumps(payload, ensure_ascii=False)))
            self._telemetry(
                "info",
                "task_phase_published",
                phase=phase,
                frame_id=payload["frame_id"],
                detail=str(detail or ""),
            )
        except Exception:
            rospy.logwarn("[TASK_PHASE] publish failed phase=%s", phase)

    def _handle_get_pre_command(self) -> None:
        """处理 GET_PRE：从准备队列推进到执行队列。"""
        self._bump_task_generation("switch_prompt")
        # 每次 GET_PRE 重建当前执行队列（单条）
        self.command_content = []
        if not self.prepare_content:
            return

        prompt = self.pre_prompt.pop(0)
        # 记录当前位置作为 last_state（return 类命令经专用工具进入，不排队列）
        if self.frame is not None and self.frame.current_state is not None:
            self.last_state = self.frame.current_state.copy()
        else:
            self.last_state = None

        # 将下一条准备任务推进到 command_content（元素为 (prompt, SkillCommand) 元组）
        self.replan_content = self.prepare_content.pop(0)
        self.command_content.append(self.replan_content)
        rospy.loginfo(f"Current task: prompt={self.replan_content[0]}")
        self.publish_command_content(self.command_content)
        self.if_plan = True
        # time.sleep(0.5)
        self.command_status = COMMAND_STATUS.RUNNING

    def _load_next_prompt(self, *, delay_sec: float = 0.0) -> bool:
        """在节点内部推进到下一条 prompt。"""
        if delay_sec > 0.0:
            time.sleep(delay_sec)
        if not self.prepare_content:
            self.if_plan = False
            if not self._task_sequence_failed:
                pending = self.pop_task_result()
                self._publish_task_phase(
                    "done",
                    progress=self._task_phase_progress,
                    detail="prompt sequence finished",
                    result=dict(pending) if isinstance(pending, dict) else None,
                )
            # self._set_dispatcher_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason="load_next_prompt:prepare_empty")
            return False
        self._handle_get_pre_command()
        # self._set_dispatcher_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason="load_next_prompt:prepared_next")
        return True

    def _validate_active_tool(self, call: ToolCall) -> bool:
        """Reject DISPATCH work that did not originate from the registered runtime."""
        if self._active_tool_name:
            return True
        rospy.logwarn(
            "DISPATCH has no active registered tool, prompt=%r",
            str(call.display_text or call.name),
        )
        self._advance_to_next_prompt()
        return False

    def _set_if_handle_yaw(self, enabled: bool) -> None:
        """按任务类型切换底层 ego planner 的 yaw 处理逻辑。"""
        enabled = bool(enabled)
        if bool(getattr(self, "if_handle_yaw", True)) == enabled:
            return
        msg = Bool()
        msg.data = enabled
        self.if_handle_yaw_pub.publish(msg)
        self.if_handle_yaw = enabled
        rospy.loginfo("Publish if_handle_yaw=%s", "true" if enabled else "false")

    def _handle_plan_tool(self, cmd, skill_command: SkillCommand) -> bool:
        """Continue the active registered tool through its workflow adapter."""
        # P3.8：技能解析键直接取随 prompt 穿越队列的原生 ToolCall.name
        # （normalize_call 保证恒非空；原 SkillCommand.tool_name 字段已删除，
        # or 链仅为形式保留——_active_tool_name 兜底永不可达）
        tool_name = str(skill_command.call.name or self._active_tool_name or "")
        self._set_if_handle_yaw(True)
        # P3.4：本轮 DISPATCH 分发命中技能复位；命中注册表技能时记录实例，供
        # arm_action 快照为 _action_owner_skill（完成门/verdict 归属）
        self._current_plan_skill = None

        # P3 技能注册表分发：异步技能（flight.* → FlightSkill，P3.2；
        # scene.* → SceneNavSkill，P3.3；navigation.vla_reach → VlaSkill，
        # P3.4）经 plan_tick 推进；同步技能（graph.*）不入队，永不走到
        # 这里（synchronous 守卫）
        skill = self._skills.get(tool_name)
        if skill is not None and not skill.synchronous:
            self._current_plan_skill = skill
            return skill.plan_tick(skill_command)

        rospy.logwarn(
            "Unregistered active tool in DISPATCH: name=%r prompt=%r",
            tool_name,
            str(skill_command.call.display_text or skill_command.call.name),
        )
        self._advance_to_next_prompt()
        return True

    ## 全局状态控制
    def _bump_task_generation(self, reason: str = "") -> int:
        """推进任务代次，使阻塞推理返回的旧结果失效。"""
        self.task_generation = int(getattr(self, "task_generation", 0)) + 1
        rospy.loginfo(
            "Task generation advanced to %d (%s)",
            int(self.task_generation),
            reason or "unspecified",
        )
        return int(self.task_generation)

    def _enter_global_stop(
        self,
        reason: str = "",
        shutdown_program: bool = True,
        emit_soft_stop_log: bool = True,
        record_stop_event: bool = True,
        publish_hold: bool = True,
    ):
        """
        急停入口。
        - shutdown_program=True: 进入 STOP 状态并停机。
        - shutdown_program=False: 仅中断当前任务，回到 WAIT_FOR_MISSION。
        - emit_soft_stop_log: 软急停时是否打印日志。
        - publish_hold: 是否发布当前位置悬停目标（reset 场景必须为 False，
          否则 hold goal 会经 /mission/task 被 planner 执行，污染 reset）。
        """
        if shutdown_program and self.global_stop_active:
            return
        self._bump_task_generation(f"global_stop:{reason or 'requested'}")
        self.global_stop_active = bool(shutdown_program)
        if shutdown_program:
            rospy.logwarn(f"Global stop activated: {reason or 'requested'}")
        else:
            if emit_soft_stop_log:
                rospy.logwarn(
                    f"Emergency stop: cancel current mission and wait for new command ({reason or 'requested'})"
                )
        self.command_content = []
        self.prepare_content = []
        self.pre_prompt = []
        self.replan_content = None
        self.previous_return_record_cursor = None
        self.pending_action.clear()
        self.action_in_progress = False
        self.action_finish = False
        self.command_status = COMMAND_STATUS.ADVANCE_READY
        self.if_plan = False
        if publish_hold:
            self.emergency_stop_pub.publish(Empty())
        if shutdown_program:
            self.command_type = COMMAND_TYPE.STOP
            self.dispatcher_state = DISPATCHER_STATE.STOP
        else:
            self.command_type = COMMAND_TYPE.WAIT
            self._set_dispatcher_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason=f"global_stop:{reason}")

    def pop_task_result(self):
        """SkillHost 任务结果口：取走并清空暂存的任务级结果。"""
        result = self._task_result_stash
        self._task_result_stash = None
        return result

    def _action_done(self) -> bool:
        """基于触发信号与最小等待时间判断动作是否完成。"""
        # P3.2/P3.3 技能完成门：注册表技能的 action_done_gate 优先裁决（flight
        # return topo 返航与 scene map_search/smart_nav 的 FSM/JSON 判停已
        # 分别迁入 FlightSkill/SceneNavSkill）；None = 无门，走下方通用判定。
        # P3.4：技能实例优先取 _action_owner_skill（发布动作时的归属快照），
        # 字符串注册表解析仅作未绑定路径（壳内直发动作）的回退
        if self.action_in_progress:
            gate_skill = self._action_owner_skill
            if gate_skill is None:
                gate_skill = self._skills.get(str(self._active_tool_name or ""))
            if gate_skill is not None:
                gate_verdict = gate_skill.action_done_gate()
                if gate_verdict is not None:
                    return gate_verdict

        if not self.action_finish:
            return False
        # 拒绝旧代次的 action result（任务切换/新动作发布会增代）
        if self._action_finish_generation != self._action_generation:
            rospy.loginfo(
                "[ActionDone] reject stale action result (gen=%d != current=%d)",
                self._action_finish_generation,
                self._action_generation,
            )
            self._telemetry(
                "info",
                "task_action_result_ignored",
                reason="stale_generation",
                result_generation=self._action_finish_generation,
                action_generation=self._action_generation,
            )
            self.action_finish = False
            return False
        if time.time() - float(self.action_start_time) < float(self._min_action_wait):
            return False
        if self.waypoint is not None and self.frame is not None:
            try:
                cur = np.array(self.frame.current_state[:3], dtype=np.float64)
                tgt = np.array(self.waypoint[:3], dtype=np.float64)
                # if np.all(np.isfinite(cur)) and np.all(np.isfinite(tgt)):
                #     if np.linalg.norm(cur - tgt) > float(self.action_reach_threshold):
                #         return False
            except Exception:
                pass
        return True

    def _advance_to_next_prompt(self, *, pop_current: bool = True, delay_sec: float = 0.0) -> bool:
        """结束当前 prompt，并请求下一条任务。"""
        next_prompt = ""
        if len(self.prepare_content) > 1:
            # 队列元素为 (prompt, SkillCommand) 元组，日志只取 prompt 文本
            next_prompt = str(self.prepare_content[1][0] or "")
        self._telemetry(
            "info",
            "prompt_advanced",
            next_prompt=next_prompt,
            reason="advance_to_next_prompt",
        )
        if pop_current and self.command_content:
            self.command_content.pop(0)
        self.command_status = COMMAND_STATUS.ADVANCE_READY
        self._load_next_prompt(delay_sec=delay_sec)
        if self.command_status == COMMAND_STATUS.ADVANCE_READY:
            self.command_status = COMMAND_STATUS.MISSION_DONE
        return True

    def _reset_plan_cycle_if_needed(self) -> None:
        """在新一轮 prompt 规划前重置任务态。"""
        if self.command_status not in (
            COMMAND_STATUS.MISSION_DONE,
            COMMAND_STATUS.ADVANCE_READY,
        ):
            return
        self.command_status = COMMAND_STATUS.RUNNING

    def _handle_post_action(self) -> None:
        """POST_ACTION 技能 verdict 分发线（P3.4）：裁决权归技能，壳只机械执行。

        裁决来自「发布该动作的技能实例」（_action_owner_skill，与 _action_done
        完成门同一归属快照；未绑定的壳内直发路径回退注册表名解析）。四裁决的
        机械执行与原内联分支逐点对应：
        - REPLAN：清 replan 标记回 DISPATCH，围绕同一条 prompt 下一轮感知/规划；
        - ADVANCE：装下一条 prompt（队尽 done 由 _load_next_prompt 发）；
          与原壳一致本 tick 不切态，下一 tick 由技能再裁决（此时
          command_status 已非 ADVANCE_READY → IDLE）完成回 WAIT_FOR_MISSION；
        - IDLE：记 task_completed 回 WAIT_FOR_MISSION；
        - NEW_ACTION：技能已自行武装并发布新动作（landing 贴地腿经
          VlaSkill._dispatch_waypoint：arm_action + 立即发 goal），壳不动。
        """
        owner = self._action_owner_skill
        if owner is None:
            owner = self._skills.get(str(self._active_tool_name or ""))
        if owner is not None:
            verdict = owner.on_action_result(self._last_action_result)
        elif self.command_status == COMMAND_STATUS.ADVANCE_READY:
            verdict = SkillVerdict.ADVANCE
        else:
            verdict = SkillVerdict.IDLE

        if verdict is SkillVerdict.REPLAN:
            self.pending_action.replan_cmd = None
            self.pending_action.replan_reason = None
            self.dispatcher_state = DISPATCHER_STATE.DISPATCH
            self.if_plan = True
            return

        if verdict is SkillVerdict.NEW_ACTION:
            return

        if verdict is SkillVerdict.ADVANCE:
            self._load_next_prompt()
            if self.command_status == COMMAND_STATUS.ADVANCE_READY:
                self.command_status = COMMAND_STATUS.MISSION_DONE
            return

        self._set_dispatcher_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason="post_action:no_advance_ready")

    # 主状态机模块函数
    ## 推理与执行主循环
    # 通过ros1通信，将需要检测的RGB图像和标签发布到ros。检测节点接收到RGB图像和标签，执行检测任务，并通过ros1通信返回是否检测到目标与bbox。
    def _run_inference_loop(self):
        """
        主状态机循环（FSM）完整说明。

        全局前置跳转（每轮循环最先检查）：
        1) 任意状态 --(command_type==STOP 且当前非 STOP)--> STOP
           通过 _enter_global_stop("stop") 触发。

        各状态转移关系：

        INIT:
        - INIT --(frame 和 cloud_xyz 就绪)--> WAIT_FOR_MISSION
        - INIT --(未就绪)--> INIT（等待并重试）

        WAIT_FOR_MISSION:
        - WAIT_FOR_MISSION --(if_plan=True 且 action_in_progress=False)--> DISPATCH
        - WAIT_FOR_MISSION --(否则)--> WAIT_FOR_MISSION

        DISPATCH:
        - DISPATCH --(action_in_progress=True)--> WAIT_ACTION_FINISH
        - DISPATCH --(self.frame is None)--> INIT
        - DISPATCH --(command_content 为空)--> WAIT_FOR_MISSION
        - DISPATCH --(技能武装动作)--> WAIT_ACTION_FINISH
          航点类技能经自身 dispatch 编排调用 arm_action（通用记账+切态）
          与 publish 传输口发 goal；非航点技能只 arm_action。壳不做发布编排。
        - DISPATCH --(部分文本流程需要取下一条任务)--> WAIT_FOR_MISSION
          例如：搜索耗尽、连续未见目标超过阈值、生成航点失败、近距离到达等。
          这些分支会在节点内部直接装载下一条 prompt。
        - DISPATCH --(命令不匹配任何处理分支)--> WAIT_FOR_MISSION

        WAIT_ACTION_FINISH:
        - WAIT_ACTION_FINISH --(_action_done()==True)--> POST_ACTION
        - WAIT_ACTION_FINISH --(否则)--> WAIT_ACTION_FINISH

        POST_ACTION:
        - POST_ACTION --(verdict==REPLAN)--> DISPATCH
          （清理 replan 标记并置 if_plan=True）
        - POST_ACTION --(verdict==ADVANCE)--> WAIT_FOR_MISSION
          （在节点内部装载下一条 prompt，随后将 command_status 置为 MISSION_DONE）
        - POST_ACTION --(verdict==IDLE)--> WAIT_FOR_MISSION
        - POST_ACTION --(verdict==NEW_ACTION)--> WAIT_ACTION_FINISH
          （技能已自行武装并发布新动作，arm_action 已切态）

        默认分支：
        - 若状态枚举异常或未覆盖，短暂 sleep 后继续下一轮，避免 CPU 忙等。
        """
        # 主循环固定 20Hz，真正的等待节奏由各状态内部按需 sleep 控制。
        rate = rospy.Rate(20)
        self.dispatcher_state = DISPATCHER_STATE.INIT
        self.last_plan_time = None
        rospy.loginfo("Waiting for sensor readiness...")

        # 节点刚启动时，先等到第一帧同步数据到达。
        # 这里不直接进入 INIT 分支，是为了避免 first_image 在空 frame 上取值。
        # 等待期间以 dispatcher_wait_cloud 节流信号点名死通道（issue #90）——
        # 曾经这里整场静默，fluent-bit 流里看不到任何等待原因。
        if not self.headless:
            while not rospy.is_shutdown() and self.get_frame_snapshot() is None:
                rospy.logwarn_throttle(
                    2.0,
                    "dispatcher_wait_cloud context=first_frame %s",
                    self._decision_chain_wait_diag(),
                )
                time.sleep(1)
            self.frame = self.get_frame_snapshot()
            # first_image 保存任务开始时的初始观察，可供某些 VLM 流程做首帧对比。
            self.first_image = self.frame.rgb_image if self.frame is not None else None
        else:
            self.frame = None
            self.first_image = None
        rospy.loginfo("Mission start")

        while not rospy.is_shutdown():
            # STOP 具有最高优先级，任何状态下都允许抢占当前流程。
            if self.command_type == COMMAND_TYPE.STOP and self.dispatcher_state != DISPATCHER_STATE.STOP:
                self._enter_global_stop("stop")

            # 每轮都刷新最新 frame，后续所有状态统一使用 self.frame。
            if not self.headless:
                self.frame = self.get_frame_snapshot()

            # [py38] match -> if/elif chain (ported by py38_match_port)
            # INIT:
            # 等待基础感知数据准备完成。只有在 frame 和点云/深度关键数据齐备时，
            # 才允许进入后续任务调度阶段。
            if self.dispatcher_state == DISPATCHER_STATE.INIT:
                # headless headless 模式: 无需等待传感器数据, 直接进入任务调度
                if self.headless:
                    print("Initialization complete (headless mode)")
                    self._set_dispatcher_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason="init:headless")
                    continue
                frame = self.get_frame_snapshot()
                if frame is not None and frame.cloud_xyz is not None:
                    print("Initialization complete")
                    self.emergency_stop_pub.publish(Empty())
                    self._set_dispatcher_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason="init:ready")
                else:
                    # INIT 等待的可观测信号（issue #90）：与 mission 侧
                    # fsm_wait_* 家族对齐的节流 warn，2s 一条点名死通道。
                    rospy.logwarn_throttle(
                        2.0,
                        "dispatcher_wait_cloud context=init_cloud %s",
                        self._decision_chain_wait_diag(),
                    )
                    rate.sleep()
                    continue

                # WAIT_FOR_MISSION:
                # 空闲态，只看两个信号：
                # 1. 外部是否已经把 if_plan 置真；
                # 2. 当前是否仍有动作在执行。
                # 满足“需要规划且没有在飞”的条件时，再切入 DISPATCH。
            elif self.dispatcher_state == DISPATCHER_STATE.WAIT_FOR_MISSION:
                if self.if_plan and not self.action_in_progress:
                    self.dispatcher_state = DISPATCHER_STATE.DISPATCH
                    self.if_plan = False
                time.sleep(0.1)
                continue

                # DISPATCH:
                # 状态机的核心调度态。这里不直接堆放所有细节，而是做三层分发：
                # 1. 前置保护：动作未结束、frame 丢失、命令为空。
                # 2. 新一轮 prompt 的 reset 与解析。
                # 3. 具体命令分发到 special/text 两条处理链。
            elif self.dispatcher_state == DISPATCHER_STATE.DISPATCH:
                # 如果上一个动作还没真正结束，就不要在 DISPATCH 中重复做新规划。
                if self.action_in_progress:
                    self.dispatcher_state = DISPATCHER_STATE.WAIT_ACTION_FINISH
                    continue
                # 运行时如果 frame 丢失，退回 INIT，等待底层感知恢复。
                # headless headless 模式下不检查 frame
                if not self.headless and self.frame is None:
                    self.dispatcher_state = DISPATCHER_STATE.INIT
                    continue
                # 没有待执行命令时，回到空闲态。
                if not self.command_content:
                    self._set_dispatcher_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason="plan:command_content_empty")
                    time.sleep(0.1)
                    continue

                # 若上一条 prompt 已结束，则对当前 prompt 做一次规划上下文重置。
                self._reset_plan_cycle_if_needed()
                # 队列元素为 (prompt, SkillCommand) 元组：结构化命令随 prompt
                # 一起入队，DISPATCH 直接取用，不再需要 stash/文本匹配兜底。
                cmd, skill_command = self.command_content[0]
                # P3.8：SkillCommand 直接携带原生 ToolCall，telemetry 各字段
                # 从 call 原生字段派生（kind←call.name；nav_mode 已无适配层
                # 预派生，vla 场景由 skill 内部现算，此处恒空串保留键——
                # slog 事件名与键集不变原则，字段值变化可接受）
                call = skill_command.call
                self._telemetry(
                    "info",
                    "prompt_parsed",
                    prompt=cmd,
                    kind=str(call.name),
                    name=str(call.display_text or ""),
                    object_name=str(call.arguments.get("object", "")),
                    nav_mode="",
                )

                # （原「全局控制命令预检」调用点已删除：急停在
                # forward_emergency_stop_tool 直发路径处理，kind 守卫与
                # DISPATCH 队列内容恒不重叠，属死检查——见 P3.8 迁移注记）
                if not self._validate_active_tool(call):
                    continue

                # origin 只在首次收到任务时记录一次，后续 return to origin 依赖此记录。

                # 经技能注册表分发到命中的技能。
                if self._handle_plan_tool(cmd, skill_command):
                    continue

                # 未命中任何分支时，不强行报错，先回到 WAIT_FOR_MISSION，
                # 让外部有机会刷新任务或注入新 prompt。
                self._set_dispatcher_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason="plan:unhandled_prompt")

                # WAIT_ACTION_FINISH:
                # 已经把动作发出去了，现在只关心规划器/飞控是否完成。
            elif self.dispatcher_state == DISPATCHER_STATE.WAIT_ACTION_FINISH:
                # P3.4：等待期技能钩（VLA reacquire 到期重启搜索等，已迁入
                # VlaSkill.wait_action_tick）在完成门判定之前每 tick 调用；
                # 技能切态（如回 WAIT_FOR_MISSION）则本轮不再判停
                wait_skill = self._action_owner_skill
                if wait_skill is None:
                    wait_skill = self._skills.get(str(self._active_tool_name or ""))
                if wait_skill is not None:
                    wait_skill.wait_action_tick()
                    if self.dispatcher_state != DISPATCHER_STATE.WAIT_ACTION_FINISH:
                        continue
                if self._action_done():
                    # 一旦确认执行完成，就清理动作执行态，
                    # 把后续决策统一交给 POST_ACTION。
                    self.action_in_progress = False
                    self.action_finish = False
                    self.dispatcher_state = DISPATCHER_STATE.POST_ACTION
                    continue
                time.sleep(0.05)
                continue

                # POST_ACTION:
                # 收敛动作完成后的后处理，包括：
                # - 临时动作后的 replan
                # - prompt 结束后的内部下一条任务装载
                # - landing 的贴地补动作
            elif self.dispatcher_state == DISPATCHER_STATE.POST_ACTION:
                # P3.4：_handle_post_action 为技能 verdict 分发线——裁决权归
                # 「发布该动作的技能实例」，壳只机械执行 REPLAN / ADVANCE /
                # IDLE / NEW_ACTION 四裁决（landing 贴地腿走 NEW_ACTION）。
                self._handle_post_action()
                continue

                # STOP 直接结束节点。
            elif self.dispatcher_state == DISPATCHER_STATE.STOP:
                rospy.signal_shutdown("Stopped by command")
                break

                # 未知状态：仅短暂休眠，下一轮继续。
            else:
                time.sleep(0.05)

            rate.sleep()

    def _recover_inference_after_exception(self, exc: BaseException) -> None:
        """推理线程异常兜底：把 FSM 复位到空闲态，保证后续任务可被唤醒。

        @param[in] exc  未捕获的异常对象
        @return None
        """
        try:
            self.dispatcher_state = DISPATCHER_STATE.WAIT_FOR_MISSION
            self.if_plan = False
            self.action_in_progress = False
            self.action_finish = False
            self.command_status = COMMAND_STATUS.RUNNING
            self.command_content.clear()
            self.prepare_content.clear()
            self.pending_action.clear()
            self._telemetry("error", "inference_thread_recovered", detail=str(exc))
        except Exception:  # noqa: BLE001
            pass

    def run_inference(self) -> None:
        """推理线程守护包装：任何未捕获异常都不允许杀死 FSM 主循环。

        _run_inference_loop 内任一 handler 抛异常都会让整条任务调度链静默
        瘫痪（prompt_parsed/map_search 消失、结果不返回 l4）。这里记录错误、
        复位到 WAIT_FOR_MISSION 后重启循环，保证 FSM 永远可被新任务唤醒。
        """
        while not rospy.is_shutdown():
            try:
                self._run_inference_loop()
                return
            except Exception as exc:  # noqa: BLE001
                self._recover_inference_after_exception(exc)
                rospy.logerr(
                    "[INFERENCE] run_inference crashed (recovering after 1s): %s",
                    exc,
                )
                time.sleep(1.0)


def create_dispatcher_engine(config_path: str):
    """Build and configure the task-0 engine without starting process lifecycle."""
    cfg = load_yaml(config_path)

    variant = str(cfg.get("variant", "real")).strip().lower()
    ros_params = {}
    ros_params.update(merge_config_sections(cfg, ["ros.topics", "ros.sync", "ros.publishers", "ros.camera"]))
    ros_params.update(merge_pointcloud_mode_params(get_nested_config(cfg, "ros.pointcloud")))
    ros_params.update(flatten_leaf_params(get_nested_config(cfg, "policy.mission")))
    ros_params["variant"] = variant

    if ros_params:
        set_ros_params(ros_params)

    node = DispatcherEngine()
    apply_config(
        node,
        merge_config_sections(cfg, ["base_policy", "policy.base"]),
        section_name="base_policy",
        key_aliases=CONFIG_KEY_ALIASES,
    )
    apply_config(
        node,
        merge_config_sections(
            cfg,
            [
                "uav_policy",
                "policy.mission",
                "policy.motion",
                "policy.safety",
                "policy.search",
                "policy.planner",
                "policy.scene_nav",
                "policy.overdepth",
            ],
        ),
        section_name="uav_policy",
        key_aliases=CONFIG_KEY_ALIASES,
    )
    node.sync_task_buffers_from_prepare()
    return node


def start_dispatcher_workers(node):
    """Start task-0 workflow workers and return the non-daemon inference thread."""
    inference_thread = threading.Thread(target=node.run_inference)
    inference_thread.start()
    return inference_thread
