"""zenoh middleware 的 ROS 反馈面（S4a 方案 §4.4）。

只做订阅、``ServiceProxy`` 与消息→纯数据翻译（R5）：3 个 Subscriber 的
topic 名 / ``queue_size`` / ``tcp_nodelay``、reset 服务名与 ``timeout=5.0``、
回调内的字段翻译表达式与迁移前 ``utils/zenoh_rpc.py`` 内联实现逐字一致
（行为不变式见方案 §5.1）；编号映射与状态推进不在本文件——写状态经
middleware 的 ``record_*`` 缝。

懒 import 语义保留（方案 §5.1）：quadrotor_msgs / sensor_msgs / std_msgs /
std_srvs 的导入延迟到 ``attach()`` / ``reset_stack()`` 使用点内，不提升为
模块级导入。
"""

from __future__ import annotations

import json
import os

STACK_RESET_SERVICE = "/agent/stack_reset"


class FeedbackPlane:
    """zenoh middleware 的 ROS 反馈面适配（3 个订阅 + reset 服务 + 消息翻译）。"""

    def __init__(self, middleware) -> None:
        self._middleware = middleware

    def attach(self) -> None:
        """按原参数构造 3 个反馈 Subscriber（调用位点在 middleware.start 序列内不变）。"""
        import rospy
        from quadrotor_msgs.msg import InstructionResMsg
        from sensor_msgs.msg import CompressedImage
        from std_msgs.msg import String

        rospy.Subscriber("/Instruct_res", InstructionResMsg, self._on_instruct_res)
        rospy.Subscriber(
            os.environ.get("LX_GRASP_RESULT_IMAGE_TOPIC", "/agent/grasp_result_image"),
            CompressedImage,
            self._on_grasp_result_image,
            queue_size=1,
            tcp_nodelay=True,
        )
        rospy.Subscriber("/agent_scene_objects", String, self._on_scene_objects_msg)

    def reset_stack(self) -> tuple[bool, str]:
        """调用 /agent/stack_reset（std_srvs/Trigger），等待与调用语义逐字不变。"""
        import rospy
        from std_srvs.srv import Trigger

        proxy = rospy.ServiceProxy(STACK_RESET_SERVICE, Trigger)
        rospy.wait_for_service(STACK_RESET_SERVICE, timeout=5.0)
        resp = proxy()
        return resp.success, resp.message

    def _on_instruct_res(self, msg) -> None:
        call_id = str(getattr(msg, "frame_id", "") or "")
        detail = f"Instruct_res: instruction_type={msg.instruction_type} is_succeed={msg.is_succeed}"
        self._middleware.record_instruct_res(call_id, detail)

    def _on_grasp_result_image(self, msg) -> None:
        call_id = str(getattr(getattr(msg, "header", None), "frame_id", "") or "")
        data = bytes(getattr(msg, "data", b"") or b"")
        self._middleware.record_grasp_image(call_id, data)

    def _on_scene_objects_msg(self, msg) -> None:
        try:
            data = json.loads(str(getattr(msg, "data", "") or ""))
            objects = data.get("objects") or []
        except (ValueError, AttributeError):
            return
        if not isinstance(objects, list):
            return
        active = str(data.get("active", "") or "")
        self._middleware.record_scene_objects(active, objects)
