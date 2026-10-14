"""跟踪帧数据，不承载流程或 ROS 类型。"""
from __future__ import annotations
import numpy as np
from dataclasses import dataclass

def ros_seconds(stamp_ns):
    secs, nsecs = divmod(stamp_ns, 10**9)
    return secs + nsecs / 1e9

@dataclass(frozen=True)
class EncodedRGB:
    """相机原始 JPEG；解码用于尺寸检查和遥测，传输保留原字节。"""

    data: bytes
    shape: tuple

    @property
    def nbytes(self):
        return len(self.data)

    def copy(self):
        import cv2

        image = cv2.imdecode(np.frombuffer(self.data, np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.shape != self.shape:
            raise ValueError("invalid_compressed_rgb")
        return image


@dataclass(frozen=True)
class TrackingFrame:
    stamp_ns: int
    received: float
    rgb: np.ndarray | EncodedRGB
    intrinsics: dict | None = None

    @property
    def stamp(self):
        return ros_seconds(self.stamp_ns)



