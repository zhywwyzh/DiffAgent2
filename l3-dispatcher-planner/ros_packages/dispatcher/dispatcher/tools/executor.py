"""Direct dispatch from the canonical registry to the execution seams (P3.8).

原 parse_cmd 适配层（FlightTools / VlaTool / SceneTools / SceneGraphEditTools
四个 adapter，只做「字段搬运 + 语义派生」、无新信息注入）整体删除：
三条直发工具在 executor 内联直发，其余注册工具经 ToolSpec 元数据构造
携带原生 ToolCall 的 SkillCommand 后进入工作流。
"""

from __future__ import annotations

from dispatcher.tools.model import SkillCommand, ToolCall
from dispatcher.tools.registry import ToolRegistry


class ToolExecutor:
    """Route one registered tool call directly to its execution seam."""

    def __init__(self, registry: ToolRegistry, host) -> None:
        self._registry = registry
        self._host = host

    def execute(self, call: ToolCall) -> None:
        # 三条直发（等价原 FlightTools.start 前三行）：起飞/降落/急停不进
        # prompt 队列、不构造 SkillCommand；急停 arguments 恒为空 dict，
        # 下游只按 call.name 分发，不做任何 arguments 直读。
        if call.name == "flight.takeoff":
            self._host.forward_takeoff_tool(call)
            return
        if call.name == "flight.land":
            self._host.forward_land_tool(call)
            return
        if call.name == "flight.emergency_stop":
            self._host.forward_emergency_stop_tool(call)
            return
        # 其余注册工具：经注册表元数据驱动（requires_perception 仅
        # navigation.vla_reach 为 True），携带原生 ToolCall 入工作流；
        # 感知需求判断从 adapter 硬编码下沉为 ToolSpec 声明字段。
        spec = self._registry.tool_for_name(call.name)
        self._host.start_tool_workflow(
            call,
            SkillCommand(call, requires_perception=spec.requires_perception),
        )

    @staticmethod
    def cancel(host, call: ToolCall, reason: str) -> None:
        host.cancel_tool_call(call, reason)
