"""vla 工具发现面元数据：navigation.vla_nav 的 ToolSpec（waypoint 载荷）。

经 dispatcher/tool_plane/registry.py::ToolRegistry.default()（flight_specs() +
vla_specs()，顺序固定）汇入生产发现面；revision 权威记录见
specs/implemented/inner/l3-tool-plane.spec.md §1。

waypoint schema（与 DiffAgent2 旧版 tools/registry.py 对齐，去任务编号）：
站端以「累积点云（最新，世界系）+ 位姿按帧时戳插值 + VLM bbox」解算
waypoint_world 后下发；机上为航点执行器。必填 object/prompt/waypoint_world
（恰 3 项）；yaw/look_forward 可选。完成语义 action_result；
requires_perception=False（机上仅需 odometry，由共享执行校验）。
waypoint_world 有限性与 yaw 有限性由 vla_skill._consume_station_waypoint
fail-closed，不进 schema。
"""
from dispatcher.tool_plane.model import ToolSpec


def vla_specs():
    """navigation.vla_nav 的发现面元数据（与 flight/catalog.py 同构）。"""
    output = {'type': 'object', 'properties': {}, 'additionalProperties': False}
    waypoint = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'object': {'type': 'string', 'minLength': 1},
            'prompt': {'type': 'string', 'minLength': 1},
            'waypoint_world': {
                'type': 'array',
                'items': {'type': 'number'},
                'minItems': 3,
                'maxItems': 3,
            },
            'yaw': {'type': 'number'},
            'look_forward': {'type': 'boolean'},
        },
        'required': ['object', 'prompt', 'waypoint_world'],
    }
    return (
        ToolSpec(
            'navigation.vla_nav',
            'Reach a visual target',
            'Reach a station-grounded visual target: consume the '
            'station-resolved waypoint (world frame, computed on the '
            'station from the grounded bbox + accumulated cloud + '
            'pose@image_stamp) and execute it as one terminal leg.',
            waypoint,
            output,
            'action_result',
            requires_perception=False,
        ),
    )
