#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基础策略节点（ROS1）。

主要职责：
1. 同步里程计、RGB、深度/点云数据并缓存帧快照。
2. 将像素检测结果或分割 mask 反投影到世界坐标系。
3. 发布调试可视化信息（状态、marker、点云）。
"""

from __future__ import annotations

import logging
import numpy as np
import threading
import cv2
import rospy
import copy
from collections import deque
from dataclasses import dataclass, replace
from typing import Optional, Any
from message_filters import Subscriber as MFSubscriber
from sensor_msgs.msg import CompressedImage, Image
from nav_msgs.msg import Odometry
from geometry_msgs.msg import PoseStamped
import pdb
from sensor_msgs.msg import PointCloud2, PointField
import sensor_msgs.point_cloud2 as pc2
from visualization_msgs.msg import Marker
import math
import time
import cv_bridge
import re
from dispatcher.state import MISSION_TYPE
from dispatcher.perception.pointcloud_accumulator import (
    PointCloudAccumulator,
    PointCloudTimeWindow,
)

@dataclass
class Frame:
    """一次同步传感器数据的快照。"""

    rgb_image: np.ndarray
    depth_image: Optional[np.ndarray]
    cloud_msg: Optional[PointCloud2]
    cloud_xyz: Optional[np.ndarray]
    cloud_ranges: Optional[np.ndarray]
    current_state: np.ndarray
    current_depth_state: np.ndarray
    stamp: float
    cloud_projection_cache: Optional[dict] = None


@dataclass
class PixelRegion:
    """统一表示 bbox / mask 对应的图像区域。"""

    kind: str
    u: float
    v: float
    bbox: Optional[tuple[float, float, float, float]] = None
    mask_u8: Optional[np.ndarray] = None
    xs_all: Optional[np.ndarray] = None
    ys_all: Optional[np.ndarray] = None


@dataclass
class WaypointCandidate:
    """某一几何源估计得到的原始 3D 候选。"""

    source: str
    point_world: np.ndarray
    bearing_world: np.ndarray
    raw_depth: float
    over_edge: bool
    match_ok: bool
    overdepth_ratio: float
    half_w: float
    half_h: float
    bbox_points_world: Optional[np.ndarray] = None
    mask_points_world: Optional[np.ndarray] = None
    target_yaw_world: Optional[float] = None
    geometry_debug: Optional[dict] = None


class OdometryBuffer:
    """缓存里程计，并按目标时间戳插值得到同步位姿。"""

    def __init__(self, max_len: int = 1000, sync_slop: float = 0.05):
        self.lock = threading.Lock()
        self.buffer = deque(maxlen=max(2, int(max_len)))
        self.sync_slop = float(sync_slop)

    def add_odom(self, odom_msg: Odometry) -> None:
        """保存最新里程计；ROS 回调与主同步回调会并发访问该缓存。"""
        with self.lock:
            self.buffer.append(odom_msg)

    def get_latest(self) -> Optional[Odometry]:
        """返回最新里程计（系统时钟），图像时间戳无法匹配时回退。"""
        with self.lock:
            if not self.buffer:
                return None
            return copy.deepcopy(self.buffer[-1])

    def get_interpolated_odom(self, target_stamp: rospy.Time) -> Optional[Odometry]:
        """返回与目标时间对齐的里程计，超出缓存时间范围时返回 None。"""
        target_sec = target_stamp.to_sec()
        with self.lock:
            if len(self.buffer) < 2:
                return None
            newest_time = self.buffer[-1].header.stamp.to_sec()
            oldest_time = self.buffer[0].header.stamp.to_sec()
            if target_sec > newest_time + self.sync_slop:
                return None
            if target_sec < oldest_time - self.sync_slop:
                return None

            prev_idx = -1
            for idx in range(len(self.buffer) - 1, -1, -1):
                if self.buffer[idx].header.stamp.to_sec() <= target_sec:
                    prev_idx = idx
                    break
            if prev_idx < 0:
                return copy.deepcopy(self.buffer[0])
            if prev_idx >= len(self.buffer) - 1:
                return copy.deepcopy(self.buffer[-1])
            odom_prev = self.buffer[prev_idx]
            odom_next = self.buffer[prev_idx + 1]

        return self._interpolate(odom_prev, odom_next, target_sec)

    def _interpolate(
        self, odom_prev: Odometry, odom_next: Odometry, target_sec: float
    ) -> Odometry:
        """对位置和速度线性插值，对姿态四元数球面插值。"""
        t0 = odom_prev.header.stamp.to_sec()
        t1 = odom_next.header.stamp.to_sec()
        if abs(t1 - t0) < 1e-9:
            return copy.deepcopy(odom_prev)
        alpha = (target_sec - t0) / (t1 - t0)

        res = Odometry()
        res.header.stamp = rospy.Time.from_sec(target_sec)
        res.header.frame_id = odom_prev.header.frame_id
        res.child_frame_id = odom_prev.child_frame_id

        p0 = odom_prev.pose.pose.position
        p1 = odom_next.pose.pose.position
        res.pose.pose.position.x = p0.x + alpha * (p1.x - p0.x)
        res.pose.pose.position.y = p0.y + alpha * (p1.y - p0.y)
        res.pose.pose.position.z = p0.z + alpha * (p1.z - p0.z)

        q0 = np.array(
            [
                odom_prev.pose.pose.orientation.x,
                odom_prev.pose.pose.orientation.y,
                odom_prev.pose.pose.orientation.z,
                odom_prev.pose.pose.orientation.w,
            ],
            dtype=np.float64,
        )
        q1 = np.array(
            [
                odom_next.pose.pose.orientation.x,
                odom_next.pose.pose.orientation.y,
                odom_next.pose.pose.orientation.z,
                odom_next.pose.pose.orientation.w,
            ],
            dtype=np.float64,
        )
        q_res = self._slerp(q0, q1, alpha)
        res.pose.pose.orientation.x = float(q_res[0])
        res.pose.pose.orientation.y = float(q_res[1])
        res.pose.pose.orientation.z = float(q_res[2])
        res.pose.pose.orientation.w = float(q_res[3])

        v0 = odom_prev.twist.twist
        v1 = odom_next.twist.twist
        res.twist.twist.linear.x = v0.linear.x + alpha * (v1.linear.x - v0.linear.x)
        res.twist.twist.linear.y = v0.linear.y + alpha * (v1.linear.y - v0.linear.y)
        res.twist.twist.linear.z = v0.linear.z + alpha * (v1.linear.z - v0.linear.z)
        res.twist.twist.angular.x = v0.angular.x + alpha * (v1.angular.x - v0.angular.x)
        res.twist.twist.angular.y = v0.angular.y + alpha * (v1.angular.y - v0.angular.y)
        res.twist.twist.angular.z = v0.angular.z + alpha * (v1.angular.z - v0.angular.z)
        return res

    def _slerp(self, q0: np.ndarray, q1: np.ndarray, alpha: float) -> np.ndarray:
        """四元数球面线性插值，保证姿态过渡走最短路径。"""
        q0 = q0 / (np.linalg.norm(q0) + 1e-12)
        q1 = q1 / (np.linalg.norm(q1) + 1e-12)
        dot = float(np.dot(q0, q1))
        if dot < 0.0:
            q1 = -q1
            dot = -dot
        if dot > 0.9995:
            result = q0 + alpha * (q1 - q0)
            return result / (np.linalg.norm(result) + 1e-12)
        theta_0 = np.arccos(np.clip(dot, -1.0, 1.0))
        sin_theta_0 = np.sin(theta_0)
        theta = theta_0 * alpha
        s0 = np.cos(theta) - dot * np.sin(theta) / sin_theta_0
        s1 = np.sin(theta) / sin_theta_0
        return s0 * q0 + s1 * q1


class SensorBuffer:
    """通用时间戳索引 buffer，支持最近匹配。

    独立于 ApproximateTimeSynchronizer，存储原始传感器消息。
    调用方按需惰性解码，避免同步回调中阻塞。
    """

    def __init__(self, maxlen: int = 500, max_delta: float = 0.1):
        self._buffer = deque(maxlen=max(1, int(maxlen)))
        self._lock = threading.Lock()
        self.max_delta = float(max_delta)

    def put(self, stamp: float, data) -> None:
        """存入一条时间戳索引的数据。"""
        with self._lock:
            self._buffer.append((float(stamp), data))

    def get_nearest(self, target_stamp: float):
        """返回 target_stamp 最近一条数据，超出 max_delta 返回 None。

        不区分前后方向，纯最近邻匹配。
        """
        try:
            target = float(target_stamp)
        except (TypeError, ValueError):
            return None
        with self._lock:
            if not self._buffer:
                return None
            best_stamp, best_data = min(self._buffer, key=lambda x: abs(x[0] - target))
            if abs(best_stamp - target) > self.max_delta:
                return None
            return best_data


class BasePolicyNode(object):
    """感知到世界坐标转换的基础节点。"""

    def __init__(self, node_name: str = "base_policy_node"):
        """初始化订阅器、发布器和坐标转换相关参数。"""
        # 不在此 init_node；由外部 main 初始化 rospy
        self.frame_lock = threading.Lock()
        self.frame: Optional[Frame] = None
        self.frame_history_lock = threading.Lock()
        self.frame_history_size = int(rospy.get_param("~frame_history_size", 8))
        self.frame_history = deque(maxlen=max(1, self.frame_history_size))
        self.headless = bool(
            rospy.get_param("~headless", False)
        )  # headless 模式: 不订阅任何传感器
        # Camera extrinsics: pose of the color camera relative to the body
        # frame (body-frame x = forward). The odom is the BODY pose; the camera world
        # pose is composed as R_w_cam = R_wb @ R, t_wc = t_wb + R_wb @ T.
        self.camera_extrins_T = np.asarray(
            rospy.get_param("~camera_extrins_T", [0.0, 0.0, 0.0]),
            dtype=np.float64,
        ).reshape(3)
        self.camera_extrins_R = np.asarray(
            rospy.get_param(
                "~camera_extrins_R",
                [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            ),
            dtype=np.float64,
        ).reshape(3, 3)
        self.if_safe_dis = True
        self.safe_dis_radius_m = 0.4
        self.geometry_agree_safe_dis_radius_m = 0.8
        self.geometry_mismatch_safe_dis_radius_m = 1.2
        self.cloud_depth_mismatch_threshold_m = float(
            rospy.get_param("~cloud_depth_mismatch_threshold_m", 0.3)
        )
        self.is_stable = False
        self.use_intrinsics = True
        self.depth_scale_param = 57.0
        self.mission_type = MISSION_TYPE.NOT_MISSION
        self.behind_dist = 2.0
        self.depth_format_logged = False
        self.max_overdepth = float(rospy.get_param("~max_overdepth", 0.5))
        self.depth_valid_ratio_margin = float(
            rospy.get_param("~depth_valid_ratio_margin", 0.05)
        )
        self.depth_valid_max_range = float(
            rospy.get_param("~depth_valid_max_range", 5.0)
        )
        self.depth_match_ok = True
        self.last_waypoint_source = ""
        self.last_waypoint_geometry_debug = None
        self.last_mix_far_ratio = 0.0
        self.last_mix_valid_count = 0
        self.last_mix_far_count = 0
        self.last_mix_total_count = 0
        self.last_mix_required_ratio = 0.0

        self.depth_info = self._camera_info_from_params(
            "depth_camera",
            {
                "height": 480,
                "width": 640,
                "fx": 442.025,
                "fy": 442.025,
                "cx": 320.0,
                "cy": 240.0,
                "fov": 57.0,
            },
        )
        self.color_info = self._camera_info_from_params(
            "color_camera",
            {
                # D435i color intrinsics reported by jetson-j30 at 640x480.
                "height": 480,
                "width": 640,
                "fx": 603.1439208984375,
                "fy": 602.61083984375,
                "cx": 326.0789794921875,
                "cy": 249.1268310546875,
                "fov": 79.0,
            },
        )

        self.bridge = cv_bridge.CvBridge()

        self.depth_source = (
            str(rospy.get_param("~depth_source", "cloud")).strip().lower()
        )
        if self.depth_source in ("pointcloud", "cloud_registered", "pc"):
            self.depth_source = "cloud"
        elif self.depth_source in ("depth_image", "image"):
            self.depth_source = "depth"
        elif self.depth_source not in ("cloud", "depth", "mix"):
            self.depth_source = "cloud"
        self.odom_topic = rospy.get_param("~odom_topic", "/ekf_quat/ekf_odom")
        self.rgb_topic = rospy.get_param(
            "~rgb_topic", "/camera/color/image_raw/compressed"
        )
        self.depth_topic = rospy.get_param(
            "~depth_topic", "/camera/aligned_depth/image_raw"
        )
        self.depth_enabled = bool(str(self.depth_topic).strip())
        self.cloud_topic = rospy.get_param(
            "~cloud_topic", "/cloud_registered_no_point_filter"
        )
        # 输入通道健康跟踪（dispatcher_wait_cloud 等待信号的数据源，issue #90）：
        # 每路订阅记录最后收到消息的墙钟时刻；None = 从未收到。只记时间戳，
        # 不复制消息负载，message_filters 的 filter 本身就是逐消息回调点。
        self._input_health_lock = threading.Lock()
        self._input_last_rcv: dict = {}
        self.cloud_topic_ori = rospy.get_param("~cloud_topic_ori", self.cloud_topic)
        self.cloud_accumulator_enabled = bool(
            rospy.get_param("~cloud_accumulator_enabled", False)
        )
        self.cloud_accumulator_frame_count = int(
            rospy.get_param("~cloud_accumulator_frame_count", 5)
        )
        self.cloud_accumulator_downsample_stride = int(
            rospy.get_param("~cloud_accumulator_downsample_stride", 1)
        )
        self.cloud_accumulator_publish_rate = float(
            rospy.get_param("~cloud_accumulator_publish_rate", 0.0)
        )
        self.cloud_accumulator_queue_size = int(
            rospy.get_param("~cloud_accumulator_queue_size", 5)
        )
        self.cloud_accumulator = self._init_cloud_accumulator()
        self.cloud_history_enabled = bool(
            rospy.get_param("~cloud_history_enabled", False)
        )
        self.cloud_history_window_s = float(
            rospy.get_param("~cloud_history_window_s", 1.0)
        )
        self.cloud_history_voxel_size = float(
            rospy.get_param("~cloud_history_voxel_size", 0.0)
        )
        self.cloud_history_max_frames = int(
            rospy.get_param("~cloud_history_max_frames", 30)
        )
        self.bbox_dense_window_enabled = bool(
            rospy.get_param("~bbox_dense_window_enabled", False)
        )
        self.bbox_dense_window_size_px = int(
            rospy.get_param("~bbox_dense_window_size_px", 2)
        )
        self.bbox_dense_window_min_points = int(
            rospy.get_param("~bbox_dense_window_min_points", 2)
        )
        self.bbox_cloud_margin_px = int(rospy.get_param("~bbox_cloud_margin_px", 12))
        self.bbox_dense_window_search_ratio = float(
            rospy.get_param("~bbox_dense_window_search_ratio", 0.5)
        )
        self.bbox_dense_window_face_target_yaw = bool(
            rospy.get_param("~bbox_dense_window_face_target_yaw", True)
        )
        self.cloud_history = (
            PointCloudTimeWindow(
                window_seconds=self.cloud_history_window_s,
                voxel_size=self.cloud_history_voxel_size,
                max_frames=self.cloud_history_max_frames,
            )
            if self.cloud_history_enabled
            else None
        )
        self.is_rgb_compressed = "compressed" in str(self.rgb_topic).lower()
        depth_topic_lower = str(self.depth_topic).lower()
        self.is_depth_compressed = (
            "compresseddepth" in depth_topic_lower or "compressed" in depth_topic_lower
        )
        self.sync_slop = float(rospy.get_param("~sync_slop", 0.2))
        self.sync_mode = (
            str(rospy.get_param("~sync_mode", "strict_all")).strip().lower()
        )
        self.odom_sync_slop = float(rospy.get_param("~odom_sync_slop", self.sync_slop))
        self.odom_buffer_size = int(rospy.get_param("~odom_buffer_size", 100))
        if self.sync_mode not in ("strict_all", "odom_interpolation"):
            rospy.logwarn(
                "Unknown sync_mode '%s', fallback to strict_all. Supported: strict_all, odom_interpolation.",
                self.sync_mode,
            )
            self.sync_mode = "strict_all"
        self.odom_buffer = OdometryBuffer(
            max_len=self.odom_buffer_size,
            sync_slop=self.odom_sync_slop,
        )
        self.depth_uint8_max_range = float(
            rospy.get_param("~depth_uint8_max_range", 5.0)
        )
        # headless 模式: 不初始化 RGB/depth/cloud 同步链路
        if self.headless:
            rospy.loginfo(
                "[BasePolicy] headless mode, skipping all sensor subscriptions."
            )
            self.rgb_sub = None
            self.depth_sub = None
            self.cloud_sub = None
            self.odom_sub = None
            self.pc_frame_id = "world"
            # The frame builder reads the fast-RGB buffer unconditionally; keep
            # its state initialized so headless runs degrade to "no frame"
            # instead of AttributeError (host test slice, 2026-08-31).
            self._fast_rgb_lock = threading.Lock()
            self._fast_rgb_image: Optional[np.ndarray] = None
            self._fast_rgb_stamp: float = 0.0
            self._fast_rgb_wall_time: float = 0.0
            self._fast_rgb_generation: int = 0
            if self.odom_topic:
                self.odom_sub = rospy.Subscriber(
                    self.odom_topic,
                    Odometry,
                    self._headless_callback,
                    queue_size=100,
                    tcp_nodelay=True,
                )
                rospy.loginfo("[BasePolicy] headless: subscribed %s", self.odom_topic)
            else:
                rospy.loginfo(
                    "[BasePolicy] headless: odom_topic is empty, no odom subscription (pure headless)"
                )
                rospy.logwarn(
                    "[ORIGIN] pure headless (odom_topic 为空): 无法从 odom 记录 origin_state，"
                    "return to origin 将回退到默认原点 (0, 0, 1)。"
                )
            return

        # message_filters 同步订阅；sync_mode 控制 odom 是否参与强同步。
        # depth_topic 为空时 depth_sub 不创建；独立缓存构帧仍以 RGB/cloud/odom
        # 为主，存在 aligned depth 时将其作为几何 fallback。
        rgb_msg_type = CompressedImage if self.is_rgb_compressed else Image
        depth_msg_type = CompressedImage if self.is_depth_compressed else Image
        self.rgb_sub = MFSubscriber(
            self.rgb_topic, rgb_msg_type, queue_size=10, tcp_nodelay=True
        )
        self.depth_sub = (
            MFSubscriber(
                self.depth_topic,
                depth_msg_type,
                queue_size=20,
                tcp_nodelay=True,
            )
            if self.depth_enabled
            else None
        )
        self.cloud_sub = MFSubscriber(
            self.cloud_topic, PointCloud2, queue_size=10, tcp_nodelay=True
        )

        self.pc_frame_id = rospy.get_param(
            "~pc_frame_id", "world"
        )  # 点云坐标系，默认世界系
        self.pc_stride = int(rospy.get_param("~pc_stride", 1))  # 采样步长，=1表示逐像素
        default_max_range = 10.0 if self.depth_source in ("cloud", "mix") else 5.0
        self.pc_max_range = float(
            rospy.get_param("~pc_max_range", default_max_range)
        )  # 超过此距离的深度视为无效
        self.pc_keep_far = bool(
            rospy.get_param("~pc_keep_far", False)
        )  # 是否保留“最远平面”(30m)的点
        default_z_offset = -0.1 if self.depth_source in ("cloud", "mix") else 0.0
        self.pc_z_offset = float(
            rospy.get_param("~pc_z_offset", default_z_offset)
        )  # 点云整体高度偏移(m)
        self.ray_grid = int(rospy.get_param("~ray_grid", 3))  # 多射线采样网格边长
        self.ray_max_dist = float(
            rospy.get_param("~ray_max_dist", 0.2)
        )  # 射线-点云最大距离(m)
        self.ray_min_hits = int(rospy.get_param("~ray_min_hits", 2))  # 多射线最小命中数

        # 点云发布器 + 定时器（10Hz）
        self.cloud_pub = rospy.Publisher("cloud_depth", PointCloud2, queue_size=1)
        self.cloud_timer = rospy.Timer(rospy.Duration(0.1), self._cloud_timer_cb)

        if self.sync_mode == "odom_interpolation":
            self.odom_sub = rospy.Subscriber(
                self.odom_topic,
                Odometry,
                self.odom_callback,
                queue_size=100,
                tcp_nodelay=True,
            )
        else:
            self.odom_sub = MFSubscriber(
                self.odom_topic, Odometry, queue_size=20, tcp_nodelay=True
            )
        # 同步 Frame（ApproximateTimeSynchronizer）已移除（2026-08-22）：
        # RGB/cloud 时间戳不同源，同步器永不触发。self.frame 改由独立缓存
        # 在 cloud 回调里用 build_frame_from_latest_cache 构建。
        self.ts = None
        # 每路输入的逐消息健康戳（独立订阅，零额外流量）
        self._track_input_health()
        rospy.loginfo(
            "BasePolicy sync_mode=%s, sync_slop=%.3f, odom_sync_slop=%.3f",
            self.sync_mode,
            self.sync_slop,
            self.odom_sync_slop,
        )
        # rospy.loginfo('message_filters 同步器已启动')

        # 发布当前机器人状态
        self.state_pub = rospy.Publisher(
            "robot/current_state", PoseStamped, queue_size=10
        )

        # 发布目标点marker
        self.marker_pub = rospy.Publisher(
            "pixel_to_world_marker", Marker, queue_size=10
        )
        # 发布bbox内点云（世界坐标系）
        self.bbox_cloud_pub = rospy.Publisher("bbox_cloud", PointCloud2, queue_size=1)
        # 发布mask参与计算的点云（世界坐标系）
        self.mask_cloud_topic = rospy.get_param(
            "~mask_cloud_topic", "/vla_llm/seg/mask_cloud"
        )
        self.mask_cloud_pub = rospy.Publisher(
            self.mask_cloud_topic, PointCloud2, queue_size=1
        )
        # 发布沿路前进任务确认后的地面/台阶支撑点云
        self.road_cloud_topic = rospy.get_param(
            "~road_cloud_topic", "monitor/road_cloud"
        )
        self.road_cloud_pub = rospy.Publisher(
            self.road_cloud_topic, PointCloud2, queue_size=1
        )

        # -- 分通道独立订阅（tracking 快通道，不参与 Frame 同步）--
        self.tracking_sensor_enable = bool(
            rospy.get_param("~tracking_sensor_enable", True)
        )
        self.tracking_depth_max_delta = float(
            rospy.get_param("~tracking_depth_max_delta", 0.1)
        )
        self.tracking_cloud_max_delta = float(
            rospy.get_param("~tracking_cloud_max_delta", 0.05)
        )

        # 快通道 RGB（高帧率，不经过同步器）
        self._fast_rgb_lock = threading.Lock()
        self._fast_rgb_image: Optional[np.ndarray] = None
        self._fast_rgb_stamp: float = 0.0
        self._fast_rgb_wall_time: float = 0.0
        self._fast_rgb_generation: int = 0
        self._fast_rgb_sub = rospy.Subscriber(
            self.rgb_topic,
            rgb_msg_type,
            self._fast_rgb_callback,
            queue_size=1,
            tcp_nodelay=True,
        )

        # Depth buffer stores aligned-depth messages and decodes them lazily.
        self.depth_buffer = SensorBuffer(
            maxlen=300, max_delta=self.tracking_depth_max_delta
        )
        if self.depth_enabled:
            self._tracking_depth_sub = rospy.Subscriber(
                self.depth_topic,
                depth_msg_type,
                self._depth_raw_callback,
                queue_size=1,
                tcp_nodelay=True,
            )
        else:
            self._tracking_depth_sub = None

        # Cloud buffer（存原始 PointCloud2，投影时惰性解码）
        self.cloud_buffer = SensorBuffer(
            maxlen=200, max_delta=self.tracking_cloud_max_delta
        )
        self._tracking_cloud_sub = rospy.Subscriber(
            self.cloud_topic,
            PointCloud2,
            self._cloud_raw_callback,
            queue_size=1,
            tcp_nodelay=True,
        )

    def _init_cloud_accumulator(self):
        """按配置启动原始点云积累器，并将结果发布到 cloud_topic。"""
        if not self.cloud_accumulator_enabled:
            return None
        input_topic = str(self.cloud_topic_ori or "").strip()
        output_topic = str(self.cloud_topic or "").strip()
        if not input_topic or not output_topic:
            rospy.logwarn(
                "[PointCloudAccumulator] cloud_topic_ori/cloud_topic is empty, disable accumulator."
            )
            return None
        if input_topic == output_topic:
            rospy.logwarn(
                "[PointCloudAccumulator] cloud_topic_ori equals cloud_topic (%s), disable accumulator.",
                input_topic,
            )
            return None
        return PointCloudAccumulator(
            input_topic=input_topic,
            output_topic=output_topic,
            frame_count=self.cloud_accumulator_frame_count,
            downsample_stride=self.cloud_accumulator_downsample_stride,
            queue_size=self.cloud_accumulator_queue_size,
            publish_rate=self.cloud_accumulator_publish_rate,
        )

    # ──────────── 独立快通道回调（tracking 传感器，不参与 Frame 同步） ────────────

    def _fast_rgb_callback(self, msg):
        """高帧率 RGB 回调，仅解码图像并缓存，不触发 Frame 同步。"""
        try:
            image = self._decode_rgb_message(msg)
            stamp = msg.header.stamp.to_sec()
            with self._fast_rgb_lock:
                self._fast_rgb_image = image
                self._fast_rgb_stamp = stamp
                self._fast_rgb_wall_time = time.time()
                self._fast_rgb_generation += 1
        except Exception as exc:
            rospy.logerr_throttle(
                2.0,
                "[FAST_RGB] decode failed: %s (stamp=%.3f)",
                exc,
                msg.header.stamp.to_sec(),
            )

    def _depth_raw_callback(self, msg):
        """Depth 回调，存入 buffer（不解码，投影时惰性解码）。"""
        stamp = msg.header.stamp.to_sec()
        self.depth_buffer.put(stamp, msg)

    def _cloud_raw_callback(self, msg):
        """Store raw cloud, maintain the world-cloud window, and refresh the frame."""
        stamp = msg.header.stamp.to_sec()
        self.cloud_buffer.put(stamp, msg)
        if self.cloud_history is None:
            return
        try:
            cloud_xyz = self._cloud_to_xyz_array(msg)
            if cloud_xyz is None:
                return
            if abs(self.pc_z_offset) > 1e-9:
                cloud_xyz = cloud_xyz.copy()
                cloud_xyz[:, 2] += self.pc_z_offset
            self.cloud_history.add(stamp, cloud_xyz, wall_time=time.time())
        except Exception:
            return
        self._refresh_frame_from_cache()

    def _refresh_frame_from_cache(self):
        """Build self.frame from independent caches (replaces the removed synchronizer).

        Called on every cloud arrival; keeps the FSM's frame fresh without
        requiring RGB/cloud header-stamp alignment.
        """
        try:
            frame = self.build_frame_from_latest_cache()
        except Exception:
            return
        if frame is None:
            return
        with self.frame_lock:
            self.frame = frame

    def get_fast_rgb(self):
        """非阻塞获取最新快通道 RGB 图像和时间戳。（快通道未启用时返回 (None, 0.0)）"""
        with self._fast_rgb_lock:
            return self._fast_rgb_image, self._fast_rgb_stamp

    def get_fast_rgb_generation(self) -> int:
        """Return the number of RGB frames received by the fast subscriber."""
        with self._fast_rgb_lock:
            return self._fast_rgb_generation

    def _build_buffer_frame(self, target_stamp: float):
        """从独立 buffer 构造临时 Frame，用于 tracking 3D 投影。

        深度/点云惰性解码，仅在投影时触发。
        若 buffer 数据不满足时间匹配要求，返回 None（调用方回退到同步 Frame）。
        """
        if not getattr(self, "tracking_sensor_enable", True):
            return None

        # Odom 插值到 target_stamp
        odom_stamp = rospy.Time.from_sec(target_stamp)
        odom_msg = self.odom_buffer.get_interpolated_odom(odom_stamp)
        if odom_msg is None:
            return None

        current_state, current_depth_state, p_w_cam = self._extract_pose_from_odom(
            odom_msg
        )

        # Depth 惰性解码
        depth_msg = self.depth_buffer.get_nearest(target_stamp)
        depth_image = None
        if depth_msg is not None:
            try:
                depth_image = self._decode_depth_message(depth_msg)
            except Exception:
                pass

        # Cloud 惰性解码
        cloud_msg_raw = self.cloud_buffer.get_nearest(target_stamp)
        cloud_xyz = None
        if cloud_msg_raw is not None:
            try:
                cloud_xyz = self._cloud_to_xyz_array(cloud_msg_raw)
                if cloud_xyz is not None and self.pc_z_offset != 0.0:
                    cloud_xyz = cloud_xyz.copy()
                    cloud_xyz[:, 2] += self.pc_z_offset
            except Exception:
                pass

        cloud_ranges = self._compute_cloud_ranges(cloud_xyz, p_w_cam)

        return Frame(
            rgb_image=None,
            depth_image=depth_image,
            cloud_msg=cloud_msg_raw,
            cloud_xyz=cloud_xyz,
            cloud_ranges=cloud_ranges,
            current_state=current_state,
            current_depth_state=current_depth_state,
            stamp=target_stamp,
        )

    def get_frame_snapshot(self) -> Optional[Frame]:
        """线程安全地获取最新帧快照。"""
        with self.frame_lock:
            return self.frame

    def get_frame_snapshot_near_stamp(
        self, stamp: float, max_delta: float = 0.25
    ) -> Optional[Frame]:
        """按时间戳在历史缓存中查找最接近的帧。"""
        try:
            target = float(stamp)
        except Exception:
            return self.get_frame_snapshot()
        if not np.isfinite(target):
            return self.get_frame_snapshot()
        with self.frame_history_lock:
            if not self.frame_history:
                return None
            best = None
            best_dt = None
            for frame in self.frame_history:
                dt = abs(float(frame.stamp) - target)
                if best_dt is None or dt < best_dt:
                    best = frame
                    best_dt = dt
        if best is None:
            return None
        if best_dt is not None and max_delta is not None and best_dt > float(max_delta):
            return None
        return best

    def build_world_frame_for_image_stamp(
        self, current_frame: Frame, image_stamp: float
    ) -> Optional[Frame]:
        """Build a frame from image-time odom and the latest world-cloud history."""
        if current_frame is None:
            return None
        try:
            stamp_value = float(image_stamp)
        except (TypeError, ValueError):
            return None
        if not np.isfinite(stamp_value):
            return None
        odom_msg = self.odom_buffer.get_interpolated_odom(
            rospy.Time.from_sec(stamp_value)
        )
        if odom_msg is None:
            if getattr(self, "_eval_debug_log", False):
                with self.odom_buffer.lock:
                    odom_count = len(self.odom_buffer.buffer)
                    odom_range = (
                        (
                            self.odom_buffer.buffer[0].header.stamp.to_sec(),
                            self.odom_buffer.buffer[-1].header.stamp.to_sec(),
                        )
                        if odom_count >= 2
                        else (None, None)
                    )
                rospy.logerr(
                    "[EVAL] odom match failed: target=%.3f count=%d range=%s",
                    stamp_value,
                    odom_count,
                    odom_range,
                )
            self._last_image_odom_delta_ms = None
            return None
        self._last_image_odom_delta_ms = (
            abs(odom_msg.header.stamp.to_sec() - stamp_value) * 1000.0
        )
        current_state, current_depth_state, p_w_cam = self._extract_pose_from_odom(
            odom_msg
        )
        cloud_xyz = current_frame.cloud_xyz
        if self.cloud_history is not None:
            history_snapshot = self.cloud_history.snapshot()
            if history_snapshot is not None:
                cloud_xyz = history_snapshot
        return replace(
            current_frame,
            cloud_xyz=cloud_xyz,
            cloud_ranges=self._compute_cloud_ranges(cloud_xyz, p_w_cam),
            current_state=current_state,
            current_depth_state=current_depth_state,
            stamp=stamp_value,
            cloud_projection_cache=None,
        )

    def build_frame_from_latest_cache(
        self,
        *,
        image_max_age_s: float = 0.5,
        cloud_max_age_s: float = 1.0,
        rgb_image=None,
        image_stamp=None,
    ) -> Optional[Frame]:
        """Build a frame purely from independent caches; no synchronizer.

        The waypoint chain must never depend on RGB/cloud message-filter
        synchronization. This method uses only:
          - latest fast RGB (with receive wall time)
          - newest odom sample (no interpolation)
          - current world-cloud time window snapshot
        Any stale or unaligned input returns None; no fallback to an older
        synchronized Frame is allowed.
        """
        with self._fast_rgb_lock:
            fast_image = self._fast_rgb_image
            fast_stamp = self._fast_rgb_stamp
            fast_wall = self._fast_rgb_wall_time
        if rgb_image is not None and image_stamp is not None:
            fast_image = rgb_image
            fast_stamp = float(image_stamp)
            fast_wall = time.time()
        if fast_image is None or float(fast_stamp) <= 0.0:
            return None
        wall_now = time.time()
        image_age = (wall_now - float(fast_wall)) if fast_wall > 0.0 else None
        if image_age is None or image_age > float(image_max_age_s):
            if getattr(self, "_eval_debug_log", False):
                rospy.logerr(
                    "[BasePolicy] stale RGB: age_ms=%s stamp=%.3f wall=%.3f now=%.3f",
                    None if image_age is None else image_age * 1000.0,
                    fast_stamp,
                    fast_wall,
                    wall_now,
                )
            return None
        # Use the newest odom sample directly (static scenes; 250Hz odom means
        # the newest sample is at most a few ms old).
        odom_msg = self.odom_buffer.get_latest()
        if odom_msg is None:
            if getattr(self, "_eval_debug_log", False):
                with self.odom_buffer.lock:
                    odom_count = len(self.odom_buffer.buffer)
                rospy.logerr(
                    "[BasePolicy] odom empty count=%d (RGB stamp=%.3f wall=%.3f)",
                    odom_count,
                    fast_stamp,
                    fast_wall,
                )
            return None
        cloud_xyz = None
        if self.cloud_history is not None:
            cloud_stats = self.cloud_history.stats()
            if cloud_stats.get("frames", 0) > 0:
                cloud_wall = cloud_stats.get("latest_wall_time")
                if cloud_wall is not None and (wall_now - float(cloud_wall)) > float(
                    cloud_max_age_s
                ):
                    if getattr(self, "_eval_debug_log", False):
                        rospy.logerr(
                            "[BasePolicy] stale cloud: age_ms=%.1f",
                            (wall_now - float(cloud_wall)) * 1000.0,
                        )
                    return None
                cloud_xyz = self.cloud_history.snapshot()
        if cloud_xyz is None:
            return None
        current_state, current_depth_state, p_w_cam = self._extract_pose_from_odom(
            odom_msg
        )
        depth_image = None
        if self.depth_enabled:
            depth_msg = self.depth_buffer.get_nearest(float(fast_stamp))
            if depth_msg is not None:
                try:
                    depth_image = self._decode_depth_message(depth_msg)
                except Exception:
                    depth_image = None
        frame = Frame(
            rgb_image=fast_image.copy(),
            depth_image=depth_image,
            cloud_msg=None,
            cloud_xyz=cloud_xyz,
            cloud_ranges=self._compute_cloud_ranges(cloud_xyz, p_w_cam),
            current_state=current_state,
            current_depth_state=current_depth_state,
            stamp=float(fast_stamp),
            cloud_projection_cache=None,
        )
        self._last_image_odom_delta_ms = (
            abs(odom_msg.header.stamp.to_sec() - float(fast_stamp)) * 1000.0
        )
        return frame

    def _camera_info_for_image_space(self, image_space: str = "depth"):
        """按像素所属图像空间返回对应内参。"""
        space = str(image_space or "depth").strip().lower()
        if space in ("rgb", "color"):
            return getattr(self, "color_info", None)
        return getattr(self, "depth_info", None)

    def _camera_info_from_params(self, prefix: str, defaults: dict) -> dict:
        """从 YAML 展开的 ROS 私有参数读取相机静态默认内参。"""
        info = {}
        for key, default_value in defaults.items():
            param_name = f"~{prefix}_{key}"
            if key in ("height", "width"):
                info[key] = int(rospy.get_param(param_name, int(default_value)))
            else:
                info[key] = float(rospy.get_param(param_name, float(default_value)))
        return info

    def _planar_axes_from_yaw(self, yaw: float):
        """根据平面 yaw 构造世界系前向/左向单位向量。"""
        forward_world = np.array([math.cos(yaw), math.sin(yaw), 0.0], dtype=np.float64)
        forward_world = forward_world / (np.linalg.norm(forward_world) + 1e-12)
        left_world = np.array(
            [-forward_world[1], forward_world[0], 0.0], dtype=np.float64
        )
        left_world = left_world / (np.linalg.norm(left_world) + 1e-12)
        return forward_world, left_world

    def _planar_axes_from_bearing(self, origin_xyz, target_xyz, fallback_yaw: float):
        """根据 origin->target 的平面朝向构造世界系前向/左向单位向量。"""
        origin = np.asarray(origin_xyz, dtype=np.float64).reshape(-1)
        target = np.asarray(target_xyz, dtype=np.float64).reshape(-1)
        if origin.size < 2 or target.size < 2:
            return (
                *self._planar_axes_from_yaw(float(fallback_yaw)),
                float(fallback_yaw),
            )
        vec = np.array(
            [target[0] - origin[0], target[1] - origin[1], 0.0], dtype=np.float64
        )
        norm = float(np.linalg.norm(vec[:2]))
        if not np.isfinite(norm) or norm < 1e-6:
            forward_world, left_world = self._planar_axes_from_yaw(float(fallback_yaw))
            return forward_world, left_world, float(fallback_yaw)
        forward_world = vec / (norm + 1e-12)
        bearing_yaw = float(math.atan2(forward_world[1], forward_world[0]))
        left_world = np.array(
            [-forward_world[1], forward_world[0], 0.0], dtype=np.float64
        )
        left_world = left_world / (np.linalg.norm(left_world) + 1e-12)
        return forward_world, left_world, bearing_yaw

    def _decode_rgb_message(self, rgb_msg: Any) -> np.ndarray:
        """统一解码压缩/非压缩 RGB 图像。"""
        if isinstance(rgb_msg, CompressedImage):
            return self.bridge.compressed_imgmsg_to_cv2(rgb_msg, "bgr8")
        return self.bridge.imgmsg_to_cv2(rgb_msg, "bgr8")

    def _decode_depth_compressed_message(self, depth_msg: CompressedImage):
        """解码普通 compressed 或 compressedDepth 深度消息。"""
        raw_data = np.frombuffer(depth_msg.data, np.uint8)
        fmt = str(getattr(depth_msg, "format", "") or "")
        fmt_lower = fmt.lower()
        if "compresseddepth" in fmt_lower:
            if raw_data.size <= 12:
                raise ValueError("compressedDepth payload is shorter than 12 bytes")
            raw_data = raw_data[12:]
        depth = cv2.imdecode(raw_data, cv2.IMREAD_UNCHANGED)
        if depth is None:
            raise ValueError("cv2.imdecode failed for depth message")
        return depth, fmt

    def _normalize_depth_image(
        self, depth_raw: np.ndarray, encoding_hint: str = ""
    ) -> np.ndarray:
        """将不同格式的深度图统一转换成米。"""
        depth = np.asarray(depth_raw)
        if depth.ndim == 3:
            depth = depth[:, :, 0]
        src_dtype = depth.dtype
        enc = str(encoding_hint or "").lower()

        if np.issubdtype(src_dtype, np.floating) or ("32f" in enc) or ("64f" in enc):
            depth_m = depth.astype(np.float32)
        elif np.issubdtype(src_dtype, np.unsignedinteger) and (
            ("16u" in enc)
            or ("mono16" in enc)
            or ("16uc1" in enc)
            or float(np.nanmax(depth)) > 255.0
        ):
            depth_m = depth.astype(np.float32) * 0.001
        elif np.issubdtype(src_dtype, np.integer) and float(np.nanmax(depth)) <= 255.0:
            depth_m = (
                (255.0 - depth.astype(np.float32))
                / 255.0
                * float(self.depth_uint8_max_range)
            )
            depth_m[depth_m < 1e-6] = float(self.depth_uint8_max_range) + 0.1
        else:
            depth_m = depth.astype(np.float32)

        invalid = (~np.isfinite(depth_m)) | (depth_m <= 0.0)
        if np.any(invalid):
            depth_m = depth_m.copy()
            depth_m[invalid] = float(self.pc_max_range) + 0.1
        return depth_m

    def _decode_depth_message(self, depth_msg: Any) -> np.ndarray:
        """统一解码压缩/非压缩深度图，并输出米制深度。"""
        if isinstance(depth_msg, CompressedImage):
            depth_raw, encoding_hint = self._decode_depth_compressed_message(depth_msg)
        else:
            encoding_hint = str(getattr(depth_msg, "encoding", "") or "")
            depth_raw = self.bridge.imgmsg_to_cv2(
                depth_msg, desired_encoding="passthrough"
            )
        return self._normalize_depth_image(depth_raw, encoding_hint=encoding_hint)

    def _extract_pose_from_odom(self, odom_msg: Odometry):
        """从 odom 提取机器人位姿和深度相机位姿。

        odom 是机体系(EKF)位姿;相机位姿由外参合成
        (compose_camera_state)。
        """
        pos = odom_msg.pose.pose.position
        ori = odom_msg.pose.pose.orientation
        roll, pitch, yaw = self.quaternion_to_euler(ori.x, ori.y, ori.z, ori.w)
        t_wb = np.array([pos.x, pos.y, pos.z], dtype=np.float64)
        current_state = np.array(
            [t_wb[0], t_wb[1], t_wb[2], roll, pitch, yaw], dtype=np.float64
        )
        current_depth_state = self.compose_camera_state(current_state)
        return current_state, current_depth_state, current_depth_state[:3]

    def compose_camera_state(self, body_state):
        """由机体系位姿 [x,y,z,roll,pitch,yaw] 合成相机系位姿(外参 T/R)。

        R_w_cam = R_wb @ camera_extrins_R;t_wc = t_wb + R_wb @ camera_extrins_T。
        """
        body_state = np.asarray(body_state, dtype=np.float64).reshape(6)
        R_wb = self.euler_rpy_to_R(body_state[3], body_state[4], body_state[5])
        R_w_cam = R_wb @ self.camera_extrins_R
        t_wc = body_state[:3] + R_wb @ self.camera_extrins_T
        roll_cam, pitch_cam, yaw_cam = self._R_to_rpy(R_w_cam)
        return np.array(
            [t_wc[0], t_wc[1], t_wc[2], roll_cam, pitch_cam, yaw_cam],
            dtype=np.float64,
        )

    def _compute_cloud_ranges(
        self, cloud_xyz: Optional[np.ndarray], origin_xyz: np.ndarray
    ) -> Optional[np.ndarray]:
        """计算世界系点云到相机原点的距离。"""
        if cloud_xyz is None:
            return None
        diffs = np.asarray(cloud_xyz, dtype=np.float64) - np.asarray(
            origin_xyz, dtype=np.float64
        ).reshape(1, 3)
        return np.linalg.norm(diffs, axis=1)

    def _headless_callback(self, odom_msg: Odometry) -> None:
        """headless 模式回调: 仅用里程计构建最小 Frame。odom_topic 为空时不调用。"""
        current_state, current_depth_state, p_w_cam = self._extract_pose_from_odom(
            odom_msg
        )
        frame = Frame(
            rgb_image=np.zeros(
                (self.depth_info["height"], self.depth_info["width"], 3), dtype=np.uint8
            ),
            depth_image=None,
            cloud_msg=None,
            cloud_xyz=None,
            cloud_ranges=None,
            current_state=current_state,
            current_depth_state=current_depth_state,
            stamp=odom_msg.header.stamp.to_sec(),
        )
        with self.frame_lock:
            self.frame = frame
        with self.frame_history_lock:
            self.frame_history.append(frame)

    def odom_callback(self, odom_msg: Odometry) -> None:
        """独立里程计回调：供 odom_interpolation 模式按图像时间戳插值。"""
        self._stamp_input("odom")
        self.odom_buffer.add_odom(odom_msg)

    def _stamp_input(self, channel: str) -> None:
        """记录一路输入的最后收到时刻（健康跟踪）。"""
        with self._input_health_lock:
            self._input_last_rcv[channel] = time.time()

    def _track_input_health(self) -> None:
        """在 message_filters 订阅上注册零拷贝健康戳（issue #90）。

        Subscriber 本身是逐消息触发的 filter，registerCallback 与同步器
        共用同一条底层订阅，不产生第二份点云/图像流量。
        odom_interpolation 模式下 odom 走独立回调（odom_callback 内打戳）。
        """
        self.rgb_sub.registerCallback(lambda _msg: self._stamp_input("rgb"))
        if self.depth_sub is not None:
            self.depth_sub.registerCallback(lambda _msg: self._stamp_input("depth"))
        self.cloud_sub.registerCallback(lambda _msg: self._stamp_input("cloud"))
        if isinstance(self.odom_sub, MFSubscriber):
            self.odom_sub.registerCallback(lambda _msg: self._stamp_input("odom"))

    def get_sensor_input_health(self) -> dict:
        """各输入通道的 (topic, 距上次收包秒数) 快照；None = 从未收到。

        供 INIT/首帧等待的可观测信号（dispatcher_wait_cloud）与链就绪判定
        （chain_not_ready 拒单原因）直接点名死掉的那一路。
        """
        now = time.time()
        topics = {
            "odom": self.odom_topic,
            "rgb": self.rgb_topic,
            "cloud": self.cloud_topic,
        }
        if self.depth_enabled:
            topics["depth"] = self.depth_topic
        with self._input_health_lock:
            stamps = dict(self._input_last_rcv)
        return {
            channel: (topic, (now - stamps[channel]) if channel in stamps else None)
            for channel, topic in topics.items()
        }

    def _cloud_to_xyz_array(self, cloud_msg: PointCloud2) -> Optional[np.ndarray]:
        """PointCloud2 -> (N, 3) 点云数组（保持话题原始坐标系，不做外参转换）"""
        if cloud_msg is None:
            return None
        points = np.array(
            list(
                pc2.read_points(cloud_msg, field_names=("x", "y", "z"), skip_nans=False)
            ),
            dtype=np.float32,
        )
        if points.size == 0:
            return None
        return points.reshape((-1, 3))

    def quaternion_to_euler(self, x, y, z, w):
        """四元数 -> 欧拉角 (roll, pitch, yaw)"""
        t0 = +2.0 * (w * x + y * z)
        t1 = +1.0 - 2.0 * (x * x + y * y)
        roll = np.arctan2(t0, t1)

        t2 = +2.0 * (w * y - z * x)
        t2 = +1.0 if t2 > +1.0 else t2
        t2 = -1.0 if t2 < -1.0 else t2
        pitch = np.arcsin(t2)

        t3 = +2.0 * (w * z + x * y)
        t4 = +1.0 - 2.0 * (y * y + z * z)
        yaw = np.arctan2(t3, t4)
        return roll, pitch, yaw

    def euler_to_quaternion(self, roll, pitch, yaw):
        """欧拉角 -> 四元数 (x, y, z, w)"""
        cy = np.cos(yaw * 0.5)
        sy = np.sin(yaw * 0.5)
        cp = np.cos(pitch * 0.5)
        sp = np.sin(pitch * 0.5)
        cr = np.cos(roll * 0.5)
        sr = np.sin(roll * 0.5)
        qw = cr * cp * cy + sr * sp * sy
        qx = sr * cp * cy - cr * sp * sy
        qy = cr * sp * cy + sr * cp * sy
        qz = cr * cp * sy - sr * sp * cy
        return qx, qy, qz, qw

    def euler_rpy_to_R(self, roll, pitch, yaw):
        """R = Rz(yaw) @ Ry(pitch) @ Rx(roll)"""
        sr, cr = np.sin(roll), np.cos(roll)
        sp, cp = np.sin(pitch), np.cos(pitch)
        sy, cy = np.sin(yaw), np.cos(yaw)
        Rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]], dtype=np.float64)
        Ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]], dtype=np.float64)
        Rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]], dtype=np.float64)
        return Rz @ Ry @ Rx

    def _R_to_rpy(self, R):
        """Rz@Ry@Rx 旋转矩阵 -> (roll, pitch, yaw),与 euler_rpy_to_R 互逆。"""
        R = np.asarray(R, dtype=np.float64)
        pitch = float(np.arcsin(np.clip(-R[2, 0], -1.0, 1.0)))
        roll = float(np.arctan2(R[2, 1], R[2, 2]))
        yaw = float(np.arctan2(R[1, 0], R[0, 0]))
        return roll, pitch, yaw

    def _backproject(self, u, v, depth_value, fx, fy, cx, cy, mode="z"):
        """基于内参将像素点回投到相机坐标系。"""
        d = np.array([(u - cx) / fx, (v - cy) / fy, 1.0], dtype=np.float64)
        if mode == "z":
            Z = depth_value
            return d * Z
        elif mode == "range":
            s = d / np.linalg.norm(d)
            return s * depth_value
        else:
            raise ValueError(f"Unknown depth mode: {mode}")

    def bbox_center(self, results):
        """从检测结果中提取首个 bbox 的中心像素。"""
        if not results:
            raise ValueError("Results list is empty")
        bbox = results[0].get("bbox_2d", None)
        if bbox is None or len(bbox) != 4:
            raise ValueError("Invalid bbox_2d format")
        x1, y1, x2, y2 = bbox
        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2
        return center_x, center_y

    def _to_rad(self, ang):
        """度/弧度自适应：若|ang|>pi视为度并转弧度"""
        if isinstance(ang, (list, tuple, np.ndarray)):
            return [self._to_rad(a) for a in ang]
        return np.deg2rad(ang) if abs(float(ang)) > np.pi else float(ang)

    def _fov_hv_from_info(self, fov_info, W, H):
        """
        接受：
        - 标量：默认为水平FOV
        - 字典：{'h':.., 'v':..} / 仅 'h' / 仅 'v' / {'diag':..}
        返回：fh, fv（弧度）
        """
        r = W / float(H)
        if isinstance(fov_info, dict):
            if "h" in fov_info and "v" in fov_info:
                fh, fv = self._to_rad(fov_info["h"]), self._to_rad(fov_info["v"])
            elif "h" in fov_info:
                fh = self._to_rad(fov_info["h"])
                fv = 2.0 * np.arctan(np.tan(fh / 2.0) * (1.0 / r))
            elif "v" in fov_info:
                fv = self._to_rad(fov_info["v"])
                fh = 2.0 * np.arctan(np.tan(fv / 2.0) * r)
            elif "diag" in fov_info:
                fd = self._to_rad(fov_info["diag"])
                a = np.tan(fd / 2.0)
                t = a / np.sqrt(r * r + 1.0)
                fv = 2.0 * np.arctan(t)
                fh = 2.0 * np.arctan(r * t)
            else:
                raise ValueError("fov dict 需含 'h'/'v'/'diag' 之一")
        else:
            fh = self._to_rad(fov_info)
            fv = 2.0 * np.arctan(np.tan(fh / 2.0) * (1.0 / r))
        return fh, fv

    def _backproject_from_fov(self, u, v, depth_value, W, H, fov_info, mode="z"):
        """用FOV回投到相机光学系(OpenCV: x右、y下、z前)"""
        fh, fv = self._fov_hv_from_info(fov_info, W, H)
        cx = (W - 1) * 0.5
        cy = (H - 1) * 0.5
        nx = (u - cx) / max(cx, 1e-9)
        ny = (v - cy) / max(cy, 1e-9)
        thx = nx * (fh * 0.5)
        thy = ny * (fv * 0.5)
        d = np.array([np.tan(thx), np.tan(thy), 1.0], dtype=np.float64)
        if mode == "z":
            return d * float(depth_value)
        elif mode == "range":
            s = d / np.linalg.norm(d)
            return s * float(depth_value)
        else:
            raise ValueError(f"Unknown depth mode: {mode}")

    def _depth_bbox_inner_bounds(self, bbox, W: int, H: int):
        """对 bbox 做中心内收 ROI。"""
        x1, y1, x2, y2 = [float(v) for v in bbox]
        x1 = max(0, min(int(round(x1)), W - 1))
        x2 = max(0, min(int(round(x2)), W - 1))
        y1 = max(0, min(int(round(y1)), H - 1))
        y2 = max(0, min(int(round(y2)), H - 1))
        x0 = int((x2 - x1) / 4) + x1
        x1b = int((x1 - x2) / 4) + x2 + 1
        y0 = int((y2 - y1) / 4) + y1
        y1b = int((y1 - y2) / 4) + y2 + 1
        x0 = max(0, min(x0, W - 1))
        y0 = max(0, min(y0, H - 1))
        x1b = max(0, min(x1b, W))
        y1b = max(0, min(y1b, H))
        if x1b <= x0 or y1b <= y0:
            x0, y0 = x1, y1
            x1b, y1b = min(W, x2 + 1), min(H, y2 + 1)
        return x0, y0, x1b, y1b

    def _build_region_from_bbox(self, results, frame: Frame) -> PixelRegion:
        """由检测结果构造 bbox 区域。"""
        if results is None or "pos" not in results:
            raise ValueError("bbox result is invalid")
        u, v = float(results["pos"][0]), float(results["pos"][1])
        bbox = results.get("bbox")
        bbox_tuple = None if bbox is None else tuple(float(vv) for vv in bbox)
        return PixelRegion(kind="bbox", u=u, v=v, bbox=bbox_tuple)

    def _build_region_from_mask(self, mask_u8, frame: Frame) -> PixelRegion:
        """由分割 mask 构造区域。"""
        if frame is None or frame.rgb_image is None:
            raise ValueError("frame rgb_image is not ready")
        Hr, Wr = frame.rgb_image.shape[:2]
        mask = self._normalize_mask_to_shape(mask_u8, H=Hr, W=Wr)
        ys_all, xs_all = np.where(mask > 0)
        if xs_all.size == 0:
            raise ValueError("mask is empty")
        bbox = (
            float(np.min(xs_all)),
            float(np.min(ys_all)),
            float(np.max(xs_all)),
            float(np.max(ys_all)),
        )
        return PixelRegion(
            kind="mask",
            u=float(np.mean(xs_all)),
            v=float(np.mean(ys_all)),
            bbox=bbox,
            mask_u8=mask,
            xs_all=xs_all.astype(np.float64),
            ys_all=ys_all.astype(np.float64),
        )

    def _compute_adjusted_depth_value(
        self, depth_raw: float, max_valid_range: float, depth_scale: float
    ):
        """按安全半径规则将原始深度转换为最终推进深度。"""
        skip_safe_dis = self.mission_type == MISSION_TYPE.PASS_THROUGH
        if not self.if_safe_dis or skip_safe_dis:
            depth_val = depth_raw * depth_scale
        elif depth_raw > 2.0 + 1e-6:
            # if depth_raw > max_valid_range - 1e-6:
            #     depth_val = depth_raw - self.safe_dis_radius_m
            # else:
            #     depth_val = (depth_raw - self.safe_dis_radius_m) * depth_scale
            depth_val = (depth_raw - self.safe_dis_radius_m) * depth_scale
        else:
            depth_val = (depth_raw - self.safe_dis_radius_m * 0.5) * depth_scale
            if not skip_safe_dis:
                self.if_safe_dis = True
        return max(float(depth_val), 0.0)

    def bbox_candidate_to_body_incremental_waypoints(
        self,
        region: PixelRegion,
        candidate: WaypointCandidate,
        frame: Frame,
        *,
        safe_dis_radius_m: float,
    ) -> dict:
        """Convert bbox depth into body increments and absolute world targets."""
        camera_info = (
            self.depth_info if candidate.source == "depth" else self.color_info
        )
        if camera_info is None:
            raise ValueError(f"{candidate.source} camera intrinsics are not ready")

        state = np.asarray(frame.current_state, dtype=np.float64).reshape(-1)
        R_wb = self.euler_rpy_to_R(float(state[3]), float(state[4]), float(state[5]))
        body_position_world = state[:3]
        ray_camera = self.bbox_pixel_to_camera(
            region.u,
            region.v,
            1.0,
            camera_info,
            depth_mode="range",
        )
        ray_world = R_wb @ (ray_camera / (np.linalg.norm(ray_camera) + 1e-12))
        ray_xy_norm = float(np.linalg.norm(ray_world[:2]))
        target_yaw = (
            float(state[5])
            if ray_xy_norm <= 1e-9
            else math.atan2(float(ray_world[1]), float(ray_world[0]))
        )
        if str(self.depth_source).lower() == "mix" and candidate.source == "cloud":
            object_world = np.asarray(
                candidate.bearing_world, dtype=np.float64
            ).reshape(3)
            object_increment = R_wb.T @ (object_world - body_position_world)
        elif str(self.depth_source).lower() == "mix" and candidate.source == "depth":
            object_increment = self.bbox_pixel_to_camera(
                region.u,
                region.v,
                candidate.raw_depth,
                camera_info,
                depth_mode="z",
            )
            object_world = np.asarray(
                candidate.bearing_world, dtype=np.float64
            ).reshape(3)
        else:
            depth_mode = "z" if candidate.source == "depth" else "range"
            object_increment = self.bbox_pixel_to_camera(
                region.u,
                region.v,
                candidate.raw_depth,
                camera_info,
                depth_mode=depth_mode,
            )
            object_world = body_position_world + R_wb @ object_increment

        target_increment = object_increment.copy()
        target_increment[0] = max(
            0.0, float(target_increment[0]) - float(safe_dis_radius_m)
        )
        target_world = body_position_world + R_wb @ target_increment

        object_delta = object_world[:2] - target_world[:2]
        if float(np.linalg.norm(object_delta)) > 1e-6:
            target_yaw = math.atan2(float(object_delta[1]), float(object_delta[0]))
        incremental_yaw = math.atan2(
            math.sin(target_yaw - float(state[5])),
            math.cos(target_yaw - float(state[5])),
        )

        return {
            "object_increment": object_increment,
            "target_increment": target_increment,
            "object_world": object_world,
            "target_world": target_world,
            "target_yaw": target_yaw,
            "incremental_yaw": incremental_yaw,
            "yaw_source": "image_bbox_center_ray",
        }

    def _get_camera_world_pose(self, frame: Frame):
        """返回相机在世界系下的位姿。"""
        tx_c, ty_c, tz_c, roll_c, pitch_c, yaw_c = map(
            float, frame.current_depth_state.tolist()
        )
        R_w_cam = self.euler_rpy_to_R(roll_c, pitch_c, yaw_c)
        t_wc = np.array([tx_c, ty_c, tz_c], dtype=np.float64)
        return R_w_cam, t_wc

    def bbox_pixel_to_camera(
        self,
        u: float,
        v: float,
        depth: float,
        camera_info: dict,
        *,
        depth_mode: str = "z",
    ) -> np.ndarray:
        """Back-project one bbox pixel into the x-forward camera frame."""
        fx = float(camera_info["fx"])
        fy = float(camera_info["fy"])
        cx = float(camera_info["cx"])
        cy = float(camera_info["cy"])
        dx = (float(u) - cx) / (fx if abs(fx) > 1e-12 else 1e-12)
        dy = (float(v) - cy) / (fy if abs(fy) > 1e-12 else 1e-12)
        point_optical = np.array([dx, dy, 1.0], dtype=np.float64)
        if str(depth_mode).lower() == "range":
            point_optical *= float(depth) / (np.linalg.norm(point_optical) + 1e-12)
        else:
            point_optical *= float(depth)
        return np.asarray(
            self._optical_to_camera_points(point_optical), dtype=np.float64
        ).reshape(3)

    def bbox_camera_to_world(self, point_camera, frame: Frame) -> np.ndarray:
        """Transform a camera-frame bbox point into the world frame."""
        R_w_cam, t_wc = self._get_camera_world_pose(frame)
        return t_wc + R_w_cam @ np.asarray(point_camera, dtype=np.float64).reshape(3)

    def bbox_camera_waypoint_to_body_world(
        self, camera_waypoint_world, target_yaw: float
    ) -> np.ndarray:
        """Return the body odom target that places the camera at a world waypoint."""
        R_wb_goal = self.euler_rpy_to_R(0.0, 0.0, float(target_yaw))
        return (
            np.asarray(camera_waypoint_world, dtype=np.float64).reshape(3)
            - R_wb_goal @ self.camera_extrins_T
        )

    def _optical_to_camera_points(self, P_opt):
        """OpenCV 光学系点转换到机体系（x前、y左、z上）。"""
        R_opt2cam = np.array(
            [
                [0, 0, 1],
                [-1, 0, 0],
                [0, -1, 0],
            ],
            dtype=np.float64,
        )
        arr = np.asarray(P_opt, dtype=np.float64)
        if arr.ndim == 1:
            return R_opt2cam @ arr
        return (R_opt2cam @ arr.T).T

    def _depth_pixels_to_optical(
        self, xs, ys, depths, fx, fy, cx, cy, W, H, depth_mode="z"
    ):
        """将一组深度像素回投到光学系。"""
        xs = np.asarray(xs, dtype=np.float64)
        ys = np.asarray(ys, dtype=np.float64)
        depths = np.asarray(depths, dtype=np.float64)
        if self.use_intrinsics:
            dx = (xs - cx) / (fx if abs(fx) > 1e-12 else 1e-12)
            dy = (ys - cy) / (fy if abs(fy) > 1e-12 else 1e-12)
            return np.stack([dx * depths, dy * depths, depths], axis=1)
        fh, fv = self._fov_hv_from_info(self.depth_info["fov"], W, H)
        cxf = (W - 1) * 0.5
        cyf = (H - 1) * 0.5
        nx = (xs - cxf) / max(cxf, 1e-9)
        ny = (ys - cyf) / max(cyf, 1e-9)
        thx = nx * (fh * 0.5)
        thy = ny * (fv * 0.5)
        d = np.stack([np.tan(thx), np.tan(thy), np.ones_like(thx)], axis=1)
        if str(depth_mode).lower() == "range":
            d_norm = np.linalg.norm(d, axis=1, keepdims=True)
            return (d / (d_norm + 1e-12)) * depths[:, None]
        return d * depths[:, None]

    def _pixel_dir_world(
        self,
        px: float,
        py: float,
        fx: float,
        fy: float,
        cx: float,
        cy: float,
        R_w_cam: np.ndarray,
    ):
        """像素对应的世界系射线方向。"""
        dx = (px - cx) / (fx if abs(fx) > 1e-12 else 1e-12)
        dy = (py - cy) / (fy if abs(fy) > 1e-12 else 1e-12)
        dir_opt = np.array([dx, dy, 1.0], dtype=np.float64)
        dir_opt = dir_opt / (np.linalg.norm(dir_opt) + 1e-12)
        dir_cam = self._optical_to_camera_points(dir_opt)
        dir_world = R_w_cam @ dir_cam
        return dir_world / (np.linalg.norm(dir_world) + 1e-12)

    def _effective_depth_percent_point(self, percent_point: float) -> float:
        """返回 depth 分支实际用于选点的比例，供 mix 判定复用同一阈值。"""
        percent_point_local = float(percent_point)
        if self.mission_type == MISSION_TYPE.PASS_THROUGH:
            percent_point_local = 0.15
        elif not self.if_safe_dis:
            percent_point_local = 0.3
        return percent_point_local

    def _compute_region_depth_stats(
        self, region: PixelRegion, frame: Frame, *, percent_point: float = 0.2
    ):
        """根据区域在深度图上的像素分布统计有效深度占比。"""
        if frame is None or frame.depth_image is None:
            return {
                "valid_count": 0,
                "total_count": 0,
                "valid_ratio": 0.0,
                "required_ratio": 1.0,
            }
        depth_img = np.asarray(frame.depth_image, dtype=np.float64)
        H, W = depth_img.shape[:2]
        finite = np.isfinite(depth_img)
        max_valid_depth = float(getattr(self, "depth_valid_max_range", 5.0)) - 1e-6
        valid_depth = finite & (depth_img > 0.2 + 1e-6) & (depth_img < max_valid_depth)
        if region.kind == "mask":
            mask = self._normalize_mask_to_shape(region.mask_u8, H=H, W=W) > 0
            total_count = int(np.count_nonzero(mask))
            valid_count = int(np.count_nonzero(mask & valid_depth))
        else:
            bbox = region.bbox
            if bbox is None:
                return {
                    "valid_count": 0,
                    "total_count": 0,
                    "valid_ratio": 0.0,
                    "required_ratio": 1.0,
                }
            x0, y0, x1b, y1b = self._depth_bbox_inner_bounds(bbox, W=W, H=H)
            patch_valid = valid_depth[y0:y1b, x0:x1b]
            total_count = int(max(0, x1b - x0) * max(0, y1b - y0))
            valid_count = int(np.count_nonzero(patch_valid))
        effective_percent = self._effective_depth_percent_point(percent_point)
        required_ratio = min(
            1.0, max(0.0, effective_percent + float(self.depth_valid_ratio_margin))
        )
        valid_ratio = (
            0.0 if total_count <= 0 else float(valid_count) / float(total_count)
        )
        return {
            "valid_count": valid_count,
            "total_count": total_count,
            "valid_ratio": valid_ratio,
            "required_ratio": required_ratio,
        }

    def _sensor_priority_for_region(
        self, region: PixelRegion, frame: Frame, *, percent_point: float = 0.2
    ):
        """Return the configured geometry source order for one image region."""
        source = str(self.depth_source or "cloud").strip().lower()
        if source == "depth":
            return ["depth", "cloud"]
        if source == "cloud":
            return ["cloud", "depth"]
        stats = self._compute_region_depth_stats(
            region, frame, percent_point=percent_point
        )
        self.last_mix_valid_count = int(stats["valid_count"])
        self.last_mix_total_count = int(stats["total_count"])
        self.last_mix_far_count = max(
            0, int(stats["total_count"]) - int(stats["valid_count"])
        )
        self.last_mix_far_ratio = 1.0 - float(stats["valid_ratio"])
        self.last_mix_required_ratio = float(stats["required_ratio"])
        # Mix keeps both geometry sources available, but registered cloud is
        # authoritative; aligned depth is used only when cloud estimation fails.
        return ["cloud", "depth"]

    def _publish_candidate_debug_points(
        self, candidate: WaypointCandidate, frame: Frame
    ):
        """发布候选点对应的调试点云。"""
        bbox_has_sub = (
            self.bbox_cloud_pub is not None
            and hasattr(self.bbox_cloud_pub, "get_num_connections")
            and self.bbox_cloud_pub.get_num_connections() > 0
        )
        mask_has_sub = (
            self.mask_cloud_pub is not None
            and hasattr(self.mask_cloud_pub, "get_num_connections")
            and self.mask_cloud_pub.get_num_connections() > 0
        )
        if not bbox_has_sub and not mask_has_sub:
            return
        if (
            bbox_has_sub
            and candidate.bbox_points_world is not None
            and candidate.bbox_points_world.shape[0] > 0
        ):
            self._publish_bbox_cloud(candidate.bbox_points_world, frame.stamp)
        if (
            mask_has_sub
            and candidate.mask_points_world is not None
            and candidate.mask_points_world.shape[0] > 0
        ):
            self._publish_mask_cloud(candidate.mask_points_world, frame.stamp)

    def _finalize_waypoint_candidate(
        self,
        candidate: WaypointCandidate,
        frame: Frame,
        *,
        pose_yaw: float,
        direction: str = "",
        behind_dist: float = 0.0,
        d_side: float = 0.5,
        d_forward: float = 0.5,
    ):
        """对候选 3D 点统一施加任务偏移并更新状态。"""
        self.last_waypoint_source = candidate.source
        self.depth_match_ok = bool(candidate.match_ok)
        self._publish_candidate_debug_points(candidate, frame)

        roll, pitch = map(float, frame.current_state[3:5].tolist())
        P_w = np.asarray(candidate.point_world, dtype=np.float64).reshape(
            3,
        )
        bearing_world = np.asarray(candidate.bearing_world, dtype=np.float64).reshape(
            3,
        )
        origin_xyz = np.asarray(frame.current_state[:3], dtype=np.float64)
        forward_world, left_world, _ = self._planar_axes_from_bearing(
            origin_xyz,
            bearing_world,
            float(frame.current_state[5]),
        )
        half_w = float(candidate.half_w)
        half_h = float(candidate.half_h)
        outward_extra = max(d_side, half_w)

        # [py38] match -> if/elif chain (ported by py38_match_port)
        if self.mission_type == MISSION_TYPE.NAVIGATION:
            # [py38] match -> if/elif chain (ported by py38_match_port)
            if direction == "left":
                side_total = half_w + outward_extra
                P_target = P_w + side_total * left_world + d_forward * forward_world
            elif direction == "right":
                side_total = half_w + outward_extra
                P_target = P_w - side_total * left_world + d_forward * forward_world
            elif direction in ("上方", "up"):
                P_target = P_w + 0.2 * forward_world
                P_target[2] += half_h + 0.8
            elif direction in ("后方", "后面"):
                P_target = P_w + behind_dist * forward_world
            else:
                P_target = P_w
        elif self.mission_type == MISSION_TYPE.BYPASS:
            # [py38] match -> if/elif chain (ported by py38_match_port)
            if direction in ("左", "left"):
                side_total = half_w + outward_extra
                P_target = (
                    P_w + side_total * left_world + (d_forward + 1.5) * forward_world
                )
            elif direction in ("右", "right"):
                side_total = half_w + outward_extra
                P_target = (
                    P_w - side_total * left_world + (d_forward + 1.5) * forward_world
                )
            else:
                P_target = P_w
        elif self.mission_type == MISSION_TYPE.PASS_THROUGH:
            pass_point = P_w.copy()
            if self.is_stable:
                pass_point[2] = self.stable_height
            P_target = pass_point + 1.5 * forward_world
        else:
            P_target = P_w

        target_yaw = pose_yaw
        if candidate.target_yaw_world is not None:
            target_yaw = float(candidate.target_yaw_world)
        P_target = self.bbox_camera_waypoint_to_body_world(P_target, target_yaw)
        P_w_full = np.concatenate(
            [P_target, np.array([roll, pitch, target_yaw], dtype=np.float64)]
        )
        self._publish_p2w_marker(P_w_full, frame.stamp)
        if self.first_frame is None:
            self.first_waypoint = P_w_full
            self.first_depth = float(candidate.raw_depth)
        return P_w_full

    def _estimate_region_point_depth(
        self,
        region: PixelRegion,
        frame: Frame,
        *,
        depth_scale=1.0,
        window=0,
        depth_mode="z",
        avg_depth=True,
        percent_point=0.2,
        use_median=False,
    ) -> WaypointCandidate:
        """使用深度图估计区域对应的 3D 原始点。"""
        if self.depth_info is None:
            raise ValueError("相机参数未就绪")
        if frame.depth_image is None:
            raise ValueError("深度图未就绪")

        depth_img = np.asarray(frame.depth_image, dtype=np.float64)
        H, W = depth_img.shape[:2]
        u = float(region.u)
        v = float(region.v)
        ui = int(round(u))
        vi = int(round(v))
        if not (0 <= ui < W and 0 <= vi < H):
            raise ValueError(f"(u,v)=({ui},{vi}) 超出图像范围 {W}x{H}")

        fx = float(self.depth_info["fx"])
        fy = float(self.depth_info["fy"])
        cx = float(self.depth_info["cx"])
        cy = float(self.depth_info["cy"])
        overdepth_ratio = 0.0
        match_ok = True
        over_edge = False
        P_cam_override = None
        mask_points_world = None
        half_w = 0.0
        half_h = 0.0

        if region.kind == "mask":
            mask = self._normalize_mask_to_shape(region.mask_u8, H=H, W=W)
            ys_all, xs_all = np.where(mask > 0)
            if xs_all.size == 0:
                raise ValueError("mask is empty")
            mask_bool = mask > 0
            finite = np.isfinite(depth_img)

            mask_cloud_valid = mask_bool & finite & (depth_img > 1e-6)
            if np.any(mask_cloud_valid):
                ys_mask_all, xs_mask_all = np.where(mask_cloud_valid)
                depths_mask_all = depth_img[mask_cloud_valid].astype(np.float64)
                P_opt_mask_all = self._depth_pixels_to_optical(
                    xs_mask_all.astype(np.float64),
                    ys_mask_all.astype(np.float64),
                    depths_mask_all,
                    fx,
                    fy,
                    cx,
                    cy,
                    W,
                    H,
                    depth_mode=depth_mode,
                )
                P_cam_all = self._optical_to_camera_points(P_opt_mask_all)
                R_w_cam, t_wc = self._get_camera_world_pose(frame)
                mask_points_world = (R_w_cam @ P_cam_all.T).T + t_wc
                if self.is_stable:
                    mask_points_world[:, 2] = self.stable_height

            if np.any(mask_bool):
                overdepth_ratio = float(np.mean(depth_img[mask_bool] > 5.0 + 1e-6))
                match_ok = overdepth_ratio <= float(self.max_overdepth)

            valid_mask = (
                mask_bool
                & np.isfinite(depth_img)
                & (depth_img < 5.0 - 1e-6)
                & (depth_img > 0.2 + 1e-6)
            )
            valid_depths = depth_img[valid_mask]
            if valid_depths.size == 0:
                raise ValueError("no valid aligned depth in mask region")
            else:
                percent_point_local = percent_point
                if self.mission_type == MISSION_TYPE.PASS_THROUGH:
                    percent_point_local = 0.15
                elif not self.if_safe_dis:
                    percent_point_local = 0.3
                sort_idx = np.argsort(valid_depths)
                num_points = max(1, int(len(sort_idx) * percent_point_local))
                sel_idx = sort_idx[:num_points]
                ys_valid, xs_valid = np.where(valid_mask)
                sel_x = xs_valid[sel_idx].astype(np.float64)
                sel_y = ys_valid[sel_idx].astype(np.float64)
                sel_depths = valid_depths[sel_idx].astype(np.float64)
                P_opt_selected = self._depth_pixels_to_optical(
                    sel_x,
                    sel_y,
                    sel_depths,
                    fx,
                    fy,
                    cx,
                    cy,
                    W,
                    H,
                    depth_mode=depth_mode,
                )
                if self.mission_type == MISSION_TYPE.PASS_THROUGH:
                    P_cam_sel = self._optical_to_camera_points(P_opt_selected)
                    ranges_sel = np.linalg.norm(P_cam_sel, axis=1)
                    weights = 1.0 / (ranges_sel + 1e-6)
                    weighted_vec = np.sum(P_cam_sel * weights[:, None], axis=0) / (
                        np.sum(weights) + 1e-12
                    )
                    P_cam_override = weighted_vec
                    depth_raw = float(np.linalg.norm(weighted_vec))
                else:
                    selected_depths = valid_depths[sel_idx]
                    depth_raw = float(
                        np.median(selected_depths)
                        if use_median
                        else np.mean(selected_depths)
                    )

            x_span = float(np.max(xs_all) - np.min(xs_all) + 1.0)
            y_span = float(np.max(ys_all) - np.min(ys_all) + 1.0)
        else:
            bbox = region.bbox
            if bbox is None:
                raise ValueError("bbox is None")
            if avg_depth:
                x0, y0, x1b, y1b = self._depth_bbox_inner_bounds(bbox, W=W, H=H)
                bbox_depth = depth_img[y0:y1b, x0:x1b]
                if bbox_depth.size > 0:
                    overdepth_ratio = float(np.mean(bbox_depth > 5.0 + 1e-6))
                    match_ok = overdepth_ratio <= float(self.max_overdepth)
                valid_mask = (
                    np.isfinite(bbox_depth)
                    & (bbox_depth < 5.0 - 1e-6)
                    & (bbox_depth > 0.2 + 1e-6)
                )
                valid_depths = bbox_depth[valid_mask]
                if valid_depths.size == 0:
                    raise ValueError("no valid aligned depth in bbox region")
                else:
                    if self.mission_type == MISSION_TYPE.PASS_THROUGH:
                        sort_idx = np.argsort(valid_depths)
                        num_points = max(1, int(len(sort_idx) * 0.15))
                        sel_idx = sort_idx[:num_points]
                        ys, xs = np.where(valid_mask)
                        sel_x = xs[sel_idx].astype(np.float64) + float(x0)
                        sel_y = ys[sel_idx].astype(np.float64) + float(y0)
                        sel_depths = valid_depths[sel_idx].astype(np.float64)
                        P_opt_sel = self._depth_pixels_to_optical(
                            sel_x,
                            sel_y,
                            sel_depths,
                            fx,
                            fy,
                            cx,
                            cy,
                            W,
                            H,
                            depth_mode=depth_mode,
                        )
                        P_cam_sel = self._optical_to_camera_points(P_opt_sel)
                        ranges_sel = np.linalg.norm(P_cam_sel, axis=1)
                        weights = 1.0 / (ranges_sel + 1e-6)
                        weighted_vec = np.sum(P_cam_sel * weights[:, None], axis=0) / (
                            np.sum(weights) + 1e-12
                        )
                        P_cam_override = weighted_vec
                        depth_raw = float(np.linalg.norm(weighted_vec))
                    else:
                        selected_depths = self._select_bbox_depth_cluster(
                            bbox_depth,
                            valid_mask,
                        )
                        depth_raw = float(np.median(selected_depths))
            else:
                if window > 0:
                    u0, u1 = max(0, ui - window), min(W - 1, ui + window)
                    v0, v1 = max(0, vi - window), min(H - 1, vi + window)
                    patch = depth_img[v0 : v1 + 1, u0 : u1 + 1]
                    depth_raw = float(np.median(patch))
                else:
                    depth_raw = float(depth_img[vi, ui])
            x1, y1, x2, y2 = bbox
            x_span = max(1.0, float(x2 - x1))
            y_span = max(1.0, float(y2 - y1))

        if depth_raw > 5.0 + 1e-6:
            over_edge = True
            depth_raw = 5.1
        depth_val = self._compute_adjusted_depth_value(depth_raw, 5.0, depth_scale)

        if self.use_intrinsics:
            P_cam = self.bbox_pixel_to_camera(
                u,
                v,
                depth_val,
                self.depth_info,
                depth_mode=depth_mode,
            )
        else:
            P_opt = self._backproject_from_fov(
                u, v, depth_val, W, H, self.depth_info["fov"], mode=depth_mode
            )
            P_cam = self._optical_to_camera_points(P_opt)
        if P_cam_override is not None:
            P_cam = np.asarray(P_cam_override, dtype=np.float64).reshape(
                3,
            )

        P_w = self.bbox_camera_to_world(P_cam, frame)
        bearing_world = P_w.copy()
        if self.is_stable:
            P_w[2] = self.stable_height

        Z_forward = float(P_cam[0])
        if self.use_intrinsics:
            half_w = (
                0.5
                * (max(1.0, x_span) / (fx if abs(fx) > 1e-12 else 1e-12))
                * Z_forward
            )
            half_h = (
                0.5
                * (max(1.0, y_span) / (fy if abs(fy) > 1e-12 else 1e-12))
                * Z_forward
            )

        return WaypointCandidate(
            source="depth",
            point_world=np.asarray(P_w, dtype=np.float64).reshape(
                3,
            ),
            bearing_world=np.asarray(bearing_world, dtype=np.float64).reshape(
                3,
            ),
            raw_depth=float(depth_raw),
            over_edge=bool(over_edge),
            match_ok=bool(match_ok),
            overdepth_ratio=float(overdepth_ratio),
            half_w=float(max(0.0, half_w)),
            half_h=float(max(0.0, half_h)),
            mask_points_world=mask_points_world,
        )

    def _select_bbox_depth_cluster(
        self, bbox_depth: np.ndarray, valid_mask: np.ndarray
    ) -> np.ndarray:
        """Select the center-supported continuous depth cluster in a bbox."""
        ys, xs = np.where(valid_mask)
        depths = np.asarray(bbox_depth[valid_mask], dtype=np.float64)
        if depths.size == 0:
            raise ValueError("no valid aligned depth in bbox region")
        order = np.argsort(depths)
        sorted_depths = depths[order]
        median_depth = float(np.median(sorted_depths))
        gap_m = max(0.05, 0.03 * median_depth)
        split_at = np.flatnonzero(np.diff(sorted_depths) > gap_m) + 1
        clusters = np.split(order, split_at)
        center = np.array(
            [(bbox_depth.shape[1] - 1) * 0.5, (bbox_depth.shape[0] - 1) * 0.5],
            dtype=np.float64,
        )
        center_half_w = max(1, int(round(bbox_depth.shape[1] * 0.15)))
        center_half_h = max(1, int(round(bbox_depth.shape[0] * 0.15)))
        center_x = int(round(center[0]))
        center_y = int(round(center[1]))
        center_patch = bbox_depth[
            max(0, center_y - center_half_h) : min(
                bbox_depth.shape[0], center_y + center_half_h + 1
            ),
            max(0, center_x - center_half_w) : min(
                bbox_depth.shape[1], center_x + center_half_w + 1
            ),
        ]
        center_valid = center_patch[
            np.isfinite(center_patch)
            & (center_patch > 0.2 + 1e-6)
            & (center_patch < 5.0 - 1e-6)
        ]
        center_seed = (
            float(np.median(center_valid))
            if center_valid.size > 0
            else float(np.median(depths))
        )
        best = None
        for indices in clusters:
            if indices.size == 0:
                continue
            pixels = np.column_stack((xs[indices], ys[indices])).astype(np.float64)
            center_distance = float(np.linalg.norm(np.mean(pixels, axis=0) - center))
            cluster_depth = float(np.median(depths[indices]))
            key = (
                abs(cluster_depth - center_seed),
                center_distance,
                -int(indices.size),
                cluster_depth,
            )
            if best is None or key < best[0]:
                best = (key, indices)
        if best is None:
            raise ValueError("no continuous aligned depth cluster in bbox region")
        return depths[best[1]]

    def _estimate_region_point_cloud(
        self,
        region: PixelRegion,
        frame: Frame,
        *,
        depth_scale=1.0,
        avg_depth=True,
        percent_point=0.2,
        use_median=False,
    ) -> WaypointCandidate:
        """使用点云估计区域对应的 3D 原始点。"""
        color_info = self._camera_info_for_image_space("rgb")
        if color_info is None:
            raise ValueError("相机参数未就绪")
        if frame.cloud_xyz is None or frame.cloud_ranges is None:
            raise ValueError("点云未就绪")

        fx = float(color_info["fx"])
        fy = float(color_info["fy"])
        cx = float(color_info["cx"])
        cy = float(color_info["cy"])
        Hr, Wr = frame.rgb_image.shape[:2]
        projection = self._cloud_projection_for_frame(frame, color_info)
        R_w_cam = projection["R_w_cam"]
        t_wc = projection["t_wc"]
        forward_world = R_w_cam[:, 0]
        points_w = projection["points_w"]
        pts_opt = projection["pts_opt"]
        u_proj = projection["u_proj"]
        v_proj = projection["v_proj"]

        if region.kind == "mask":
            mask = self._normalize_mask_to_shape(region.mask_u8, H=Hr, W=Wr)
            u_idx = np.rint(u_proj).astype(np.int32)
            v_idx = np.rint(v_proj).astype(np.int32)
            uv_valid = (u_idx >= 0) & (u_idx < Wr) & (v_idx >= 0) & (v_idx < Hr)
            region_hits = uv_valid.copy()
            if np.any(uv_valid):
                region_hits[uv_valid] = mask[v_idx[uv_valid], u_idx[uv_valid]] > 0
            patch_points = points_w[region_hits]
            patch_ranges = np.linalg.norm(pts_opt[region_hits], axis=1)
            bbox_points_world = patch_points
            mask_points_world = patch_points
            xs_all = region.xs_all
            ys_all = region.ys_all
        else:
            bbox = region.bbox
            if bbox is None:
                raise ValueError("bbox is None")
            x1, y1, x2, y2 = bbox
            x1 = float(max(0, min(Wr - 1, x1)))
            x2 = float(max(0, min(Wr - 1, x2)))
            y1 = float(max(0, min(Hr - 1, y1)))
            y2 = float(max(0, min(Hr - 1, y2)))
            margin = max(0, int(self.bbox_cloud_margin_px))
            cloud_bbox = (
                max(0.0, x1 - margin),
                max(0.0, y1 - margin),
                min(float(Wr - 1), x2 + margin),
                min(float(Hr - 1), y2 + margin),
            )
            cloud_x1, cloud_y1, cloud_x2, cloud_y2 = cloud_bbox
            region_hits = (
                (u_proj >= cloud_x1)
                & (u_proj <= cloud_x2)
                & (v_proj >= cloud_y1)
                & (v_proj <= cloud_y2)
            )
            patch_points = points_w[region_hits]
            patch_ranges = np.linalg.norm(pts_opt[region_hits], axis=1)
            bbox_points_world = patch_points
            mask_points_world = None
            xs_all = np.array([cloud_x1, cloud_x2], dtype=np.float64)
            ys_all = np.array([cloud_y1, cloud_y2], dtype=np.float64)

        overdepth_ratio = (
            float(np.mean(patch_ranges > self.pc_max_range))
            if patch_ranges.size > 0
            else 1.0
        )
        match_ok = overdepth_ratio <= float(self.max_overdepth)

        valid_mask = (
            np.isfinite(patch_points).all(axis=1)
            & np.isfinite(patch_ranges)
            & (patch_ranges > 0.1 + 1e-6)
            & (patch_ranges <= self.pc_max_range)
        )
        valid_points = patch_points[valid_mask]
        valid_ranges = patch_ranges[valid_mask]
        valid_u_proj = u_proj[region_hits][valid_mask]
        valid_v_proj = v_proj[region_hits][valid_mask]
        selected_points = np.empty((0, 3), dtype=np.float64)
        target_yaw_world = None
        geometry_debug = None

        dir_world = self._pixel_dir_world(region.u, region.v, fx, fy, cx, cy, R_w_cam)
        ray_hits = []
        if (
            avg_depth
            and patch_points.shape[0] > 0
            and self.ray_grid > 1
            and not (region.kind == "bbox" and self.bbox_dense_window_enabled)
        ):
            xs = np.linspace(
                float(np.min(xs_all)),
                float(np.max(xs_all)),
                self.ray_grid,
                dtype=np.float64,
            )
            ys = np.linspace(
                float(np.min(ys_all)),
                float(np.max(ys_all)),
                self.ray_grid,
                dtype=np.float64,
            )
            v_all = patch_points - t_wc
            v_norm2 = np.sum(v_all * v_all, axis=1)
            for px in xs:
                for py in ys:
                    ray_dir = self._pixel_dir_world(
                        float(px), float(py), fx, fy, cx, cy, R_w_cam
                    )
                    proj = v_all @ ray_dir
                    valid_proj = proj > 1e-6
                    if not np.any(valid_proj):
                        continue
                    proj_v = proj[valid_proj]
                    v_sel = v_all[valid_proj]
                    dist2 = np.maximum(v_norm2[valid_proj] - proj_v * proj_v, 0.0)
                    near = dist2 <= (self.ray_max_dist * self.ray_max_dist)
                    if not np.any(near):
                        continue
                    idx = int(np.argmin(proj_v[near]))
                    ray_hits.append(v_sel[near][idx] + t_wc)

        if len(ray_hits) >= self.ray_min_hits:
            hit_points = np.array(ray_hits, dtype=np.float64)
            valid_points = hit_points
            valid_ranges = np.linalg.norm(hit_points - t_wc, axis=1)

        dense_selection = None
        if (
            region.kind == "bbox"
            and self.bbox_dense_window_enabled
            and valid_points.shape[0] > 0
        ):
            dense_selection = self._select_densest_bbox_cloud_window(
                valid_points,
                valid_u_proj,
                valid_v_proj,
                cloud_bbox,
                t_wc,
                body_origin_world=np.asarray(frame.current_state[:3], dtype=np.float64),
                body_forward_world=self.euler_rpy_to_R(
                    *map(float, frame.current_state[3:6])
                )[:, 0],
            )
            if dense_selection is None:
                raise ValueError("no dense cloud target in bbox center search region")

        if dense_selection is not None:
            P_w_raw, selected_points, geometry_debug = dense_selection
            depth_raw = float(np.linalg.norm(P_w_raw - t_wc))
            if self.bbox_dense_window_face_target_yaw:
                target_yaw_world = math.atan2(
                    float(P_w_raw[1] - t_wc[1]), float(P_w_raw[0] - t_wc[0])
                )
        elif valid_points.shape[0] == 0:
            raise ValueError("no valid cloud points in image region")
        else:
            percent_point_local = percent_point
            if self.mission_type == MISSION_TYPE.PASS_THROUGH:
                percent_point_local = 0.2
            elif not self.if_safe_dis:
                percent_point_local = 0.3
            sort_idx = np.argsort(valid_ranges)
            num_points = max(1, int(len(sort_idx) * percent_point_local))
            sel_idx = sort_idx[:num_points]
            sel_points = valid_points[sel_idx]
            sel_ranges = valid_ranges[sel_idx]
            selected_points = sel_points
            if self.mission_type == MISSION_TYPE.PASS_THROUGH:
                weights = 1.0 / (sel_ranges + 1e-6)
                vecs = sel_points - t_wc
                weighted_vec = np.sum(vecs * weights[:, None], axis=0) / (
                    np.sum(weights) + 1e-12
                )
                P_w_raw = t_wc + weighted_vec
                depth_raw = float(np.linalg.norm(weighted_vec))
            elif use_median:
                depth_raw = float(np.median(sel_ranges))
                P_w_raw = np.median(sel_points, axis=0)
            else:
                depth_raw = float(np.mean(sel_ranges))
                P_w_raw = np.mean(sel_points, axis=0)

        over_edge = False
        if depth_raw > self.pc_max_range + 1e-6:
            over_edge = True
            depth_raw = self.pc_max_range + 0.1

        vec = P_w_raw - t_wc
        dist = float(np.linalg.norm(vec))
        if not np.isfinite(dist) or dist <= 1e-6:
            dir_vec = forward_world / (np.linalg.norm(forward_world) + 1e-12)
        else:
            dir_vec = vec / dist
        depth_val = self._compute_adjusted_depth_value(
            depth_raw, self.pc_max_range, depth_scale
        )
        P_w = t_wc + dir_vec * depth_val
        if self.is_stable:
            P_w[2] = self.stable_height

        bearing_world = np.asarray(P_w_raw, dtype=np.float64).reshape(
            3,
        )
        _, left_world, _ = self._planar_axes_from_bearing(
            np.asarray(frame.current_state[:3], dtype=np.float64),
            bearing_world,
            float(frame.current_state[5]),
        )
        half_w = 0.0
        half_h = 0.0
        if selected_points.shape[0] > 0:
            proj = (selected_points - bearing_world) @ left_world
            if proj.size > 0:
                half_w = float(np.max(np.abs(proj)))
            half_h = float(np.max(np.abs((selected_points - bearing_world)[:, 2])))

        return WaypointCandidate(
            source="cloud",
            point_world=np.asarray(P_w, dtype=np.float64).reshape(
                3,
            ),
            bearing_world=bearing_world,
            raw_depth=float(depth_raw),
            over_edge=bool(over_edge),
            match_ok=bool(match_ok),
            overdepth_ratio=float(overdepth_ratio),
            half_w=float(max(0.0, half_w)),
            half_h=float(max(0.0, half_h)),
            bbox_points_world=bbox_points_world,
            mask_points_world=mask_points_world,
            target_yaw_world=target_yaw_world,
            geometry_debug=geometry_debug,
        )

    def _select_densest_bbox_cloud_window(
        self,
        points_world: np.ndarray,
        u_proj: np.ndarray,
        v_proj: np.ndarray,
        bbox,
        origin_world: np.ndarray,
        *,
        body_origin_world=None,
        body_forward_world=None,
    ):
        """Select the median 3D point in the densest pixel window inside a bbox."""
        if bbox is None or points_world.shape[0] == 0:
            return None
        window_size = max(1, int(self.bbox_dense_window_size_px))
        half = window_size // 2
        x1, y1, x2, y2 = [int(round(float(value))) for value in bbox]
        if x2 < x1 or y2 < y1:
            return None

        u_int = np.rint(u_proj).astype(np.int32)
        v_int = np.rint(v_proj).astype(np.int32)
        bbox_point_count = int(points_world.shape[0])
        ratio = float(np.clip(self.bbox_dense_window_search_ratio, 0.05, 1.0))
        bbox_center_u = 0.5 * (x1 + x2)
        bbox_center_v = 0.5 * (y1 + y2)
        search_half_w = max(float(half), 0.5 * float(x2 - x1) * ratio)
        search_half_h = max(float(half), 0.5 * float(y2 - y1) * ratio)
        search_x1 = max(x1, int(math.ceil(bbox_center_u - search_half_w)))
        search_x2 = min(x2, int(math.floor(bbox_center_u + search_half_w)))
        search_y1 = max(y1, int(math.ceil(bbox_center_v - search_half_h)))
        search_y2 = min(y2, int(math.floor(bbox_center_v + search_half_h)))
        search_mask = (
            (u_int >= search_x1)
            & (u_int <= search_x2)
            & (v_int >= search_y1)
            & (v_int <= search_y2)
        )
        if not np.any(search_mask):
            return None
        points_world = points_world[search_mask]
        u_int = u_int[search_mask]
        v_int = v_int[search_mask]
        width = search_x2 - search_x1 + 1
        height = search_y2 - search_y1 + 1
        search_center = np.array([(width - 1) * 0.5, (height - 1) * 0.5])
        ranges = np.linalg.norm(
            points_world - np.asarray(origin_world, dtype=np.float64).reshape(1, 3),
            axis=1,
        )
        if body_origin_world is None or body_forward_world is None:
            cluster_depths = ranges
        else:
            body_origin = np.asarray(body_origin_world, dtype=np.float64).reshape(1, 3)
            body_forward = np.asarray(body_forward_world, dtype=np.float64).reshape(3)
            body_forward /= np.linalg.norm(body_forward) + 1e-12
            cluster_depths = (points_world - body_origin) @ body_forward
        forward_mask = cluster_depths > 0.0
        if not np.any(forward_mask):
            return None
        points_world = points_world[forward_mask]
        u_int = u_int[forward_mask]
        v_int = v_int[forward_mask]
        ranges = ranges[forward_mask]
        cluster_depths = cluster_depths[forward_mask]
        range_order = np.argsort(cluster_depths)
        sorted_ranges = cluster_depths[range_order]
        range_gap_m = 0.1
        split_at = np.flatnonzero(np.diff(sorted_ranges) > range_gap_m) + 1
        range_clusters = np.split(range_order, split_at)
        best = None
        for cluster_index, cluster in enumerate(range_clusters):
            if cluster.size == 0:
                continue
            occupancy = np.zeros((height, width), dtype=np.float32)
            local_u = u_int[cluster] - search_x1
            local_v = v_int[cluster] - search_y1
            inside = (
                (local_u >= 0) & (local_u < width) & (local_v >= 0) & (local_v < height)
            )
            if not np.any(inside):
                continue
            np.add.at(occupancy, (local_v[inside], local_u[inside]), 1)
            counts = cv2.boxFilter(
                occupancy,
                ddepth=cv2.CV_32F,
                ksize=(window_size, window_size),
                normalize=False,
                borderType=cv2.BORDER_CONSTANT,
                anchor=(0, 0),
            )
            max_count = int(np.max(counts))
            if max_count < max(1, int(self.bbox_dense_window_min_points)):
                continue
            candidates = np.argwhere(counts == max_count)
            candidate_center = candidates.astype(np.float64) + 0.5 * float(
                window_size - 1
            )
            distances = np.linalg.norm(
                candidate_center[:, ::-1] - search_center, axis=1
            )
            candidate_index = int(np.argmin(distances))
            top_v_local, top_u_local = candidates[candidate_index]
            top_u = int(top_u_local + search_x1)
            top_v = int(top_v_local + search_y1)
            selected = np.zeros(points_world.shape[0], dtype=bool)
            selected[cluster] = (
                (u_int[cluster] >= top_u)
                & (u_int[cluster] < top_u + window_size)
                & (v_int[cluster] >= top_v)
                & (v_int[cluster] < top_v + window_size)
            )
            median_body_x = float(np.median(cluster_depths[selected]))
            key = (
                median_body_x,
                -max_count,
                float(distances[candidate_index]),
                top_v,
                top_u,
            )
            if best is None or key < best[0]:
                best = (key, selected, top_u, top_v, cluster_index, max_count)
        if best is None:
            return None

        _, selected, top_u, top_v, cluster_index, max_count = best
        selected_points = points_world[selected]
        target_world = np.median(selected_points, axis=0)
        window_center_u = int(round(float(top_u) + 0.5 * float(window_size - 1)))
        window_center_v = int(round(float(top_v) + 0.5 * float(window_size - 1)))
        debug = {
            "window_size_px": window_size,
            "window_center_pixel": [window_center_u, window_center_v],
            "window_point_count": int(selected_points.shape[0]),
            "bbox_point_count": bbox_point_count,
            "search_point_count": int(points_world.shape[0]),
            "range_cluster_count": int(len(range_clusters)),
            "selected_range_cluster": int(cluster_index),
            "selected_range_m": float(np.median(ranges[selected])),
            "selected_body_x_m": float(np.median(cluster_depths[selected])),
            "range_gap_m": float(range_gap_m),
            "cluster_axis": "body_x",
            "bbox_cloud_margin_px": int(getattr(self, "bbox_cloud_margin_px", 0)),
            "search_ratio": ratio,
            "search_region_pixel": [search_x1, search_y1, search_x2, search_y2],
        }
        return target_world, selected_points, debug

    def _cloud_projection_for_frame(self, frame: Frame, color_info: dict) -> dict:
        """缓存同一帧点云到图像平面的投影，避免 tracking 内重复全点云投影。"""
        _ct0 = time.perf_counter()
        if frame.cloud_xyz is None:
            raise ValueError("点云未就绪")
        fx = float(color_info["fx"])
        fy = float(color_info["fy"])
        cx = float(color_info["cx"])
        cy = float(color_info["cy"])
        R_w_cam, t_wc = self._get_camera_world_pose(frame)
        pose_key = tuple(float(v) for v in frame.current_depth_state.reshape(-1)[:6])
        cache_key = (
            int(id(frame.cloud_xyz)),
            float(frame.stamp),
            pose_key,
            fx,
            fy,
            cx,
            cy,
        )
        cache = frame.cloud_projection_cache
        if isinstance(cache, dict) and cache.get("key") == cache_key:
            _hit_ms = (time.perf_counter() - _ct0) * 1000.0
            with open("/tmp/_apply_timing.log", "a") as _atf:
                _atf.write(f"[APPLY_DETAIL] cloud_project: CACHE HIT {_hit_ms:.1f}ms\n")
            return cache

        points_w = frame.cloud_xyz.astype(np.float64)
        finite_mask = np.isfinite(points_w).all(axis=1)
        points_w = points_w[finite_mask]
        pts_cam = (R_w_cam.T @ (points_w - t_wc).T).T
        R_cam2opt = np.array(
            [
                [0, -1, 0],
                [0, 0, -1],
                [1, 0, 0],
            ],
            dtype=np.float64,
        )
        pts_opt = (R_cam2opt @ pts_cam.T).T
        z = pts_opt[:, 2]
        in_front = z > 1e-6
        pts_opt = pts_opt[in_front]
        points_w = points_w[in_front]
        z = z[in_front]
        u_proj = fx * (pts_opt[:, 0] / z) + cx
        v_proj = fy * (pts_opt[:, 1] / z) + cy
        cache = {
            "key": cache_key,
            "R_w_cam": R_w_cam,
            "t_wc": t_wc,
            "points_w": points_w,
            "pts_opt": pts_opt,
            "z": z,
            "u_proj": u_proj,
            "v_proj": v_proj,
        }
        frame.cloud_projection_cache = cache
        _miss_ms = (time.perf_counter() - _ct0) * 1000.0
        with open("/tmp/_apply_timing.log", "a") as _atf:
            _atf.write(
                f"[APPLY_DETAIL] cloud_project: CACHE MISS {_miss_ms:.1f}ms (n_pts={len(points_w)})\n"
            )
        return cache

    def _pixel_to_world_region(
        self,
        region: PixelRegion,
        frame: Frame,
        cmd: str,
        *,
        pose_yaw: float,
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
    ):
        """统一处理 bbox / mask 与 depth / cloud / mix 的 waypoint 计算。"""
        candidate = self._estimate_waypoint_candidate_for_region(
            region,
            frame,
            depth_scale=depth_scale,
            window=window,
            depth_mode=depth_mode,
            avg_depth=avg_depth,
            percent_point=percent_point,
            use_median=use_median,
        )
        return self._finalize_waypoint_candidate(
            candidate,
            frame,
            pose_yaw=pose_yaw,
            direction=direction,
            behind_dist=behind_dist,
            d_side=d_side,
            d_forward=d_forward,
        )

    def _estimate_waypoint_candidate_for_region(
        self,
        region: PixelRegion,
        frame: Frame,
        *,
        depth_scale=1.0,
        window=0,
        depth_mode="z",
        avg_depth=True,
        percent_point=0.2,
        use_median=False,
    ) -> WaypointCandidate:
        """只完成一次区域 3D 估计，不发布 marker，也不做任务方向偏移。"""
        _ew0 = time.perf_counter()
        if self.depth_info is None and self.color_info is None:
            raise ValueError("相机参数未就绪")
        priorities = self._sensor_priority_for_region(
            region, frame, percent_point=percent_point
        )
        _prio_ms = (time.perf_counter() - _ew0) * 1000.0
        errors = []
        tried = set()
        for source in priorities:
            if source in tried:
                continue
            tried.add(source)
            try:
                _t0 = time.perf_counter()
                if source == "depth":
                    result = self._estimate_region_point_depth(
                        region,
                        frame,
                        depth_scale=depth_scale,
                        window=window,
                        depth_mode=depth_mode,
                        avg_depth=avg_depth,
                        percent_point=percent_point,
                        use_median=use_median,
                    )
                    _src_ms = (time.perf_counter() - _t0) * 1000.0
                    with open("/tmp/_apply_timing.log", "a") as _atf:
                        _atf.write(
                            f"[APPLY_DETAIL] waypoint_candidate: depth path, "
                            f"priority_check={_prio_ms:.1f}ms estimate={_src_ms:.1f}ms\n"
                        )
                    self.last_waypoint_geometry_debug = result.geometry_debug
                    return result
                result = self._estimate_region_point_cloud(
                    region,
                    frame,
                    depth_scale=depth_scale,
                    avg_depth=avg_depth,
                    percent_point=percent_point,
                    use_median=use_median,
                )
                _src_ms = (time.perf_counter() - _t0) * 1000.0
                with open("/tmp/_apply_timing.log", "a") as _atf:
                    _atf.write(
                        f"[APPLY_DETAIL] waypoint_candidate: cloud path, "
                        f"priority_check={_prio_ms:.1f}ms estimate={_src_ms:.1f}ms\n"
                    )
                self.last_waypoint_geometry_debug = result.geometry_debug
                return result
            except Exception as exc:
                errors.append(f"{source}: {exc}")
                continue
        raise ValueError(
            " / ".join(errors) if errors else "No valid sensor source for waypoint"
        )

    def _cloud_depth_ranges_agree(
        self, cloud_range_m: float, depth_range_m: float
    ) -> bool:
        """Accept cloud/depth ranges that differ by at most the fixed threshold."""
        return abs(float(cloud_range_m) - float(depth_range_m)) <= float(
            self.cloud_depth_mismatch_threshold_m
        )

    def _select_nearest_geometry_candidate(
        self, cloud_candidate: WaypointCandidate, depth_candidate: WaypointCandidate
    ) -> WaypointCandidate:
        """Select the geometry candidate with the shorter measured range."""
        return min(
            (cloud_candidate, depth_candidate),
            key=lambda candidate: float(candidate.raw_depth),
        )

    def _geometry_safe_distance(self, cloud_depth_mismatch: bool) -> float:
        """Select safety distance by geometry agreement, independent of source."""
        if cloud_depth_mismatch:
            return float(self.geometry_mismatch_safe_dis_radius_m)
        return float(self.geometry_agree_safe_dis_radius_m)

    def _candidate_with_safe_distance(
        self,
        candidate: WaypointCandidate,
        frame: Frame,
        *,
        safe_dis_radius_m: float = None,
        apply_safe_distance: bool = True,
        depth_scale=1.0,
    ) -> WaypointCandidate:
        """基于同一个原始 3D 候选点，按安全半径派生新的航点候选。"""
        R_w_cam, t_wc = self._get_camera_world_pose(frame)
        raw_point = np.asarray(candidate.bearing_world, dtype=np.float64).reshape(
            3,
        )
        vec = raw_point - t_wc
        dist = float(np.linalg.norm(vec))
        if not np.isfinite(dist) or dist <= 1e-6:
            forward_world = R_w_cam[:, 0]
            dir_vec = forward_world / (np.linalg.norm(forward_world) + 1e-12)
        else:
            dir_vec = vec / dist

        safe_backup = float(self.safe_dis_radius_m)
        safe_flag_backup = bool(self.if_safe_dis)
        try:
            if safe_dis_radius_m is not None:
                self.safe_dis_radius_m = float(safe_dis_radius_m)
            self.if_safe_dis = bool(apply_safe_distance)
            depth_val = self._compute_adjusted_depth_value(
                float(candidate.raw_depth),
                self.pc_max_range,
                depth_scale,
            )
        finally:
            self.safe_dis_radius_m = safe_backup
            self.if_safe_dis = safe_flag_backup

        point_world = t_wc + dir_vec * depth_val
        if self.is_stable:
            point_world[2] = self.stable_height
        return replace(
            candidate,
            point_world=np.asarray(point_world, dtype=np.float64).reshape(
                3,
            ),
        )

    def pixel_to_world(
        self,
        results,
        frame: Frame,
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
    ):
        """统一的 bbox waypoint 计算入口。"""
        if frame is None:
            raise ValueError("frame is None")
        roll, pitch, yaw = map(float, frame.current_state[3:6].tolist())
        yaw = yaw - results.get("yaw", 0.0) / 180.0 * math.pi
        if results["pos"] == [-1, -1]:
            P_w = [
                frame.current_state[0],
                frame.current_state[1],
                frame.current_state[2],
            ]
            return np.concatenate([P_w, np.array([roll, pitch, yaw], dtype=np.float64)])
        region = self._build_region_from_bbox(results, frame)
        return self._pixel_to_world_region(
            region,
            frame,
            cmd,
            pose_yaw=yaw,
            depth_scale=depth_scale,
            window=window,
            depth_mode=depth_mode,
            direction=direction,
            behind_dist=behind_dist,
            avg_depth=avg_depth,
            percent_point=percent_point,
            use_median=use_median,
            d_side=d_side,
            d_forward=d_forward,
        )

    def _normalize_mask_to_shape(self, mask_u8, H: int, W: int) -> np.ndarray:
        """将 mask 统一为 uint8 且尺寸匹配目标图像。"""
        if mask_u8 is None:
            raise ValueError("mask is None")
        mask = np.asarray(mask_u8)
        if mask.ndim == 3:
            mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
        if mask.dtype != np.uint8:
            mask = np.clip(mask, 0, 255).astype(np.uint8)
        if mask.shape[:2] != (H, W):
            mask = cv2.resize(mask, (W, H), interpolation=cv2.INTER_NEAREST)
        return mask

    def pixel_to_world_mask(
        self,
        mask_u8,
        frame: Frame,
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
    ):
        """统一的 mask waypoint 计算入口。"""
        if frame is None:
            raise ValueError("frame is None")
        yaw = float(frame.current_state[5])
        region = self._build_region_from_mask(mask_u8, frame)
        return self._pixel_to_world_region(
            region,
            frame,
            cmd,
            pose_yaw=yaw,
            depth_scale=depth_scale,
            window=window,
            depth_mode=depth_mode,
            direction=direction,
            behind_dist=behind_dist,
            avg_depth=avg_depth,
            percent_point=percent_point,
            use_median=use_median,
            d_side=d_side,
            d_forward=d_forward,
        )

    def publish_image(self, image, pub):
        """发布图像到ROS话题"""
        # 确定编码方式
        if image is None:
            return None
        # 判断编码
        if image.dtype == np.uint8:
            if len(image.shape) == 3 and image.shape[2] == 3:
                encoding = "bgr8"
            elif len(image.shape) == 2:
                encoding = "mono8"
            else:
                # rospy.logerr(f"不支持的图像 shape: {image.shape}")
                rospy.logerr(f"Unsupported image shape: {image.shape}")
                return None
        elif image.dtype == np.uint16:
            encoding = "16UC1"  # 深度图常用
        elif image.dtype == np.float32:
            encoding = "32FC1"  # 浮点深度图常用
        else:
            # rospy.logerr(f"不支持的图像 dtype: {image.dtype}")
            rospy.logerr(f"Unsupported image dtype: {image.dtype}")
            return None

        # 转换并发布
        total_start = time.perf_counter()
        bridge_start = time.perf_counter()
        ros_img = self.bridge.cv2_to_imgmsg(image, encoding=encoding)
        bridge_ms = (time.perf_counter() - bridge_start) * 1000.0
        publish_start = time.perf_counter()
        pub.publish(ros_img)
        publish_ms = (time.perf_counter() - publish_start) * 1000.0
        total_ms = (time.perf_counter() - total_start) * 1000.0
        return {
            "encoding": encoding,
            "bridge_ms": float(bridge_ms),
            "publish_ms": float(publish_ms),
            "total_ms": float(total_ms),
        }
        # rospy.loginfo(f"图像已发布，编码: {encoding}, shape: {image.shape}, dtype: {image.dtype}")

    def publish_compressed_image(self, image, pub):
        """发布压缩图像到ROS话题。"""
        if image is None or pub is None:
            return
        try:
            total_start = time.perf_counter()
            bridge_start = time.perf_counter()
            ros_img = self.bridge.cv2_to_compressed_imgmsg(image, dst_format="jpg")
            bridge_ms = (time.perf_counter() - bridge_start) * 1000.0
            ros_img.header.stamp = rospy.Time.now()
            publish_start = time.perf_counter()
            pub.publish(ros_img)
            publish_ms = (time.perf_counter() - publish_start) * 1000.0
            total_ms = (time.perf_counter() - total_start) * 1000.0
            return {
                "bridge_ms": float(bridge_ms),
                "publish_ms": float(publish_ms),
                "total_ms": float(total_ms),
            }
        except Exception as exc:
            rospy.logwarn(f"compressed image publish failed: {exc}")
            return None

    def publish_current_state(self, current_state: np.ndarray, stamp: float):
        """发布当前位姿到 `robot/current_state`。"""
        msg = PoseStamped()
        msg.header.stamp = rospy.Time.from_sec(stamp)
        msg.header.frame_id = "world"
        msg.pose.position.x = float(current_state[0])
        msg.pose.position.y = float(current_state[1])
        msg.pose.position.z = float(current_state[2])
        qx, qy, qz, qw = self.euler_to_quaternion(
            current_state[3], current_state[4], current_state[5]
        )
        msg.pose.orientation.x = qx
        msg.pose.orientation.y = qy
        msg.pose.orientation.z = qz
        msg.pose.orientation.w = qw
        self.state_pub.publish(msg)

    def _cloud_timer_cb(self, event):
        """10Hz 定时发布点云"""
        frame = self.get_frame_snapshot()
        if frame is None:
            return
        if frame.depth_image is None and frame.cloud_msg is None:
            return
        cloud_msg = self._build_pointcloud_from_frame(frame)
        if cloud_msg is not None:
            self.cloud_pub.publish(cloud_msg)

    def _build_pointcloud_from_frame(self, frame: Frame) -> Optional[PointCloud2]:
        """
        优先复用同步点云；若点云不可用，再由同步深度图回投生成点云。
        """
        if frame.cloud_msg is not None:
            if abs(self.pc_z_offset) <= 1e-9 or frame.cloud_xyz is None:
                return frame.cloud_msg
            header = rospy.Header()
            header.stamp = rospy.Time.from_sec(frame.stamp)
            header.frame_id = self.pc_frame_id
            points = frame.cloud_xyz.astype(np.float32)
            return pc2.create_cloud_xyz32(header, points.tolist())

        if frame.depth_image is not None:
            depth = frame.depth_image
            H, W = depth.shape[:2]
            if H == 0 or W == 0:
                return None

            # 生成像素网格（可通过 stride 下采样）
            s = max(1, int(self.pc_stride))
            us = np.arange(0, W, s, dtype=np.float64)
            vs = np.arange(0, H, s, dtype=np.float64)
            uu, vv = np.meshgrid(us, vs)  # 形状: [H/s, W/s]

            # 对应的深度取值
            depth_vals = depth[vv.astype(np.int64), uu.astype(np.int64)].astype(
                np.float64
            )

            # 过滤无效/哨兵深度
            if self.pc_keep_far:
                depth_vals = np.where(
                    depth_vals > self.pc_max_range, self.pc_max_range, depth_vals
                )
                valid = np.isfinite(depth_vals) & (depth_vals > 0.0)
            else:
                valid = (
                    np.isfinite(depth_vals)
                    & (depth_vals > 0.0)
                    & (depth_vals <= self.pc_max_range)
                )

            if not np.any(valid):
                return None

            uu = uu[valid]
            vv = vv[valid]
            depth_vals = depth_vals[valid]

            if self.use_intrinsics:
                fx = float(self.depth_info["fx"])
                fy = float(self.depth_info["fy"])
                cx = float(self.depth_info["cx"])
                cy = float(self.depth_info["cy"])

                dx = (uu - cx) / (fx if abs(fx) > 1e-12 else 1e-12)
                dy = (vv - cy) / (fy if abs(fy) > 1e-12 else 1e-12)
                dz = np.ones_like(dx)

                P_opt = np.stack(
                    [dx * depth_vals, dy * depth_vals, dz * depth_vals], axis=1
                )
            else:
                fh, fv = self._fov_hv_from_info(self.depth_info["fov"], W, H)
                cx = (W - 1) * 0.5
                cy = (H - 1) * 0.5
                nx = (uu - cx) / max(cx, 1e-9)
                ny = (vv - cy) / max(cy, 1e-9)
                thx = nx * (fh * 0.5)
                thy = ny * (fv * 0.5)
                tx = np.tan(thx)
                ty = np.tan(thy)
                ones = np.ones_like(tx)
                P_opt = np.stack(
                    [tx * depth_vals, ty * depth_vals, ones * depth_vals], axis=1
                )

            R_opt2cam = np.array(
                [
                    [0, 0, 1],
                    [-1, 0, 0],
                    [0, -1, 0],
                ],
                dtype=np.float64,
            )
            P_cam = (R_opt2cam @ P_opt.T).T

            tx_c, ty_c, tz_c, roll_c, pitch_c, yaw_c = map(
                float, frame.current_depth_state.tolist()
            )
            R_w_cam = self.euler_rpy_to_R(roll_c, pitch_c, yaw_c)
            t_wc = np.array([tx_c, ty_c, tz_c], dtype=np.float64)
            P_out = (R_w_cam @ P_cam.T).T + t_wc

            if abs(self.pc_z_offset) > 1e-9:
                P_out[:, 2] += self.pc_z_offset

            header = rospy.Header()
            header.stamp = rospy.Time.from_sec(frame.stamp)
            header.frame_id = self.pc_frame_id

            points = P_out.astype(np.float32)
            return pc2.create_cloud_xyz32(header, points.tolist())

        return None

    def _publish_p2w_marker(self, P_w, stamp):
        """发布 pixel_to_world 结果 marker。"""
        m = Marker()
        m.header.stamp = rospy.Time.from_sec(stamp)
        m.header.frame_id = self.pc_frame_id  # 通常为 "world"
        m.ns = "pixel_to_world"
        m.id = 0
        m.type = Marker.SPHERE
        m.action = Marker.ADD
        m.pose.position.x = float(P_w[0])
        m.pose.position.y = float(P_w[1])
        m.pose.position.z = float(P_w[2])
        m.pose.orientation.x = 0.0
        m.pose.orientation.y = 0.0
        m.pose.orientation.z = 0.0
        m.pose.orientation.w = 1.0
        m.scale.x = m.scale.y = m.scale.z = 0.3  # 直径 0.1 m
        m.color.r = 0.0
        m.color.g = 1.0
        m.color.b = 0.0
        m.color.a = 1.0
        m.lifetime = rospy.Duration(0)  # 保持显示
        self.marker_pub.publish(m)

    def _publish_bbox_cloud(self, points_w: np.ndarray, stamp: float):
        """发布bbox内的点云（世界坐标系，PointCloud2）"""
        if points_w is None or points_w.shape[0] == 0:
            return
        header = rospy.Header()
        header.stamp = rospy.Time.from_sec(stamp)
        header.frame_id = self.pc_frame_id
        cloud_msg = pc2.create_cloud_xyz32(header, points_w.astype(np.float32).tolist())
        self.bbox_cloud_pub.publish(cloud_msg)

    def _publish_mask_cloud(self, points_w: np.ndarray, stamp: float):
        """发布mask参与计算的点云（世界坐标系，PointCloud2）"""
        if points_w is None:
            return
        pts = np.asarray(points_w, dtype=np.float32).reshape(-1, 3)
        if pts.shape[0] == 0:
            return
        header = rospy.Header()
        header.stamp = rospy.Time.from_sec(stamp)
        header.frame_id = self.pc_frame_id
        cloud_msg = pc2.create_cloud_xyz32(header, pts.tolist())
        self.mask_cloud_pub.publish(cloud_msg)

    def _publish_road_cloud(self, points_w: np.ndarray, stamp: float):
        """发布确认后的道路/地面支撑点云（世界坐标系，PointCloud2）。"""
        if points_w is None:
            return
        pts = np.asarray(points_w, dtype=np.float32).reshape(-1, 3)
        if pts.shape[0] == 0:
            return
        header = rospy.Header()
        header.stamp = rospy.Time.from_sec(stamp)
        header.frame_id = self.pc_frame_id
        cloud_msg = pc2.create_cloud_xyz32(header, pts.tolist())
        self.road_cloud_pub.publish(cloud_msg)
