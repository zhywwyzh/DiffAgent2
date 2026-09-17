"""飞行能力宿主的通用 FSM/动作记账实现；不承载工具名分支。"""
import time
from dispatcher.utils.state import DISPATCHER_STATE


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
