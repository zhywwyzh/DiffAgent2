"""显式跟踪装配的发现元数据；尚未加入默认生产集合。"""
from dispatcher.tool_plane.model import ToolSpec


def track_specs():
    properties = {key: {'type':'string','minLength':1} for key in ('object','prompt','session_id')}
    properties.update(bbox={'type':'array','items':{'type':'number'},'minItems':4,'maxItems':4},
                      image_stamp={'type':'number','exclusiveMinimum':0})
    return (ToolSpec('navigation.track', '连续跟随目标', '从站端原图种子开始机上跟踪，稳定后停止并报告完成。',
        {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False},
        {'type':'object'}, 'workflow_result', requires_perception=False),)
