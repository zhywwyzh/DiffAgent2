"""Single-worker UETrack HTTP boundary; startup errors prevent readiness."""

import base64
from contextlib import asynccontextmanager
import logging
import os

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from session import ProtocolError, TrackingSession
from uetrack_engine import UETrackEngine

LOG = logging.getLogger("uetrack")


class Stamp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    secs: StrictInt = Field(ge=0)
    nsecs: StrictInt = Field(ge=0, lt=1000000000)


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: StrictStr = Field(min_length=1, max_length=128)
    expected_epoch: StrictStr = Field(min_length=1, max_length=128)
    send_seq: StrictInt = Field(gt=0)
    reason: StrictStr = Field(default="", max_length=256)


class TrackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: StrictStr = Field(min_length=1, max_length=128)
    expected_epoch: StrictStr = Field(min_length=1, max_length=128)
    send_seq: StrictInt = Field(gt=0)
    stamp: Stamp
    image_base64: StrictStr = Field(min_length=1, max_length=16000000)
    init_bbox: list[float] | None = None
    reset: StrictBool = False


def decode_image(data):
    try:
        raw = base64.b64decode(data, validate=True)
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.size > 24000000:
            raise ValueError("invalid_image")
        return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    except Exception as exc:
        raise ProtocolError("invalid_image") from exc


def create_app(factory=None):
    @asynccontextmanager
    async def lifespan(app):
        if factory is None:
            # Configure once, before model work or request workers are created.
            for key in ('LX_OPENCV_THREADS', 'LX_TORCH_THREADS', 'LX_TORCH_INTEROP_THREADS'):
                if key in os.environ and int(os.environ[key]) < 1:
                    raise ValueError(key + ' must be positive')
            if 'LX_OPENCV_THREADS' in os.environ:
                cv2.setNumThreads(int(os.environ['LX_OPENCV_THREADS']))
            import torch
            if 'LX_TORCH_THREADS' in os.environ:
                torch.set_num_threads(int(os.environ['LX_TORCH_THREADS']))
            if 'LX_TORCH_INTEROP_THREADS' in os.environ:
                torch.set_num_interop_threads(int(os.environ['LX_TORCH_INTEROP_THREADS']))
            engine = UETrackEngine(os.environ["TRACK_WEIGHTS_DIR"], os.environ["UETRACK_DEVICE"])
            warmup_steps = int(os.environ.get('LX_TRACK_WARMUP_STEPS', '0'))
            if not 0 <= warmup_steps <= 10:
                raise ValueError('LX_TRACK_WARMUP_STEPS must be between 0 and 10')
            if warmup_steps:
                engine.warmup(warmup_steps)
            app.state.tracker = TrackingSession(
                engine,
                score_floor=float(os.environ["UETRACK_SCORE_FLOOR"]),
                loss_timeout=float(os.environ["UETRACK_LOSS_TIMEOUT"]),
                recovery_frames=int(os.environ["UETRACK_RECOVERY_FRAMES"]),
                recovery_distance=float(os.environ["UETRACK_RECOVERY_DISTANCE"]),
            )
        else:
            app.state.tracker = factory()
        yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/status")
    def status():
        tracker = getattr(app.state, "tracker", None)
        if tracker is None or not tracker.ready:
            raise HTTPException(503, detail="model_not_ready")
        result = tracker.status()
        runtime_status = getattr(tracker.engine, "runtime_status", None)
        if runtime_status is not None:
            result.update(runtime_status())
        return result

    def transact(operation, request):
        try:
            return app.state.tracker.apply(operation, request.model_dump(), decode_image)
        except ProtocolError as exc:
            raise HTTPException(409, detail=str(exc)) from exc
        except Exception as exc:
            LOG.exception(
                "tracking transaction failed session=%s seq=%s", request.session_id, request.send_seq
            )
            raise HTTPException(500, detail="tracking_state_invalidated") from exc

    @app.post("/track")
    def track(request: TrackRequest):
        return transact("track", request)

    @app.post("/reset")
    def reset(request: ResetRequest):
        return transact("reset", request)

    return app


app = create_app()
