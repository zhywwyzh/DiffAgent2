"""技能接口契约（设计文档 design-dispatcher-skill-refactor.md §2 的固化）。

P2 冻结：SkillVerdict / Skill / SkillHost。实现者在 P3 逐个落地
（graph_edit → flight → scene_nav → vla）；引擎壳对 SkillHost 的
结构化适配在 P3 完成，本模块仅为契约工件。

P3.4 定型注记：
- Skill 新增 wait_action_tick：WAIT_ACTION_FINISH 轮询期的技能钩子
  （reacquire 到期推进等迁入；默认空实现语义）。
P3.5 拆解注记（历史）：原 SkillHost.set_pending_action 全 knob 口拆为
arm_action 通用记账口（归属快照/元数据缓存/代次推进/切 WAIT_ACTION_FINISH，
不发 goal）+ publish_action / publish_waypoint_nav_action 航点传输口，发布
编排（记账→记录→发 goal）下放至 waypoint 驱动技能（vla/flight 的
_dispatch_waypoint），替代 P3.4 的显式全 knob 单口设计。
P3.7 收窄注记：publish_action / publish_waypoint_nav_action 双传输口进一步
下沉删除（一两个技能独有的航点塑形动作模型不进引擎壳），改为
send_task_goal 通用航点传输原语 + 技能内联塑形（yaw/clamp/簿记/
mode_burst 在 vla/flight 的 _dispatch_waypoint 内完成）；publish_mode_burst
作为通用规划器模式发布口一并登记。
- 代次守卫端口公开：capture_task_generation / task_generation_valid
  （阻塞 VLM 调用前后的快照/校验对）。
- get_fast_rgb 返回值注记修正为二元组 (image, stamp)（与
  base_policy.get_fast_rgb 实现一致，原「五元组」为笔误）。
- vlm 属性类型注记为 VlmFacade（P3.4 落地，TYPE_CHECKING 引用避免
  契约模块拖入 VLM 重依赖链）。
- 新增共享字段声明块：技能经 host 直读的壳机械字段在此显式声明。
- P3.6 增补：Skill 新增三个会话生命周期钩子（on_new_prompt_task /
  on_global_stop / on_plan_cycle_reset），壳经 _notify_skills 注册表广播，
  替代此前对 _vla_skill/_scene_nav_skill 的硬编码点名；新增 SkillBase
  模板基类提供全部钩子默认实现（新技能只覆写关心的钩子）。
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from dispatcher.recording import RecordingService
    from dispatcher.tools.model import SkillCommand
    from dispatcher.tools.vla.vlm_facade import VlmFacade


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
        # P3.2 细化：DISPATCH 态每 tick 携带队首命令调用（技能不再回读引擎队列）；
        # 返回 True=已处理（continue），False=未命中（壳回 WAIT_FOR_MISSION）
    def wait_action_tick(self) -> None: ...
        # P3.4 增补：WAIT_ACTION_FINISH 轮询期每 tick 调用（完成门判定之前），
        # 技能在等待期间仍需推进的子状态机挂这里（VLA reacquire 到期重启搜索等）；
        # 无等待期事务的技能空实现即可
    def action_done_gate(self) -> bool | None: ...
        # P3.2 增补：WAIT_ACTION_FINISH 轮询的技能完成门（return topo / 后续
        # scene_nav 的 FSM 判停同构）。None=本技能无门（走壳通用 action_finish
        # 判定）；True/False=技能裁决完成与否
    def on_action_result(self, result: Any) -> SkillVerdict: ...
    def on_cancel(self) -> None: ...
    # P3.6 会话生命周期钩子：壳在三个通用生命周期点遍历注册表广播
    # （engine._notify_skills），技能按需覆写（无状态技能走 SkillBase 默认空实现）
    def on_new_prompt_task(self) -> None: ...
        # 新 AgentPrompt 准入（_start_prompt_task）：技能重置任务级会话态
        # （vla 清搜索计数；scene_nav 重置会话等待态）
    def on_global_stop(self) -> None: ...
        # 全局停止（_enter_global_stop，软/硬急停 + prompt 覆盖）：技能解除
        # 在途子机制（vla 停动画/重置搜索会话/解除 reacquire 挂表）
    def on_plan_cycle_reset(self) -> None: ...
        # 新 DISPATCH 周期（_reset_plan_cycle_if_needed，command_status 回 RUNNING）：
        # 技能重置规划上下文（vla first_* 重采样 + 搜索会话重置）


class SkillBase:
    """技能模板基类（P3.6）：全部 Skill 钩子提供默认实现，新技能继承后只
    覆写关心的钩子；协议加新钩子时只在此补默认实现，存量技能零改动
    （双源一致性由 tests/skill-contract 契约测试锁定）。

    语义默认（覆写前确认默认语义符合本技能）：
    - plan_tick 默认 False = 本技能不处理该命令（壳回 WAIT_FOR_MISSION）；
    - on_action_result 默认 IDLE = 记 task_completed 回 WAIT_FOR_MISSION。

    空操作默认：on_start / wait_action_tick / on_cancel /
    on_new_prompt_task / on_global_stop / on_plan_cycle_reset。

    端点规则：技能可在构造/装配期自建自己的 publisher/subscriber（先例
    SceneNavSkill.subscribe_once），engine 不为每种指令通道开 host 端口。
    指令驱动技能（tracking/exploration：发一条指令、下层决策一系列航点）
    据此接入——arm_action 通用记账 + 自有通道，壳零改动。

    类属性 name / requires_perception / synchronous 由子类覆写声明。
    """

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
    # ------------------------------------------------------------------
    # 共享字段（壳引擎直挂属性，技能经 host 只读/机械写，P3.4 显式声明）
    # ------------------------------------------------------------------
    dispatcher_state: Any                # 六态骨架当前态（DISPATCHER_STATE 枚举值）
    action_in_progress: bool      # 动作执行中标志（技能武装动作态时置位）
    action_finish: bool           # action result 到达标志（armed/disarm 机械写）
    action_start_time: float      # 当前动作开始时刻（最小等待判定基准）
    # 航点塑形共享字段（P3.7 登记：vla/flight _dispatch_waypoint 内联塑形读写）
    waypoint: Any                 # 当前导航目标点（机械写，np.ndarray）
    last_published_waypoint: Any  # 最近一次成功发布的动作目标点（机械写）
    min_height: float             # 只读配置：最低允许飞行高度（clamp 下界）
    max_height: float             # 只读配置：最高允许飞行高度（clamp 上界）
    planner_ego_mode_value: int   # 只读配置：ego 模式枚举值（mode_burst 入参）

    # 感知（base_policy 共享层，各技能共用）
    def latest_frame(self) -> Any: ...        # Frame | None，封装 _latest_prompt_frame
    def get_fast_rgb(self) -> tuple: ...      # 快通道 RGB 二元组 (image, stamp)
    # 记录（P2 显式服务对象；几何服务 P3.7 起 VLA 私有——见 tools/vla/geometry.py，
    # vla/grasp 各自持有实例，不再作为 SkillHost 端口）
    recording: RecordingService
    # VLM（VlmFacade 于 P3.4 落地，封装 open_serve_* 函数族）
    vlm: VlmFacade
    # 行动（P3.5 拆解，P3.7 收窄）：arm_action 为通用记账口（归属快照/元数据
    # 缓存/代次推进/切 WAIT_ACTION_FINISH，不发 goal）；send_task_goal 为通用
    # 航点传输原语（构造 TaskActionGoal → /mission/task，含 dry-run 劫持），
    # 航点塑形（yaw/clamp/簿记/mode_burst）由调用方技能内联完成——原
    # publish_action / publish_waypoint_nav_action 双传输口已下沉删除。
    # arm_action 返回 bool：False=动作被拒绝（任务停止/无效）。
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
        # 通用航点传输原语：构造 TaskActionGoal → /mission/task（含 dry-run 劫持）；
        # 塑形（yaw/clamp/簿记/mode_burst）由调用方技能完成
    def publish_mode_burst(self, mode_value: int, repeat: int = None, interval: float = None) -> None: ...
        # 通用规划器模式发布（ego/nav 切模可靠性）
    # 任务结果（P3.6 端口化：原 engine._scene_nav_pending_result 场景导航
    # 专属字段泛化——技能暂存任务级结果，壳在 done 相位取走上报）
    def stash_task_result(self, result: dict) -> None: ...
        # 技能暂存任务级结果（如 scene map_search 的 objs），随 done 相位上报
    def pop_task_result(self) -> Any: ...
        # 壳取走并清空暂存结果（_load_next_prompt 队尽 done 分支）
    # 事件
    def publish_phase(self, phase: str, **kw: Any) -> None: ...
    # 任务态
    def fail_sequence(self, reason: str) -> None: ...   # _task_sequence_failed=True 的唯一写口
    # 代次守卫（P3.4 公开）：阻塞 VLM 调用前 capture、返回后 valid 校验，
    # 急停/任务覆盖导致的过期结果由技能据此丢弃
    def capture_task_generation(self) -> int: ...
    def task_generation_valid(self, generation: int, *, reason: str = "") -> bool: ...
    # prompt 队列机械操作（P3.2 增补：装哪条由技能裁决，壳只执行）
    def consume_head_prompt(self) -> None: ...   # 本条 prompt 已转化为动作：pop 队首 + command_status=ADVANCE_READY
    def advance_prompt(self) -> None: ...        # 本条 prompt 无动作直接结束：_advance_to_next_prompt
