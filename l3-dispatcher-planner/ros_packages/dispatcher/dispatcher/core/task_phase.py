"""任务相位桥（S3 方案 §2.5/§5）：相位事件组装与上报。

自 engine.py 迁出（零语义变更：/agent_task_phase payload 键序与取值、
on_tool_phase 触发时机与先后（先 middleware 后 topic）、task_phase_published
事件键集字节级一致）。zenoh middleware 出口不是 ROS 通道（§4.5 裁定），
由本桥持有引用（经 set_middleware 设置，workflow.bind_tool_middleware 时
同步），topic 发布经 CoreChannels 端口。
"""

from __future__ import annotations

import json

from dispatcher.core.ports import CoreChannels
from dispatcher.core.telemetry import RunTelemetry


class TaskPhaseBridge:
    """任务生命周期事件的组装、middleware 出口与 topic 上报。"""

    def __init__(self, channels: CoreChannels, runlog: RunTelemetry) -> None:
        self.channels = channels
        self.runlog = runlog
        # Frame_id of the AgentPrompt that OWNS the currently active task. Set
        # in _start_prompt_task; every task-phase event (incl. terminals) must
        # use it instead of latest_agent_prompt_frame_id so a late fail is
        # correlated to the ORIGINAL step_id/request_id, not to a later
        # prompt's frame (L4 cancel "急停" overwrites the latest frame).
        self._active_task_frame_id = "Null"
        # 死字段如实保留（S3 §2.3/§9）：无自增点，属技能轮次的登记项，
        # 不臆造自增逻辑。
        self._task_phase_progress = 0  # 当前 prompt 已完成的原始动作计数
        # zenoh 生命周期事件出口（经 set_middleware 绑定）
        self.middleware = None

    def set_active_frame(self, frame_id: str) -> None:
        """记录发起当前任务的 AgentPrompt frame（_activate_tool_call 写入）。"""
        self._active_task_frame_id = frame_id

    def set_middleware(self, middleware) -> None:
        """绑定 zenoh 生命周期事件出口（workflow.bind_tool_middleware 同步）。"""
        self.middleware = middleware

    def publish(
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
            if self.middleware is not None:
                self.middleware.on_tool_phase(payload)
            self.channels.publish_task_phase(json.dumps(payload, ensure_ascii=False))
            self.runlog.emit(
                "info",
                "task_phase_published",
                phase=phase,
                frame_id=payload["frame_id"],
                detail=str(detail or ""),
            )
        except Exception:
            self.runlog.warn("[TASK_PHASE] publish failed phase=%s", phase)
