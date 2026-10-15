# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest"]
# ///
"""navigation.vla_nav 发现面元数据回归（tools/vla/catalog.py，waypoint 载荷）。

权威记录：specs/implemented/inner/l3-tool-plane.spec.md §1（schema 字段表与
revision 现行值）。断言分三层：
- 元数据与 spec §1 记录逐项一致（含 _meta 键集、completion、并发语义）；
- 生产发现面（ToolRegistry.default()，flight+vla 同一机制汇入）恰为
  八工具且 revision == spec 记录值（G24）；
- waypoint schema 的结构校验正/负例（必填缺省、waypoint_world 恰 3 项、
  additionalProperties=false）；有限性语义校验归技能 fail-closed
  （tests/core-boundary/test_vla_skill.py），不进 schema。
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
SPEC_REVISION = "sha256:32b34a601073402fdef66c6f097bc4073f7fb1ad595beeea296305b05cde1228"

SPEC_TOOL_NAMES = {
    "basic_flight.takeoff", "basic_flight.land", "basic_flight.translate",
    "basic_flight.rotate", "basic_flight.return", "basic_flight.emergency_stop",
    "navigation.vla_nav", "navigation.vla_rotate",
}


def vla_registry() -> ToolRegistry:
    """仅含 vla 工具的注册面（schema 校验用）。"""
    return ToolRegistry(vla_specs())


def waypoint_arguments(**overrides) -> dict:
    """完整合法的 station waypoint 参数（负例按字段覆盖/剔除）。"""
    arguments = {
        "object": "red marker",
        "prompt": "fly to the red marker",
        "waypoint_world": [2.2, 0.0, 1.0],
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


def test_vla_specs_are_vla_nav_then_vla_rotate() -> None:
    specs = tuple(vla_specs())
    assert [spec.name for spec in specs] == ["navigation.vla_nav", "navigation.vla_rotate"]
    for spec in specs:
        assert isinstance(spec, ToolSpec)
        assert spec.requires_perception is False
        assert spec.completion == "action_result"


def test_public_metadata_matches_tool_plane_record() -> None:
    spec = vla_specs()[0]
    public = spec.public_dict()
    assert public["title"] == "Reach a visual target"
    assert public["description"] == (
        "Reach a station-grounded visual target: consume the station-resolved "
        "waypoint (world frame, computed on the station from the grounded bbox + "
        "accumulated cloud + pose@image_stamp) and execute it as one terminal leg."
    )
    assert public["outputSchema"] == {
        "type": "object", "properties": {}, "additionalProperties": False,
    }
    # _meta 键集恰为完成语义 + 并发语义（flight-exclusive，与飞行共用独占）
    assert public["_meta"] == {
        "lx.completion": "action_result",
        "lx.concurrency": "flight-exclusive",
    }
    # 无任务编号标识（B2/B7/B8）：发现面不携带任何编号字段
    assert "task_id" not in public
    assert "task_id" not in public["inputSchema"].get("properties", {})


def test_input_schema_field_table_matches_tool_plane_record() -> None:
    schema = vla_specs()[0].input_schema
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["object", "prompt", "waypoint_world"]
    properties = schema["properties"]
    assert set(properties) == {"object", "prompt", "waypoint_world", "yaw", "look_forward"}
    assert properties["object"] == {"type": "string", "minLength": 1}
    assert properties["prompt"] == {"type": "string", "minLength": 1}
    # waypoint_world：恰 3 项数值数组；有限性由技能 fail-closed
    assert properties["waypoint_world"] == {
        "type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
    }
    assert properties["yaw"] == {"type": "number"}
    assert properties["look_forward"] == {"type": "boolean"}


def test_vla_rotate_metadata_and_schema_match_tool_plane_record() -> None:
    """navigation.vla_rotate：VLA 搜索旋转腿（站端 visible=false 重扫）。

    schema 与 DiffAgent2 旧版 tools/registry.py 一致：`yaw_delta_deg` 限
    `(-360, 360]`（`exclusiveMinimum=-360`、`maximum=360`）。
    """
    rotate = vla_specs()[1]
    public = rotate.public_dict()
    assert public["title"] == "Rotate for VLA search"
    assert public["outputSchema"] == {
        "type": "object", "properties": {}, "additionalProperties": False,
    }
    assert public["_meta"] == {
        "lx.completion": "action_result",
        "lx.concurrency": "flight-exclusive",
    }
    schema = rotate.input_schema
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["yaw_delta_deg"]
    assert set(schema["properties"]) == {"yaw_delta_deg"}
    assert schema["properties"]["yaw_delta_deg"] == {
        "type": "number", "exclusiveMinimum": -360, "maximum": 360,
    }

    registry = ToolRegistry((rotate,))

    def rotate_call(delta):
        return registry.normalize_call({
            "call_id": "call_1",
            "name": "navigation.vla_rotate",
            "arguments": {"yaw_delta_deg": delta},
            "context": {"flight_session_id": "flight_a", "step_id": "step_1"},
        })

    assert rotate_call(40.0).arguments["yaw_delta_deg"] == 40.0
    assert rotate_call(360.0).arguments["yaw_delta_deg"] == 360.0
    for bad in (-360.0, 361.0, "40"):
        with pytest.raises(ToolProtocolError) as caught:
            rotate_call(bad)
        assert caught.value.data["reason"] == "argument_out_of_range"
    with pytest.raises(ToolProtocolError) as caught:
        registry.normalize_call({
            "call_id": "call_1",
            "name": "navigation.vla_rotate",
            "arguments": {},
            "context": {"flight_session_id": "flight_a", "step_id": "step_1"},
        })
    assert caught.value.data["reason"] == "missing_required_argument"


def test_production_registry_surface_matches_spec_record() -> None:
    """生产发现面即八工具（default() 汇入 flight+vla）；
    revision == l3-tool-plane.spec.md §1 记录的现行值（G24）。"""
    listing = ToolRegistry.default().list_tools()
    assert {tool["name"] for tool in listing["tools"]} == SPEC_TOOL_NAMES
    assert listing["revision"] == SPEC_REVISION


# ---------------------------------------------------------------------------
# schema 结构校验：正例
# ---------------------------------------------------------------------------


def test_full_waypoint_call_passes_schema() -> None:
    call = normalize(vla_registry(), waypoint_arguments(yaw=0.6, look_forward=False))
    assert call.name == "navigation.vla_nav"
    assert call.arguments["waypoint_world"] == [2.2, 0.0, 1.0]
    assert call.arguments["yaw"] == 0.6
    assert call.arguments["look_forward"] is False


def test_minimal_waypoint_call_passes_schema() -> None:
    call = normalize(vla_registry(), waypoint_arguments())
    assert set(call.arguments) == {"object", "prompt", "waypoint_world"}


# ---------------------------------------------------------------------------
# schema 结构校验：负例
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing", ["object", "prompt", "waypoint_world"])
def test_missing_required_argument_is_rejected(missing: str) -> None:
    arguments = waypoint_arguments()
    del arguments[missing]
    assert reject_reason(vla_registry(), arguments) == "missing_required_argument"


@pytest.mark.parametrize("waypoint", [
    [2.2, 0.0],                       # 2 项（< minItems 3）
    [2.2, 0.0, 1.0, 0.6],             # 4 项（> maxItems 3）
    [2.2, "0.0", 1.0],                # 项非有限数值
    [2.2, 0.0, float("inf")],         # 项非有限数值
])
def test_waypoint_world_cardinality_and_item_type_are_rejected(waypoint: list) -> None:
    assert reject_reason(vla_registry(), waypoint_arguments(waypoint_world=waypoint)) \
        == "argument_out_of_range"


@pytest.mark.parametrize("field,value", [
    ("object", ""),              # minLength=1
    ("prompt", "  "),            # minLength=1（strip 后为空）
    ("yaw", "0.6"),              # 类型不符
    ("yaw", float("nan")),       # 非有限数
    ("look_forward", "yes"),     # boolean
    ("look_forward", 1),         # boolean（int 值不是布尔）
])
def test_field_rule_violations_are_rejected(field: str, value) -> None:
    assert reject_reason(vla_registry(), waypoint_arguments(**{field: value})) \
        == "argument_out_of_range"


@pytest.mark.parametrize("unknown", [{"task_id": 0}, {"bbox_1000": [1, 2, 3, 4]}])
def test_unknown_arguments_are_rejected(unknown: dict) -> None:
    assert reject_reason(vla_registry(), waypoint_arguments(**unknown)) \
        == "unknown_argument"


def test_finite_semantics_stay_in_skill_fail_closed() -> None:
    """waypoint_world 有限性与 yaw 有限性的语义校验不进 schema（spec §1 记录）。

    schema 层只做元数/类型：非有限值（inf/nan）结构上可过 number 校验的
    边界由注册表 number 规则拒绝；其余语义拒绝归
    vla_skill._consume_station_waypoint → invalid_station_waypoint。
    """
    call = normalize(vla_registry(), waypoint_arguments(waypoint_world=[5.0, 5.0, 4.0]))
    assert call.arguments["waypoint_world"] == [5.0, 5.0, 4.0]
