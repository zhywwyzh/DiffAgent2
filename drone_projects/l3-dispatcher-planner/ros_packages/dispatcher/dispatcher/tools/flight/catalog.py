"""基础飞行元数据；完整验收前只由测试显式装配。"""
from dispatcher.tool_plane.model import ToolSpec


def flight_specs():
    empty = {'type': 'object', 'properties': {}, 'additionalProperties': False}
    translate = {'type': 'object', 'additionalProperties': False,
                 'properties': {'direction': {'type': 'string', 'enum': ['forward', 'backward', 'left', 'right']},
                                'distance_m': {'type': 'number', 'exclusiveMinimum': 0}},
                 'required': ['direction', 'distance_m']}
    rotate = {'type': 'object', 'additionalProperties': False,
              'properties': {'yaw_delta_deg': {'type': 'number'}}, 'required': ['yaw_delta_deg']}
    result = {'type': 'object', 'properties': {'completion': {'type': 'string'}},
              'required': ['completion'], 'additionalProperties': False}
    return tuple(ToolSpec('basic_flight.' + name, title, description, schema, result, completion)
                 for name, title, description, schema, completion in (
                     ('takeoff', '起飞', '转交起飞请求，不表示已升空。', empty, 'forwarded'),
                     ('land', '降落', '转交当前位置降落请求。', empty, 'forwarded'),
                     ('translate', '平移', '按当前机体水平朝向平移指定距离。', translate, 'action_result'),
                     ('rotate', '旋转', '原地有符号偏航，左正右负，单位度。', rotate, 'action_result'),
                     ('return', '返航', '返回本次飞行起飞点的水平位置，不自动降落。', empty, 'action_result'),
                     ('emergency_stop', '急停', '请求停止并生成保持命令。', empty, 'forwarded')))
