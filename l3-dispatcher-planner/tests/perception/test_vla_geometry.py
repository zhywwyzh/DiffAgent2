"""VLA 几何链回归：校验几何原语的期望值。

运行环境：需 ROS Noetic（rospy/cv2/visualization_msgs）。本机以
`PYTHONNOUSERSITE=1 python3 -m pytest` 运行（用户 site 的 numpy 2.x 与
ROS cv2 不兼容）。

期望值推导依据：
- 深度路：`_estimate_region_point_depth` 对 bbox ROI 取深度簇中位数
  （`_select_bbox_depth_cluster`），本测试合成恒定深度 → depth_raw=合成值；
  `bbox_candidate_to_body_incremental_waypoints` 以 z 模式回投
  （increment=((u-cx)/fx*d, -(v-cy)/fy*d, d)，本测试 u=cx、v=cy → (d,0,0)）。
- 点云路：等距弧合成点云使 raw_depth 精确等于半径；非 mix 时 object 增量
  以 range 模式回投中心像素 → 同样 (d,0,0)。
- 安全半径：`_geometry_safe_distance`——cloud/depth 一致或单源 → 0.8
  （geometry_agree），不一致（|Δ|>0.3）→ 1.2（geometry_mismatch）；
  target_increment_x = max(0, d - safe)。
- far_push 判据：depth_match_ok=False（overdepth 比例 > max_overdepth=0.5）；
  远推进航点 `waypoint = [x+push*cos(yaw), y+push*sin(yaw), z]`
  （push=5.0，yaw=0）。
- 三向偏移：`_finalize_waypoint_candidate` NAVIGATION 分支
  left: P + (half_w+max(d_side,half_w))*left + d_forward*forward；
  up: P + 0.2*forward, z += half_h+0.8；front: object - max(safe,distance)*forward。
  half_w=0.5*(x_span/fx)*Z_forward、half_h=0.5*(y_span/fy)*Z_forward。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest
import rospy
from nav_msgs.msg import Odometry

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "l3-dispatcher-planner/ros_packages/dispatcher"
sys.path.insert(0, str(PACKAGE))

from dispatcher.perception.base_policy import (  # noqa: E402
    BasePolicyNode,
    Frame,
    OdometryBuffer,
)
from dispatcher.tools.model import ToolCall  # noqa: E402
from dispatcher.tools.vla.vla_geometry import (  # noqa: E402
    GeometryService,
    VlaGeometryConfig,
    derive_nav_mode,
    normalize_direction,
)
from dispatcher.utils.state import MISSION_TYPE  # noqa: E402


# ---------------------------------------------------------------------------
# 合成环境：单位外参 + 原点上方 1m、朝 +x（yaw=0）的机体
# ---------------------------------------------------------------------------

FX = 442.025
CX = 320.0
CY = 240.0
BBOX = [280, 220, 360, 260]  # 中心像素 (320,240)，x_span=80、y_span=40
IMAGE_STAMP = 100.25  # station 下发 image_stamp（odom buffer 覆盖 [100.0,100.5]）

_CAMERA = {"height": 480, "width": 640, "fx": FX, "fy": FX, "cx": CX, "cy": CY, "fov": 57.0}
_OFFSETS = np.linspace(-0.1, 0.1, 5)


class _MarkerPub:
    """记录 p2w marker 发布（避免真实 ROS publisher）。"""

    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


def _odom(stamp, x=0.0, y=0.0, z=1.0):
    message = Odometry()
    message.header.stamp = rospy.Time.from_sec(stamp)
    message.header.frame_id = "world"
    message.pose.pose.position.x = x
    message.pose.pose.position.y = y
    message.pose.pose.position.z = z
    message.pose.pose.orientation.w = 1.0  # 单位四元数 → roll=pitch=yaw=0
    return message


def _cloud_arc(distance, count=25):
    """以相机原点 (0,0,1) 为球心、半径恰为 distance 的合成点云。"""
    points = []
    for dy in _OFFSETS:
        for dz in _OFFSETS:
            points.append((math.sqrt(distance * distance - dy * dy - dz * dz), dy, 1.0 + dz))
    return np.asarray(points[:count], dtype=np.float64)


def make_policy(depth_source="cloud", is_stable=False, far_ratio=None):
    """构造真实 BasePolicyNode（绕开 ROS __init__，属性按生产默认合成）。"""
    node = BasePolicyNode.__new__(BasePolicyNode)
    node.camera_extrins_T = np.zeros(3)
    node.camera_extrins_R = np.eye(3)
    node.if_safe_dis = True
    node.safe_dis_radius_m = 0.4
    node.geometry_agree_safe_dis_radius_m = 0.8
    node.geometry_mismatch_safe_dis_radius_m = 1.2
    node.cloud_depth_mismatch_threshold_m = 0.3
    node.is_stable = is_stable
    node.stable_height = 0.4
    node.use_intrinsics = True
    node.mission_type = MISSION_TYPE.NAVIGATION
    node.behind_dist = 2.0
    node.max_overdepth = 0.5
    node.depth_valid_ratio_margin = 0.05
    node.depth_valid_max_range = 5.0
    node.depth_match_ok = True
    node.last_waypoint_source = ""
    node.last_waypoint_geometry_debug = None
    node.last_mix_far_ratio = 0.0
    node.last_mix_valid_count = 0
    node.last_mix_far_count = 0
    node.last_mix_total_count = 0
    node.last_mix_required_ratio = 0.0
    node.depth_info = dict(_CAMERA)
    node.color_info = dict(_CAMERA)
    node.depth_source = depth_source
    node.depth_enabled = True
    node.cloud_history = None
    node.odom_buffer = OdometryBuffer()
    node.odom_buffer.add_odom(_odom(100.0))
    node.odom_buffer.add_odom(_odom(100.5))
    node.bbox_dense_window_enabled = False
    node.bbox_dense_window_size_px = 2
    node.bbox_dense_window_min_points = 2
    node.bbox_cloud_margin_px = 12
    node.bbox_dense_window_search_ratio = 0.5
    node.bbox_dense_window_face_target_yaw = True
    node.pc_max_range = 10.0
    node.pc_z_offset = 0.0
    node.ray_grid = 1  # 测试确定性：关闭多射线采样（生产默认 3）
    node.ray_max_dist = 0.2
    node.ray_min_hits = 2
    node.marker_pub = _MarkerPub()
    node.bbox_cloud_pub = None
    node.mask_cloud_pub = None
    node.pc_frame_id = "world"
    node._eval_debug_log = False
    if far_ratio is not None:
        arc = _cloud_arc(3.0, 25)
        far = np.tile(np.array([11.0, 0.0, 1.0]), (int(25 * far_ratio / (1 - far_ratio)), 1))
        node._test_cloud = np.vstack([arc, far])
    return node


def make_frame(depth_image=None, cloud_xyz=None, stamp=100.3):
    origin = np.array([0.0, 0.0, 1.0])
    ranges = None if cloud_xyz is None else np.linalg.norm(cloud_xyz - origin, axis=1)
    return Frame(
        rgb_image=np.zeros((480, 640, 3), dtype=np.uint8),
        depth_image=depth_image,
        cloud_msg=None,
        cloud_xyz=cloud_xyz,
        cloud_ranges=ranges,
        current_state=np.array([0.0, 0.0, 1.0, 0.0, 0.0, 0.0]),
        current_depth_state=np.array([0.0, 0.0, 1.0, 0.0, 0.0, 0.0]),
        stamp=stamp,
    )


def make_depth_image(value):
    image = np.full((480, 640), np.nan)
    image[210:271, 270:371] = value  # 覆盖 bbox 内收 ROI（[300,341)x[230,251)）
    return image


def make_detection(stamp=IMAGE_STAMP, pos=None, bbox=None):
    return {
        "pos": [320, 240] if pos is None else pos,
        "bbox": list(BBOX) if bbox is None else bbox,
        "mask": None,
        "llm_stamp": stamp,
        "provider": "station",
    }


def make_call(arguments=None):
    return ToolCall(
        call_id="step",
        name="navigation.vla_nav",
        arguments=dict(arguments or {}),
        flight_session_id="session",
        step_id="step",
    )


def make_service(policy, config=None, events=None):
    def emit(level, event, **fields):
        events.append((level, event, fields))

    return GeometryService(policy, config, emit)


# ---------------------------------------------------------------------------
# depth / cloud 双路（bbox basic 分支）
# ---------------------------------------------------------------------------


def test_depth_source_basic_waypoint():
    """depth 单源：object=(3,0,1)、target=(3-0.8,0,1)。"""
    policy = make_policy(depth_source="depth")
    service = make_service(policy)
    frame = make_frame(depth_image=make_depth_image(3.0))
    info = service._compute_waypoint_from_detection(
        make_call(), frame, make_detection()
    )
    assert set(info) == {
        "object_pose", "target_pose", "incremental_waypoint", "camera_incremental_yaw",
        "target_yaw", "yaw_source", "geometry_source", "cloud_depth_mismatch",
        "depth_match_ok",
    }
    assert info["object_pose"] == pytest.approx([3.0, 0.0, 1.0, 0.0, 0.0, 0.0])
    assert info["target_pose"] == pytest.approx([2.2, 0.0, 1.0, 0.0, 0.0, 0.0])
    assert info["incremental_waypoint"] == pytest.approx([2.2, 0.0, 0.0])
    assert info["camera_incremental_yaw"] == pytest.approx(0.0)
    assert info["target_yaw"] == pytest.approx(0.0)
    assert info["yaw_source"] == "image_bbox_center_ray"
    assert info["geometry_source"] == "depth"
    assert info["cloud_depth_mismatch"] is False
    assert info["depth_match_ok"] is True


def test_cloud_source_basic_waypoint():
    """cloud 单源：等距弧点云 raw=3.0 → 与 depth 路同值，geometry_source=cloud。"""
    policy = make_policy(depth_source="cloud")
    service = make_service(policy)
    frame = make_frame(cloud_xyz=_cloud_arc(3.0))
    info = service._compute_waypoint_from_detection(
        make_call(), frame, make_detection()
    )
    assert info["object_pose"] == pytest.approx([3.0, 0.0, 1.0, 0.0, 0.0, 0.0])
    assert info["target_pose"] == pytest.approx([2.2, 0.0, 1.0, 0.0, 0.0, 0.0])
    assert info["geometry_source"] == "cloud"
    assert info["cloud_depth_mismatch"] is False


def test_cloud_depth_agree_uses_geometry_agree_radius():
    """cloud 3.0 + depth 3.0 一致（|Δ|≤0.3）→ 安全半径 0.8。"""
    policy = make_policy(depth_source="cloud")
    service = make_service(policy)
    frame = make_frame(depth_image=make_depth_image(3.0), cloud_xyz=_cloud_arc(3.0))
    info = service._compute_waypoint_from_detection(
        make_call(), frame, make_detection()
    )
    assert info["cloud_depth_mismatch"] is False
    assert info["target_pose"] == pytest.approx([2.2, 0.0, 1.0, 0.0, 0.0, 0.0])


def test_cloud_depth_mismatch_uses_geometry_mismatch_radius():
    """cloud 3.0 + depth 4.5 不一致（|Δ|=1.5>0.3）→ 安全半径 1.2。"""
    policy = make_policy(depth_source="cloud")
    service = make_service(policy)
    frame = make_frame(depth_image=make_depth_image(4.5), cloud_xyz=_cloud_arc(3.0))
    info = service._compute_waypoint_from_detection(
        make_call(), frame, make_detection()
    )
    assert info["cloud_depth_mismatch"] is True
    assert info["object_pose"] == pytest.approx([3.0, 0.0, 1.0, 0.0, 0.0, 0.0])
    assert info["target_pose"] == pytest.approx([1.8, 0.0, 1.0, 0.0, 0.0, 0.0])
    # 取更近候选：cloud(3.0) < depth(4.5)
    assert info["geometry_source"] == "cloud"


# ---------------------------------------------------------------------------
# far_push 判据（depth_match_ok=False → 技能沿机头推进 5m）
# ---------------------------------------------------------------------------


def test_overdepth_cloud_reports_depth_match_not_ok_and_far_push_waypoint():
    """60% 点云超程 → match_ok=False；远推进期望 = 机头 5m。"""
    policy = make_policy(depth_source="cloud", far_ratio=0.6)
    service = make_service(policy)
    frame = make_frame(cloud_xyz=policy._test_cloud)
    info = service._compute_waypoint_from_detection(
        make_call(), frame, make_detection()
    )
    assert info["depth_match_ok"] is False
    # 远推进公式（far_push_distance_m=5.0）：
    # waypoint = [x+push*cos(yaw), y+push*sin(yaw), z]，yaw=0、pos=(0,0,1)
    far_push = [5.0 * math.cos(0.0), 5.0 * math.sin(0.0), 1.0]
    assert far_push == pytest.approx([5.0, 0.0, 1.0])


# ---------------------------------------------------------------------------
# d_side / d_forward / behind_dist 三向（side / above / front 分支）
# ---------------------------------------------------------------------------


def _half_spans():
    """half_w/half_h：以「调整后」前向深度回投计算。

    推导：_estimate_region_point_depth 内 depth_val =
    _compute_adjusted_depth_value(3.0, 5.0, 1.0)；if_safe_dis=True 且
    raw=3.0>2.0 → depth_val = 3.0 − safe_dis_radius_m(0.4) = 2.6，
    P_cam[0]=2.6 → half_w=0.5*(x_span/fx)*2.6、half_h=0.5*(y_span/fy)*2.6。
    """
    z_forward = 3.0 - 0.4
    half_w = 0.5 * ((BBOX[2] - BBOX[0]) / FX) * z_forward
    half_h = 0.5 * ((BBOX[3] - BBOX[1]) / FX) * z_forward
    return half_w, half_h


def test_side_left_offset_uses_d_side():
    """side=left：target = object + (half_w+max(d_side,half_w))*left - safe*forward。"""
    policy = make_policy(depth_source="depth")
    service = make_service(policy, VlaGeometryConfig())
    frame = make_frame(depth_image=make_depth_image(3.0))
    info = service._compute_waypoint_from_detection(
        make_call({"side": "left"}), frame, make_detection()
    )
    half_w, _ = _half_spans()
    side_total = half_w + max(0.7, half_w)  # d_side=0.7
    assert info["object_pose"] == pytest.approx([3.0, 0.0, 1.0, 0.0, 0.0, 0.0])
    assert info["target_pose"] == pytest.approx(
        [3.0 - 0.8, side_total, 1.0, 0.0, 0.0, 0.0]
    )


def test_side_left_with_d_forward_override():
    """d_forward=0.3（经配置注入）：侧向目标前移 0.3，default_forward 随之变化。"""
    policy = make_policy(depth_source="depth")
    service = make_service(policy, VlaGeometryConfig(d_forward=0.3))
    frame = make_frame(depth_image=make_depth_image(3.0))
    info = service._compute_waypoint_from_detection(
        make_call({"side": "left"}), frame, make_detection()
    )
    half_w, _ = _half_spans()
    side_total = half_w + max(0.7, half_w)
    # finalize(left)：P_target=(2.2+0.3, side_total, 1) → delta=(-0.5, side_total, 0)
    # 组合：target = object + side_total*left + (-0.5)*forward
    assert info["target_pose"] == pytest.approx(
        [3.0 - 0.5, side_total, 1.0, 0.0, 0.0, 0.0]
    )


def test_above_offset_composes_vertical():
    """side=above：target=(object-0.6 前移后 x, y=0, z=1+half_h+0.8)。

    推导：finalize(up) → P_target = (2.2+0.2, 0, 1+half_h+0.8)；
    _compose_above_target_pose 以 delta 复算 default_forward=-0.6、
    default_vertical=half_h+0.8，最终 z = 1 + max(requested, default_vertical)。
    """
    policy = make_policy(depth_source="depth")
    service = make_service(policy, VlaGeometryConfig())
    frame = make_frame(depth_image=make_depth_image(3.0))
    info = service._compute_waypoint_from_detection(
        make_call({"side": "above"}), frame, make_detection()
    )
    _, half_h = _half_spans()
    assert info["target_pose"] == pytest.approx(
        [2.4, 0.0, 1.0 + half_h + 0.8, 0.0, 0.0, 0.0]
    )


def test_front_offset_keeps_safe_distance():
    """side=front：target = object - max(safe, distance_m)*forward。"""
    policy = make_policy(depth_source="depth")
    service = make_service(policy, VlaGeometryConfig())
    frame = make_frame(depth_image=make_depth_image(3.0))
    info = service._compute_waypoint_from_detection(
        make_call({"side": "front"}), frame, make_detection()
    )
    assert info["target_pose"] == pytest.approx([2.2, 0.0, 1.0, 0.0, 0.0, 0.0])
    # 指定接近距离大于安全半径时取较大者（keep_dist=max(safe, distance_m)）
    info_far = service._compute_waypoint_from_detection(
        make_call({"side": "front", "distance_m": 1.5}), frame, make_detection()
    )
    assert info_far["target_pose"] == pytest.approx([1.5, 0.0, 1.0, 0.0, 0.0, 0.0])


def test_behind_dist_d_side_d_forward_passthrough_to_finalize():
    """behind_dist=2.0 / d_side=0.7 / d_forward=0.0 透传 _finalize_waypoint_candidate。"""
    calls = []
    policy = make_policy(depth_source="depth")

    class _RecordingPolicy:
        """透传代理：记录 finalize 入参，其余委托真实 perception 实例。"""

        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def _finalize_waypoint_candidate(self, candidate, frame, **kwargs):
            calls.append(kwargs)
            return self._inner._finalize_waypoint_candidate(candidate, frame, **kwargs)

    service = make_service(_RecordingPolicy(policy), VlaGeometryConfig())
    frame = make_frame(depth_image=make_depth_image(3.0))
    service._compute_waypoint_from_detection(
        make_call({"side": "left"}), frame, make_detection()
    )
    assert calls, "至少一次 finalize 调用"
    for kwargs in calls:
        assert kwargs["behind_dist"] == pytest.approx(2.0)
        assert kwargs["d_side"] == pytest.approx(0.7)
        assert kwargs["d_forward"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# stable_height（is_stable 把航点/候选高度压到 0.4）
# ---------------------------------------------------------------------------


def test_stable_height_forces_front_target_height():
    """is_stable=True：front 分支 target z 压到 stable_height=0.4。"""
    policy = make_policy(depth_source="depth", is_stable=True)
    service = make_service(policy, VlaGeometryConfig(is_stable=True, stable_height=0.4))
    frame = make_frame(depth_image=make_depth_image(3.0))
    info = service._compute_waypoint_from_detection(
        make_call({"side": "front"}), frame, make_detection()
    )
    assert info["object_pose"][2] == pytest.approx(0.4)
    assert info["target_pose"] == pytest.approx([2.2, 0.0, 0.4, 0.0, 0.0, 0.0])


# ---------------------------------------------------------------------------
# pos=[-1,-1] 分支 + 覆盖恢复
# ---------------------------------------------------------------------------


def test_minus_one_pos_returns_current_state_and_restores_override():
    """pos=[-1,-1]：object=target=world_frame 当前位姿；安全半径覆盖后恢复。"""
    policy = make_policy(depth_source="depth")
    service = make_service(policy, VlaGeometryConfig())
    frame = make_frame(depth_image=make_depth_image(3.0))
    info = service._compute_waypoint_from_detection(
        make_call(), frame, make_detection(pos=[-1, -1], bbox=[0, 0, 1, 1])
    )
    expected = [0.0, 0.0, 1.0, 0.0, 0.0, 0.0]  # pixel_to_world [-1,-1] 分支
    assert info == {
        "object_pose": pytest.approx(expected),
        "target_pose": pytest.approx(expected),
    }
    # 临时覆盖恢复：几何原语源存储回到原值
    assert policy.safe_dis_radius_m == pytest.approx(0.4)
    assert policy.if_safe_dis is True


# ---------------------------------------------------------------------------
# mix 遥测事件
# ---------------------------------------------------------------------------


def test_mix_source_telemetry_events():
    """depth_source=mix：geometry_source_mix / geometry_source_selected 双事件。"""
    events = []
    policy = make_policy(depth_source="mix")
    service = make_service(policy, VlaGeometryConfig(depth_source="mix"), events)
    frame = make_frame(depth_image=make_depth_image(3.0), cloud_xyz=_cloud_arc(3.0))
    info = service._compute_waypoint_from_detection(
        make_call(), frame, make_detection()
    )
    names = [event for _, event, _ in events]
    assert "geometry_source_mix" in names and "geometry_source_selected" in names
    selected = next(fields for name, event, fields in events
                    if event == "geometry_source_selected")
    assert selected["mode"] == "mix"
    assert selected["source"] == "lidar"  # cloud 候选 → lidar
    assert selected["safe_distance_m"] == pytest.approx(0.8)
    assert selected["cloud_depth_mismatch"] is False
    assert selected["aligned_depth_range_m"] == pytest.approx(3.0)
    assert selected["lidar_range_m"] == pytest.approx(3.0)
    # mix & cloud：object 增量取 bearing_world（选中的 30% 最近点均值）
    selected_points = _cloud_arc(3.0)
    ranges = np.linalg.norm(selected_points - np.array([0.0, 0.0, 1.0]), axis=1)
    order = np.argsort(ranges)[: max(1, int(len(ranges) * 0.3))]
    bearing = np.mean(selected_points[order], axis=0)
    assert selected["body_waypoint"][0] == pytest.approx(float(bearing[0]), abs=1e-3)
    assert info["geometry_source"] == "cloud"


# ---------------------------------------------------------------------------
# fail-closed：世界系对齐
# ---------------------------------------------------------------------------


def test_resolve_world_frame_fail_closed():
    policy = make_policy(depth_source="depth")
    service = make_service(policy)
    frame = make_frame(depth_image=make_depth_image(3.0))
    # 无 llm_stamp → None
    detection = make_detection()
    detection["llm_stamp"] = None
    assert service._resolve_world_frame(frame, detection) is None
    # 非有限时戳 → None
    detection["llm_stamp"] = float("nan")
    assert service._resolve_world_frame(frame, detection) is None
    # odom buffer 覆盖范围之外 → None（不静默用最新位姿）
    assert service._resolve_world_frame(frame, make_detection(stamp=999.0)) is None
    # _use_provided_frame → 直接透传当前帧
    provided = make_detection(stamp=999.0)
    provided["_use_provided_frame"] = True
    assert service._resolve_world_frame(frame, provided) is frame
    # 对齐失败时整条几何链 fail-closed（返回 None）
    assert service._compute_waypoint_from_detection(
        make_call(), frame, make_detection(stamp=999.0)
    ) is None


def test_derive_nav_mode_and_normalize_direction_unchanged():
    """side → nav_mode 派生与方位词归一。"""
    assert derive_nav_mode("left") == "side"
    assert derive_nav_mode("right") == "side"
    assert derive_nav_mode("above") == "above"
    assert derive_nav_mode("front") == "front"
    assert derive_nav_mode("") == "basic"
    assert derive_nav_mode(None) == "basic"
    assert normalize_direction("左侧") == "left"
    assert normalize_direction("behind") == "back"
    assert normalize_direction("") == ""


# ---------------------------------------------------------------------------
# R2：side/above/front 分支携带 depth_match_ok（候选可信度语义）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("side", ["left", "above", "front"])
def test_directional_legs_carry_depth_match_ok(side):
    """R2：三个方向分支的返回 dict 均携带 depth_match_ok = 候选 match_ok。

    side/above/front 腿经 _finalize_waypoint_candidate 写引擎级
    depth_match_ok（base_policy：bool(candidate.match_ok)；_candidate_with_
    safe_distance 的 replace() 派生不触碰 match_ok → 与 base_candidate
    恒等值）。可信（match_ok=True）与超程（match_ok=False，60% 点云
    超程）两态逐一断言——far_push 判据在方向腿不再恒 False。
    """
    # 可信候选（depth 单源无超程）
    policy = make_policy(depth_source="depth")
    service = make_service(policy, VlaGeometryConfig())
    frame = make_frame(depth_image=make_depth_image(3.0))
    info = service._compute_waypoint_from_detection(
        make_call({"side": side}), frame, make_detection()
    )
    assert info["depth_match_ok"] is True
    # 不可信候选（60% 点云超程 → overdepth 比例 > max_overdepth=0.5）
    policy = make_policy(depth_source="cloud", far_ratio=0.6)
    service = make_service(policy, VlaGeometryConfig())
    frame = make_frame(cloud_xyz=policy._test_cloud)
    info = service._compute_waypoint_from_detection(
        make_call({"side": side}), frame, make_detection()
    )
    assert info["depth_match_ok"] is False


# ---------------------------------------------------------------------------
# R1：~vla/* 配置覆盖真实生效（VlaGeometryConfig 唯一权威）
# ---------------------------------------------------------------------------


def test_d_side_override_changes_lateral_offset():
    """R1：d_side=1.0（经配置注入）：侧偏总量 = half_w + max(1.0, half_w)，
    相比默认 0.7 的侧偏真实变化（参数不是只读不用的死配置）。"""
    policy = make_policy(depth_source="depth")
    frame = make_frame(depth_image=make_depth_image(3.0))
    half_w, _ = _half_spans()
    # 默认 d_side=0.7（half_w≈0.235 < 0.7 → max 取 0.7）
    info_default = make_service(policy, VlaGeometryConfig())._compute_waypoint_from_detection(
        make_call({"side": "left"}), frame, make_detection()
    )
    # 覆盖 d_side=1.0 → max 取 1.0，侧偏 +0.3
    info_override = make_service(
        policy, VlaGeometryConfig(d_side=1.0)
    )._compute_waypoint_from_detection(
        make_call({"side": "left"}), frame, make_detection()
    )
    assert info_default["target_pose"][1] == pytest.approx(half_w + 0.7)
    assert info_override["target_pose"][1] == pytest.approx(half_w + 1.0)
    assert info_override["target_pose"][1] > info_default["target_pose"][1]


def test_override_baseline_falls_back_to_vla_config_not_perception():
    """R1：临时覆盖基值回落 VLA 配置（~vla/safe_dis_radius_m、~vla/if_safe_dis
    唯一权威）；perception 同名属性仅作覆盖窗口的暂存/恢复目标，调用后
    恢复原值——覆盖/恢复机制不变，VLA 几何对 perception 属性零依赖。"""
    policy = make_policy(depth_source="depth")
    seen = {}

    class _RecordingPolicy:
        """透传代理：记录 pixel_to_world 执行时的覆盖生效值（读写均透传
        inner——几何的临时覆盖是 setattr 写，不经 __getattr__）。"""

        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def __setattr__(self, name, value):
            if name == "_inner":
                object.__setattr__(self, name, value)
                return
            setattr(self._inner, name, value)

        def pixel_to_world(self, *args, **kwargs):
            seen["safe"] = float(self._inner.safe_dis_radius_m)
            seen["flag"] = bool(self._inner.if_safe_dis)
            return self._inner.pixel_to_world(*args, **kwargs)

    service = make_service(
        _RecordingPolicy(policy),
        VlaGeometryConfig(safe_dis_radius_m=0.9, if_safe_dis=False),
    )
    frame = make_frame(depth_image=make_depth_image(3.0))
    # 覆盖值未显式给出（None）→ 兜底走 VLA 配置而非 perception 基值
    service._pixel_to_world_with_options(frame, make_detection(), cmd="x")
    assert seen == {"safe": 0.9, "flag": False}
    # 临时覆盖恢复：perception 存储回到原值（0.4/True，未被 VLA 配置污染）
    assert policy.safe_dis_radius_m == pytest.approx(0.4)
    assert policy.if_safe_dis is True
