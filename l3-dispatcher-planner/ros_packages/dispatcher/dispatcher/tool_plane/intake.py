"""按已注册调用名把工具面调用接入技能工作流。"""

from __future__ import annotations

from dispatcher.tool_plane.model import SkillCommand, ToolCall
from dispatcher.tool_plane.registry import ToolRegistry


class ToolIntake:
    """Route one registered tool call directly to its execution seam."""

    def __init__(self, registry: ToolRegistry, host) -> None:
        self._registry = registry
        self._host = host

    def start(self, call: ToolCall) -> None:
        spec = self._registry.tool_for_name(call.name)
        self._host.start_tool_workflow(
            call,
            SkillCommand(call, requires_perception=spec.requires_perception),
        )

    @staticmethod
    def cancel(host, call: ToolCall, reason: str) -> None:
        host.cancel_tool_call(call, reason)
