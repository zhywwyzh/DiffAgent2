"""通用机制测试自有的能力元数据；不进入生产默认注册表。"""

from dispatcher.tool_plane.model import ToolSpec
from dispatcher.tool_plane.registry import ToolRegistry


def test_registry():
    empty = {"type": "object", "properties": {}, "additionalProperties": False}
    move = {
        "type": "object", "additionalProperties": False,
        "properties": {"direction": {"enum": ["forward", "backward", "left", "right"]},
                       "distance_m": {"type": "number", "exclusiveMinimum": 0}},
        "required": ["direction", "distance_m"],
    }
    rotate = {
        "type": "object", "additionalProperties": False,
        "properties": {"yaw_delta_deg": {"type": "number", "exclusiveMinimum": -360, "maximum": 360}},
        "required": ["yaw_delta_deg"],
    }
    return ToolRegistry(tuple(
        ToolSpec(name, name, "仅用于机制测试", schema, empty, "workflow_result", requires_perception=name == "test.sense")
        for name, schema in (("test.start", empty), ("test.finish", empty),
                             ("test.move", move), ("test.rotate", rotate), ("test.replace", empty), ("test.sense", empty))
    ))


test_registry.__test__ = False
