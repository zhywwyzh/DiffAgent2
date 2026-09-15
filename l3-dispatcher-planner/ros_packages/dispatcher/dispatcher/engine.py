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
from pathlib import Path
from dataclasses import dataclass
from typing import Any

import numpy as np

from dispatcher.utils.state import COMMAND_TYPE, COMMAND_STATUS, DISPATCHER_STATE
from dispatcher.utils.config import UAV_POLICY_DEFAULTS, set_defaults
from dispatcher.tools.skill_api import SkillVerdict
from dispatcher.core.ports import CoreChannels, RuntimeClock, LogSink
from dispatcher.core.telemetry import RunTelemetry
from dispatcher.core.task_phase import TaskPhaseBridge
from dispatcher.core.skill_router import SkillRouter
from dispatcher.core.workflow import ToolWorkflowHost
from dispatcher.core.actuators import PlannerActuators

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

    def __init__(
        self,
        *,
        headless: bool,
        telemetry_node_name: str,
        telemetry_level: str,
        telemetry_stdout_en: bool,
        log_dir_root: Path,
        channels: CoreChannels,
        clock: RuntimeClock,
        log: LogSink,
    ):
        """初始化节点状态、协作对象与后台线程。

        ROS 面（四类 core 通道、节律关停、运行日志）经端口注入（S3 §4.7）：
        实现由 composition root（dispatcher_node.py）构造并传入，engine 与
        core 只持端口引用，自身零 rospy（G7/G8）。
        """
        super().__init__()

        # 端口注入（engine 属性命名见 S3 §4.4）
        self.channels = channels  # 四类 core 通道出站端口（急停/yaw/监控/相位）
        self.clock = clock  # 节律与关停端口（rate/is_shutdown/request_shutdown）
        self.runlog = log  # 运行日志端口（info/warn/err/warn_throttle）

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
        # 运行遥测（S3 §2.4/§5 迁入 core/telemetry.py）：slog/trace/监控/等待
        # 诊断；构造期覆盖开头的 runlog 端口占位（绑定同一 LogSink）。
        self.runlog = RunTelemetry(
            node_name=telemetry_node_name,
            level=telemetry_level,
            stdout_en=telemetry_stdout_en,
            log_root=log_dir_root,
            headless=headless,
            log=log,
            channels=channels,
        )

        # 过程记录与动作日志
        self.previous_return_record_cursor = None
        # 任务相位桥（S3 §2.5/§5 迁入 core/task_phase.py）：_active_task_frame_id
        # 与 _task_phase_progress 字段随桥持有（原注释见该文件）。
        self.task_phase = TaskPhaseBridge(channels=channels, runlog=self.runlog)

        # 技能注册表（S3 §2.6/§5 迁入 core/skill_router.py）：查表/分发/
        # 归属快照/结果暂存；_active_tool_name 读值经回调（指向 workflow
        # 宿主的同名字段，lambda 延迟求值）。
        self.skills = SkillRouter(active_tool_name=lambda: self.tools._active_tool_name)

        # 工具执行缝宿主（S3 §2.7/§5 迁入 core/workflow.py）：3 缝 + 6 字段；
        # 全局停止与任务代次经回调注入（workflow 不回引 engine）。
        self.tools = ToolWorkflowHost(
            runlog=self.runlog,
            task_phase=self.task_phase,
            skills=self.skills,
            enter_global_stop=self._enter_global_stop,
            task_generation=lambda: self.task_generation,
        )

        # planner 动作面（S3 §2.8/§5 迁入 core/actuators.py）：yaw 模式切换；
        # 守卫初值取 engine 配置快照（set_defaults 已装 if_handle_yaw）。
        self.actuators = PlannerActuators(
            channels=channels,
            runlog=self.runlog,
            if_handle_yaw=bool(getattr(self, "if_handle_yaw", True)),
        )

        ## 点云环境订阅
        self.headless = bool(headless)  # headless模式: 不订阅任何传感器（值经注入，S3 §4.7）

        # 四类 core 通道发布器已迁 dispatcher/ros_adapter/core_channels_ros.py
        # （S3 §4.6，端口化，禁止二次搬迁）；engine 只持 self.channels 引用；
        # _task_phase_progress 死字段随任务相位桥持有（core/task_phase.py）。

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
                self.runlog.err(
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
            self.runlog.emit(
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
        self.runlog.info(f"Current task: prompt={self.replan_content[0]}")
        self.runlog.publish_command_content(self.command_content)
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
                pending = self.skills.pop_task_result()
                self.task_phase.publish(
                    "done",
                    progress=self.task_phase._task_phase_progress,
                    detail="prompt sequence finished",
                    result=dict(pending) if isinstance(pending, dict) else None,
                )
            # self._set_dispatcher_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason="load_next_prompt:prepare_empty")
            return False
        self._handle_get_pre_command()
        # self._set_dispatcher_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason="load_next_prompt:prepared_next")
        return True

    ## 全局状态控制
    def _bump_task_generation(self, reason: str = "") -> int:
        """推进任务代次，使阻塞推理返回的旧结果失效。"""
        self.task_generation = int(getattr(self, "task_generation", 0)) + 1
        self.runlog.info(
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
            self.runlog.warn(f"Global stop activated: {reason or 'requested'}")
        else:
            if emit_soft_stop_log:
                self.runlog.warn(
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
            self.channels.publish_emergency_stop()
        if shutdown_program:
            self.command_type = COMMAND_TYPE.STOP
            self.dispatcher_state = DISPATCHER_STATE.STOP
        else:
            self.command_type = COMMAND_TYPE.WAIT
            self._set_dispatcher_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason=f"global_stop:{reason}")

    def _action_done(self) -> bool:
        """基于触发信号与最小等待时间判断动作是否完成。"""
        # P3.2/P3.3 技能完成门：注册表技能的 action_done_gate 优先裁决（flight
        # return topo 返航与 scene map_search/smart_nav 的 FSM/JSON 判停已
        # 分别迁入 FlightSkill/SceneNavSkill）；None = 无门，走下方通用判定。
        # P3.4：技能实例优先取 _action_owner_skill（发布动作时的归属快照），
        # 字符串注册表解析仅作未绑定路径（壳内直发动作）的回退
        # （S3 起查表委托 self.skills.owner_skill）
        if self.action_in_progress:
            gate_skill = self.skills.owner_skill()
            if gate_skill is not None:
                gate_verdict = gate_skill.action_done_gate()
                if gate_verdict is not None:
                    return gate_verdict

        if not self.action_finish:
            return False
        # 拒绝旧代次的 action result（任务切换/新动作发布会增代）
        if self._action_finish_generation != self._action_generation:
            self.runlog.info(
                "[ActionDone] reject stale action result (gen=%d != current=%d)",
                self._action_finish_generation,
                self._action_generation,
            )
            self.runlog.emit(
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
        self.runlog.emit(
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
        owner = self.skills.owner_skill()
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

    def _fail_unregistered_dispatch(self, *, tool_name: str, frame_id: str) -> None:
        """分发未命中已注册技能：上报 fail 并停在 WAIT_FOR_MISSION。

        B5：不得排空队列后回报完成——本方法不 pop command_content、不清
        prepare_content、不调用 _advance_to_next_prompt；
        O3：fail 载荷携带未命中的工具名（detail 与 error.message）。
        """
        self.task_phase.publish(
            "fail",
            detail=f"tool not registered: {tool_name}",
            error={
                "code": "tool_not_registered",
                "message": f"tool not registered: {tool_name}",
            },
            frame_id=str(frame_id or "Null"),
        )
        self._task_sequence_failed = True
        self.if_plan = False
        self._set_dispatcher_state(
            DISPATCHER_STATE.WAIT_FOR_MISSION,
            reason="plan:tool_not_registered",
        )

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
        rate = self.clock.rate(20)
        self.dispatcher_state = DISPATCHER_STATE.INIT
        self.last_plan_time = None
        self.runlog.info("Waiting for sensor readiness...")

        # 节点刚启动时，先等到第一帧同步数据到达。
        # 这里不直接进入 INIT 分支，是为了避免 first_image 在空 frame 上取值。
        # 等待期间以 dispatcher_wait_cloud 节流信号点名死通道（issue #90）——
        # 曾经这里整场静默，fluent-bit 流里看不到任何等待原因。
        if not self.headless:
            while not self.clock.is_shutdown() and self.get_frame_snapshot() is None:
                # 等待诊断（S3 §5）：health 由外部取值并兜底异常（与迁移前
                # _decision_chain_wait_diag 的 try/except 语义一致），串组装
                # 在 RunTelemetry.wait_diag。
                try:
                    wait_diag = self.runlog.wait_diag(self.get_sensor_input_health())
                except Exception:
                    wait_diag = "input_health_unavailable"
                self.runlog.warn_throttle(
                    2.0,
                    "dispatcher_wait_cloud context=first_frame %s",
                    wait_diag,
                )
                time.sleep(1)
            self.frame = self.get_frame_snapshot()
            # first_image 保存任务开始时的初始观察，可供某些 VLM 流程做首帧对比。
            self.first_image = self.frame.rgb_image if self.frame is not None else None
        else:
            self.frame = None
            self.first_image = None
        self.runlog.info("Mission start")

        while not self.clock.is_shutdown():
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
                    self.channels.publish_emergency_stop()
                    self._set_dispatcher_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason="init:ready")
                else:
                    # INIT 等待的可观测信号（issue #90）：与 mission 侧
                    # fsm_wait_* 家族对齐的节流 warn，2s 一条点名死通道。
                    # （等待诊断取值兜底同 first_frame 处，S3 §5）
                    try:
                        wait_diag = self.runlog.wait_diag(self.get_sensor_input_health())
                    except Exception:
                        wait_diag = "input_health_unavailable"
                    self.runlog.warn_throttle(
                        2.0,
                        "dispatcher_wait_cloud context=init_cloud %s",
                        wait_diag,
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
                self.runlog.emit(
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
                if not self.skills.validate_active_tool(call):
                    # 未命中已注册运行时：fail 上报并停在 WAIT_FOR_MISSION
                    # （B5/O3；S6 §4.2 写法 B，router 只判定不推进）。
                    self.runlog.warn(
                        "DISPATCH has no active registered tool, prompt=%r",
                        str(call.display_text or call.name),
                    )
                    self._fail_unregistered_dispatch(
                        tool_name=str(call.name or call.display_text or ""),
                        frame_id=call.frame_id,
                    )
                    continue

                # origin 只在首次收到任务时记录一次，后续 return to origin 依赖此记录。

                # 经技能注册表分发到命中的技能（yaw 模式切换随原
                # _handle_plan_tool 首步动作面，S3 §5 明示改写点：经
                # actuators 发布）。
                self.actuators.set_if_handle_yaw(True)
                if not self.skills.dispatch_plan(cmd, skill_command):
                    # 未注册回退（S3 §4.10：dispatch_plan False=未命中，
                    # 不自行推进、不发任何相位）：fail 上报并停在
                    # WAIT_FOR_MISSION（B5/O3，S6 §4.2 写法 B）。
                    self.runlog.warn(
                        "Unregistered active tool in DISPATCH: name=%r prompt=%r",
                        str(skill_command.call.name or self.skills.active_tool_name() or ""),
                        str(skill_command.call.display_text or skill_command.call.name),
                    )
                    self._fail_unregistered_dispatch(
                        tool_name=str(skill_command.call.name or ""),
                        frame_id=skill_command.call.frame_id,
                    )
                # §4.10 冻结接口：True=已处理（原 _handle_plan_tool 返回 True
                # 的 continue 语义），进入下一轮。
                continue

                # WAIT_ACTION_FINISH:
                # 已经把动作发出去了，现在只关心规划器/飞控是否完成。
            elif self.dispatcher_state == DISPATCHER_STATE.WAIT_ACTION_FINISH:
                # P3.4：等待期技能钩（VLA reacquire 到期重启搜索等，已迁入
                # VlaSkill.wait_action_tick）在完成门判定之前每 tick 调用；
                # 技能切态（如回 WAIT_FOR_MISSION）则本轮不再判停
                wait_skill = self.skills.owner_skill()
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
                self.clock.request_shutdown("Stopped by command")
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
            self.runlog.emit("error", "inference_thread_recovered", detail=str(exc))
        except Exception:  # noqa: BLE001
            pass

    def run_inference(self) -> None:
        """推理线程守护包装：任何未捕获异常都不允许杀死 FSM 主循环。

        _run_inference_loop 内任一 handler 抛异常都会让整条任务调度链静默
        瘫痪（prompt_parsed/map_search 消失、结果不返回 l4）。这里记录错误、
        复位到 WAIT_FOR_MISSION 后重启循环，保证 FSM 永远可被新任务唤醒。
        """
        while not self.clock.is_shutdown():
            try:
                self._run_inference_loop()
                return
            except Exception as exc:  # noqa: BLE001
                self._recover_inference_after_exception(exc)
                self.runlog.err(
                    "[INFERENCE] run_inference crashed (recovering after 1s): %s",
                    exc,
                )
                time.sleep(1.0)
