#!/usr/bin/env python3
"""ROS 订阅与标准数据编码装配；不持有任务控制面。"""
import json
import math
import os
import time

import numpy as np
import rospy
from nav_msgs.msg import Odometry
from sensor_msgs.msg import CameraInfo, Image, PointCloud2
from sensor_msgs.point_cloud2 import read_points

from telemetry_bridge.encoding import camera_payload, cloud_payload, depth_payload, json_payload
from telemetry_bridge.uplink import Uplink


class TelemetryRos:
    def __init__(self):
        with open(rospy.get_param("~config")) as source:
            self.settings = json.load(source)
        self.calibration = None
        self.subscriptions = []
        self.timer = None
        self.started = time.monotonic()
        self.uplink = Uplink(os.environ["LX_STACK_ID"], os.environ["ZENOH_ROUTER"], self.encode, rospy.logwarn)
        try:
            self.subscriptions = [
                rospy.Subscriber("/ekf_quat/ekf_odom", Odometry, self.odom, queue_size=1),
                rospy.Subscriber("/camera/color/camera_info", CameraInfo, self.info, queue_size=1),
                rospy.Subscriber("/camera/color/image_raw", Image, lambda msg: self.submit("camera", msg), queue_size=1, buff_size=8 * 1024 * 1024),
                rospy.Subscriber("/camera/aligned_depth_to_color/image_raw", Image, lambda msg: self.submit("depth", msg), queue_size=1, buff_size=8 * 1024 * 1024),
                rospy.Subscriber("/cloud_registered", PointCloud2, lambda msg: self.submit("cloud", msg), queue_size=1, buff_size=8 * 1024 * 1024),
            ]
            self.timer = rospy.Timer(rospy.Duration(1), self.meta)
        except Exception:
            self.close()
            raise

    def submit(self, channel, message):
        stamp = message.header.stamp.to_sec()
        age = rospy.Time.now().to_sec() - stamp
        if not math.isfinite(stamp) or stamp <= 0 or not -0.1 <= age <= 1.5:
            rospy.logwarn_throttle(5, f"{channel} 输入时戳无效或陈旧")
            return
        if channel == "cloud" and message.header.frame_id != "world":
            rospy.logwarn_throttle(5, "点云不是 world 坐标，拒绝上传")
            return
        self.uplink.submit(channel, message)

    def info(self, message):
        if message.width <= 0 or message.height <= 0 or not all(math.isfinite(value) for value in message.K):
            return
        if message.K[0] <= 0 or message.K[4] <= 0:
            return
        self.calibration = {"width": message.width, "height": message.height, "fx": message.K[0],
                            "fy": message.K[4], "cx": message.K[2], "cy": message.K[5], "frame_id": message.header.frame_id}

    def odom(self, message):
        if message.header.frame_id != "world":
            rospy.logwarn_throttle(5, "odometry 不是 world 坐标，拒绝上传")
            return
        self.submit("drone_status", message)

    def meta(self, _event):
        self.uplink.submit("meta", {"type": "hello", "role": "drone_bridge", "version": 2,
                                   "uptime_s": round(time.monotonic() - self.started, 1),
                                   "params": {"cloud_leaf": self.settings["cloud_leaf"]}})

    def encode(self, channel, value):
        if channel == "camera":
            return camera_payload(value.header.stamp.to_sec(), image_array(value, color=True))
        if channel == "depth":
            return depth_payload(image_array(value, color=False))
        if channel == "cloud":
            points = list(read_points(value, field_names=("x", "y", "z"), skip_nans=True))
            return cloud_payload(points, self.settings["cloud_leaf"], self.settings["cloud_max_points"])
        if channel == "drone_status":
            p, q, v = value.pose.pose.position, value.pose.pose.orientation, value.twist.twist.linear
            data = {"stamp": value.header.stamp.to_sec(), "odom": {"x": p.x, "y": p.y, "z": p.z,
                    "qx": q.x, "qy": q.y, "qz": q.z, "qw": q.w, "vx": v.x, "vy": v.y, "vz": v.z},
                    "battery": None, "mode": None}
            if self.calibration is not None:
                data["camera_calibration"] = self.calibration
            return json_payload(data)
        return json_payload(value)

    def close(self):
        if self.timer:
            self.timer.shutdown()
        for subscription in self.subscriptions:
            subscription.unregister()
        self.uplink.close()


def image_array(message, color):
    """按 wire 的行步长与端序取数组，不加载另一 Python ABI 的 cv_bridge。"""
    if message.width <= 0 or message.height <= 0 or len(message.data) != message.step * message.height:
        raise ValueError("ROS Image 尺寸或行步长非法")
    if color:
        if message.encoding not in ("rgb8", "bgr8") or message.step < message.width * 3:
            raise ValueError("RGB 仅支持 rgb8/bgr8")
        rows = np.frombuffer(message.data, dtype=np.uint8).reshape(message.height, message.step)
        rgb = rows[:, :message.width * 3].reshape(message.height, message.width, 3)
        return rgb if message.encoding == "rgb8" else rgb[:, :, ::-1]
    if message.encoding != "16UC1" or message.step < message.width * 2 or message.step % 2:
        raise ValueError("深度必须为 16UC1 毫米图像")
    dtype = ">u2" if message.is_bigendian else "<u2"
    rows = np.frombuffer(message.data, dtype=dtype).reshape(message.height, message.step // 2)
    return rows[:, :message.width].astype(np.uint16)


if __name__ == "__main__":
    rospy.init_node("telemetry_bridge")
    node = TelemetryRos()
    rospy.on_shutdown(node.close)
    rospy.spin()
