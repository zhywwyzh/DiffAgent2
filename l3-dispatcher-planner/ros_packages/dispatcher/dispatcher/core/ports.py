"""core 端口协议集合（S3 方案 §4.5）。

只声明端口，不含实现、不含 rospy、不含 ROS 消息类型（R2）：
engine 与 core 只依赖本文件的 Protocol；ROS 实现全部落在
dispatcher/ros_adapter/（由 composition root 构造并注入，S3 §4.7）。
端口命名与 SkillHost（dispatcher/tools/skill_api.py）不重名、不增删。
"""

from __future__ import annotations

from typing import Protocol


class CoreChannels(Protocol):
    """四类 core 通道（B3 语义白名单）的 ROS 出站端口。"""

    def publish_emergency_stop(self) -> None: ...                 # Empty → ~emergency_stop_topic
    def publish_if_handle_yaw(self, enabled: bool) -> None: ...    # Bool  → if_handle_yaw
    def publish_command_content(self, payload: str) -> None: ...   # String→ monitor/command_content
    def publish_task_phase(self, payload: str) -> None: ...        # String→ ~task_phase_topic


class Ticker(Protocol):
    def sleep(self) -> None: ...


class RuntimeClock(Protocol):
    """节律与关停判定（O1 / STOP 所需的最小运行端口）。"""

    def rate(self, hz: float) -> Ticker: ...
    def is_shutdown(self) -> bool: ...
    def request_shutdown(self, reason: str) -> None: ...


class LogSink(Protocol):
    """日志端口：为让 engine/core 零 rospy 而必需（否则直调 rospy 日志仍命中 G7 检索）。"""

    def info(self, msg: str, *args: object) -> None: ...
    def warn(self, msg: str, *args: object) -> None: ...
    def err(self, msg: str, *args: object) -> None: ...
    def warn_throttle(self, period: float, msg: str, *args: object) -> None: ...
