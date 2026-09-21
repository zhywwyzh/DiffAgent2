"""技能身份、默认生命周期与通用宿主端口；生产技能由实际实现提供。"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from dispatcher.tool_plane.model import SkillCommand


class SkillVerdict(Enum):       # post_action 的裁决，替代 _handle_post_action 内部分支
    REPLAN = "replan"           # 回 DISPATCH，同 prompt 重规划（原 replan_cmd 分支）
    ADVANCE = "advance"         # 装下一条 prompt / 队尽发 done
    IDLE = "idle"               # 回 WAIT_FOR_MISSION（原 task_completed 分支）
    NEW_ACTION = "new_action"   # 技能已自行武装并发布新动作（如 landing 贴地腿）→ WAIT_ACTION_FINISH


class Skill(Protocol):
    name: str
    requires_perception: bool   # 是否需要感知帧（P1 起随 SkillCommand 携带）
    synchronous: bool           # P3.1 增补：True = 同步执行不入队（graph_edit）；False = 经 prompt 队列进 DISPATCH

    def on_start(self, cmd: SkillCommand) -> None: ...
    def plan_tick(self, cmd: SkillCommand) -> bool: ...
    def wait_action_tick(self) -> None: ...
    def action_done_gate(self) -> bool | None: ...
    def on_action_result(self, result: Any) -> SkillVerdict: ...
    def on_cancel(self) -> None: ...
    def on_new_prompt_task(self) -> None: ...
    def on_global_stop(self) -> None: ...
    def on_plan_cycle_reset(self) -> None: ...


class SkillBase:
    """技能生命周期默认实现；具体能力覆写所需钩子并声明身份。"""

    name = "base"
    requires_perception = False
    synchronous = False

    def __init__(self, host) -> None:
        self._host = host

    def on_start(self, cmd: SkillCommand) -> None:
        pass

    def plan_tick(self, cmd: SkillCommand) -> bool:
        return False

    def wait_action_tick(self) -> None:
        pass

    def action_done_gate(self) -> bool | None:
        return None

    def on_action_result(self, result: Any) -> SkillVerdict:
        return SkillVerdict.IDLE

    def on_cancel(self) -> None:
        pass

    def on_new_prompt_task(self) -> None:
        pass

    def on_global_stop(self) -> None:
        pass

    def on_plan_cycle_reset(self) -> None:
        pass


class SkillHost(Protocol):
    dispatcher_state: Any                # 六态骨架当前态（DISPATCHER_STATE 枚举值）
    action_in_progress: bool      # 动作执行中标志（技能武装动作态时置位）
    action_finish: bool           # action result 到达标志（armed/disarm 机械写）
    action_start_time: float      # 当前动作开始时刻（最小等待判定基准）
    waypoint: Any                 # 当前导航目标点（机械写，np.ndarray）
    last_published_waypoint: Any  # 最近一次成功发布的动作目标点（机械写）
    min_height: float             # 只读配置：最低允许飞行高度（clamp 下界）
    max_height: float             # 只读配置：最高允许飞行高度（clamp 上界）
    planner_ego_mode_value: int   # 只读配置：ego 模式枚举值（mode_burst 入参）

    def latest_frame(self) -> Any: ...        # Frame | None，封装 _latest_prompt_frame
    def arm_action(
        self,
        *,
        action_name: str = "",
        prompt_raw: str = "",
        replan_cmd: Any = None,
        replan_reason: Any = None,
        instruction_type: Any = None,
        owner: Any = None,
    ) -> bool: ...
    def send_task_goal(
        self, x: float, y: float, z: float, yaw: Any, yaw_source: str = "unspecified"
    ) -> None: ...
    def publish_mode_burst(self, mode_value: int, repeat: int = None, interval: float = None) -> None: ...
    def stash_task_result(self, result: dict) -> None: ...
    def pop_task_result(self) -> Any: ...
    def publish_phase(self, phase: str, **kw: Any) -> None: ...
    def fail_sequence(self, reason: str) -> None: ...   # _task_sequence_failed=True 的唯一写口
    def capture_task_generation(self) -> int: ...
    def task_generation_valid(self, generation: int, *, reason: str = "") -> bool: ...
    def consume_head_prompt(self) -> None: ...   # 本条 prompt 已转化为动作：pop 队首 + command_status=ADVANCE_READY
    def advance_prompt(self) -> None: ...        # 本条 prompt 无动作直接结束：_advance_to_next_prompt
