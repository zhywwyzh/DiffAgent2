"""工具执行缝宿主（S3 方案 §2.7/§5）：三缝 + 六字段。

自 engine.py 迁出（零语义变更）。§4.9 裁决：start_tool_workflow 内
hasattr(self, "_start_prompt_task") 守卫、早退段与其后的整段不可达代码
（含 _decision_chain_not_ready_reason 孤儿调用与 _start_prompt_task
未定义调用）逐字保留——属既有断裂，待任务注入轮次迁入
_start_prompt_task 时一并处置，不补造任何定义。协作对象经注入工作：
全局停止经 enter_global_stop 回调触发（本模块不 import engine）。
"""

from __future__ import annotations

from typing import Callable

from dispatcher.tools.model import SkillCommand, ToolCall
from dispatcher.core.skill_router import SkillRouter
from dispatcher.core.task_phase import TaskPhaseBridge
from dispatcher.core.telemetry import RunTelemetry


class ToolWorkflowHost:
    """工具执行缝宿主：ToolControlPlane / ToolExecutor 的 duck-typed host。"""

    def __init__(
        self,
        runlog: RunTelemetry,
        task_phase: TaskPhaseBridge,
        skills: SkillRouter,
        enter_global_stop: Callable[..., None],
        task_generation: Callable[[], int],
    ) -> None:
        self.runlog = runlog
        self.task_phase = task_phase
        self.skills = skills
        # 全局停止回调（engine._enter_global_stop 注入；cancel_tool_call 触发）
        self.enter_global_stop = enter_global_stop
        # 任务代次取值回调（engine.task_generation 注入；tool_call_received
        # 事件字段需要，workflow 不回引 engine 对象）
        self.task_generation = task_generation
        # 工具执行缝字段（自 engine 迁入）：_activate_tool_call
        # 写入 / cancel_tool_call 清空；latest_agent_prompt_frame_id 的
        # 初始值 "Null" 与 OLD 语义一致；
        # task_action_client 为任务注入轮次的 action 客户端缝，
        # cancel_tool_call 沿用 OLD 原有 None 守卫。
        self._active_tool_name = ""
        self.zenoh_middleware = None
        self._active_tool_call = None
        self.latest_agent_prompt_frame_id = "Null"
        self.task_action_client = None

    def bind_tool_middleware(self, middleware) -> None:
        """Bind the lifecycle event sink composed by dispatcher_node."""
        self.zenoh_middleware = middleware
        # 同步任务相位桥的 zenoh 出口（S3 §5：bind 时 set_middleware）
        self.task_phase.set_middleware(middleware)
        # 注册 agent_log 快照兜底通道（stream -> 快照文件绝对路径，站端
        # 断档/重连后经 agent_log/snapshot queryable 拉全量），并把绑定前
        # 暂存的记录按 FIFO 补发进 zenoh 上行 outbox。
        # recording 未随本轮迁入：三流快照注册与 pending 补发暂缺，先注册
        # 空表（middleware 侧按 dict 契约容忍空），recording 轮次迁入后
        # 恢复三流注册与 _publish_latest_log_if_pending 补发。
        middleware.agent_log_snapshot_files = {}

    def _activate_tool_call(self, call: ToolCall) -> None:
        self._active_tool_call = call
        self._active_tool_name = call.name
        self.latest_agent_prompt_frame_id = call.frame_id
        self.task_phase.set_active_frame(call.frame_id)
        self.runlog.emit(
            "info",
            "tool_call_received",
            call_id=call.call_id,
            tool_name=call.name,
            frame_id=call.frame_id,
            task_generation=self.task_generation(),
        )

    def start_tool_workflow(
        self,
        call: ToolCall,
        command: SkillCommand,
    ) -> None:
        """Enter the existing workflow loop through one registered tool seam."""
        # 任务注入守卫缝（同 zenoh_middleware 的 None 守卫模式）：NEW 尚未
        # 迁入 _start_prompt_task（任务注入轮次补齐）。能力预检放在
        # _activate_tool_call 记账之前——缺失时不污染 _active_tool_name/
        # _active_task_frame_id/latest_agent_prompt_frame_id，且经 fail
        # 终态发布（frame→call_id 回退）释放 runtime 的 _active_call_id，
        # 站端不会悬空等待终态；
        # 任务注入轮次迁入 _start_prompt_task 后移除守卫。
        if not hasattr(self, "_start_prompt_task"):
            self.runlog.warn(
                "[dispatcher] _start_prompt_task not migrated yet; drop tool workflow for %s",
                call.name,
            )
            self.task_phase.publish(
                "fail",
                detail="task injection not migrated",
                error={
                    "code": "task_injection_not_migrated",
                    "message": "_start_prompt_task not migrated yet",
                },
                frame_id=call.frame_id,
            )
            return
        self._activate_tool_call(call)
        # prompt_text 兜底链：display_text → vla 的 arguments.prompt → 工具名。
        # 第二层为保持原 vla 适配器 raw=arguments["prompt"] 的行为（display_text
        # 为空时 VLM/日志仍取到 prompt）；其余工具 arguments 无 prompt 键，
        # .get() 返回 None，等价 display_text or name。
        prompt_text = str(call.display_text or call.arguments.get("prompt") or call.name)
        # P3 技能分发：注册表命中的技能先收 on_start（替代 _tool_parsed_cmd
        # stash 的准入期语义）；同步技能（scene_nav.graph.* 编辑族 →
        # GraphEditSkill）在 consumer 线程直跑 on_start 后即返回——不进感知门、
        # 不发 planning、不入 prompt 队列（外部事件序列与旧短路分支一致）。
        # 异步技能（flight.* → FlightSkill，P3.2；scene.* → SceneNavSkill，
        # P3.3）on_start 为 no-op，继续走下方 planning + 入队路径。
        # （S3 起注册表查表委托 self.skills）
        skill = self.skills.get(call.name)
        if skill is not None:
            skill.on_start(command)
            if skill.synchronous:
                return
        if command.requires_perception:
            not_ready_reason = self._decision_chain_not_ready_reason()
            if not_ready_reason:
                self.task_phase.publish(
                    "fail",
                    detail=f"chain_not_ready: {not_ready_reason}",
                    error={"code": "chain_not_ready", "message": not_ready_reason},
                    frame_id=call.frame_id,
                )
                return
        self.task_phase.publish(
            "planning",
            message=prompt_text,
            frame_id=call.frame_id,
        )
        self._start_prompt_task(
            prompt_text=prompt_text,
            prompt_entries=[(prompt_text, command)],
            already_paused=False,
        )

    def cancel_tool_call(self, call: ToolCall, reason: str) -> None:
        """Cancel one call without implicitly publishing emergency-stop outputs."""
        if self._active_tool_call is not None and (self._active_tool_call.call_id == call.call_id):
            # P3.2 取消入口转发技能（设计文档 §1：转发 skill.on_cancel()）——
            # FlightSkill 借此解除 return topo 完成门，SceneNavSkill 重置
            # 会话等待态（P3.3）
            # （S3 起注册表查表委托 self.skills）
            skill = self.skills.get(call.name)
            if skill is not None:
                skill.on_cancel()
            self.enter_global_stop(
                f"tool_cancel:{reason or 'requested'}",
                shutdown_program=False,
                publish_hold=False,
            )
            if self.task_action_client is not None:
                self.task_action_client.cancel_all_goals()
            self._active_tool_call = None
            self._active_tool_name = ""
        if self.zenoh_middleware is not None:
            self.zenoh_middleware.runtime.mark_cancelled(call.call_id, reason)
