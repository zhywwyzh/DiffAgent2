"""执行宿主的通用 FSM/动作记账实现（飞行 / VLA）；不承载工具名分支。"""
import time
from dispatcher.support.state import COMMAND_STATUS, COMMAND_TYPE, DISPATCHER_STATE
from dispatcher.execution.ports import Goal
from dispatcher.tools.vla.ports import VlaHostConfig


class DispatcherFlightHost:
    def __init__(self, engine, execution, session):
        self.engine = engine
        self.execution = execution
        self.session = session
        self.config = execution.config

    def state(self):
        try:
            state = self.execution.state()
        except RuntimeError:
            self.session.reset()
            raise
        self.session.observe(state)
        return state

    def origin(self):
        return self.session.origin(self.state())

    def start_goal(self, owner, goal):
        engine = self.engine
        engine.skills.snapshot_owner()
        if engine.skills.owner_skill() is not owner:
            raise RuntimeError('action_owner_mismatch')
        gate = engine.action_gate
        gate._action_generation += 1
        gate._action_finish_generation = -1
        gate._last_action_result = None
        engine.action_start_time = time.time()
        engine.action_finish = False
        engine.action_in_progress = True
        engine.waypoint = goal.position
        gate.pending_action.waypoint = goal.position
        gate.pending_action.nav_yaw = goal.yaw
        engine.ledger.set_state(DISPATCHER_STATE.WAIT_ACTION_FINISH, reason='action:armed')
        try:
            self.execution.start(goal)
            engine.last_published_waypoint = goal.position
        except Exception:
            engine.action_in_progress = False
            raise

    def poll_result(self):
        self.state()
        result = self.execution.poll()
        if result is not None:
            gate = self.engine.action_gate
            gate._last_action_result = result
            gate._action_finish_generation = gate._action_generation
            self.engine.action_finish = True
        return result

    def cancel_execution(self, owner=None):
        if owner is None or self.engine.skills.owner_skill() is owner:
            self.execution.cancel()

    def request_takeoff(self):
        self.session.prepare_takeoff(self.state())
        try:
            self.execution.ports.takeoff()
        except Exception:
            self.session.reject_takeoff()
            raise

    def request_land(self):
        self.state()
        self.execution.ports.land()

    def request_safety_stop(self):
        self.execution.stop()

    def publish_phase(self, phase, **kwargs):
        self.engine.task_phase.publish(phase, **kwargs)

    def fail_sequence(self, reason):
        try:
            self.execution.cancel()
        finally:
            self.engine.ledger.fail_sequence(reason)
            self.publish_phase('fail', error={'code': 'execution_failed', 'message': reason})
            self.engine.action_gate.clear_action_state()
            self.engine.if_plan = False
            self.engine.ledger.set_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason='skill:failed')

    def stash_task_result(self, result):
        self.engine.skills.stash_task_result(result)

    def reset_session(self):
        with self.engine.operation_lock:
            self.engine._enter_global_stop('stack_reset', shutdown_program=False, publish_hold=False)
            self.session.reset()


class VlaSkillHost:
    """VLA 技能宿主：组合注入 engine（动作账务+代数）+ perception（几何原语源）+ 配置。

    端口契约见 dispatcher/tools/vla/ports.py::VlaSkillHost（与
    tools/skill_api.py::SkillHost 通用端口对齐，增加 geometry_source 访问）。
    动作武装复用 DispatcherFlightHost.start_goal 的武装序列
    （snapshot_owner → 代次 → action_finish=False → WAIT_ACTION_FINISH），
    动作出海复用 WaypointExecution；与飞行共用飞行独占
    （_meta.lx.concurrency = "flight-exclusive"）。不模拟 engine 属性、
    不给 core 增加领域几何方法。
    """

    def __init__(self, engine, execution, perception, config: VlaHostConfig):
        self.engine = engine
        self.execution = execution
        self.perception = perception
        self.config = config
        # 技能内联塑形所需的只读配置（SkillHost 通用端口属性）
        self.min_height = config.min_height
        self.max_height = config.max_height
        self.planner_ego_mode_value = config.planner_ego_mode_value

    # ------------------------------------------------------------------
    # 入站读取（帧 + 几何原语源）
    # ------------------------------------------------------------------

    def latest_frame(self):
        return self.engine.get_frame_snapshot()

    def get_fast_rgb(self):
        return self.perception.get_fast_rgb()

    def geometry_source(self):
        return self.perception

    # ------------------------------------------------------------------
    # 出站动作：武装（记账）→ 下发（传输原语）
    # ------------------------------------------------------------------

    def arm_action(
        self,
        *,
        action_name: str = "",
        prompt_raw: str = "",
        replan_cmd=None,
        replan_reason=None,
        instruction_type=None,
        owner=None,
    ) -> bool:
        """通用动作记账：归属快照 + 元数据缓存 + 代次推进 + 切 WAIT_ACTION_FINISH。

        只做账务不发 goal——航点类技能随后调用 send_task_goal 传输原语
        （航点塑形由技能内联完成）。owner 归属沿用飞行同款守卫：快照后
        归属必须与传入 owner 一致（本轮 DISPATCH 命中者），不做跨技能
        私有写入。
        """
        engine = self.engine
        # 停止态/急停拒绝新动作的门
        if (
            engine.dispatcher_state == DISPATCHER_STATE.STOP
            or engine.ledger.command_type == COMMAND_TYPE.STOP
            or bool(engine.global_stop_active)
        ):
            engine.runlog.emit("warning", "arm_action_skipped_task_stopped")
            return False
        engine.skills.snapshot_owner()
        if owner is not None and engine.skills.owner_skill() is not owner:
            engine.runlog.emit(
                "warning", "arm_action_owner_mismatch", action_name=str(action_name or "")
            )
            return False
        gate = engine.action_gate
        gate._action_generation += 1
        gate._action_finish_generation = -1
        gate._last_action_result = None
        pending = gate.pending_action
        pending.replan_cmd = replan_cmd
        pending.replan_reason = replan_reason
        pending.action_name = str(action_name or "")
        pending.prompt_raw = str(prompt_raw or "")
        pending.instruction_type = instruction_type
        engine.action_start_time = time.time()
        engine.action_finish = False
        engine.action_in_progress = True
        engine.runlog.emit(
            "info",
            "action_dispatch_prepared",
            action_generation=gate._action_generation,
            action_name=str(pending.action_name or "unknown"),
            instruction_type=str(pending.instruction_type),
            prompt=str(pending.prompt_raw or ""),
        )
        engine.ledger.set_state(DISPATCHER_STATE.WAIT_ACTION_FINISH, reason='action:armed')
        return True

    def send_task_goal(self, x, y, z, yaw, yaw_source: str = "unspecified"):
        """航点下发（传输原语）：经 WaypointExecution 出海；塑形由技能内联完成。

        yaw=None 表示 look_forward（沿路径朝前）——Goal 契约要求 yaw 为有限
        数值（LocalGoalSet.yaw 消息字段），look_forward=True 时以 0.0 占位、
        由下游按路径朝向接管；给定 yaw 则按 terminal yaw 下发。发送失败时
        按 start_goal 同款回滚动作执行态并上抛。
        """
        engine = self.engine
        gate = engine.action_gate
        goal = Goal(
            (float(x), float(y), float(z)),
            0.0 if yaw is None else float(yaw),
            look_forward=yaw is None,
        )
        engine.waypoint = goal.position
        gate.pending_action.waypoint = goal.position
        gate.pending_action.nav_yaw = None if yaw is None else float(yaw)
        gate.pending_action.yaw_source = str(yaw_source or "unspecified")
        try:
            self.execution.start(goal)
            engine.last_published_waypoint = goal.position
        except Exception:
            engine.action_in_progress = False
            raise

    def publish_mode_burst(self, mode_value: int, repeat: int = None, interval: float = None):
        """按设定频率连续发布规划器模式（出站回调经配置注入）。

        EGO 直连栈暂无模式触发通道：装配层（P3）必须显式接通出口或提供
        受控空实现；未接通直接失败，不静默降级。
        """
        if repeat is None:
            repeat = int(self.config.planner_mode_repeat)
        if interval is None:
            interval = float(self.config.planner_mode_interval)
        sink = self.config.publish_planner_mode
        if sink is None:
            raise RuntimeError("planner_mode_burst_not_wired")
        for _ in range(max(1, int(repeat))):
            if self.engine.clock.is_shutdown():
                return
            sink(int(mode_value))
            if max(0.0, float(interval)) > 0.0:
                time.sleep(max(0.0, float(interval)))

    def poll_result(self):
        result = self.execution.poll()
        if result is not None:
            gate = self.engine.action_gate
            gate._last_action_result = result
            gate._action_finish_generation = gate._action_generation
            self.engine.action_finish = True
        return result

    def cancel_execution(self, owner=None):
        if owner is None or self.engine.skills.owner_skill() is owner:
            self.execution.cancel()

    # ------------------------------------------------------------------
    # 生命周期：相位 / 结果 / 失败 / 代次 / 队列机械操作
    # ------------------------------------------------------------------

    def stash_task_result(self, result):
        self.engine.skills.stash_task_result(result)

    def publish_phase(self, phase, **kwargs):
        self.engine.task_phase.publish(phase, **kwargs)

    def fail_sequence(self, reason: str):
        """VLA fail 序列唯一写口；相位 error.code 携带语义原因。

        invalid_grounded_bbox / target_not_visible / odom_stamp_unavailable
        三态经 reason 传入并原样出现在 fail 相位（error={"code": reason, ...}）；
        区别于飞行宿主的 execution_failed 通用码。
        """
        try:
            self.execution.cancel()
        finally:
            self.engine.ledger.fail_sequence(reason)
            self.publish_phase(
                'fail',
                detail=str(reason or 'sequence failed'),
                error={'code': str(reason or 'sequence_failed'), 'message': str(reason or '')},
            )
            self.engine.action_gate.clear_action_state()
            self.engine.if_plan = False
            self.engine.ledger.set_state(
                DISPATCHER_STATE.WAIT_FOR_MISSION, reason='skill:failed'
            )

    def capture_task_generation(self) -> int:
        return int(self.engine.ledger.task_generation)

    def task_generation_valid(self, generation: int, *, reason: str = "") -> bool:
        if not bool(getattr(self.engine, "task_generation_guard_enabled", True)):
            return True
        current = int(self.engine.ledger.task_generation)
        if int(generation) == current:
            return True
        self.engine.runlog.emit(
            "warning",
            "stale_task_result_discarded",
            reason=reason or "",
            captured_generation=int(generation),
            current_generation=current,
        )
        return False

    def consume_head_prompt(self) -> None:
        """本条 prompt 已转化为动作：置 ADVANCE_READY 并弹出队首。"""
        self.engine.ledger.command_status = COMMAND_STATUS.ADVANCE_READY
        if self.engine.prompt_queue.command_content:
            self.engine.prompt_queue.command_content.pop(0)

    def advance_prompt(self) -> None:
        """本条 prompt 无动作直接结束：推进到下一条 prompt。"""
        self.engine.prompt_queue.advance_head_prompt()
