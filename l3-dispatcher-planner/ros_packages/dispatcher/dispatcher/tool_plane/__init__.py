"""工具面（tool plane）：承接 l4 工具调用的传输、协议、发现、准入、事件、取消与连接租约。

一行定义：l4 调用从 zenoh 进入本栈后，经「连接租约 → 传输接收 → 协议信封
→ 工具发现与参数校验 → 调用准入/事件/取消 → 交给技能工作流」的全部处理，
外加该服务栈的线程装配。工具本体（技能协议与家族实现）在 dispatcher/tools/。

契约归属 l3-dispatcher/tool-plane 与 l3-dispatcher/l4-rpc；
平面划分见 l3-dispatcher/package-layout。
"""

from dispatcher.tool_plane.model import SkillCommand, ToolCall, ToolCommand, ToolSpec
from dispatcher.tool_plane.protocol import ToolProtocolError
from dispatcher.tool_plane.registry import ToolRegistry
from dispatcher.tool_plane.runtime import ToolRuntime
from dispatcher.tool_plane.intake import ToolIntake

__all__ = [
    "ToolProtocolError",
    "ToolCall",
    "ToolCommand",
    "ToolSpec",
    "SkillCommand",
    "ToolRegistry",
    "ToolRuntime",
    "ToolIntake",
]
