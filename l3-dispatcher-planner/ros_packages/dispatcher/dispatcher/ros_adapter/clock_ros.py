"""装配面最小 ROS 端口（S4a 方案 §4.4）：关停探测 / 日志 / 进程生命周期。

只做透传（R5）：关停探测、日志文本、``init_node``/``spin`` 与迁移前
``utils/control_plane.py``、``dispatcher_node.py`` 内的 rospy 直调逐字
一致（行为不变式见方案 §5.1）；不含线程循环与状态推进（循环仍在
``utils/control_plane.py``）。

不建时钟端口（``RosClock``）：当前三个消费方无时钟消费者，预造即桩
（方案 §7.1 登记，待后续消费方出现时补建）。
"""

from __future__ import annotations

import rospy


class RosShutdown:
    """关停探测端口：透传 rospy.is_shutdown()。"""

    def is_shutdown(self) -> bool:
        return rospy.is_shutdown()


class RosLog:
    """日志端口：文本与参数逐字透传给 rospy 日志函数。"""

    def warn(self, msg: str, *args: object) -> None:
        rospy.logwarn(msg, *args)

    def info(self, msg: str, *args: object) -> None:
        rospy.loginfo(msg, *args)

    def err(self, msg: str, *args: object) -> None:
        rospy.logerr(msg, *args)


class RosNode:
    """进程生命周期端口（组合根专用）：init_node / spin 透传。"""

    def init_node(self, name: str, anonymous: bool) -> None:
        rospy.init_node(name, anonymous=anonymous)

    def spin(self) -> None:
        rospy.spin()
