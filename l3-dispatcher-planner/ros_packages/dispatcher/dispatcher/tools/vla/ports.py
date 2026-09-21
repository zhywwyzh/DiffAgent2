"""VLA 技能宿主端口：通用 SkillHost 端口（航点执行器形态）。

l3-skill-contract.spec.md §7/§10：VLA 技能使用通用 SkillHost 端口
（最新帧、动作武装、航点下发、模式发布、相位上报、任务结果暂存、
失败终止、代次守卫、队列机械操作），不新增飞行专属端口；航点塑形
（高度限幅、mode 脉冲）由技能内联完成。机上不做 VLM/bbox 推理，也不做
几何解算：waypoint_world 由站端解算后随调用下行，本协议不含几何原语源。

实现见 dispatcher/execution/skill_host.py::VlaSkillHost（与
DispatcherFlightHost 同文件的执行宿主，动作出海共用 WaypointExecution）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class VlaHostConfig:
    """VLA 宿主只读配置与出站回调。

    publish_planner_mode 为模式脉冲的出站回调（旧链 planner_mode_topic 的
    Int32 发布）。EGO 直连栈当前没有模式触发通道，装配层必须显式接通真实
    出口或提供受控空实现；未接通时 publish_mode_burst 直接失败，
    不静默降级。
    """

    min_height: float = 0.0  # 最低允许飞行高度（clamp 下界，米）
    max_height: float = 1.8  # 最高允许飞行高度（clamp 上界，米）
    planner_ego_mode_value: int = 1  # ego 模式枚举值（mode_burst 入参）
    planner_mode_repeat: int = 3  # 模式脉冲重复次数
    planner_mode_interval: float = 0.03  # 模式脉冲间隔（秒）
    publish_planner_mode: Callable[[int], None] | None = None


class VlaSkillHost(Protocol):
    """VLA 技能宿主端口；成员签名与 tools/skill_api.py::SkillHost 通用端口对齐。"""

    min_height: float  # 只读配置：最低允许飞行高度（clamp 下界）
    max_height: float  # 只读配置：最高允许飞行高度（clamp 上界）
    planner_ego_mode_value: int  # 只读配置：ego 模式枚举值（mode_burst 入参）

    def latest_frame(self) -> Any: ...                       # 最新感知帧（Frame | None）；仅距离过近判定消费，可为 None

    def arm_action(                                          # 通用动作记账：归属快照、代次推进、切至等待完成态（不发 goal）
        self,
        *,
        action_name: str = "",
        prompt_raw: str = "",
        instruction_type: Any = None,
        owner: Any = None,
    ) -> bool: ...

    def send_task_goal(                                      # 航点下发（传输原语，塑形由技能内联完成后传入）
        self, x: float, y: float, z: float, yaw: Any, yaw_source: str = "unspecified"
    ) -> None: ...

    def publish_mode_burst(                                  # 按设定频率连续发布规划器模式，提升切模可靠性
        self, mode_value: int, repeat: int = None, interval: float = None
    ) -> None: ...

    def poll_result(self) -> Any: ...                        # 轮询共享执行（WaypointExecution）；结果到达置 action_finish
    def cancel_execution(self, owner=None) -> None: ...      # 取消当前执行（归属校验后发布保持意图）
    def stash_task_result(self, result: dict) -> None: ...   # 技能暂存任务级结果（随 done 相位上报）
    def publish_phase(self, phase: str, **kw: Any) -> None: ...  # 相位/终态上报
    def fail_sequence(self, reason: str) -> None: ...        # 任务序列失败唯一写入口（invalid_station_waypoint 经 reason 传入）
    def capture_task_generation(self) -> int: ...            # 阻塞调用前做任务代次快照
    def task_generation_valid(self, generation: int, *, reason: str = "") -> bool: ...  # 返回后校验代次未过期
    def consume_head_prompt(self) -> None: ...               # 本条 prompt 已转化为动作：置 ADVANCE_READY 并弹出队首
    def advance_prompt(self) -> None: ...                    # 本条 prompt 无动作直接结束：推进到下一条
