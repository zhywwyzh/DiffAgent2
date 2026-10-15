"""Continuous RGB tracking; geometry and dispatcher ticks never pace inference."""

import threading


class TrackingProducer:
    def __init__(self, client, frames, seed, bbox, observe, ros_now, max_age):
        self.client, self.frames = client, frames
        self.seed, self.bbox = seed, bbox
        self.observe, self.ros_now, self.max_age = observe, ros_now, max_age
        self.clock_generation = frames.generation
        self.cancelled = threading.Event()
        self.lock = threading.Lock()

    def cancel(self):
        # Serialized with publication: no callback starts after cancel returns.
        with self.lock:
            self.cancelled.set()

    def _accept(self, output, frame, initializing=False):
        with self.lock:
            if self.cancelled.is_set():
                return False
            if output.ok:
                state = "init" if initializing else (
                    "recovered" if output.reason == "recovered" else "active"
                )
                self.observe(state, output, frame)
            else:
                self.observe("lost" if output.reason == "track_lost" else "recovering", output, frame)
            return True

    def run(self):
        reason = "cancelled"
        try:
            if self.cancelled.is_set():
                return reason
            output = self.client.start(self.seed.rgb, self.bbox, self.seed.stamp_ns)
            if self.frames.generation != self.clock_generation:
                return "track_execution_failed"
            if not self._accept(output, self.seed, initializing=True):
                return reason
            if not output.ok:
                return "tracker_start_failed"
            last_stamp = self.seed.stamp_ns
            while not self.cancelled.is_set():
                if self.frames.generation != self.clock_generation:
                    return "track_execution_failed"
                frame = self.frames.latest_rgb(last_stamp, self.ros_now(), self.max_age)
                if frame is None:
                    self.cancelled.wait(0.01)
                    continue
                if frame.rgb.shape != self.seed.rgb.shape:
                    return "track_execution_failed"
                last_stamp = frame.stamp_ns
                output = self.client.update(frame.rgb, frame.stamp_ns)
                if self.frames.generation != self.clock_generation:
                    return "track_execution_failed"
                if not self._accept(output, frame):
                    return reason
                if output.reason == "track_lost":
                    return "track_lost"
        finally:
            # The worker owns all HTTP calls, including reset after an in-flight
            # request. The next session cannot start until this worker exits.
            self.client.reset()
        return reason
