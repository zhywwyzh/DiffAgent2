"""Transport-independent tool model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    """One validated invocation admitted to the runtime."""

    call_id: str
    name: str
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
    """随队首进入核心的原始工具调用及感知需求元数据。"""

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
    title: str
    description: str
    input_schema: dict
    output_schema: dict
    completion: str
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
                "lx.completion": self.completion,
                "lx.concurrency": "flight-exclusive",
            },
        }
