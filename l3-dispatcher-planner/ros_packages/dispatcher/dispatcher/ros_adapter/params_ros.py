"""ROS 私有参数装载与读取（S4a 方案 §4.4，config 的 ROS 面）。

只做参数读写翻译（R5）：写入集合与顺序、键名 ``~{key}``、默认值与
迁移前 ``utils/config.py::set_ros_params`` / ``dispatcher_node.py`` 内
的 rospy 直调逐字一致（行为不变式见方案 §5.1）。
"""

from __future__ import annotations

from typing import Any

import rospy


def set_ros_params(params: dict) -> None:
    """把字典写入当前节点私有参数空间(~key)，键名与顺序逐字不变。"""
    for key, value in params.items():
        rospy.set_param(f"~{key}", value)


def get_private_param(name: str, default: Any = None) -> Any:
    """读当前节点私有参数 ~name，缺失时返回 default。"""
    return rospy.get_param(f"~{name}", default)


def get_node_name() -> str:
    """读当前节点全名（rospy.get_name 的最小端口化）。"""
    return rospy.get_name()
