#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基础策略节点（ROS1）。

主要职责：
1. 同步里程计、RGB、深度/点云数据并缓存帧快照。
2. 发布调试可视化信息（状态、点云）。

（像素 bbox/mask → 世界系反投影几何链已随「几何上移 station」整段退役：
station 以累积云+位姿@image_stamp+VLM bbox 解算航点下发，机上不再有
pixel_to_world 家族。）
"""

from __future__ import annotations

import logging
import numpy as np
import threading
import cv2
import rospy
import copy
from collections import deque
from dataclasses import dataclass
from typing import Optional, Any
from message_filters import Subscriber as MFSubscriber
from sensor_msgs.msg import CompressedImage, Image
from nav_msgs.msg import Odometry
from geometry_msgs.msg import PoseStamped
from sensor_msgs.msg import PointCloud2, PointField
import sensor_msgs.point_cloud2 as pc2
import math
import time
import cv_bridge
import re
from dispatcher.support.state import MISSION_TYPE
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
        # 几何安全距离/密集窗/ray-grid 等参数族已随几何上移 station 退役
        # （站端等价配置见 l4 station_sidecar/vla/geometry.py env 前缀）。
        self.is_stable = False
        self.use_intrinsics = True
        self.depth_scale_param = 57.0
        self.mission_type = MISSION_TYPE.NOT_MISSION
        self.behind_dist = 2.0
        self.depth_format_logged = False

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

    # get_fast_rgb / get_fast_rgb_generation 已随 VLA 几何上移退役删除：
    # fast-RGB 缓存本身保留——build_frame_from_latest_cache 仍经私有属性
    # 消费它；站端 VLA 接地从 camera 遥测流取帧。

    def get_frame_snapshot(self) -> Optional[Frame]:
        """线程安全地获取最新帧快照。"""
        with self.frame_lock:
            return self.frame

    # get_frame_snapshot_near_stamp / build_world_frame_for_image_stamp 已随
    # VLA 几何上移 station 退役删除：站端以帧时戳在自身 odom 序列上插值，
    # 机上不再需要任何按 stamp 取帧/对齐通路（sensor.capture 同步口一并退役）。

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
