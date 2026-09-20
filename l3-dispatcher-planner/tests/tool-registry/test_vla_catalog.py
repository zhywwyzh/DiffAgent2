# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest"]
# ///
"""navigation.vla_nav 发现面元数据回归（tools/vla/catalog.py）。

权威记录：specs/implemented/inner/l3-tool-plane.spec.md §1（schema 字段表与
revision 现行值 sha256:cacb240e...）。断言分三层：
- 元数据与 spec §1 记录逐项一致（含 _meta 键集、completion、并发语义）；
- 生产发现面（ToolRegistry.default()，P3 起 flight+vla 同一机制汇入）恰为
  七工具且 revision == spec 记录值（G24）；
- grounded schema 的结构校验正/负例（必填缺省、bbox_1000 恰 4 项、enum、
  additionalProperties=false）；0..1000 值域与 x1<x2 语义校验归技能
  fail-closed（tests/core-boundary/test_vla_skill.py），不进 schema。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "ros_packages" / "dispatcher"))

from dispatcher.tool_plane.model import ToolSpec  # noqa: E402
from dispatcher.tool_plane.protocol import ToolProtocolError  # noqa: E402
from dispatcher.tool_plane.registry import ToolRegistry  # noqa: E402
from dispatcher.tools.vla.catalog import vla_specs  # noqa: E402

# l3-tool-plane.spec.md §1 记录的现行 revision
SPEC_REVISION = "sha256:cacb240ea0d6b94294831f23574d4bde9f7781528f617d69ed2583c4eb08f269"

SPEC_TOOL_NAMES = {
    "basic_flight.takeoff", "basic_flight.land", "basic_flight.translate",
    "basic_flight.rotate", "basic_flight.return", "basic_flight.emergency_stop",
    "navigation.vla_nav",
}


def vla_registry() -> ToolRegistry:
    """仅含 vla 工具的注册面（schema 校验用）。"""
    return ToolRegistry(vla_specs())


def grounded_arguments(**overrides) -> dict:
    """完整合法的 grounded detection 参数（负例按字段覆盖/剔除）。"""
    arguments = {
        "object": "red marker",
        "prompt": "fly to the red marker",
        "bbox_1000": [250.0, 250.0, 500.0, 500.0],
        "image_stamp": 100.25,
    }
    arguments.update(overrides)
    return arguments


def normalize(registry: ToolRegistry, arguments: dict):
    return registry.normalize_call({
        "call_id": "call_1",
        "name": "navigation.vla_nav",
        "arguments": arguments,
        "context": {"flight_session_id": "flight_a", "step_id": "step_1"},
    })


def reject_reason(registry: ToolRegistry, arguments: dict) -> str:
    with pytest.raises(ToolProtocolError) as caught:
        normalize(registry, arguments)
    return caught.value.data["reason"]


# ---------------------------------------------------------------------------
# 元数据与 spec §1 记录一致
# ---------------------------------------------------------------------------


def test_single_tool_named_navigation_vla_nav() -> None:
    specs = tuple(vla_specs())
    assert len(specs) == 1
    spec = specs[0]
    assert isinstance(spec, ToolSpec)
    assert spec.name == "navigation.vla_nav"
    assert spec.requires_perception is True
    assert spec.completion == "workflow_result"


def test_public_metadata_matches_tool_plane_record() -> None:
    spec = vla_specs()[0]
    public = spec.public_dict()
    assert public["title"] == "Reach a visual target"
    assert public["description"] == (
        "Reach a station-grounded visual target: consume the bbox downlinked "
        "by the station (rgb camera stamp bound) and execute the waypoint chain."
    )
    assert public["outputSchema"] == {
        "type": "object", "properties": {}, "additionalProperties": False,
    }
    # _meta 键集恰为完成语义 + 并发语义（flight-exclusive，与飞行共用独占）
    assert public["_meta"] == {
        "lx.completion": "workflow_result",
        "lx.concurrency": "flight-exclusive",
    }
    # 无任务编号标识（B2/B7/B8）：发现面不携带任何编号字段
    assert "task_id" not in public
    assert "task_id" not in public["inputSchema"].get("properties", {})


def test_input_schema_field_table_matches_tool_plane_record() -> None:
    schema = vla_specs()[0].input_schema
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["object", "prompt", "bbox_1000", "image_stamp"]
    properties = schema["properties"]
    assert set(properties) == {
        "object", "prompt", "bbox_1000", "image_stamp", "side", "distance_m",
        "visible", "finish", "provider", "image_width", "image_height",
    }
    assert properties["object"] == {"type": "string", "minLength": 1}
    assert properties["prompt"] == {"type": "string", "minLength": 1}
    # bbox_1000：恰 4 项数值数组；0..1000 值域与 x1<x2 语义校验由技能 fail-closed
    assert properties["bbox_1000"] == {
        "type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4,
    }
    assert properties["image_stamp"] == {"type": "number", "exclusiveMinimum": 0}
    assert properties["side"] == {"enum": ["front", "left", "right", "above"]}
    assert properties["distance_m"] == {"type": "number", "exclusiveMinimum": 0}
    assert properties["visible"] == {"type": "boolean"}
    assert properties["finish"] == {"type": "boolean"}
    assert properties["provider"] == {"type": "string", "enum": ["station"]}
    assert properties["image_width"] == {"type": "integer", "exclusiveMinimum": 0}
    assert properties["image_height"] == {"type": "integer", "exclusiveMinimum": 0}


def test_production_registry_surface_matches_spec_record() -> None:
    """P3 起生产发现面即七工具（default() 汇入 flight+vla）；
    revision == l3-tool-plane.spec.md §1 记录的现行值（G24）。"""
    listing = ToolRegistry.default().list_tools()
    assert {tool["name"] for tool in listing["tools"]} == SPEC_TOOL_NAMES
    assert listing["revision"] == SPEC_REVISION


# ---------------------------------------------------------------------------
# schema 结构校验：正例
# ---------------------------------------------------------------------------


def test_full_grounded_call_passes_schema() -> None:
    call = normalize(vla_registry(), grounded_arguments(
        side="front", distance_m=1.5, visible=True, finish=False,
        provider="station", image_width=1280, image_height=960,
    ))
    assert call.name == "navigation.vla_nav"
    assert call.arguments["image_stamp"] == 100.25
    assert call.arguments["bbox_1000"] == [250.0, 250.0, 500.0, 500.0]


def test_minimal_grounded_call_passes_schema() -> None:
    call = normalize(vla_registry(), grounded_arguments())
    assert set(call.arguments) == {"object", "prompt", "bbox_1000", "image_stamp"}


# ---------------------------------------------------------------------------
# schema 结构校验：负例
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing", ["object", "prompt", "bbox_1000", "image_stamp"])
def test_missing_required_argument_is_rejected(missing: str) -> None:
    arguments = grounded_arguments()
    del arguments[missing]
    assert reject_reason(vla_registry(), arguments) == "missing_required_argument"


@pytest.mark.parametrize("bbox", [
    [250.0, 250.0, 500.0],                                   # 3 项（< minItems 4）
    [250.0, 250.0, 500.0, 600.0, 700.0],                     # 5 项（> maxItems 4）
    [250.0, 250.0, "500", 500.0],                            # 项非有限数值
    [250.0, 250.0, 500.0, float("inf")],                     # 项非有限数值
])
def test_bbox_1000_cardinality_and_item_type_are_rejected(bbox: list) -> None:
    assert reject_reason(vla_registry(), grounded_arguments(bbox_1000=bbox)) \
        == "argument_out_of_range"


@pytest.mark.parametrize("field,value", [
    ("side", "behind"),          # enum 外方位词
    ("provider", "onboard"),     # enum 仅 station
    ("object", ""),              # minLength=1
    ("prompt", "  "),            # minLength=1（strip 后为空）
    ("image_stamp", 0),          # exclusiveMinimum=0
    ("image_stamp", -1.0),       # exclusiveMinimum=0
    ("image_stamp", "100.25"),   # 类型不符
    ("distance_m", 0),           # exclusiveMinimum=0
    ("visible", "yes"),          # boolean
    ("finish", 1),               # boolean（bool 值 1 不是布尔）
    ("image_width", 640.5),      # integer
    ("image_width", True),       # integer（bool 排除）
    ("image_height", 0.5),       # integer
])
def test_field_rule_violations_are_rejected(field: str, value) -> None:
    assert reject_reason(vla_registry(), grounded_arguments(**{field: value})) \
        == "argument_out_of_range"


@pytest.mark.parametrize("unknown", [{"task_id": 0}, {"nav_mode": "side"}])
def test_unknown_arguments_are_rejected(unknown: dict) -> None:
    assert reject_reason(vla_registry(), grounded_arguments(**unknown)) \
        == "unknown_argument"


def test_bbox_semantic_bounds_stay_in_skill_fail_closed() -> None:
    """0..1000 值域与 x1<x2、y1<y2 语义校验不进 schema（spec §1 记录）。

    schema 层只做元数/类型：x2<x1（400<500）的 bbox 结构上合法，语义
    拒绝归 vla_skill._consume_grounded_detection → invalid_grounded_bbox。
    """
    call = normalize(vla_registry(), grounded_arguments(bbox_1000=[500.0, 500.0, 400.0, 600.0]))
    assert call.arguments["bbox_1000"] == [500.0, 500.0, 400.0, 600.0]
