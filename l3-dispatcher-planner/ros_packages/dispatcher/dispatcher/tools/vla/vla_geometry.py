"""vla 专用几何逻辑。不同能力按各自语义调用几何，本模块不通用共享。"""

# 迁移说明（design-dispatcher-vla-migration §4/§5）：
# 本模块自 DiffAgent2 旧版 tools/vla/geometry.py 迁入，`self._eng.*` 全部改为
# 注入的「几何原语源」端口（VlaGeometrySource，由 perception/base_policy.py
# 实例实现）与只读配置（VlaGeometryConfig）；数值计算、返回结构与遥测
# 事件名与旧链逐字对齐。几何不通用化：不抽跨域共享服务、不给 core 增加
# 领域几何方法、不给 engine 加 _geometry 别名。
#
# 与旧链的两处受控适配（端口架构所迫，其余逐字一致）：
# 1. 旧库把 last_waypoint_source / depth_match_ok 写到引擎（即 base_policy
#    持有者）状态；新库禁止几何写宿主状态，改为在返回 dict 增补
#    "depth_match_ok" 键（far_push 判据由技能读取该键）：bbox/basic 分支
#    读 base_candidate.match_ok，side/above/front 分支对齐旧链
#    _finalize_waypoint_candidate 的写入值（同源 match_ok，见函数尾注）；
#    pos==[-1,-1] 分支旧链不写，保持缺省 True。
# 2. detection 结果（旧 self._eng.result）改为 `_compute_waypoint_from_detection`
#    的显式入参，由技能自有状态传入（技能不读宿主私有，l3-skill-contract §5/G14）。

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Protocol

import numpy as np

from dispatcher.tool_plane.model import ToolCall


# ---------------------------------------------------------------------------
# 只读配置（旧库 config.py UAV_POLICY_DEFAULTS + base_policy 默认值核对）：
# search_success_distance_thresh=0.3 / far_push_distance_m=5.0 属技能层
# （vla_skill，P2 迁入），不在本几何配置内。
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VlaGeometryConfig:
    """VLA 几何只读配置；默认值与旧库逐项核对一致。

    唯一权威面：装配层（dispatcher_node.create_vla_runtime）经 ROS 私有参数
    ~vla/* 逐字段覆盖（同名键），生产技能经 install_vla 注入本配置消费；
    perception 侧同名属性（safe_dis_radius_m / if_safe_dis / behind_dist /
    is_stable / stable_height 等）属 perception 自有，VLA 几何链不依赖。
    """

    safe_dis_radius_m: float = 0.4  # 旧 base_policy 默认安全半径（米）
    if_safe_dis: bool = True  # 旧 base_policy 默认安全距离开关
    behind_dist: float = 2.0  # 旧 config「后方」目标点偏移距离（米）
    d_side: float = 0.7  # 旧 config 侧向偏移基准距离（米）
    d_forward: float = 0.0  # 旧 config 前向附加偏移距离（米）
    depth_source: str = "cloud"  # 旧 config 几何源：cloud / depth / mix
    is_stable: bool = False  # 旧 config 是否强制保持稳定高度
    stable_height: float = 0.4  # 旧 config 稳定飞行高度（米）
    geometry_agree_safe_dis_radius_m: float = 0.8  # 旧 config 几何一致安全距离（米）


class VlaGeometrySource(Protocol):
    """几何原语源端口：只声明 VLA 实际用到的原语子集与覆盖存储。

    生产实现为 dispatcher/perception/base_policy.py 的 BasePolicyNode 实例
    （原语本体归属 perception，不改）；本端口是技能侧唯一合法耦合面。
    safe_dis_radius_m / if_safe_dis 同时是 base_policy 原语内部的消费值，
    旧链经引擎单存储临时覆盖/恢复——本端口沿用同一存储语义。
    """

    safe_dis_radius_m: float
    if_safe_dis: bool

    def build_world_frame_for_image_stamp(
        self, current_frame: Any, image_stamp: float
    ) -> Any: ...
    def _planar_axes_from_bearing(
        self, origin_xyz, target_xyz, fallback_yaw: float
    ): ...
    def _build_region_from_bbox(self, results, frame): ...
    def bbox_candidate_to_body_incremental_waypoints(
        self, region, candidate, frame, *, safe_dis_radius_m: float
    ) -> dict: ...
    def _publish_candidate_debug_points(self, candidate, frame) -> None: ...
    def _finalize_waypoint_candidate(
        self,
        candidate,
        frame,
        *,
        pose_yaw: float,
        direction: str = "",
        behind_dist: float = 0.0,
        d_side: float = 0.5,
        d_forward: float = 0.5,
    ): ...
    def _estimate_region_point_depth(
        self, region, frame, *, depth_scale=1.0, window=0, depth_mode="z",
        avg_depth=True, percent_point=0.2, use_median=False,
    ): ...
    def _estimate_waypoint_candidate_for_region(
        self, region, frame, *, depth_scale=1.0, window=0, depth_mode="z",
        avg_depth=True, percent_point=0.2, use_median=False,
    ): ...
    def _cloud_depth_ranges_agree(
        self, cloud_range_m: float, depth_range_m: float
    ) -> bool: ...
    def _select_nearest_geometry_candidate(self, cloud_candidate, depth_candidate): ...
    def _geometry_safe_distance(self, cloud_depth_mismatch: bool) -> float: ...
    def _candidate_with_safe_distance(
        self,
        candidate,
        frame,
        *,
        safe_dis_radius_m: float = None,
        apply_safe_distance: bool = True,
        depth_scale=1.0,
    ): ...
    def pixel_to_world(
        self,
        results,
        frame,
        cmd: str,
        depth_scale=1.0,
        window=0,
        depth_mode="z",
        direction: str = "",
        behind_dist=0.0,
        avg_depth=True,
        percent_point=0.2,
        use_median=False,
        d_side=0.5,
        d_forward=0.5,
    ): ...
    def _publish_p2w_marker(self, P_w, stamp) -> None: ...


# ---------------------------------------------------------------------------
# 辅助函数（自旧库 tools/helpers.py::pose_to_list 与
# tools/text_utils.py::normalize_direction 迁入；新库无对应模块，
# 本模块 vla 专用，不外提共享）
# ---------------------------------------------------------------------------


def pose_to_list(pose, fallback_state=None):
    """位姿/航点数组转 [x, y, z, roll, pitch, yaw]（与旧链逐字一致）。"""
    arr = np.asarray(pose, dtype=np.float64).reshape(-1)
    if arr.size >= 6:
        return arr[:6].astype(np.float64).tolist()
    if arr.size >= 3:
        roll = pitch = yaw = 0.0
        if fallback_state is not None:
            fb = np.asarray(fallback_state, dtype=np.float64).reshape(-1)
            if fb.size >= 6:
                roll, pitch, yaw = map(float, fb[3:6].tolist())
        return [
            float(arr[0]),
            float(arr[1]),
            float(arr[2]),
            float(roll),
            float(pitch),
            float(yaw),
        ]
    if fallback_state is not None:
        fb = np.asarray(fallback_state, dtype=np.float64).reshape(-1)
        if fb.size >= 6:
            return fb[:6].astype(np.float64).tolist()
    return None


def normalize_direction(direction: str) -> str:
    """统一中英文方位词到内部规范表达（与旧链逐字一致）。"""
    if direction is None:
        return ""
    d = str(direction).strip().lower()
    mapping = {
        "左": "left",
        "左侧": "left",
        "left": "left",
        "右": "right",
        "右侧": "right",
        "right": "right",
        "上方": "up",
        "上面": "up",
        "above": "up",
        "下方": "down",
        "below": "down",
        "后方": "back",
        "后面": "back",
        "behind": "back",
        "back": "back",
    }
    return mapping.get(d, direction)


def derive_nav_mode(side: str) -> str:
    """side 参数 → nav_mode 导航模式派生（与旧链逐字等价）。

    规则与原 vla 适配器逐字等价：side 为 left/right → "side"（侧向接近）、
    "above" → "above"（上方接近）、"front" → "front"（正面接近），其余
    （含缺省空串）→ "basic"。vla_skill 判断 nav_mode 时从本模块 import
    复用，保持派生规则的单一来源。
    """
    side = str(side or "")
    if side in ("left", "right"):
        return "side"
    if side == "above":
        return "above"
    if side == "front":
        return "front"
    return "basic"


class GeometryService:
    """VLA 私有几何服务（design-dispatcher-vla-migration P1 迁入）。

    几何原语经注入的 `geom_src` 端口调用；只读配置与遥测 emit 经构造
    注入。detection 结果（grounded detection result dict）由调用方（技能）
    显式传入，本服务不持有技能会话状态。
    """

    def __init__(
        self,
        geom_src: VlaGeometrySource,
        config: VlaGeometryConfig = None,
        emit: Callable[..., None] = None,
    ) -> None:
        self._geom = geom_src
        self._config = VlaGeometryConfig() if config is None else config
        # 遥测出口（旧链 self._eng.telemetry.emit / self._eng._telemetry 同源）
        self._emit = emit if emit is not None else (lambda *a, **k: None)

    def _apply_stable_height_if_enabled(self, pose):
        """仅在稳定模式下将航点高度压到 stable_height。"""
        if pose is None:
            return None
        if bool(self._config.is_stable):
            pose[2] = float(self._config.stable_height)
        return pose

    def _resolve_world_frame(self, current_frame, payload):
        """依据检测回传的 rgb 相机时戳对齐世界坐标参考帧（fail-closed）。

        payload 即 grounded detection result：llm_stamp = station 下发 bbox
        携带的 image_stamp（rgb 相机时戳）。bracket 快照优先、odom_buffer
        兜底（build_world_frame_for_image_stamp），两者皆败返回 None——不
        回落 frame_history，更不静默用当前帧位姿；无有效时戳同样 None。
        """
        if current_frame is None:
            return None
        if isinstance(payload, dict) and bool(
            payload.get("_use_provided_frame", False)
        ):
            return current_frame
        stamp_val = None
        if isinstance(payload, dict):
            raw_stamp = payload.get("llm_stamp", None)
            try:
                stamp_val = None if raw_stamp is None else float(raw_stamp)
            except (TypeError, ValueError):
                stamp_val = None
        if stamp_val is None or not np.isfinite(stamp_val):
            return None
        return self._geom.build_world_frame_for_image_stamp(current_frame, stamp_val)

    def _pixel_to_world_with_options(
        self,
        world_frame,
        detection: dict,
        cmd: str,
        *,
        direction: str = "",
        safe_dis_radius_m: float = None,
        apply_safe_distance: bool = None,
    ):
        """临时覆盖安全半径 / if_safe_dis 计算像素到世界系航点。

        覆盖基值（safe_dis_radius_m / apply_safe_distance 未显式给出时）
        回落 VLA 只读配置（~vla/* 唯一权威；默认 0.4/True 与旧库一致），
        不再读 perception 同名属性——VLA 几何对 perception 属性零依赖。
        覆盖目标为几何原语源上的同名存储（旧链引擎单存储语义：原语内部
        的 _compute_adjusted_depth_value / _effective_depth_percent_point
        读取同一份值），调用后恢复原值——临时覆盖/恢复机制不变。
        """
        if safe_dis_radius_m is None:
            safe_dis_radius_m = float(self._config.safe_dis_radius_m)
        if apply_safe_distance is None:
            apply_safe_distance = bool(self._config.if_safe_dis)
        safe_backup = float(self._geom.safe_dis_radius_m)
        safe_flag_backup = bool(self._geom.if_safe_dis)
        try:
            self._geom.safe_dis_radius_m = float(safe_dis_radius_m)
            self._geom.if_safe_dis = bool(apply_safe_distance)
            return self._geom.pixel_to_world(
                detection,
                world_frame,
                cmd=cmd,
                percent_point=0.3,
                direction=direction,
                behind_dist=self._config.behind_dist,
                d_side=self._config.d_side,
                d_forward=self._config.d_forward,
            )
        finally:
            self._geom.safe_dis_radius_m = safe_backup
            self._geom.if_safe_dis = safe_flag_backup

    def _bearing_axes_for_pose(self, pose_state, target_pose_xyz):
        """基于当前位姿到目标点的 bearing 构造平面偏移轴。"""
        pose_arr = np.asarray(pose_state, dtype=np.float64).reshape(-1)
        fallback_yaw = float(pose_arr[5]) if pose_arr.size >= 6 else 0.0
        return self._geom._planar_axes_from_bearing(
            pose_arr[:3],
            np.asarray(target_pose_xyz, dtype=np.float64).reshape(-1)[:3],
            fallback_yaw,
        )

    def _compose_above_target_pose(
        self, object_pose_arr, default_target, forward_world, requested_distance
    ):
        """组合“到目标上方”的最终航点，距离取默认计算值与用户指定值中的较大者。"""
        object_pose_arr = np.asarray(object_pose_arr, dtype=np.float64).reshape(-1)
        target_pose = object_pose_arr.copy()
        default_forward = 0.2
        default_vertical = 0.8
        if default_target is not None:
            default_arr = np.asarray(default_target, dtype=np.float64).reshape(-1)
            if default_arr.size >= 3:
                delta = default_arr[:3] - object_pose_arr[:3]
                default_forward = float(np.dot(delta, forward_world))
                default_vertical = max(0.0, float(delta[2]))
                target_pose = default_arr.copy()
        vertical = max(float(requested_distance or 0.0), default_vertical)
        target_pose[:3] = object_pose_arr[:3] + default_forward * forward_world
        target_pose[2] = float(object_pose_arr[2]) + vertical
        return target_pose

    def _compute_waypoint_from_detection(
        self, call: ToolCall, current_frame, detection: dict
    ):
        """基于检测结果同时计算物体位姿和最终目标位姿。

        入参 call 为原生 ToolCall——raw 统一 display_text or name；side 直读
        arguments 并经 normalize_direction 归一；nav_mode 由 derive_nav_mode
        从原始 side 现算；接近距离直读 arguments["distance_m"]。detection
        为技能消费后的 grounded detection result（旧链经 self._eng.result
        到达，现改显式入参）。
        """
        cmd = call.display_text or call.name
        side = normalize_direction(call.arguments.get("side", ""))
        nav_mode = derive_nav_mode(call.arguments.get("side", ""))
        world_frame = self._resolve_world_frame(current_frame, detection)
        if world_frame is None:
            # odom 对齐失败（bracket/buffer 皆未命中）：fail-closed，不回退
            # 当前帧位姿（上层 vla_skill 据此终止呼叫）
            return None

        if detection.get("pos") == [-1, -1]:
            object_pose = self._pixel_to_world_with_options(
                world_frame,
                detection,
                cmd=cmd,
                safe_dis_radius_m=float(self._config.geometry_agree_safe_dis_radius_m),
                direction="",
                apply_safe_distance=False,
            )
            if object_pose is None:
                return None
            object_pose_arr = np.asarray(object_pose, dtype=np.float64).reshape(-1)
            target_pose_arr = object_pose_arr.copy()
            return {
                "object_pose": pose_to_list(
                    object_pose_arr, fallback_state=world_frame.current_state
                ),
                "target_pose": pose_to_list(
                    target_pose_arr, fallback_state=world_frame.current_state
                ),
            }
        region = self._geom._build_region_from_bbox(detection, world_frame)
        pose_yaw = (
            float(world_frame.current_state[5])
            - detection.get("yaw", 0.0) / 180.0 * math.pi
        )

        # 同一帧只做一次 depth/cloud 区域估计；object_pose 和 target_pose
        # 只是在同一条相机射线上使用不同安全半径派生，避免重复投影整帧点云。
        base_candidate = self._geom._estimate_waypoint_candidate_for_region(
            region,
            world_frame,
            percent_point=0.3,
        )
        cloud_candidate = base_candidate if base_candidate.source == "cloud" else None
        depth_candidate = None
        cloud_depth_mismatch = False
        if base_candidate.source == "cloud" and world_frame.depth_image is not None:
            try:
                depth_candidate = self._geom._estimate_region_point_depth(
                    region,
                    world_frame,
                    percent_point=0.3,
                )
                cloud_depth_mismatch = not self._geom._cloud_depth_ranges_agree(
                    base_candidate.raw_depth,
                    depth_candidate.raw_depth,
                )
                base_candidate = self._geom._select_nearest_geometry_candidate(
                    base_candidate,
                    depth_candidate,
                )
            except Exception:
                depth_candidate = None
        safe_distance_m = self._geom._geometry_safe_distance(cloud_depth_mismatch)
        object_candidate = self._geom._candidate_with_safe_distance(
            base_candidate,
            world_frame,
            safe_dis_radius_m=safe_distance_m,
            apply_safe_distance=False,
        )
        target_candidate = self._geom._candidate_with_safe_distance(
            base_candidate,
            world_frame,
            safe_dis_radius_m=safe_distance_m,
            apply_safe_distance=True,
        )
        roll, pitch = map(float, world_frame.current_state[3:5].tolist())

        if region.kind == "bbox" and nav_mode in ("", "basic"):
            incremental = self._geom.bbox_candidate_to_body_incremental_waypoints(
                region,
                base_candidate,
                world_frame,
                safe_dis_radius_m=safe_distance_m,
            )
            if str(self._config.depth_source).lower() == "mix":
                geometry_source = (
                    "lidar" if base_candidate.source == "cloud" else "depth"
                )
                self._emit(
                    "info",
                    "geometry_source_mix",
                    source=geometry_source,
                    body_waypoint=np.round(incremental["object_increment"], 3).tolist(),
                    target_body=np.round(incremental["target_increment"], 3).tolist(),
                    safe_distance_m=safe_distance_m,
                )
                self._emit(
                    "info",
                    "geometry_source_selected",
                    mode="mix",
                    source=geometry_source,
                    body_waypoint=np.asarray(
                        incremental["object_increment"], dtype=np.float64
                    ).tolist(),
                    target_body=np.asarray(
                        incremental["target_increment"], dtype=np.float64
                    ).tolist(),
                    safe_distance_m=safe_distance_m,
                    cloud_depth_mismatch=cloud_depth_mismatch,
                    aligned_depth_range_m=(
                        None if depth_candidate is None else depth_candidate.raw_depth
                    ),
                    lidar_range_m=(
                        None if cloud_candidate is None else cloud_candidate.raw_depth
                    ),
                )
            # 旧链在此把 last_waypoint_source / depth_match_ok 写入引擎状态；
            # 新链禁止几何写宿主状态，改为返回 dict 增补 depth_match_ok 键
            # （far_push 判据由技能读取该键；geometry_source 键与旧链一致）。
            self._geom._publish_candidate_debug_points(base_candidate, world_frame)
            object_pose_arr = np.concatenate(
                [
                    incremental["object_world"],
                    np.array(
                        [roll, pitch, incremental["target_yaw"]], dtype=np.float64
                    ),
                ]
            )
            target_pose_arr = np.concatenate(
                [
                    incremental["target_world"],
                    np.array(
                        [roll, pitch, incremental["target_yaw"]], dtype=np.float64
                    ),
                ]
            )
            self._geom._publish_p2w_marker(target_pose_arr, world_frame.stamp)
            return {
                "object_pose": pose_to_list(
                    object_pose_arr, fallback_state=world_frame.current_state
                ),
                "target_pose": pose_to_list(
                    target_pose_arr, fallback_state=world_frame.current_state
                ),
                "incremental_waypoint": incremental["target_increment"].tolist(),
                "camera_incremental_yaw": float(incremental["incremental_yaw"]),
                "target_yaw": float(incremental["target_yaw"]),
                "yaw_source": incremental["yaw_source"],
                "geometry_source": base_candidate.source,
                "cloud_depth_mismatch": cloud_depth_mismatch,
                "depth_match_ok": bool(base_candidate.match_ok),
            }

        object_pose_arr = np.concatenate(
            [
                object_candidate.point_world,
                np.array([roll, pitch, pose_yaw], dtype=np.float64),
            ]
        )
        target_pose_arr = self._geom._finalize_waypoint_candidate(
            target_candidate,
            world_frame,
            pose_yaw=pose_yaw,
            direction="",
            behind_dist=self._config.behind_dist,
            d_side=self._config.d_side,
            d_forward=self._config.d_forward,
        )
        forward_world, left_world, _ = self._bearing_axes_for_pose(
            world_frame.current_state,
            object_pose_arr[:3],
        )

        if nav_mode == "side" and side in ("left", "right"):
            # side 模式会把“目标点”修正为物体左右侧，并保持基于 bearing 的前后留距。
            default_candidate = self._geom._candidate_with_safe_distance(
                base_candidate,
                world_frame,
                safe_dis_radius_m=safe_distance_m,
                apply_safe_distance=True,
            )
            default_target = self._geom._finalize_waypoint_candidate(
                default_candidate,
                world_frame,
                pose_yaw=pose_yaw,
                direction=side,
                behind_dist=self._config.behind_dist,
                d_side=self._config.d_side,
                d_forward=self._config.d_forward,
            )
            default_lateral = 0.0
            default_forward = -safe_distance_m
            if default_target is not None:
                delta = (
                    np.asarray(default_target[:3], dtype=np.float64)
                    - object_pose_arr[:3]
                )
                default_lateral = abs(float(np.dot(delta, left_world)))
                default_forward = float(np.dot(delta, forward_world))
                target_pose_arr = np.asarray(default_target, dtype=np.float64).reshape(
                    -1
                )
            requested_lateral = float(call.arguments.get("distance_m") or 0.0)
            lateral = max(requested_lateral, default_lateral)
            sign = 1.0 if side == "left" else -1.0
            target_pose_arr[:3] = (
                object_pose_arr[:3]
                + sign * lateral * left_world
                + default_forward * forward_world
            )
            target_pose_arr = self._apply_stable_height_if_enabled(target_pose_arr)
        elif nav_mode == "above":
            default_candidate = self._geom._candidate_with_safe_distance(
                base_candidate,
                world_frame,
                safe_dis_radius_m=safe_distance_m,
                apply_safe_distance=True,
            )
            default_target = self._geom._finalize_waypoint_candidate(
                default_candidate,
                world_frame,
                pose_yaw=pose_yaw,
                direction="up",
                behind_dist=self._config.behind_dist,
                d_side=self._config.d_side,
                d_forward=self._config.d_forward,
            )
            target_pose_arr = self._compose_above_target_pose(
                object_pose_arr,
                default_target,
                forward_world,
                call.arguments.get("distance_m"),
            )
        elif nav_mode == "front":
            keep_dist = max(
                safe_distance_m,
                float(call.arguments.get("distance_m") or 0.0),
            )
            target_pose_arr[:3] = object_pose_arr[:3] - keep_dist * forward_world
            target_pose_arr = self._apply_stable_height_if_enabled(target_pose_arr)

        # 旧链 side/above/front 腿经 _finalize_waypoint_candidate 写引擎级
        # depth_match_ok（base_policy L1703：bool(candidate.match_ok)，而
        # _candidate_with_safe_distance 的 replace() 派生不触碰 match_ok，
        # 故与 base_candidate.match_ok 恒等值）；新链同款在返回 dict 增补
        # 该键（far_push 判据由技能读取——「候选可信度」语义对齐旧链）。
        # pos==[-1,-1] 分支保持缺省（旧链该分支不写，far_push 恒 False）。
        return {
            "object_pose": pose_to_list(
                object_pose_arr, fallback_state=world_frame.current_state
            ),
            "target_pose": pose_to_list(
                target_pose_arr, fallback_state=world_frame.current_state
            ),
            "depth_match_ok": bool(base_candidate.match_ok),
        }
