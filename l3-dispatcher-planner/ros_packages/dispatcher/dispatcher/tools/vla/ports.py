"""VLA 能力端口：通用动作生命周期、新鲜执行状态和只读家族配置。

端口归 l3-skill-contract §10；实现归 execution/skill_host.py。
高度与停稳配置由 execution_config 唯一提供；技能负责位置、偏航及贴地腿顺序。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from dispatcher.execution.ports import FlightConfig, FlightState


@dataclass(frozen=True)
class VlaHostConfig:
    """VLA 宿主只读配置与出站回调。

    publish_planner_mode 为模式脉冲的出站回调（旧链 planner_mode_topic 的
    Int32 发布）。EGO 直连栈当前没有模式触发通道，装配层必须显式接通真实
    出口或提供受控空实现；未接通时 publish_mode_burst 直接失败，
    不静默降级。
    """

    final_approach_height_m: float = 0.1  # 贴地腿相对地面高度
    planner_ego_mode_value: int = 1  # ego 模式枚举值（mode_burst 入参）
    planner_mode_repeat: int = 3  # 模式脉冲重复次数
    planner_mode_interval: float = 0.03  # 模式脉冲间隔（秒）
    publish_planner_mode: Callable[[int], None] | None = None


    def __post_init__(self):
        if not math.isfinite(self.final_approach_height_m) or self.final_approach_height_m <= 0:
            raise ValueError("invalid_final_approach_height")


class VlaSkillHost(Protocol):
    """VLA 家族端口，在通用生命周期上增加新鲜状态和贴地意图。"""

    min_height: float  # 只读配置：最低允许飞行高度（clamp 下界）
    max_height: float  # 只读配置：最高允许飞行高度（clamp 上界）
    planner_ego_mode_value: int  # 只读配置：ego 模式枚举值（mode_burst 入参）

    execution_config: FlightConfig  # 共享 FlightConfig，高度和停稳参数唯一来源
    final_approach_height_m: float

    def state(self) -> FlightState: ...  # 已校验新鲜度、坐标系和有限性的 FlightState

    def arm_action(                                          # 通用动作记账：归属快照、代次推进、切至等待完成态（不发 goal）
        self,
        *,
        action_name: str = "",
        prompt_raw: str = "",
        instruction_type: Any = None,
        owner: Any = None,
    ) -> bool: ...

    def send_task_goal(                                      # 航点下发（传输原语，塑形由技能内联完成后传入）
        self, x: float, y: float, z: float, yaw: Any, yaw_source: str = "unspecified",
        *, ground_approach: bool = False, yaw_low_speed: bool = False
    ) -> None: ...

    def publish_mode_burst(                                  # 按设定频率连续发布规划器模式，提升切模可靠性
        self, mode_value: int, repeat: int = None, interval: float = None
    ) -> None: ...

    def poll_result(self) -> Any: ...                        # 轮询家族航点执行（VlaWaypointExecution）；结果到达置 action_finish
    def cancel_execution(self, owner=None) -> None: ...      # 取消当前执行（归属校验后发布保持意图）
    def stash_task_result(self, result: dict) -> None: ...   # 技能暂存任务级结果（随 done 相位上报）
    def publish_phase(self, phase: str, **kw: Any) -> None: ...  # 相位/终态上报
    def fail_sequence(self, reason: str) -> None: ...        # 任务序列失败唯一写入口（invalid_station_waypoint 经 reason 传入）
    def capture_task_generation(self) -> int: ...            # 阻塞调用前做任务代次快照
    def task_generation_valid(self, generation: int, *, reason: str = "") -> bool: ...  # 返回后校验代次未过期
    def consume_head_prompt(self) -> None: ...               # 本条 prompt 已转化为动作：置 ADVANCE_READY 并弹出队首
    def advance_prompt(self) -> None: ...                    # 本条 prompt 无动作直接结束：推进到下一条
