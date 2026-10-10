"""Serialized, idempotent single-target transactions; independently testable."""

from copy import deepcopy
import hashlib
import json
import math
import threading
import time
import uuid


class ProtocolError(ValueError):
    pass


def stamp_ns(stamp):
    if not isinstance(stamp, dict) or set(stamp) != {"secs", "nsecs"}:
        raise ProtocolError("invalid_stamp")
    sec, ns = stamp["secs"], stamp["nsecs"]
    if type(sec) is not int or type(ns) is not int or sec < 0 or not 0 <= ns < 10**9:
        raise ProtocolError("invalid_stamp")
    value = sec * 10**9 + ns
    if value <= 0:
        raise ProtocolError("invalid_stamp")
    return value


def valid_box(box, shape):
    try:
        if len(box) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in box):
            return False
        x, y, x2, y2 = box
        return 0 <= x < x2 <= shape[1] and 0 <= y < y2 <= shape[0]
    except (TypeError, ValueError):
        return False


class TrackingSession:
    def __init__(
        self,
        engine,
        score_floor=0.3,
        loss_timeout=5.0,
        recovery_frames=3,
        recovery_distance=0.0,  # 0 disables the integration-layer recovery displacement gate
        clock=time.monotonic,
    ):
        if not 0 <= score_floor <= 1 or loss_timeout <= 0 or recovery_frames < 1 or not math.isfinite(recovery_distance) or recovery_distance < 0:
            raise ValueError("invalid_tracking_configuration")
        self.engine, self.clock = engine, clock
        self.score_floor, self.loss_timeout = score_floor, loss_timeout
        self.recovery_frames, self.recovery_distance = recovery_frames, recovery_distance
        self.lock = threading.RLock()
        self.ready = True
        self.cache = None
        self._clear()

    def _clear(self):
        self.epoch = uuid.uuid4().hex
        self.session_id = ""
        self.state = "idle"
        self.seq = self.stamp = self.frame_seq = 0
        self.shape = self.box = None
        self.failed_since = None
        self.recovery = 0
        self.engine.clear()

    def status(self):
        with self.lock:
            return dict(
                model_loaded=self.ready,
                ready=self.ready,
                epoch=self.epoch,
                session_id=self.session_id,
                state=self.state,
                reason="",
            )

    def apply(self, operation, request, decode=None):
        digest = hashlib.sha256(
            (operation + json.dumps(request, sort_keys=True, allow_nan=False)).encode()
        ).hexdigest()
        with self.lock:
            if self.cache and digest == self.cache[0]:
                return deepcopy(self.cache[1])
            sid, seq = request["session_id"], request["send_seq"]
            if not self.ready:
                raise ProtocolError("service_unavailable")
            if request["expected_epoch"] != self.epoch:
                raise ProtocolError("epoch_mismatch")
            initialize = operation == "track" and request.get("reset") is True
            if not sid or type(seq) is not int or seq <= 0:
                raise ProtocolError("invalid_identity")
            if initialize:
                if seq != 1:
                    raise ProtocolError("initial_sequence")
            elif sid != self.session_id or seq <= self.seq:
                raise ProtocolError("session_or_sequence_mismatch")
            if operation == "reset":
                self._clear()
                result = dict(ok=True, session_id=sid, epoch=self.epoch, send_seq=seq, reason="reset")
            else:
                stamp = stamp_ns(request["stamp"])
                if not initialize and stamp <= self.stamp:
                    raise ProtocolError("non_increasing_stamp")
                image = decode(request["image_base64"])
                if initialize and not valid_box(request.get("init_bbox"), image.shape):
                    raise ProtocolError("invalid_init_bbox")
                if not initialize and (request.get("init_bbox") is not None or image.shape != self.shape):
                    raise ProtocolError("frame_shape_or_init_mismatch")
                try:
                    if initialize:
                        self.engine.initialize(image, request["init_bbox"])
                        self.epoch = uuid.uuid4().hex
                        self.session_id, self.shape = sid, image.shape
                        self.box = list(request["init_bbox"])
                        self.state, self.frame_seq = "active", 0
                        self.failed_since, self.recovery = None, 0
                        ok, bbox, score, reason = True, self.box, None, "initialized"
                    else:
                        ok, bbox, score, reason = self._track(image)
                except Exception:
                    self.cache = None
                    self._clear()
                    raise
                self.seq, self.stamp = seq, stamp
                self.frame_seq += 1
                result = dict(
                    ok=ok,
                    session_id=sid,
                    epoch=self.epoch,
                    send_seq=seq,
                    bbox=bbox,
                    score=score,
                    stamp=request["stamp"],
                    frame_seq=self.frame_seq,
                    reason=reason,
                )
            self.cache = digest, deepcopy(result)
            return result

    def _track(self, image):
        now = self.clock()
        if self.state == "lost" or (
            self.failed_since is not None and now - self.failed_since >= self.loss_timeout
        ):
            self.state = "lost"
            return False, None, None, "track_lost"
        bbox, score = self.engine.predict(image)
        good = valid_box(bbox, image.shape) and math.isfinite(score) and score >= self.score_floor
        if good and self.failed_since is not None and self.recovery_distance > 0:
            x, y, x2, y2 = self.box
            distance = math.hypot((bbox[0] + bbox[2] - x - x2) / 2, (bbox[1] + bbox[3] - y - y2) / 2)
            good = distance <= self.recovery_distance * math.hypot(x2 - x, y2 - y)
        if not good:
            if self.failed_since is None:
                self.failed_since = now
            self.recovery = 0
            self.state = "recovering"
            return False, None, score if math.isfinite(score) else None, "low_confidence"
        if self.failed_since is not None:
            self.recovery += 1
            if self.recovery < self.recovery_frames:
                return False, None, score, "recovering"
        recovered = self.failed_since is not None
        self.engine.commit(bbox)
        self.box = bbox
        self.failed_since, self.recovery, self.state = None, 0, "active"
        return True, bbox, score, "recovered" if recovered else "tracked"
