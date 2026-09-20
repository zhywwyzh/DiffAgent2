"""工具（技能）层：技能协议（skill_api.py）与各任务能力家族实现。

目录名 tools 为开发组协定名；契约归属 l3-dispatcher/skill-contract，
平面划分见 l3-dispatcher/package-layout。本包 __init__ 不导出家族，
技能由装配根显式注册，避免被隐式 import；调用面基础设施归 dispatcher/tool_plane/。
"""

__all__ = []
