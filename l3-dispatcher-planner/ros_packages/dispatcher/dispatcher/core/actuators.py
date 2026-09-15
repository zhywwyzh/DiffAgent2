"""planner 动作面（S3 方案 §2.8/§5）：yaw 模式切换指令。

自 engine.py 迁出（零语义变更）：if_handle_yaw topic 名与发布值、
变更守卫（getattr(..., True)==enabled 早退）保持不变；发布经
CoreChannels 端口（if_handle_yaw_pub 已迁 ros_adapter，S3 §4.6）。
守卫初值（原 engine 配置属性 if_handle_yaw，UAV_POLICY_DEFAULTS 默认
True，yaml 无同名键覆盖——迁移前实测）经构造注入。
"""

from __future__ import annotations

from dispatcher.core.ports import CoreChannels
from dispatcher.core.telemetry import RunTelemetry


class PlannerActuators:
    """planner 动作面：底层 ego planner 的 yaw 处理开关。"""

    def __init__(
        self,
        channels: CoreChannels,
        runlog: RunTelemetry,
        if_handle_yaw: bool = True,
    ) -> None:
        self.channels = channels
        self.runlog = runlog
        # 当前 yaw 模式状态（初值 = engine 配置快照，见模块 docstring）
        self.if_handle_yaw = if_handle_yaw

    def set_if_handle_yaw(self, enabled: bool) -> None:
        """按任务类型切换底层 ego planner 的 yaw 处理逻辑。"""
        enabled = bool(enabled)
        if bool(getattr(self, "if_handle_yaw", True)) == enabled:
            return
        self.channels.publish_if_handle_yaw(enabled)
        self.if_handle_yaw = enabled
        self.runlog.info("Publish if_handle_yaw=%s", "true" if enabled else "false")
