"""任务分发核心：任务队列、六态 FSM、技能裁决与全局停止。"""

from __future__ import annotations

import time
import threading
from pathlib import Path
from typing import Any, Callable

from dispatcher.support.state import COMMAND_TYPE, COMMAND_STATUS, DISPATCHER_STATE
from dispatcher.support.config import UAV_POLICY_DEFAULTS, set_defaults
from dispatcher.core.ports import CoreChannels, RuntimeClock, LogSink
from dispatcher.core.telemetry import RunTelemetry
from dispatcher.core.task_phase import TaskPhaseBridge
from dispatcher.core.skill_router import SkillRouter
from dispatcher.core.tool_workflow import ToolWorkflowHost
from dispatcher.core.actuators import PlannerActuators
from dispatcher.core.prompt_queue import PromptQueue
from dispatcher.core.state_ledger import StateLedger
from dispatcher.core.action_gate import ActionGate


class DispatcherEngine:
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
        get_frame_snapshot: Callable[[], Any],
        get_sensor_input_health: Callable[[], dict],
    ):
        """装配核心协作对象；输入读取与四类出站通道均由外部注入。"""
        self.operation_lock = threading.RLock()
        self.channels = channels
        self.clock = clock
        self.get_frame_snapshot = get_frame_snapshot
        self.get_sensor_input_health = get_sensor_input_health
        set_defaults(self, UAV_POLICY_DEFAULTS)
        self.headless = bool(headless)
        self.dispatcher_state = None
        self.if_plan = False
        self.global_stop_active = False
        self.frame = None
        self.action_in_progress = False
        self.action_finish = False
        self.action_start_time = 0.0
        self.waypoint = None
        self.last_published_waypoint = None
        self.runlog = RunTelemetry(
            node_name=telemetry_node_name, level=telemetry_level,
            stdout_en=telemetry_stdout_en, log_root=log_dir_root,
            headless=headless, log=log, channels=channels,
        )
        self.task_phase = TaskPhaseBridge(channels=channels, runlog=self.runlog)
        self.skills = SkillRouter(active_tool_name=lambda: self.tools._active_tool_name)
        self.ledger = StateLedger(
            runlog=self.runlog,
            host_state_get=lambda: self.dispatcher_state,
            host_state_set=lambda value: setattr(self, "dispatcher_state", value),
            action_snapshot=lambda: {
                "action_generation": self.action_gate._action_generation,
                "action_in_progress": self.action_in_progress,
            },
        )
        self.prompt_queue = PromptQueue(
            runlog=self.runlog, task_phase=self.task_phase, skills=self.skills,
            ledger=self.ledger,
            if_plan_set=lambda value: setattr(self, "if_plan", value),
            last_state_set=lambda value: setattr(self.ledger, "last_state", value),
            frame_state_get=lambda: self.frame.current_state if self.frame is not None else None,
        )
        self.action_gate = ActionGate(
            runlog=self.runlog, skills=self.skills, ledger=self.ledger, queue=self.prompt_queue,
            if_plan_set=lambda value: setattr(self, "if_plan", value),
            action_progress_get=lambda: self.action_in_progress,
            action_progress_set=lambda value: setattr(self, "action_in_progress", value),
            action_finish_get=lambda: self.action_finish,
            action_finish_set=lambda value: setattr(self, "action_finish", value),
            action_start_time_get=lambda: self.action_start_time,
            min_action_wait_get=lambda: self._min_action_wait,
        )
        self.tools = ToolWorkflowHost(
            runlog=self.runlog, task_phase=self.task_phase, skills=self.skills,
            operation_lock=self.operation_lock,
            enter_global_stop=self._enter_global_stop,
            task_generation=lambda: self.ledger.task_generation,
            queue=self.prompt_queue, ledger=self.ledger,
            input_ready=lambda: self.get_frame_snapshot() is not None and all(
                age is not None and age <= self.inference_timeout
                for topic, age in self.get_sensor_input_health().values()
            ),
        )
        self.actuators = PlannerActuators(
            channels=channels, runlog=self.runlog,
            if_handle_yaw=bool(getattr(self, "if_handle_yaw", True)),
        )
        self.prompt_queue.sync_task_buffers_from_prepare(self.prepare_content)

    def _enter_global_stop(
        self,
        reason: str = "",
        *,
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
        - record_stop_event: 保留的停止记录开关，记录服务尚未接入，当前不生效。
        - publish_hold: 急停悬停开关；当前仅发布急停信号，额外悬停目标
          下发尚未接入。覆盖和取消传 False，避免引入运动副作用。
        保留项与接入时机见 doc/l3-dispatcher-planner/rest/dispatcher-deferred-dependencies.md。
        """
        with self.operation_lock:
            if shutdown_program and self.global_stop_active:
                return
            self.ledger.bump_task_generation(f"global_stop:{reason or 'requested'}")
            self.global_stop_active = bool(shutdown_program)
            if shutdown_program:
                self.runlog.warn(f"Global stop activated: {reason or 'requested'}")
            else:
                if emit_soft_stop_log:
                    self.runlog.warn(
                        f"Emergency stop: cancel current mission and wait for new command ({reason or 'requested'})"
                    )
            owner = self.skills.owner_skill()
            if owner is not None:
                owner.on_global_stop()
            self.prompt_queue.clear_all()
            self.action_gate.clear_action_state()
            self.ledger.command_status = COMMAND_STATUS.ADVANCE_READY
            self.if_plan = False
            if publish_hold:
                self.channels.publish_emergency_stop()
            if shutdown_program:
                self.ledger.command_type = COMMAND_TYPE.STOP
                self.ledger.set_state(DISPATCHER_STATE.STOP, reason=f"global_stop:{reason}")
            else:
                self.ledger.command_type = COMMAND_TYPE.WAIT
                self.ledger.set_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason=f"global_stop:{reason}")

    def _fail_unregistered_dispatch(self, *, tool_name: str, frame_id: str) -> None:
        """分发未命中已注册技能：上报 fail 并停在 WAIT_FOR_MISSION。

        B5：失败保留队列供诊断，不通过推进队列冒充完成；
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
        self.ledger.fail_sequence()
        self.if_plan = False
        self.ledger.set_state(
            DISPATCHER_STATE.WAIT_FOR_MISSION,
            reason="plan:tool_not_registered",
        )

    def _sleep_unlocked(self, sleep, *args):
        """等待让出生命周期锁，准入/取消不会被 FSM 的节拍阻塞。"""
        self.operation_lock.release()
        try:
            sleep(*args)
        finally:
            self.operation_lock.acquire()

    def _run_inference_loop(self):
        """运行六态 FSM，按调用名分发并机械执行技能裁决。"""
        rate = self.clock.rate(20)
        with self.operation_lock:
            if self.dispatcher_state != DISPATCHER_STATE.STOP:
                self.ledger.set_state(DISPATCHER_STATE.INIT, reason="inference:start")
        self.runlog.info("Waiting for sensor readiness...")

        self.frame = None if self.headless else self.get_frame_snapshot()
        self.runlog.info("Mission start")

        while not self.clock.is_shutdown():
            with self.operation_lock:
                if self.ledger.command_type == COMMAND_TYPE.STOP and self.dispatcher_state != DISPATCHER_STATE.STOP:
                    self._enter_global_stop("stop")

                if not self.headless:
                    self.frame = self.get_frame_snapshot()

                try:
                    wait_diag = self.runlog.wait_diag(self.get_sensor_input_health())
                except Exception:
                    wait_diag = "input_health_unavailable"
                self.runlog.warn_throttle(
                    2.0,
                    "dispatcher_wait state=%s reason=%s action_result=%s action_elapsed=%s inputs=%s",
                    self.dispatcher_state,
                    {
                        DISPATCHER_STATE.INIT: "sensor_readiness",
                        DISPATCHER_STATE.WAIT_FOR_MISSION: "mission_or_action_release",
                        DISPATCHER_STATE.DISPATCH: "skill_plan",
                        DISPATCHER_STATE.WAIT_ACTION_FINISH: "skill_completion_gate_or_result",
                        DISPATCHER_STATE.POST_ACTION: "skill_verdict",
                        DISPATCHER_STATE.STOP: "shutdown",
                    }.get(self.dispatcher_state, "unknown_state"),
                    ("stale_generation" if self.action_gate._action_finish_generation != self.action_gate._action_generation
                     else "received") if self.action_finish else "never",
                    self.runlog.fmt_wait_age(time.time() - self.action_start_time) if self.action_in_progress else "inactive",
                    wait_diag,
                )

                if self.dispatcher_state == DISPATCHER_STATE.INIT:
                    head = self.prompt_queue.head_command()
                    skill = self.skills.get(head[1].call.name) if head is not None else None
                    can_dispatch = head is not None and (skill is None or not skill.requires_perception)
                    if self.headless or can_dispatch:
                        self.runlog.info("Initialization complete (no sensor gate)")
                        self.ledger.set_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason="init:headless")
                        continue
                    frame = self.get_frame_snapshot()
                    if frame is not None and frame.cloud_xyz is not None:
                        print("Initialization complete")
                        self.channels.publish_emergency_stop()
                        self.ledger.set_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason="init:ready")
                    else:
                        try:
                            wait_diag = self.runlog.wait_diag(self.get_sensor_input_health())
                        except Exception:
                            wait_diag = "input_health_unavailable"
                        self.runlog.warn_throttle(
                            2.0,
                            "dispatcher_wait_cloud context=init_cloud %s",
                            wait_diag,
                        )
                        self._sleep_unlocked(rate.sleep)
                        continue

                elif self.dispatcher_state == DISPATCHER_STATE.WAIT_FOR_MISSION:
                    if self.if_plan and not self.action_in_progress:
                        self.ledger.set_state(DISPATCHER_STATE.DISPATCH, reason="mission:ready")
                        self.if_plan = False
                    self._sleep_unlocked(time.sleep, 0.1)
                    continue

                elif self.dispatcher_state == DISPATCHER_STATE.DISPATCH:
                    if self.action_in_progress:
                        self.ledger.set_state(DISPATCHER_STATE.WAIT_ACTION_FINISH, reason="dispatch:action_in_progress")
                        continue
                    if self.prompt_queue.is_command_empty():
                        self.ledger.set_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason="plan:command_content_empty")
                        self._sleep_unlocked(time.sleep, 0.1)
                        continue

                    self.prompt_queue.reset_plan_cycle_if_needed()
                    cmd, skill_command = self.prompt_queue.head_command()
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

                    if not self.skills.validate_active_tool(call):
                        self.runlog.warn(
                            "DISPATCH has no active registered tool, prompt=%r",
                            str(call.display_text or call.name),
                        )
                        self._fail_unregistered_dispatch(
                            tool_name=str(call.name or call.display_text or ""),
                            frame_id=call.frame_id,
                        )
                        continue

                    skill = self.skills.get(call.name)
                    if skill.requires_perception and not self.headless and self.frame is None:
                        self.ledger.set_state(DISPATCHER_STATE.INIT, reason="dispatch:frame_missing")
                        continue

                    self.actuators.set_if_handle_yaw(True)
                    if not self.skills.dispatch_plan(skill_command):
                        self.runlog.warn(
                            "Unregistered active tool in DISPATCH: name=%r prompt=%r",
                            str(skill_command.call.name or self.skills.active_tool_name() or ""),
                            str(skill_command.call.display_text or skill_command.call.name),
                        )
                        self._fail_unregistered_dispatch(
                            tool_name=str(skill_command.call.name or ""),
                            frame_id=skill_command.call.frame_id,
                        )
                    self._sleep_unlocked(rate.sleep)
                    continue

                elif self.dispatcher_state == DISPATCHER_STATE.WAIT_ACTION_FINISH:
                    wait_skill = self.skills.owner_skill()
                    if wait_skill is not None:
                        wait_skill.wait_action_tick()
                        if self.dispatcher_state != DISPATCHER_STATE.WAIT_ACTION_FINISH:
                            continue
                    if self.action_gate.action_done():
                        self.action_in_progress = False
                        self.action_finish = False
                        self.ledger.set_state(DISPATCHER_STATE.POST_ACTION, reason="action:done")
                        continue
                    self._sleep_unlocked(time.sleep, 0.05)
                    continue

                elif self.dispatcher_state == DISPATCHER_STATE.POST_ACTION:
                    self.action_gate.handle_post_action()
                    continue

                elif self.dispatcher_state == DISPATCHER_STATE.STOP:
                    self.clock.request_shutdown("Stopped by command")
                    break

                else:
                    self._sleep_unlocked(time.sleep, 0.05)

                self._sleep_unlocked(rate.sleep)

    def _recover_inference_after_exception(self, exc: BaseException) -> None:
        """推理线程异常兜底：把 FSM 复位到空闲态，保证后续任务可被唤醒。

        @param[in] exc  未捕获的异常对象
        @return None
        """
        try:
            self.ledger.bump_task_generation("inference:exception")
            self.ledger.fail_sequence()
            self.task_phase.publish(
                "fail", detail=str(exc),
                error={"code": "internal_error", "message": str(exc)},
            )
            self.ledger.set_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason="inference:exception")
            self.if_plan = False
            self.action_gate.clear_action_state()
            self.ledger.reset_running()
            self.prompt_queue.clear_all()
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
                try:
                    wait_diag = self.runlog.wait_diag(self.get_sensor_input_health())
                except Exception:
                    wait_diag = "input_health_unavailable"
                self.runlog.warn_throttle(
                    2.0, "dispatcher_wait reason=inference_recovery inputs=%s",
                    wait_diag,
                )
                time.sleep(1.0)
