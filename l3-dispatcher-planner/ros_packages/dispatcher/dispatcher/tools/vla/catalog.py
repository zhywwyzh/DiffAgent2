"""vla 工具发现面元数据：navigation.vla_nav 的 ToolSpec（P3 起并入生产集合）。

经 dispatcher/tools/registry.py::ToolRegistry.default()（flight_specs() +
vla_specs()，顺序固定）汇入生产发现面；revision 权威记录见
specs/implemented/inner/l3-tool-plane.spec.md §1。

schema 与 DiffAgent2 旧版 tools/registry.py 同名 ToolSpec 逐字对齐（去任务编号，
l3-core-boundary B2/B7/B8；migration-protocol G23）：必填 object/prompt/bbox_1000/
image_stamp；可选 side/distance_m/visible/finish/provider/image_width/image_height。
完成语义 workflow_result；requires_perception=True。0..1000 值域与 x1<x2、y1<y2
的语义校验由 vla_skill._consume_grounded_detection fail-closed，不进 schema。
"""
from dispatcher.tools.model import ToolSpec


def vla_specs():
    """navigation.vla_nav 的发现面元数据（与 flight/catalog.py 同构）。"""
    output = {'type': 'object', 'properties': {}, 'additionalProperties': False}
    grounded = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'object': {'type': 'string', 'minLength': 1},
            'prompt': {'type': 'string', 'minLength': 1},
            'bbox_1000': {
                'type': 'array',
                'items': {'type': 'number'},
                'minItems': 4,
                'maxItems': 4,
            },
            'image_stamp': {'type': 'number', 'exclusiveMinimum': 0},
            'side': {'enum': ['front', 'left', 'right', 'above']},
            'distance_m': {'type': 'number', 'exclusiveMinimum': 0},
            'visible': {'type': 'boolean'},
            'finish': {'type': 'boolean'},
            'provider': {'type': 'string', 'enum': ['station']},
            'image_width': {'type': 'integer', 'exclusiveMinimum': 0},
            'image_height': {'type': 'integer', 'exclusiveMinimum': 0},
        },
        'required': ['object', 'prompt', 'bbox_1000', 'image_stamp'],
    }
    return (
        ToolSpec(
            'navigation.vla_nav',
            'Reach a visual target',
            'Reach a station-grounded visual target: consume the bbox downlinked '
            'by the station (rgb camera stamp bound) and execute the waypoint '
            'chain.',
            grounded,
            output,
            'workflow_result',
            requires_perception=True,
        ),
    )
