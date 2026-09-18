"""四类 core 通道的 ROS 实现 + 最小运行端口（S3 方案 §4.6）。

本文件是 engine/core 零 rospy（G7/G8）的唯一代价点：急停、if_handle_yaw、
命令内容监控、任务相位四类通道的 rospy.Publisher 与 ROS 消息类型只允许
出现在这里（R1/R4 裁决，总纲 §4.5）；topic 名、默认值、消息类型、
queue_size 与 payload 发布表达式。
同文件承载最小运行端口实现（RosRuntimeClock / RosLogSink）——S4 的
clock_ros.py 只服务装配/传输面（control_plane/zenoh_rpc），不得再迁本
文件的运行端口（禁止二次搬迁）。
"""

from __future__ import annotations

import rospy
from std_msgs.msg import String, Empty, Bool


class RosCoreChannels:
    """四类 core 通道（B3 白名单）的 ROS 出站实现。"""

    def __init__(self) -> None:
        # 急停：~emergency_stop_topic（默认 /command/emergency_stop，空串回退默认）
        self.emergency_stop_topic = (
            str(rospy.get_param("~emergency_stop_topic", "/command/emergency_stop")).strip()
            or "/command/emergency_stop"
        )
        self.emergency_stop_pub = rospy.Publisher(  # 急停发布器
            self.emergency_stop_topic, Empty, queue_size=10
        )

        self.if_handle_yaw_pub = rospy.Publisher(  # 底层 ego planner yaw 处理开关发布器
            "if_handle_yaw", Bool, queue_size=10
        )

        ## 监控状态发布
        self.command_content_pub = rospy.Publisher(  # 监控：命令内容
            "monitor/command_content", String, queue_size=10
        )
        self.task_phase_pub = rospy.Publisher(  # 任务生命周期（l4 桥消费）
            rospy.get_param("~task_phase_topic", "/agent_task_phase"),
            String,
            queue_size=10,
        )

    def publish_emergency_stop(self) -> None:
        """发布急停（std_msgs/Empty）。"""
        self.emergency_stop_pub.publish(Empty())

    def publish_if_handle_yaw(self, enabled: bool) -> None:
        """发布底层 ego planner yaw 处理开关（std_msgs/Bool）。"""
        msg = Bool()
        msg.data = enabled
        self.if_handle_yaw_pub.publish(msg)

    def publish_command_content(self, payload: str) -> None:
        """发布命令内容监控（std_msgs/String）。"""
        self.command_content_pub.publish(String(data=payload))

    def publish_task_phase(self, payload: str) -> None:
        """发布任务生命周期事件（std_msgs/String JSON）。"""
        self.task_phase_pub.publish(String(data=payload))


class RosRuntimeClock:
    """节律与关停的最小运行端口实现（rospy.Rate / is_shutdown / signal_shutdown）。"""

    def rate(self, hz: float):
        return rospy.Rate(hz)

    def is_shutdown(self) -> bool:
        return rospy.is_shutdown()

    def request_shutdown(self, reason: str) -> None:
        rospy.signal_shutdown(reason)


class RosLogSink:
    """rospy 日志端口实现（info/warn/err/warn_throttle）。"""

    def info(self, msg: str, *args: object) -> None:
        rospy.loginfo(msg, *args)

    def warn(self, msg: str, *args: object) -> None:
        rospy.logwarn(msg, *args)

    def err(self, msg: str, *args: object) -> None:
        rospy.logerr(msg, *args)

    def warn_throttle(self, period: float, msg: str, *args: object) -> None:
        rospy.logwarn_throttle(period, msg, *args)
