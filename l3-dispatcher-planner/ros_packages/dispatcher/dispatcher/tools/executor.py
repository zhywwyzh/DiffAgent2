"""按已注册调用名进入通用技能工作流。"""

from __future__ import annotations

from dispatcher.tools.model import SkillCommand, ToolCall
from dispatcher.tools.registry import ToolRegistry


class ToolExecutor:
    """Route one registered tool call directly to its execution seam."""

    def __init__(self, registry: ToolRegistry, host) -> None:
        self._registry = registry
        self._host = host

    def execute(self, call: ToolCall) -> None:
        spec = self._registry.tool_for_name(call.name)
        self._host.start_tool_workflow(
            call,
            SkillCommand(call, requires_perception=spec.requires_perception),
        )

    @staticmethod
    def cancel(host, call: ToolCall, reason: str) -> None:
        host.cancel_tool_call(call, reason)
