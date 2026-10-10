"""观测与遥测出站；图像编码运行在独立 worker。"""
import json
from contextlib import ExitStack
import threading
import time
import cv2
import rospy
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String
from quadrotor_msgs.msg import TrackingObservation

class TrackingImagePublisher:
    """Draw on the inference frame before transport, never on live camera RGB."""

    def __init__(self, session_id):
        self.session_id = session_id
        self.publisher = rospy.Publisher(
            "/tracking/image/compressed", CompressedImage, queue_size=1, latch=True
        )
        self.condition = threading.Condition()
        self.pending = None
        self.closed = False
        self.thread = threading.Thread(target=self._run, name="tracking-image", daemon=True)
        try:
            self.thread.start()
        except Exception:
            self.publisher.unregister()
            raise

    def publish(self, state, output, frame):
        with self.condition:
            if not self.closed:
                self.pending = state, output, frame, self.session_id
                self.condition.notify()

    def close(self):
        with self.condition:
            self.closed = True
            self.pending = None
            self.condition.notify()

    def dispose(self):
        self.close()
        self.thread.join()
        self.publisher.unregister()

    def _run(self):
        next_due = 0.0
        while True:
            with self.condition:
                while not self.closed:
                    delay = next_due - time.monotonic()
                    if self.pending is not None and (delay <= 0 or self.pending[0] == "lost"):
                        break
                    self.condition.wait(max(0.001, delay) if self.pending is not None else None)
                if self.closed:
                    return
                item, self.pending = self.pending, None
            try:
                message = self.render(*item)
                with self.condition:
                    if not self.closed and message is not None:
                        self.publisher.publish(message)
            except Exception as exc:
                rospy.logwarn("tracking image output failed: %s", type(exc).__name__)
            # Display telemetry is capped at 5 Hz independently of inference.
            next_due = time.monotonic() + 0.2

    def render(self, state, output, frame, session_id):
        image = frame.rgb.copy()
        color = (70, 70, 240) if state == "lost" else (90, 230, 50)
        if output.bbox is not None and state != "lost":
            x1, y1, x2, y2 = [int(round(v)) for v in output.bbox]
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        score = "-" if output.score is None else f"{output.score:.2f}"
        label = f"{state}  score {score}  seq {output.submit_seq}"
        cv2.rectangle(image, (0, 0), (image.shape[1], 28), (15, 20, 25), -1)
        cv2.putText(image, label, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return
        message = CompressedImage()
        message.header.stamp = rospy.Time(frame.stamp_ns // 10**9, frame.stamp_ns % 10**9)
        message.header.frame_id = session_id
        message.format = "bgr8; jpeg compressed bgr8"
        message.data = jpeg.tobytes()
        return message



class TrackingObservationRos:
    def __init__(self):
        with ExitStack() as resources:
            self.observation = rospy.Publisher('/planner/tracking_observation', TrackingObservation, queue_size=1)
            resources.callback(self.observation.unregister)
            self.telemetry = rospy.Publisher('/tracking/observation', String, queue_size=1)
            resources.callback(self.telemetry.unregister)
            self.image = TrackingImagePublisher('')
            resources.callback(self.image.dispose)
            self.resources = resources.pop_all()

    def publish(self, value, session_id, execution_id):
        msg = TrackingObservation()
        msg.header.stamp = rospy.Time(value.stamp_ns // 10**9, value.stamp_ns % 10**9)
        msg.session_id, msg.execution_id = session_id, execution_id
        msg.sequence = value.sequence
        msg.bbox = value.bbox
        msg.width, msg.height = value.width, value.height
        msg.intrinsics = value.intrinsics
        msg.rotation, msg.translation = value.rotation, value.translation
        self.observation.publish(msg)

    def display(self, state, output, frame, session_id, execution_id):
        self.image.session_id = session_id
        self.image.publish(state, output, frame)
        self.telemetry.publish(String(json.dumps(dict(state=state, session_id=session_id, execution_id=execution_id, identity_revision=output.identity_revision,
            stamp=output.stamp, bbox=output.bbox, score=output.score,
            send_seq=output.submit_seq, reason=output.reason,
            image_width=frame.rgb.shape[1], image_height=frame.rgb.shape[0]))))

    def close(self):
        self.resources.close()
