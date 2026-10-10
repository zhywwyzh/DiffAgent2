"""Bounded RGB history with exact ROS timestamps and clock fencing."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict

from dispatcher.support.tracking_data import TrackingFrame, EncodedRGB, ros_seconds


def ns(stamp):
    return stamp if isinstance(stamp, int) else round(float(stamp) * 1e9)



class FrameStore:
    def __init__(self, capacity=256, max_age=15.0, max_bytes=256 * 1024 * 1024):
        self.capacity, self.max_age, self.max_bytes = capacity, max_age, max_bytes
        self.lock = threading.RLock()
        self.rgb = OrderedDict()
        self.generation = 0
        self.intrinsics = None

    def _trim(self, data, budget):
        size = sum(value[1].nbytes for value in data.values())
        while data and (
            len(data) > self.capacity
            or size > budget
            or time.monotonic() - next(iter(data.values()))[0] > self.max_age
        ):
            _, entry = data.popitem(last=False)
            size -= entry[1].nbytes

    def add_rgb(self, stamp, image):
        stamp = ns(stamp)
        with self.lock:
            if self.rgb and stamp < next(reversed(self.rgb)):
                self.rgb.clear()
                self.generation += 1
            if stamp not in self.rgb:
                stored = image if isinstance(image, EncodedRGB) else image.copy()
                self.rgb[stamp] = (time.monotonic(), stored, dict(self.intrinsics or {}))
            self._trim(self.rgb, self.max_bytes)

    def seed(self, stamp):
        with self.lock:
            original = stamp
            stamp = ns(stamp)
            # Match the station's exact float representation, never a nearest frame.
            if isinstance(original, float):
                matches = [key for key in self.rgb if ros_seconds(key) == original]
                if len(matches) != 1:
                    return None
                stamp = matches[0]
            data = self.rgb.get(stamp)
            if data is None or time.monotonic() - data[0] > self.max_age:
                return None
            return TrackingFrame(stamp, data[0], data[1], intrinsics=data[2])

    def latest_rgb(self, after_stamp, ros_now, max_age):
        """Newest fresh RGB eligible for inference, independent of geometry."""
        with self.lock:
            now = time.monotonic()
            for stamp, data in reversed(self.rgb.items()):
                if stamp <= after_stamp:
                    break
                if now - data[0] <= max_age and 0 <= ros_now - ros_seconds(stamp) <= max_age:
                    return TrackingFrame(stamp, data[0], data[1], intrinsics=data[2])
        return None


