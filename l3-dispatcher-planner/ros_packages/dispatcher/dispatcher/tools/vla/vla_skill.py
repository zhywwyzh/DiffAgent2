"""vla 技能（哑执行器形态）：navigation.vla_nav 的队列执行体（P2 迁入）。

VLM 推理归 station（板上零 VLM）：arguments 由 station 单次接地携带
grounded detection（bbox_1000 + image_stamp），本技能只负责
「收 bbox → 解算 waypoint → 执行 → 报 outcome」：

- DISPATCH 态：`plan_tick` 直读 call.arguments，经 `_consume_grounded_detection`
  做语义预检（bbox 0..1000、x1<x2、y1<y2、image_stamp 有限）与
  bbox_1000→像素换算（scale = 像素宽高/1000、int 取整、中心 = 两点均值取整），
  产出统一 detection 结构后进入 `GeometryService._compute_waypoint_from_detection`
  几何链（far_push / depth_match_ok / replan 链保持不变）。
- fail-closed 三态（无旋转、无重试，经 host.fail_sequence 出 fail 相位）：
  invalid_grounded_bbox（语义预检失败）、target_not_visible（station 明示
  不可见）、odom_stamp_unavailable（bracket/odom buffer 皆无法对齐
  image_stamp，绝不静默用最新位姿）。
- WAIT_ACTION_FINISH：`wait_action_tick` 经引擎主循环逐节拍驱动
  `host.poll_result()`（FlightMotion 同构；一轮 DISPATCH 只做一次消费，
  结果到达由宿主置 action_finish，完成判定走壳通用路径）；POST_ACTION：
  `on_action_result` 四裁决（REPLAN/ADVANCE/IDLE/NEW_ACTION），
  landing 贴地腿按 NEW_ACTION 发布。

与旧链（DiffAgent2 旧版 tools/vla/vla_skill.py）的迁移映射（其余逐字对齐）：
- REPLAN 判据自宿主 pending_action 迁为技能自有 `_replan_cmd/_replan_reason`
  （rest R05 接入顺序：技能不读宿主 ActionGate 私有，l3-skill-contract §5/G14），
  与 `_dispatch_waypoint` 的 arm_action 记账同源写入、verdict 时自清。
- 旧链 command_status（壳留壳字段）的 MISSION_DONE/ADVANCE_READY 分支由技能
  自有 `_advance_after_result` 表达：station 判 finish → True（到达后 ADVANCE）；
  far_push 覆盖回 False（远推进不算到达）；队列机械（consume_head_prompt /
  advance_prompt）仍走宿主端口。
- 首帧系列、首帧/当前帧图像发布（publish_image）、raw_cmd 为空的
  置态防御分支（registry schema 下不可达：prompt 必填 minLength=1、
  name 恒非空）、recording 记录链（记录服务未建，方案 §5 登记台账）、
  mission_type/if_safe_mode 留壳写（归属 perception 装配侧）
  均不迁。
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable

import numpy as np

from dispatcher.tools.skill_api import SkillBase, SkillVerdict
from dispatcher.tools.vla.vla_geometry import GeometryService, VlaGeometryConfig


class VlaSkill(SkillBase):
    """navigation.vla_nav：经 prompt 队列进 DISPATCH 的异步技能（哑执行器）。"""

    name = "navigation.vla_nav"
    requires_perception = True
    synchronous = False  # 入队经 DISPATCH 逐 tick 推进；动作完成走壳通用完成判定

    def __init__(
        self,
        host,
        *,
        geometry_config: VlaGeometryConfig = None,
        emit: Callable[..., None] = None,
        search_success_distance_thresh: float = 0.3,
        far_push_distance_m: float = 5.0,
    ) -> None:
        # host 为 VlaSkillHost 语义（tools/vla/ports.py）；几何服务 VLA 私有持有，
        # 几何原语经宿主的 geometry_source() 端口注入。emit 为技能层 slog 出口
        # （旧链 host.telemetry.emit；装配层接 runlog，测试注入受控回调）。
        super().__init__(host)
        self._emit = emit if emit is not None else (lambda *a, **k: None)
        self._geometry = GeometryService(
            host.geometry_source(), geometry_config, self._emit
        )
        # 技能层阈值（旧库 config；方案 §2/vla_geometry.py 头注：不属几何配置）
        self._search_success_distance_thresh = float(search_success_distance_thresh)
        self._far_push_distance_m = float(far_push_distance_m)
        # 技能自有 REPLAN 状态（R05：替代旧链直读 pending_action.replan_cmd）
        self._replan_cmd: Any = None
        self._replan_reason: Any = None
        # 本腿动作完成后是否 ADVANCE（旧链 command_status MISSION_DONE/ADVANCE_READY）
        self._advance_after_result = False
        self._if_landing = False  # 是否降落（prompt 含 land 关键词）

    # ------------------------------------------------------------------
    # Skill 接口
    # ------------------------------------------------------------------

    def plan_tick(self, cmd) -> bool:
        """DISPATCH 态单 tick：消费 station 下发的 grounded detection 并驱动几何链。

        命令载体为原生 ToolCall——side/object/bbox_1000/image_stamp 直读
        call.arguments，机上无任何 VLM 调用；raw 兜底链与旧链同源
        （display_text → arguments.prompt → 工具名）。
        """
        host = self._host
        call = cmd.call
        raw_cmd = str(call.display_text or call.arguments.get("prompt") or call.name)

        current_frame = host.latest_frame()
        # （旧链 host.mission_type / host.if_safe_mode 留壳写不迁：几何原语内的
        #  NAVIGATION 分支与安全模式由 perception 装配侧持有，技能不写宿主私有）

        detection = self._consume_grounded_detection(call)
        if not bool(detection.get("visible", False)):
            # 单次接地 fail-closed：not-visible / 语义预检失败均无旋转、
            # 无重试，直接置呼叫 fail 终态
            reason = str(detection.get("reason") or "target_not_visible")
            self._emit(
                "warning",
                "vla_grounded_detection_failed",
                target=raw_cmd,
                reason=reason,
            )
            host.fail_sequence(reason)
            return True

        # station 判 finish → 到达本腿即完成该 prompt（旧链 RUNNING→MISSION_DONE；
        # 非 finish 保持 RUNNING），far_push 在下方覆盖回 False（远推进不算到达）
        self._advance_after_result = bool(detection.get("finish", False))

        # 检测结果可见性：bbox 命中即发运行期相位事件（携带像素坐标），
        # 进入相位事件流，前端据此呈现检测框。
        host.publish_phase(
            "searching",
            detail=f"target detected: {raw_cmd}",
            result={
                "kind": "vla_detection",
                "target": raw_cmd,
                "bbox": detection.get("bbox"),
            },
        )

        # odom 可用性预检：station 下发的 image_stamp（rgb 相机时戳）必须能
        # 对齐出世界系帧（bracket 快照优先 / odom buffer 兜底），失败即
        # odom_stamp_unavailable fail-closed——绝不静默用最新位姿。
        image_stamp = float(call.arguments["image_stamp"])
        if current_frame is None or self._geometry._resolve_world_frame(
            current_frame, detection.get("result")
        ) is None:
            self._emit(
                "warning",
                "vla_odom_stamp_unavailable",
                target=raw_cmd,
                image_stamp=image_stamp,
            )
            host.fail_sequence("odom_stamp_unavailable")
            return True

        waypoint_info = self._geometry._compute_waypoint_from_detection(
            call, current_frame, detection.get("result")
        )
        if waypoint_info is None:
            # 几何链无可用候选（如 odom 对齐后深度/点云双路皆空）：本条
            # prompt 无动作直接结束（旧链同款推进，不 fail）
            host.advance_prompt()
            return True

        waypoint = waypoint_info["target_pose"]
        # 远/稀疏目标：几何候选不可信（depth_match_ok=False）时不飞向不可信的
        # bbox 航点，改为沿机头按固定距离推进（far_push_distance_m，默认 5.0m）；
        # 一轮 DISPATCH 只做一次消费，推进动作按常规路径等到达。
        far_push = not bool(waypoint_info.get("depth_match_ok", True))
        self._if_landing = bool(re.search(r"\bland\b", str(raw_cmd), flags=re.IGNORECASE))
        distance = np.linalg.norm(
            np.array(waypoint[:3], dtype=np.float64)
            - np.array(current_frame.current_state[:3], dtype=np.float64)
        )
        if distance < self._search_success_distance_thresh:
            self._emit(
                "info",
                "vla_waypoint_too_close",
                waypoint=np.round(np.asarray(waypoint), 3).tolist(),
                current_pose=np.round(
                    np.asarray(current_frame.current_state), 3
                ).tolist(),
                distance=float(distance),
                threshold=self._search_success_distance_thresh,
            )
            host.stash_task_result({"completion": "workflow_result"})
            host.advance_prompt()
            return True

        # （旧链非 far_push 腿的 recording._record_process_event 记录不迁：
        #  记录服务未建（方案 §5 登记台账），相位事件流覆盖状态可见性）

        # 远推进不算到达：即便 station 判 finish，也保持 replan 循环回到
        # DISPATCH 再消费一次，逐步逼近目标（旧链置回 RUNNING）。
        if far_push:
            self._advance_after_result = False

        if self._advance_after_result:
            # finish 腿：本条 prompt 已转化为动作，弹出队首后无 replan 下发，
            # 到达后经 ADVANCE 装载下一条（队空发 done）
            host.consume_head_prompt()
            self._dispatch_waypoint(
                waypoint,
                look_forward=True,
                action_name="search",
                prompt_raw=raw_cmd,
                yaw_source=waypoint_info.get("yaw_source", "current_odom"),
            )
            return True

        # 远推进腿：目标深度不可靠，不飞向不可信的 bbox 航点，只沿当前机头
        # 推进 far_push_distance_m（默认 5.0m）；正常逼近腿同样带 replan，
        # 到达后回 DISPATCH 围绕同一条 prompt 重新感知/规划。
        if far_push:
            push_m = self._far_push_distance_m
            cur_pos = np.asarray(current_frame.current_state[:3], dtype=np.float64)
            cur_yaw = float(current_frame.current_state[5])
            waypoint = [
                float(cur_pos[0]) + push_m * math.cos(cur_yaw),
                float(cur_pos[1]) + push_m * math.sin(cur_yaw),
                float(cur_pos[2]),
            ]
        self._dispatch_waypoint(
            waypoint,
            look_forward=True,
            replan_cmd=raw_cmd,
            replan_reason="search",
            action_name="search",
            prompt_raw=raw_cmd,
            yaw_source="current_odom",
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
        """POST_ACTION 裁决（四裁决；REPLAN 由技能自有 replan 状态判定）。

        若当前动作是为重规划服务的临时动作（远推进/逼近循环腿），则只回到
        DISPATCH 围绕同一条 prompt 继续下一轮感知/规划——不提前 done；
        pending 记账的清理由 core 在 verdict 后机械执行，技能自有状态在此自清。
        """
        host = self._host
        if self._replan_cmd is not None:
            self._replan_cmd = None
            self._replan_reason = None
            return SkillVerdict.REPLAN

        # landing 逻辑分两段：1. 先走降落命令；2. 再补一次贴地航点，确保末端
        # 姿态/高度收敛。贴地腿按 NEW_ACTION verdict：主分支序列在前，贴地
        # 航点经 _dispatch_waypoint（arm_action 记账已切 WAIT_ACTION_FINISH）在后。
        if self._if_landing:
            self._if_landing = False
            if self._advance_after_result:
                # 旧链 _load_next_prompt 的队列推进经 advance_prompt 端口等价
                # （弹队首 + 装下一条；队空发 done 并收 MISSION_DONE）
                self._advance_after_result = False
                host.stash_task_result({"completion": "workflow_result"})
                host.advance_prompt()
            # （else 分支旧链仅记录 task_stop 事件——记录链不迁）
            state = host.latest_frame().current_state
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

        # 正常动作完成后：finish 腿按 ADVANCE 装载下一条（core 机械执行
        # load_next_prompt，队空发 done）；否则回到 WAIT_FOR_MISSION 等新计划。
        if self._advance_after_result:
            self._advance_after_result = False
            host.stash_task_result({"completion": "workflow_result"})
            return SkillVerdict.ADVANCE
        return SkillVerdict.IDLE

    def on_cancel(self) -> None:
        """取消：停共享执行并清理 REPLAN/会话状态（R05：技能自有状态随取消复位）。"""
        self._host.cancel_execution(self)
        self._reset_session_state()

    def on_global_stop(self) -> None:
        """全局停止（软停/硬停/任务覆盖）：与取消同款清理。"""
        self.on_cancel()

    def on_new_prompt_task(self) -> None:
        """新任务准入（覆盖旧任务）：REPLAN/会话状态清理，避免跨任务泄漏。"""
        self._reset_session_state()

    def _reset_session_state(self) -> None:
        """复位技能自有会话状态（REPLAN 标记 / finish 门 / landing 标记）。"""
        self._replan_cmd = None
        self._replan_reason = None
        self._advance_after_result = False
        self._if_landing = False

    def _dispatch_waypoint(
        self,
        waypoint,
        *,
        look_forward: bool = True,
        replan_cmd=None,
        replan_reason=None,
        action_name: str = "",
        prompt_raw: str = "",
        nav_yaw=None,
        yaw_source: str = "unspecified",
    ) -> bool:
        """内部动作发布编排：arm_action 通用记账 → 内联航点塑形（clamp →
        mode_burst）→ send_task_goal 传输原语发 goal。

        dispatched_yaw 预算与旧链等价（显式 nav_yaw → waypoint[5]（6-D，
        非 look_forward）→ None）；grounded 链恒不传 nav_yaw。waypoint /
        last_published_waypoint 簿记归 send_task_goal 内部（宿主机械写）。
        """
        host = self._host
        if waypoint is None:
            return False
        if not host.arm_action(
            action_name=action_name,
            prompt_raw=prompt_raw,
            replan_cmd=replan_cmd,
            replan_reason=replan_reason,
            owner=self,
        ):
            return False
        # 技能自有 REPLAN 状态与 arm_action 记账同源写入（R05：on_action_result
        # 判 REPLAN 用技能自有字段，不回读宿主 pending_action）
        self._replan_cmd = replan_cmd
        self._replan_reason = replan_reason
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
    # grounded detection 消费（VLM 推理迁移 station 后的感知入口）
    # ------------------------------------------------------------------

    def _consume_grounded_detection(self, call) -> dict:
        """消费 station 单次接地下发的 grounded detection，返回统一 detection 结构。

        语义预检（fail-closed；数组长度/数字类型已由 registry 结构校验）：
        - bbox_1000 四值均有限且在 [0, 1000]，且 x1 < x2、y1 < y2；
        - image_stamp 有限。
        station 明示 visible=false → {"visible": False,
        "reason": "target_not_visible"}（bbox 无论形态均不消费）；
        预检不满足 → {"visible": False, "reason": "invalid_grounded_bbox"}。

        bbox_1000 → 像素换算规则与退役的 vlm_zenoh 原样：
        scale = 像素宽高/1000、int 取整、中心 = 两点均值取整；
        image_width/height 为可选显式声明，非正值回落 640x480 缺省约定。
        """
        if call.arguments.get("visible", True) is False:
            return {"visible": False, "reason": "target_not_visible"}
        bbox_1000 = call.arguments.get("bbox_1000")
        raw_stamp = call.arguments.get("image_stamp")
        try:
            x1, y1, x2, y2 = (float(value) for value in bbox_1000)
            stamp = float(raw_stamp)
        except (TypeError, ValueError):
            return {"visible": False, "reason": "invalid_grounded_bbox"}
        edges = (x1, y1, x2, y2)
        if (
            not all(math.isfinite(value) for value in edges)
            or any(value < 0.0 or value > 1000.0 for value in edges)
            or x2 <= x1
            or y2 <= y1
            or not math.isfinite(stamp)
        ):
            return {"visible": False, "reason": "invalid_grounded_bbox"}

        image_width = int(call.arguments.get("image_width") or 0)
        image_height = int(call.arguments.get("image_height") or 0)
        if image_width <= 0:
            image_width = 640
        if image_height <= 0:
            image_height = 480
        scale_x = image_width / 1000.0
        scale_y = image_height / 1000.0
        pt1 = (int(x1 * scale_x), int(y1 * scale_y))
        pt2 = (int(x2 * scale_x), int(y2 * scale_y))
        bbox = [pt1[0], pt1[1], pt2[0], pt2[1]]
        center = [int((pt1[0] + pt2[0]) / 2), int((pt1[1] + pt2[1]) / 2)]
        result = {
            "pos": center,
            "bbox": bbox,
            "mask": None,
            # 时戳来源为 rpc 参数：station 下发 bbox 携带的 rgb 相机时戳
            # （== sensor.capture 的 camera_receive_stamp）
            "llm_stamp": stamp,
            "provider": call.arguments.get("provider", "station"),
        }
        return {
            "visible": True,
            "bbox": bbox,
            "result": result,
            "finish": bool(call.arguments.get("finish", False)),
            "latency_ms": {"visibility_vlm": 0.0, "bbox_vlm": 0.0},
        }
