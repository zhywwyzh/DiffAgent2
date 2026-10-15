"""站端航点执行：位置、终末偏航、可选贴地腿共享一个调用终态。"""
from __future__ import annotations

import math
import re
from typing import Callable

from dispatcher.tools.skill_api import SkillBase, SkillVerdict


class VlaSkill(SkillBase):
    name = "navigation.vla_nav"
    requires_perception = False
    synchronous = False

    def __init__(self, host, *, emit: Callable[..., None] = None):
        super().__init__(host)
        self._emit = emit if emit is not None else (lambda *a, **k: None)
        self._reset_session_state()

    def plan_tick(self, cmd) -> bool:
        host = self._host
        call = cmd.call
        raw_cmd = str(call.display_text or call.arguments.get("prompt") or call.name)
        waypoint = self._consume_station_waypoint(call)
        if waypoint is None:
            self._emit("warning", "vla_invalid_station_waypoint", target=raw_cmd)
            host.fail_sequence("invalid_station_waypoint")
            return True
        try:
            self._reset_session_state()
            host.state()  # 近点同样需要新鲜 odometry，禁止缓存帧直接成功。
            self._landing_pending = bool(re.search(r"\bland\b", raw_cmd, re.IGNORECASE))
            if self._landing_pending and host.execution_config.ground_z is None:
                raise RuntimeError("ground_height_unconfigured")
            self._terminal_yaw = (
                float(call.arguments["yaw"]) if call.arguments.get("yaw") is not None else None
            )
            self._target_position = (
                waypoint[0], waypoint[1],
                min(max(waypoint[2], host.min_height), host.max_height),
            )
            host.publish_phase(
                "searching", detail=f"target detected: {raw_cmd}",
                result={"kind": "vla_detection", "target": raw_cmd,
                        "waypoint": list(self._target_position)},
            )
            host.consume_head_prompt()
            # 显式终末 yaw 留给位置停稳后的独立腿。
            look_forward = self._terminal_yaw is not None or call.arguments.get("look_forward", True)
            self._dispatch_waypoint(
                self._target_position, yaw=None if look_forward else 0.0,
                action_name="search", prompt_raw=raw_cmd,
            )
        except Exception as exc:
            self._reset_session_state()
            host.fail_sequence(str(exc))
        return True

    def wait_action_tick(self) -> None:
        try:
            self._host.poll_result()
        except Exception as exc:
            self._reset_session_state()
            self._host.fail_sequence(str(exc))

    def action_done_gate(self) -> bool | None:
        return None

    def on_action_result(self, result) -> SkillVerdict:
        host = self._host
        if result is None or not result.success:
            self._reset_session_state()
            host.fail_sequence(result.reason if result is not None else "missing_result")
            return SkillVerdict.IDLE
        try:
            if self._terminal_yaw is not None:
                yaw = self._terminal_yaw
                self._terminal_yaw = None
                self._dispatch_waypoint(
                    self._target_position, yaw=yaw, yaw_low_speed=True,
                    action_name="search-terminal-yaw", yaw_source="station_geometry",
                )
                return SkillVerdict.NEW_ACTION
            if self._landing_pending:
                self._landing_pending = False
                state = host.state()
                ground = host.execution_config.ground_z
                if ground is None:
                    raise RuntimeError("ground_height_unconfigured")
                position = (state.position[0], state.position[1],
                            ground + host.final_approach_height_m)
                self._dispatch_waypoint(
                    position, yaw=state.yaw, ground_approach=True,
                    action_name="landing-final-approach", prompt_raw="landing",
                )
                return SkillVerdict.NEW_ACTION
        except Exception as exc:
            self._reset_session_state()
            host.fail_sequence(str(exc))
            return SkillVerdict.IDLE
        self._reset_session_state()
        host.stash_task_result({"completion": "action_result"})
        return SkillVerdict.ADVANCE

    def on_cancel(self) -> None:
        try:
            self._host.cancel_execution(self)
        finally:
            self._reset_session_state()

    def on_global_stop(self) -> None:
        self.on_cancel()

    def on_new_prompt_task(self) -> None:
        self._reset_session_state()

    def _reset_session_state(self) -> None:
        self._terminal_yaw = None
        self._landing_pending = False
        self._target_position = None

    def _dispatch_waypoint(
        self, position, *, yaw=None, action_name="", prompt_raw="",
        yaw_source="unspecified", ground_approach=False, yaw_low_speed=False,
    ) -> None:
        host = self._host
        if not host.arm_action(action_name=action_name, prompt_raw=prompt_raw, owner=self):
            raise RuntimeError("action_not_armed")
        self._emit("debug", "vla_waypoint_published", waypoint=list(position))
        host.publish_mode_burst(int(host.planner_ego_mode_value))
        host.send_task_goal(
            *position, yaw, yaw_source,
            ground_approach=ground_approach, yaw_low_speed=yaw_low_speed,
        )

    def _consume_station_waypoint(self, call):
        raw = call.arguments.get("waypoint_world")
        if not isinstance(raw, (list, tuple)) or len(raw) != 3:
            return None
        try:
            if any(isinstance(value, bool) for value in raw):
                return None
            waypoint = tuple(float(value) for value in raw)
            if not all(math.isfinite(value) for value in waypoint):
                return None
            yaw = call.arguments.get("yaw")
            if yaw is not None and (isinstance(yaw, bool) or not math.isfinite(float(yaw))):
                return None
        except (TypeError, ValueError, OverflowError):
            return None
        return waypoint
