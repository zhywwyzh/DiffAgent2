"""任务队列生命周期：配置同步、队首推进和序列收敛。"""

import time

from dispatcher.support.state import COMMAND_STATUS


class PromptQueue:
    def __init__(self, *, runlog, task_phase, skills, ledger,
                 if_plan_set, last_state_set,
                 frame_state_get):
        self.runlog = runlog
        self.task_phase = task_phase
        self.skills = skills
        self.ledger = ledger
        self.if_plan_set = if_plan_set
        self.last_state_set = last_state_set
        self.frame_state_get = frame_state_get
        self.command_content = []
        self.prepare_content = []
        self.replan_content = None
        self.previous_return_record_cursor = None

    def sync_task_buffers_from_prepare(self, config):
        """将 prepare_content 同步到执行期的任务缓存。"""
        # 防误配守卫：配置面（real.yaml prepare_content）可注入字符串等非法
        # 元素——流到 DISPATCH 解包时，2 字符字符串会被静默拆成单字符、其他长度
        # 直接 ValueError 进异常自愈循环。对误配采取「跳过」容忍：
        # 只保留合法 (prompt, SkillCommand) 元组，非法元素丢弃并点名索引与内容。
        valid_entries = []
        for index, entry in enumerate(config):
            if isinstance(entry, tuple) and len(entry) == 2:
                valid_entries.append(entry)
            else:
                self.runlog.err(
                    "[PREPARE] 丢弃非法 prepare_content[%d]（期望 (prompt, SkillCommand) 元组）: %r",
                    index,
                    entry,
                )
        self.prepare_content = valid_entries

    def pop_next_task(self) -> bool:
        """从准备队列装载下一条任务。"""
        self.ledger.bump_task_generation("switch_prompt")
        # 每次装载重建当前执行队列（单条）
        self.command_content = []
        if self.is_prepared_empty():
            return False

        # 记录当前位置作为 last_state（return 类命令经专用工具进入，不排队列）
        state = self.frame_state_get()
        self.last_state_set(state.copy() if state is not None else None)

        # 将下一条准备任务推进到 command_content（元素为 (prompt, SkillCommand) 元组）
        self.replan_content = self.prepare_content.pop(0)
        self.command_content.append(self.replan_content)
        self.runlog.info(f"Current task: prompt={self.replan_content[0]}")
        self.runlog.publish_command_content(self.command_content)
        self.if_plan_set(True)
        self.ledger.command_status = COMMAND_STATUS.RUNNING

        return True

    def load_next_prompt(self, *, delay_sec: float = 0.0) -> bool:
        """在节点内部推进到下一条 prompt。"""
        if delay_sec > 0.0:
            time.sleep(delay_sec)
        if self.is_prepared_empty():
            self.if_plan_set(False)
            if not self.ledger.failed:
                pending = self.skills.pop_task_result()
                self.task_phase.publish(
                    "done",
                    progress=self.task_phase._task_phase_progress,
                    detail="prompt sequence finished",
                    result=dict(pending) if isinstance(pending, dict) else None,
                )
            return False
        self.pop_next_task()
        return True


    def advance_head_prompt(self, *, pop_current: bool = True, delay_sec: float = 0.0) -> bool:
        """结束当前 prompt，并请求下一条任务。"""
        next_prompt = ""
        if len(self.prepare_content) > 1:
            # 队列元素为 (prompt, SkillCommand) 元组，日志只取 prompt 文本
            next_prompt = str(self.prepare_content[1][0] or "")
        self.runlog.emit(
            "info",
            "prompt_advanced",
            next_prompt=next_prompt,
            reason="advance_to_next_prompt",
        )
        if pop_current and self.command_content:
            self.command_content.pop(0)
        self.ledger.command_status = COMMAND_STATUS.ADVANCE_READY
        self.load_next_prompt(delay_sec=delay_sec)
        if self.ledger.command_status == COMMAND_STATUS.ADVANCE_READY:
            self.ledger.command_status = COMMAND_STATUS.MISSION_DONE
        return True


    def reset_plan_cycle_if_needed(self) -> None:
        """在新一轮 prompt 规划前重置任务态。"""
        if self.ledger.command_status not in (
            COMMAND_STATUS.MISSION_DONE,
            COMMAND_STATUS.ADVANCE_READY,
        ):
            return
        self.ledger.command_status = COMMAND_STATUS.RUNNING


    def clear_all(self) -> None:
        self.command_content.clear()
        self.prepare_content.clear()
        self.replan_content = None
        self.previous_return_record_cursor = None

    def head_command(self):
        return self.command_content[0] if self.command_content else None

    def is_command_empty(self) -> bool:
        return not self.command_content

    def is_prepared_empty(self) -> bool:
        return not self.prepare_content
