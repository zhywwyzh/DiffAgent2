"""状态与代次账本；宿主状态经读写回调保持唯一来源。"""

from dispatcher.utils.state import COMMAND_TYPE, COMMAND_STATUS, DISPATCHER_STATE


class StateLedger:
    def __init__(self, *, runlog, host_state_get, host_state_set, action_snapshot):
        self.runlog = runlog
        self.host_state_get = host_state_get
        self.host_state_set = host_state_set
        self.action_snapshot = action_snapshot
        self.last_state = None
        self.command_type = COMMAND_TYPE.WAIT
        self.command_status = COMMAND_STATUS.RUNNING
        self.task_generation = 0
        self.failed = False

    def set_state(self, new_state, *, reason: str = ""):
        """统一写入宿主状态，记录迁移来源、目标与原因。"""

        def _state_name(state_value):
            for attr_name, attr_value in vars(DISPATCHER_STATE).items():
                if attr_name.startswith("_"):
                    continue
                if attr_value == state_value:
                    return attr_name
            return str(state_value)

        old_state = self.host_state_get()
        self.host_state_set(new_state)
        state_name = _state_name(new_state)

        old_state_name = _state_name(old_state)
        if old_state != new_state:
            self.runlog.emit(
                "info",
                "dispatcher_state_transition",
                from_state=old_state_name,
                to_state=state_name,
                reason=reason,
                task_generation=self.task_generation,
                **self.action_snapshot(),
            )


    def bump_task_generation(self, reason: str = "") -> int:
        """推进任务代次，使阻塞推理返回的旧结果失效。"""
        self.task_generation = int(getattr(self, "task_generation", 0)) + 1
        self.runlog.info(
            "Task generation advanced to %d (%s)",
            int(self.task_generation),
            reason or "unspecified",
        )
        return int(self.task_generation)


    def fail_sequence(self, reason="") -> None:
        self.failed = True

    def reset_running(self) -> None:
        self.command_status = COMMAND_STATUS.RUNNING
