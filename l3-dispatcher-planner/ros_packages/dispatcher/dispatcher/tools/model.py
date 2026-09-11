"""Transport-independent tool model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ToolProtocolError(Exception):
    """Reject a tool request before it enters the execution runtime."""

    def __init__(self, code: int, message: str, data: dict | None = None) -> None:
        super().__init__(message)
        self.code = int(code)
        self.message = str(message)
        self.data = dict(data or {})

    def to_dict(self) -> dict:
        result = {"code": self.code, "message": self.message}
        if self.data:
            result["data"] = dict(self.data)
        return result


@dataclass(frozen=True)
class ToolCall:
    """One validated invocation admitted to the runtime."""

    call_id: str
    name: str
    task_id: int
    arguments: dict
    flight_session_id: str
    step_id: str
    display_text: str = ""
    station_id: str = ""
    station_instance_id: str = ""
    lease_id: str = ""

    @property
    def frame_id(self) -> str:
        return f"copaw/{self.flight_session_id}/{self.step_id}"

    @property
    def lease_identity(self) -> dict:
        """The fleet-spec connection identity triple carried by this call."""
        return {
            "station_id": self.station_id,
            "station_instance_id": self.station_instance_id,
            "lease_id": self.lease_id,
        }


@dataclass(frozen=True)
class SkillCommand:
    """随 prompt 一起穿越引擎队列的结构化命令（P3.8 起直接携带原生 ToolCall）。

    下游 Skill 经 call.name / call.arguments / call.display_text 读取执行
    所需的全部信息（schema 校验后的原生 JSON），不再经 parsed_cmd 适配层
    中转；requires_perception 保留为布尔（vla 感知门用）。原 tool_name
    字段删除——等价于 call.name（registry 分发键）。
    """

    call: ToolCall
    requires_perception: bool = False


@dataclass(frozen=True)
class ToolCommand:
    """One call/cancel command crossing into the ROS execution thread."""

    kind: str
    call: ToolCall
    reason: str = ""


@dataclass(frozen=True)
class ToolSpec:
    """Discoverable metadata plus the private argument validator."""

    name: str
    task_id: int
    title: str
    description: str
    input_schema: dict
    output_schema: dict
    completion: str
    adapter: str
    # P3.8：执行期感知需求元数据（原 adapter 层组装 SkillCommand 时内联的
    # 硬编码，仅 navigation.vla_reach 为 True）；public_dict 是手工键集，
    # 该字段为执行面私有，不得外泄进工具发现面。
    requires_perception: bool = False
    destructive: bool = True
    idempotent: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "outputSchema": self.output_schema,
            "annotations": {
                "destructiveHint": self.destructive,
                "idempotentHint": self.idempotent,
            },
            "_meta": {
                "lx.task_id": self.task_id,
                "lx.completion": self.completion,
                "lx.concurrency": "flight-exclusive",
            },
        }
