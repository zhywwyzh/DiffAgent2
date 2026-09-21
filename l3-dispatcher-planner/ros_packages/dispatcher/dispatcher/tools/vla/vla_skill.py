"""vla 技能（航点执行器形态）：navigation.vla_nav 的队列执行体。

站端解算 waypoint（累积点云（最新，世界系）+ 位姿按帧时戳插值 + VLM bbox），
`navigation.vla_nav` 的 arguments 由 station 携带 waypoint_world（world/ENU，
恰 3 项）下发，本技能只负责「收 waypoint → 语义预检 → 执行 → 报 outcome」：

- DISPATCH 态：`plan_tick` 直读 call.arguments，经 `_consume_station_waypoint`
  做语义预检（waypoint_world 恰 3 项且有限；yaw 有限）组 6-D 航点；距当前
  位姿过近（< search_success_distance_thresh，载荷带 yaw 时豁免——到达后
  转向目标；位姿不可用时跳过该判定）时 advance_prompt 静默成功，否则单次
  解算、单次下发、终态回报——无 replan、无重试。
- fail-closed（无旋转、无重试，经 host.fail_sequence 出 fail 相位）：
  invalid_station_waypoint（waypoint_world 缺失或语义预检失败）。原机上三态
  （invalid_grounded_bbox / target_not_visible / odom_stamp_unavailable）随
  几何上移退役。
- 机上保留项：高度界 clamp（min/max_height，`_dispatch_waypoint` 内联航点
  塑形）、goal 唯一写入口（send_task_goal）、取消/保持（壳通用）、独占与
  owner 门、相位与 rpc_outcome。
- WAIT_ACTION_FINISH：`wait_action_tick` 经引擎主循环逐节拍驱动
  `host.poll_result()`（FlightMotion 同构；完成判定走壳通用路径）；
  POST_ACTION：`on_action_result` 三裁决（ADVANCE/IDLE/NEW_ACTION），
  landing 贴地腿按 NEW_ACTION 发布（headless 无帧时不发贴地腿，按队列
  推进收敛）。

状态归属：技能自有 `_advance_after_result`（本腿完成后是否 ADVANCE）与
`_if_landing`（prompt 含 land 关键词），随取消/新任务/全局停止复位。
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable

import numpy as np

from dispatcher.tools.skill_api import SkillBase, SkillVerdict


class VlaSkill(SkillBase):
    """navigation.vla_nav：经 prompt 队列进 DISPATCH 的异步技能（航点执行器）。"""

    name = "navigation.vla_nav"
    requires_perception = False  # 机上仅需 odom（WaypointExecution.state() 校验）
    synchronous = False  # 入队经 DISPATCH 逐 tick 推进；动作完成走壳通用完成判定

    def __init__(
        self,
        host,
        *,
        search_success_distance_thresh: float = 0.3,
        emit: Callable[..., None] = None,
    ) -> None:
        # host 为 VlaSkillHost 语义（tools/vla/ports.py）；emit 为技能层 slog
        # 出口（装配层接 engine.runlog.emit，测试注入受控回调）。
        super().__init__(host)
        self._emit = emit if emit is not None else (lambda *a, **k: None)
        # 技能层阈值（~vla/search_success_distance_thresh 唯一权威）
        self._search_success_distance_thresh = float(search_success_distance_thresh)
        # 本腿动作完成后是否 ADVANCE（队空发 done）
        self._advance_after_result = False
        self._if_landing = False  # 是否降落（prompt 含 land 关键词）

    # ------------------------------------------------------------------
    # Skill 接口
    # ------------------------------------------------------------------

    def plan_tick(self, cmd) -> bool:
        """DISPATCH 态单 tick：消费 station 下发的 waypoint 并执行。

        命令载体为 waypoint 载荷——waypoint_world 必读，yaw/look_forward
        可选（缺省沿路径朝前）；原 grounded 字段（检测框/帧时戳/接近方位
        等）由站端消费，不再下行，机上无任何几何调用。raw 兜底链
        （display_text → arguments.prompt → 工具名）保持 mission prompt
        记录口径。
        """
        host = self._host
        call = cmd.call
        raw_cmd = str(call.display_text or call.arguments.get("prompt") or call.name)

        current_frame = host.latest_frame()

        waypoint = self._consume_station_waypoint(call)
        if waypoint is None:
            # 站端 waypoint 载荷缺失/语义预检失败：fail-closed，无旋转、
            # 无重试，直接置呼叫 fail 终态
            self._emit(
                "warning",
                "vla_invalid_station_waypoint",
                target=raw_cmd,
            )
            host.fail_sequence("invalid_station_waypoint")
            return True

        # 检测结果相位事件（携带站端航点，替代原 bbox 检测框呈现）：
        # 前端据此呈现目标位置。
        host.publish_phase(
            "searching",
            detail=f"target detected: {raw_cmd}",
            result={
                "kind": "vla_detection",
                "target": raw_cmd,
                "waypoint": [float(v) for v in waypoint[:3]],
            },
        )

        self._if_landing = bool(re.search(r"\bland\b", str(raw_cmd), flags=re.IGNORECASE))

        # 终末偏航放行：载荷带站端 terminal yaw（指向目标）时，即使距离过近
        # 也照样发腿（到达后转向目标），不因「已到达」而静默跳过。
        has_terminal_yaw = call.arguments.get("yaw") is not None
        # 距离过近判定（机上保留的位姿消费）：站端航点距当前位姿
        # < search_success_distance_thresh 时视为已到达，静默成功；位姿不可用
        # （headless 无 odom 帧）时跳过该判定，按正常航点执行（高度界 clamp
        # 与 goal 唯一写入口仍生效）。
        if current_frame is not None:
            distance = np.linalg.norm(
                np.array(waypoint[:3], dtype=np.float64)
                - np.array(current_frame.current_state[:3], dtype=np.float64)
            )
            if (
                distance < self._search_success_distance_thresh
                and not has_terminal_yaw
            ):
                self._emit(
                    "info",
                    "vla_waypoint_too_close",
                    waypoint=np.round(np.asarray(waypoint[:3]), 3).tolist(),
                    current_pose=np.round(
                        np.asarray(current_frame.current_state), 3
                    ).tolist(),
                    distance=float(distance),
                    threshold=self._search_success_distance_thresh,
                )
                host.stash_task_result({"completion": "action_result"})
                host.advance_prompt()
                return True

        # 单一终态路径：本条 prompt 已转化为动作，弹出队首后无 replan 下发，
        # 动作完成后经 ADVANCE 装载下一条（队空发 done）。
        host.consume_head_prompt()
        self._advance_after_result = True
        look_forward = call.arguments.get("look_forward", True) is not False
        nav_yaw = None
        yaw_argument = call.arguments.get("yaw")
        if yaw_argument is not None:
            # 有限性已由 registry schema 与 _consume_station_waypoint 双重校验
            nav_yaw = float(yaw_argument)
            look_forward = False
        self._dispatch_waypoint(
            waypoint,
            look_forward=look_forward,
            action_name="search",
            prompt_raw=raw_cmd,
            nav_yaw=nav_yaw,
            yaw_source="station_geometry" if nav_yaw is not None else "unspecified",
        )
        return True

    def wait_action_tick(self) -> None:
        """WAIT_ACTION_FINISH 轮询钩：驱动共享执行轮询（FlightMotion 同构）。

        引擎主循环每个节拍调用一次 host.poll_result()——结果到达时宿主
        置 action_finish / 记账代次，完成判定走壳通用路径（action_finish
        + 最小等待）；轮询异常转 fail_sequence 语义化终态（异常文本作
        fail 相位 error.code），不让 FSM 卡死在等待态。
        """
        try:
            self._host.poll_result()
        except Exception as exc:
            self._host.fail_sequence(str(exc))

    def action_done_gate(self) -> bool | None:
        """VLA 无技能完成门：动作完成判定走壳通用路径（action_finish + 最小等待）。"""
        return None

    def on_action_result(self, result) -> SkillVerdict:
        """POST_ACTION 三裁决（无 REPLAN：一轮 DISPATCH 单次消费即终态腿）。

        landing 贴地腿按 NEW_ACTION 发布；无帧（headless）时不发贴地腿，
        按队列推进收敛（不空武装）。pending 记账的清理由 core 在 verdict 后
        机械执行，技能自有状态在此自清。
        """
        host = self._host

        # landing 逻辑分两段：1. 先走降落命令；2. 再补一次贴地航点，确保末端
        # 姿态/高度收敛。贴地腿按 NEW_ACTION verdict：主分支序列在前，贴地
        # 航点经 _dispatch_waypoint（arm_action 记账已切 WAIT_ACTION_FINISH）在后。
        if self._if_landing:
            self._if_landing = False
            if self._advance_after_result:
                # 队列推进经 advance_prompt 端口（弹队首 + 装下一条；队空发 done）
                self._advance_after_result = False
                host.stash_task_result({"completion": "action_result"})
                host.advance_prompt()
            frame = host.latest_frame()
            if frame is not None:
                state = frame.current_state
                waypoint = np.array(
                    [float(state[0]), float(state[1]), 0.1, 0.0, 0.0, float(state[5])],
                    dtype=np.float64,
                )
                self._dispatch_waypoint(
                    waypoint,
                    look_forward=False,
                    action_name="landing-final-approach",
                    prompt_raw="landing",
                )
                return SkillVerdict.NEW_ACTION
            # headless 无帧：贴地腿不可构造，按队列推进收敛（不空武装）。
            return SkillVerdict.IDLE

        # 正常动作完成后：按 ADVANCE 装载下一条（core 机械执行
        # load_next_prompt，队空发 done）；否则回到 WAIT_FOR_MISSION 等新计划。
        if self._advance_after_result:
            self._advance_after_result = False
            host.stash_task_result({"completion": "action_result"})
            return SkillVerdict.ADVANCE
        return SkillVerdict.IDLE

    def on_cancel(self) -> None:
        """取消：停共享执行并清理会话状态。"""
        self._host.cancel_execution(self)
        self._reset_session_state()

    def on_global_stop(self) -> None:
        """全局停止（软停/硬停/任务覆盖）：与取消同款清理。"""
        self.on_cancel()

    def on_new_prompt_task(self) -> None:
        """新任务准入（覆盖旧任务）：会话状态清理，避免跨任务泄漏。"""
        self._reset_session_state()

    def _reset_session_state(self) -> None:
        """复位技能自有会话状态（finish 门 / landing 标记）。"""
        self._advance_after_result = False
        self._if_landing = False

    def _dispatch_waypoint(
        self,
        waypoint,
        *,
        look_forward: bool = True,
        action_name: str = "",
        prompt_raw: str = "",
        nav_yaw=None,
        yaw_source: str = "unspecified",
    ) -> bool:
        """内部动作发布编排：arm_action 通用记账 → 内联航点塑形（clamp →
        mode_burst）→ send_task_goal 传输原语发 goal。

        dispatched_yaw 预算：显式 nav_yaw（站端 terminal yaw）→ waypoint[5]
        （6-D，非 look_forward）→ None（look_forward）。waypoint /
        last_published_waypoint 簿记归 send_task_goal 内部（宿主机械写）。
        """
        host = self._host
        if waypoint is None:
            return False
        if not host.arm_action(
            action_name=action_name,
            prompt_raw=prompt_raw,
            owner=self,
        ):
            return False
        # ── 内联航点塑形（高度 clamp，min_height..max_height）──
        waypoint_arr = np.asarray(waypoint, dtype=np.float64).reshape(-1)
        dispatched_yaw = (
            float(nav_yaw)
            if nav_yaw is not None
            else float(waypoint_arr[5])
            if not look_forward and waypoint_arr.size >= 6
            else None
        )
        waypoint_arr[2] = min(
            max(float(waypoint_arr[2]), float(host.min_height)),
            float(host.max_height),
        )
        self._emit(
            "debug",
            "vla_waypoint_published",
            waypoint=[round(float(v), 2) for v in waypoint_arr],
        )
        host.publish_mode_burst(int(host.planner_ego_mode_value))
        host.send_task_goal(
            float(waypoint_arr[0]),
            float(waypoint_arr[1]),
            float(waypoint_arr[2]),
            dispatched_yaw,
            yaw_source,
        )
        return True

    # ------------------------------------------------------------------
    # station waypoint 消费（站端解算后的执行入口）
    # ------------------------------------------------------------------

    def _consume_station_waypoint(self, call) -> Any:
        """消费 station 下发的 waypoint 载荷，返回 6-D 航点（fail-closed）。

        语义预检（结构长度/数字类型已由 registry 结构校验）：
        - waypoint_world 恰 3 项且均有限（world/ENU）；
        - yaw（可选）有限；
        - look_forward（可选）缺省 true。

        预检失败返回 None（调用方以 invalid_station_waypoint 终结呼叫）。
        """
        raw = call.arguments.get("waypoint_world")
        if not isinstance(raw, (list, tuple)) or len(raw) != 3:
            return None
        try:
            x, y, z = (float(value) for value in raw)
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(value) for value in (x, y, z)):
            return None
        yaw = 0.0
        raw_yaw = call.arguments.get("yaw")
        if raw_yaw is not None:
            try:
                yaw_value = float(raw_yaw)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(yaw_value):
                return None
            yaw = yaw_value
        return np.array([x, y, z, 0.0, 0.0, yaw], dtype=np.float64)
