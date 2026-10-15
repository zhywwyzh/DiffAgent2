#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""点云积累与重发布工具。"""

from __future__ import annotations

from collections import deque
import threading
from typing import Optional

import numpy as np
import rospy
from sensor_msgs.msg import PointCloud2
from std_msgs.msg import Header
import sensor_msgs.point_cloud2 as pc2


class PointCloudTimeWindow:
    """Maintain a timestamped in-process window of world-frame XYZ clouds."""

    def __init__(
        self,
        *,
        window_seconds: float = 1.0,
        voxel_size: float = 0.03,
        max_frames: int = 30,
    ):
        self.window_seconds = max(0.0, float(window_seconds))
        self.voxel_size = max(0.0, float(voxel_size))
        self.max_frames = max(1, int(max_frames))
        self._lock = threading.Lock()
        self._frames = deque()
        self._revision = 0
        self._cached_revision = -1
        self._cached_points = None

    def _prune_locked(self, latest_stamp: float) -> None:
        cutoff = float(latest_stamp) - self.window_seconds
        while self._frames and (
            self._frames[0][0] < cutoff or len(self._frames) > self.max_frames
        ):
            self._frames.popleft()

    def add(
        self, stamp: float, points: np.ndarray, wall_time: Optional[float] = None
    ) -> None:
        arr = np.asarray(points, dtype=np.float32).reshape((-1, 3))
        arr = arr[np.isfinite(arr).all(axis=1)]
        if arr.shape[0] == 0:
            return
        stamp_value = float(stamp)
        wall_value = float(wall_time) if wall_time is not None else float(stamp)
        with self._lock:
            self._frames.append((stamp_value, wall_value, arr))
            self._prune_locked(stamp_value)
            self._revision += 1

    def _voxel_downsample(self, points: np.ndarray) -> np.ndarray:
        if self.voxel_size <= 0.0 or points.shape[0] <= 1:
            return points
        keys = np.floor(points / self.voxel_size).astype(np.int64)
        _, first_indices = np.unique(keys, axis=0, return_index=True)
        return points[np.sort(first_indices)]

    def snapshot(self) -> Optional[np.ndarray]:
        with self._lock:
            if not self._frames:
                return None
            if self._cached_revision == self._revision:
                return self._cached_points
            frames = [points for _, _, points in self._frames]
            revision = self._revision
        merged = frames[0] if len(frames) == 1 else np.concatenate(frames, axis=0)
        merged = self._voxel_downsample(merged)
        with self._lock:
            if revision == self._revision:
                self._cached_revision = revision
                self._cached_points = merged
        return merged

    def stats(self) -> dict:
        with self._lock:
            if not self._frames:
                return {"frames": 0, "span_seconds": 0.0, "raw_points": 0}
            return {
                "frames": len(self._frames),
                "span_seconds": float(self._frames[-1][0] - self._frames[0][0]),
                "raw_points": int(
                    sum(points.shape[0] for _, _, points in self._frames)
                ),
                "oldest_stamp": float(self._frames[0][0]),
                "latest_stamp": float(self._frames[-1][0]),
                "latest_wall_time": float(self._frames[-1][1]),
            }


class PointCloudAccumulator:
    """订阅原始点云，积累最近若干帧后发布给 dispatcher_node 使用。"""

    def __init__(
        self,
        *,
        input_topic: str,
        output_topic: str,
        frame_count: int = 5,
        downsample_stride: int = 1,
        queue_size: int = 5,
        publish_rate: float = 0.0,
    ):
        self.input_topic = str(input_topic or "").strip()
        self.output_topic = str(output_topic or "").strip()
        self.frame_count = max(1, int(frame_count))
        self.downsample_stride = max(1, int(downsample_stride))
        self.publish_rate = max(0.0, float(publish_rate))

        # 分离锁：frames_lock 保护点云缓冲区，时间戳无锁（GIL 保证原子性）
        self._frames_lock = threading.Lock()
        self._frames = deque(maxlen=self.frame_count)
        self._latest_stamp = None
        self._latest_frame_id = ""

        self._pub = rospy.Publisher(
            self.output_topic, PointCloud2, queue_size=max(1, int(queue_size))
        )
        self._sub = rospy.Subscriber(
            self.input_topic,
            PointCloud2,
            self._cloud_callback,
            queue_size=1,
            tcp_nodelay=True,
        )
        # 高频 Timer 异步发布，与 subscriber 的解耦锁避免争用
        timer_hz = (
            self.publish_rate if self.publish_rate > 0.0 else max(20.0, 1.0 / 0.05)
        )
        self._timer = rospy.Timer(rospy.Duration(1.0 / timer_hz), self._timer_callback)

        rospy.loginfo(
            "[PointCloudAccumulator] input=%s output=%s frames=%d stride=%d publish_rate=%.2f timer_hz=%.1f",
            self.input_topic,
            self.output_topic,
            self.frame_count,
            self.downsample_stride,
            self.publish_rate,
            timer_hz,
        )

    def _cloud_to_xyz(self, msg: PointCloud2):
        """从 PointCloud2 读取有限 xyz 点。"""
        points = np.array(
            list(pc2.read_points(msg, field_names=("x", "y", "z"), skip_nans=True)),
            dtype=np.float32,
        )
        if points.size == 0:
            return None
        points = points.reshape((-1, 3))
        finite = np.isfinite(points).all(axis=1)
        points = points[finite]
        if points.shape[0] == 0:
            return None
        if self.downsample_stride > 1:
            points = points[:: self.downsample_stride]
        return points

    def _merged_cloud_locked(self):
        """合并缓存内的点云帧；调用者需持有 _frames_lock。"""
        if not self._frames:
            return None
        if len(self._frames) == 1:
            return self._frames[0]
        return np.concatenate(list(self._frames), axis=0)

    def _cloud_callback(self, msg: PointCloud2) -> None:
        """输入点云回调：时间戳不加锁，确保 subscriber 始终能及时更新。"""
        points = self._cloud_to_xyz(msg)
        # 时间戳无锁写入 —— GIL 保证 Python 对象赋值是原子的，
        # 确保 _timer_callback 永远能读到 subscriber 收到的最新时间戳
        self._latest_stamp = msg.header.stamp
        self._latest_frame_id = msg.header.frame_id
        if points is not None:
            with self._frames_lock:
                self._frames.append(points)

    def _timer_callback(self, event) -> None:
        """高频 Timer 异步发布，只对点云缓冲区加锁。"""
        stamp = self._latest_stamp
        frame_id = self._latest_frame_id
        if stamp is None:
            return
        with self._frames_lock:
            merged = self._merged_cloud_locked()
        if merged is None or merged.shape[0] == 0:
            return
        header = Header()
        header.stamp = stamp
        header.frame_id = frame_id
        out = pc2.create_cloud_xyz32(header, merged.astype(np.float32).tolist())
        self._pub.publish(out)
