"""与站端当前解码器相同的线上编码；不依赖 ROS。"""
import json
import math
import struct

import cv2
import numpy as np


def json_payload(value):
    return json.dumps(value, allow_nan=False, separators=(",", ":")).encode()


def camera_payload(stamp, rgb):
    if not math.isfinite(stamp) or stamp <= 0:
        raise ValueError("相机源时戳无效")
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    ok, encoded = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if not ok:
        raise ValueError("JPEG 编码失败")
    return struct.pack("<d", stamp) + encoded.tobytes()


def depth_payload(depth):
    if depth.ndim != 2 or depth.dtype != np.uint16:
        raise ValueError("深度必须是 16UC1 毫米图像")
    height, width = depth.shape
    if not 0 < width <= 65535 or not 0 < height <= 65535:
        raise ValueError("深度尺寸非法")
    ok, encoded = cv2.imencode(".png", depth)
    if not ok:
        raise ValueError("深度 PNG 编码失败")
    return struct.pack("<BHH", 1, width, height) + encoded.tobytes()


def cloud_payload(points, leaf, maximum):
    xyz = np.asarray(points, dtype=np.float32).reshape(-1, 3)
    xyz = xyz[np.isfinite(xyz).all(axis=1)]
    if len(xyz):
        keys = np.floor(xyz / leaf).astype(np.int64)
        _, indices = np.unique(keys, axis=0, return_index=True)
        xyz = xyz[np.sort(indices)]
        if len(xyz) > maximum:
            xyz = xyz[np.linspace(0, len(xyz) - 1, maximum, dtype=np.int64)]
    return struct.pack("<BI", 0, len(xyz)) + xyz.astype("<f4").tobytes()
