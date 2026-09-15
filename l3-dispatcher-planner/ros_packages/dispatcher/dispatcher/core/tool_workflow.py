"""通用工具调用入口：准入技能、同步执行或写入任务队列、取消。"""

from __future__ import annotations

from dispatcher.tools.model import SkillCommand, ToolCall


class ToolWorkflowHost:
    def __init__(self, *, runlog, task_phase, skills, enter_global_stop,
                 task_generation, queue, ledger, input_ready):
        self.runlog = runlog
        self.task_phase = task_phase
        self.skills = skills
        self.enter_global_stop = enter_global_stop
        self.task_generation = task_generation
        self.queue = queue
        self.ledger = ledger
        self.input_ready = input_ready
        self._active_tool_name = ""
        self._active_tool_call = None
        self.latest_agent_prompt_frame_id = "Null"
        self.zenoh_middleware = None

    def bind_tool_middleware(self, middleware) -> None:
        self.zenoh_middleware = middleware
        self.task_phase.set_middleware(middleware)

    def _activate_tool_call(self, call: ToolCall) -> None:
        self._active_tool_call = call
        self._active_tool_name = call.name
        self.latest_agent_prompt_frame_id = call.frame_id
        self.task_phase.set_active_frame(call.frame_id)
        self.runlog.emit(
            "info", "tool_call_received", call_id=call.call_id,
            tool_name=call.name, frame_id=call.frame_id,
            task_generation=self.task_generation(),
        )

    def start_tool_workflow(self, call: ToolCall, command: SkillCommand) -> None:
        skill = self.skills.get(call.name)
        if skill is None:
            self.task_phase.publish(
                "fail", detail=f"tool not registered: {call.name}",
                error={"code": "tool_not_registered", "message": f"tool not registered: {call.name}"},
                frame_id=call.frame_id,
            )
            return
        if not skill.synchronous and skill.requires_perception and not self.input_ready():
            self.task_phase.publish(
                "fail", detail="chain_not_ready: sensor input unavailable or stale",
                error={"code": "chain_not_ready", "message": "sensor input unavailable or stale"},
                frame_id=call.frame_id,
            )
            return
        self.enter_global_stop("new_tool_call", shutdown_program=False, publish_hold=False)
        self.ledger.failed = False
        self._activate_tool_call(call)
        skill.on_new_prompt_task()
        skill.on_start(command)
        if skill.synchronous:
            return
        prompt_text = str(call.display_text or call.name)
        self.task_phase.publish("planning", message=prompt_text, frame_id=call.frame_id)
        self.queue.sync_task_buffers_from_prepare([(prompt_text, command)])
        self.queue.pop_next_task()

    def cancel_tool_call(self, call: ToolCall, reason: str) -> None:
        if self._active_tool_call is not None and self._active_tool_call.call_id == call.call_id:
            skill = self.skills.get(call.name)
            if skill is not None:
                skill.on_cancel()
            self.enter_global_stop(
                f"tool_cancel:{reason or 'requested'}",
                shutdown_program=False, publish_hold=False,
            )
            self._active_tool_call = None
            self._active_tool_name = ""
        if self.zenoh_middleware is not None:
            self.zenoh_middleware.runtime.mark_cancelled(call.call_id, reason)
