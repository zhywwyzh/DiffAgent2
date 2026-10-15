"""Synchronous bounded HTTP client. The producer owns the single worker."""

from __future__ import annotations
from dataclasses import dataclass
import base64
import math

import cv2
import requests
from dispatcher.tools.track.ports import EncodedRGB, ros_seconds


@dataclass(frozen=True)
class TrackOutput:
    ok: bool
    bbox: list | None
    stamp: float
    submit_seq: int
    reason: str
    identity_revision: int = 1
    score: float | None = None


def wire_stamp(stamp):
    ns = int(stamp) if isinstance(stamp, int) else round(float(stamp) * 1e9)
    return {"secs": ns // 10**9, "nsecs": ns % 10**9}


class UETrackClient:
    def __init__(self, api_url, session_id, timeout=5.0, init_timeout=30.0):
        self.url = api_url.rstrip("/")
        self.session_id, self.timeout, self.init_timeout = session_id, timeout, init_timeout
        self.http = requests.Session()
        self.epoch = None
        self.sequence = 0

    def _post(self, endpoint, payload, timeout):
        # A retry uses exactly the same payload; no implicit reset on transport error.
        for attempt in range(2):
            try:
                response = self.http.post(self.url + endpoint, json=payload, timeout=timeout)
                response.raise_for_status()
                result = response.json()
                if (
                    result.get("session_id") != self.session_id
                    or result.get("send_seq") != payload["send_seq"]
                ):
                    raise ValueError("reply_identity_mismatch")
                return result
            except (requests.Timeout, requests.ConnectionError):
                if attempt:
                    raise

    def _track(self, image, stamp, init_bbox=None):
        initializing = init_bbox is not None
        if initializing:
            response = self.http.get(self.url + "/status", timeout=self.timeout)
            response.raise_for_status()
            status = response.json()
            if not status.get("ready"):
                raise ValueError("tracker_not_ready")
            self.epoch = status["epoch"]
        if not self.epoch:
            raise ValueError("tracker_not_initialized")
        if isinstance(image, EncodedRGB):
            # 在 HTTP worker 中核对真实像素尺寸；仍发送原 JPEG，避免重新编码改变 seed。
            image.copy()
            encoded = image.data  # Same JPEG and pixels as the station camera.
        else:
            ok, encoded = cv2.imencode(".png", image)
            if not ok:
                raise ValueError("image_encode_failed")
        self.sequence += 1
        payload = dict(
            session_id=self.session_id,
            expected_epoch=self.epoch,
            send_seq=self.sequence,
            image_base64=base64.b64encode(encoded).decode(),
            stamp=wire_stamp(stamp),
            init_bbox=init_bbox,
            reset=initializing,
        )
        result = self._post("/track", payload, self.init_timeout if initializing else self.timeout)
        if result.get("stamp") != payload["stamp"] or type(result.get("ok")) is not bool:
            raise ValueError("reply_provenance_mismatch")
        epoch = result.get("epoch")
        if not isinstance(epoch, str) or not epoch or (not initializing and epoch != self.epoch):
            raise ValueError("reply_epoch_mismatch")
        box = result.get("bbox")
        if result["ok"]:
            if (
                not isinstance(box, list)
                or len(box) != 4
                or any(type(x) not in (int, float) or not math.isfinite(x) for x in box)
            ):
                raise ValueError("invalid_reply_bbox")
            x, y, x2, y2 = box
            if not 0 <= x < x2 <= image.shape[1] or not 0 <= y < y2 <= image.shape[0]:
                raise ValueError("invalid_reply_bbox")
        self.epoch = epoch
        raw_score = result.get("score")
        score = (
            float(raw_score)
            if isinstance(raw_score, (int, float))
            and not isinstance(raw_score, bool)
            and math.isfinite(raw_score)
            else None
        )
        return TrackOutput(
            result["ok"],
            box,
            ros_seconds(stamp) if isinstance(stamp, int) else stamp,
            self.sequence,
            result.get("reason", ""),
            score=score,
        )

    def start(self, image, bbox, stamp):
        return self._track(image, stamp, bbox)

    def update(self, image, stamp):
        return self._track(image, stamp)

    def reset(self):
        try:
            if self.epoch:
                self.sequence += 1
                self._post(
                    "/reset",
                    dict(
                        session_id=self.session_id,
                        expected_epoch=self.epoch,
                        send_seq=self.sequence,
                        reason="execution_closed",
                    ),
                    self.timeout,
                )
            return True
        finally:
            self.http.close()
