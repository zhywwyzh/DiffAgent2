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
        self._action_key = None

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
            self._action_key = self.execution.start(
                goal, generation=gate._action_generation, owner=engine.skills.owner_skill())
            engine.last_published_waypoint = goal.position
        except Exception:
            engine.action_in_progress = False
            raise

    def poll_result(self):
        key = self._action_key
        if key is None:
            return None
        result = self.execution.poll(generation=key.generation, owner=key.owner)
        gate = self.engine.action_gate
        if key.generation != gate._action_generation or self.engine.skills.owner_skill() is not key.owner:
            return None
        if result is not None:
            gate._last_action_result = result
            gate._action_finish_generation = key.generation
            self.engine.action_finish = True
        return result

    def cancel_execution(self, owner=None):
        if owner is None or self.engine.skills.owner_skill() is owner:
            self.execution.cancel(owner)
            self._action_key = None

    def request_takeoff(self):
        self.execution.require_idle()
        self.session.prepare_takeoff(self.state())
        try:
            self.execution.commands.takeoff()
        except Exception:
            self.session.reject_takeoff()
            raise

    def request_land(self):
        self.execution.require_idle()
        self.state()
        self.execution.commands.land()

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
            self.execution.stop()
            self.session.reset()


class VlaSkillHost:
    """VLA 技能宿主：组合注入 engine（动作账务+代数）+ 配置（航点执行器形态）。

    端口契约见 dispatcher/tools/vla/ports.py::VlaSkillHost（与
    tools/skill_api.py::SkillHost 通用端口对齐，无几何原语源——
    waypoint_world 由站端解算随调用下行）。
    动作武装复用 DispatcherFlightHost.start_goal 的武装序列
    （snapshot_owner → 代次 → action_finish=False → WAIT_ACTION_FINISH），
    动作经共享 ActionSession 下发；与飞行共用飞行独占
    （_meta.lx.concurrency = "flight-exclusive"）。不模拟 engine 属性、
    不给 core 增加领域方法。
    """

    def __init__(self, engine, execution, config: VlaHostConfig):
        self.engine = engine
        self.execution = execution
        self.config = config
        self._action_key = None
        # 技能内联塑形所需的只读配置（SkillHost 通用端口属性）
        self.execution_config = execution.config
        self.min_height = execution.config.min_height
        self.max_height = execution.config.max_height
        self.final_approach_height_m = config.final_approach_height_m
        self.planner_ego_mode_value = config.planner_ego_mode_value

    # ------------------------------------------------------------------
    # 入站读取（执行状态：新鲜 odometry，包含动态观测）
    # ------------------------------------------------------------------

    def state(self):
        return self.execution.state()

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

    def send_task_goal(self, x, y, z, yaw, yaw_source: str = "unspecified",
                       *, ground_approach=False, yaw_low_speed=False):
        """航点下发（传输原语）：经 ActionSession 出海；塑形由技能内联完成。

        yaw=None 表示 look_forward（沿路径朝前）——Goal 契约要求 yaw 为有限
        数值（WaypointTarget.yaw 消息字段），look_forward=True 时以 0.0 占位、
        由下游按路径朝向接管；给定 yaw 则按 terminal yaw 下发。发送失败时
        按 start_goal 同款回滚动作执行态并上抛。
        """
        engine = self.engine
        gate = engine.action_gate
        goal = Goal(
            (float(x), float(y), float(z)),
            0.0 if yaw is None else float(yaw),
            look_forward=yaw is None,
            ground_approach=ground_approach,
            yaw_low_speed=yaw_low_speed,
        )
        engine.waypoint = goal.position
        gate.pending_action.waypoint = goal.position
        gate.pending_action.nav_yaw = None if yaw is None else float(yaw)
        gate.pending_action.yaw_source = str(yaw_source or "unspecified")
        try:
            self._action_key = self.execution.start(
                goal, generation=gate._action_generation, owner=engine.skills.owner_skill())
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
        key = self._action_key
        if key is None:
            return None
        result = self.execution.poll(generation=key.generation, owner=key.owner)
        gate = self.engine.action_gate
        if key.generation != gate._action_generation or self.engine.skills.owner_skill() is not key.owner:
            return None
        if result is not None:
            gate._last_action_result = result
            gate._action_finish_generation = key.generation
            self.engine.action_finish = True
        return result

    def cancel_execution(self, owner=None):
        if owner is None or self.engine.skills.owner_skill() is owner:
            self.execution.cancel(owner)
            self._action_key = None

    # ------------------------------------------------------------------
    # 生命周期：相位 / 结果 / 失败 / 代次 / 队列机械操作
    # ------------------------------------------------------------------

    def stash_task_result(self, result):
        self.engine.skills.stash_task_result(result)

    def publish_phase(self, phase, **kwargs):
        self.engine.task_phase.publish(phase, **kwargs)

    def fail_sequence(self, reason: str):
        """VLA fail 序列唯一写口；相位 error.code 携带语义原因。

        invalid_station_waypoint（waypoint_world 缺失/非恰 3 项/非有限，或
        yaw 非有限）经 reason 传入并原样出现在 fail 相位
        （error={"code": reason, ...}），并经工具面 fail 词表贯通到
        rpc_outcome.reason；区别于飞行宿主的 execution_failed 通用码。
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


class TrackingFrames:
    """只读帧端口；不暴露缓存写入。"""
    def __init__(self, store, now):
        self._store, self.now = store, now

    @property
    def generation(self):
        return self._store.generation

    def seed(self, stamp):
        return self._store.seed(stamp)

    def latest_rgb(self, after_stamp, ros_now, max_age):
        return self._store.latest_rgb(after_stamp, ros_now, max_age)


class TrackHost:
    def __init__(self, engine, execution, config, frames, observations, rotation, translation):
        self.engine, self.execution, self.config = engine, execution, config
        self.frames, self.observations = frames, observations
        import numpy as np
        rotation = np.asarray(rotation, dtype=float)
        translation = np.asarray(translation, dtype=float)
        if rotation.size != 9 or translation.shape != (3,) or not np.isfinite(rotation).all() or not np.isfinite(translation).all():
            raise ValueError('tracking_calibration_required')
        rotation = rotation.reshape(3, 3)
        if (not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-5, rtol=0)
                or not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-5, rtol=0)):
            raise ValueError('invalid_tracking_calibration')
        self.rotation, self.translation = tuple(rotation.ravel()), tuple(translation)

    def report(self, phase, elapsed):
        self.engine.runlog.emit('info', 'tracking_wait', phase=phase, elapsed_s=elapsed)

    def state(self):
        return self.execution.state()

    def require_idle(self):
        self.execution.require_idle()

    def arm(self, owner):
        self.execution.require_idle()
        e = self.engine
        e.skills.snapshot_owner()
        if e.skills.owner_skill() is not owner:
            raise RuntimeError('action_owner_mismatch')
        e.action_gate._action_generation += 1
        e.action_gate._action_finish_generation = -1
        e.action_finish = False
        e.action_in_progress = True
        e.action_start_time = time.time()
        e.ledger.set_state(DISPATCHER_STATE.WAIT_ACTION_FINISH, reason='action:armed')

    def start_tracking(self, owner, goal):
        if self.engine.skills.owner_skill() is not owner:
            raise RuntimeError('action_owner_mismatch')
        return self.execution.start(goal, generation=self.engine.action_gate._action_generation, owner=owner)

    def poll_tracking(self, key):
        return self.execution.poll(generation=key.generation, owner=key.owner)

    def tracking_feedback(self, key):
        return self.execution.feedback(key)

    def finish_tracking(self, key):
        self.execution.finish(key)

    def publish_observation(self, output, frame, session_id, execution_id):
        import math
        import numpy as np
        from dispatcher.tools.track.ports import Observation
        info = frame.intrinsics or {}
        values = tuple(float(info.get(k, float('nan'))) for k in ('fx','fy','cx','cy'))
        rotation = np.asarray(self.rotation).reshape(3,3)
        if (not all(math.isfinite(x) for x in values) or min(values[:2]) <= 0 or
                not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-5) or
                not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-5) or
                not all(math.isfinite(x) for x in self.translation) or
                info.get('width') != frame.rgb.shape[1] or info.get('height') != frame.rgb.shape[0]):
            raise ValueError('invalid_tracking_calibration')
        value = Observation(frame.stamp_ns, output.submit_seq, tuple(output.bbox), frame.rgb.shape[1],
            frame.rgb.shape[0], values, tuple(rotation.ravel()), tuple(self.translation))
        self.observations.publish(value, session_id, execution_id)

    def publish_telemetry(self, *args):
        self.observations.display(*args)

    def complete(self, owner, result):
        e = self.engine
        if e.skills.owner_skill() is not owner:
            return
        e.skills.stash_task_result(result)
        e.action_gate._action_finish_generation = e.action_gate._action_generation
        e.action_finish = True

    def cancel_execution(self, owner=None):
        self.execution.cancel(owner)

    def fail_sequence(self, reason):
        try:
            self.execution.cancel()
        finally:
            e = self.engine
            e.ledger.fail_sequence(reason)
            e.task_phase.publish('fail', error={'code':'execution_failed', 'message':reason})
            e.action_gate.clear_action_state()
            e.if_plan = False
            e.ledger.set_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason='skill:failed')
