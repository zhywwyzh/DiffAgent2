"""ROS 仿真重置端口；工具专属反馈链已删除。"""

STACK_RESET_SERVICE = "/agent/stack_reset"


class FeedbackPlane:
    """提供通用栈重置服务，不订阅未实现工具的反馈。"""

    def __init__(self, middleware, on_reset=None) -> None:
        self._middleware = middleware
        self._on_reset = on_reset

    def reset_stack(self) -> tuple[bool, str]:
        import rospy
        from std_srvs.srv import Trigger

        proxy = rospy.ServiceProxy(STACK_RESET_SERVICE, Trigger)
        rospy.wait_for_service(STACK_RESET_SERVICE, timeout=5.0)
        resp = proxy()
        if resp.success and self._on_reset is not None:
            self._on_reset()
        return resp.success, resp.message
