"""UETrack-B RGB inference. No detector, online template update or network fetch."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np


def verified_weights(directory):
    root = Path(directory).resolve()
    manifest = json.loads((root / "weights.json").read_text())
    result = {}
    for key, default, override in (
        ("checkpoint", "uetrack_inference.pth.tar", "UETRACK_CHECKPOINT"),
        ("clip", "clip/ViT-L-14.pt", None),
    ):
        path = Path(os.environ.get(override, "") or root / default) if override else root / default
        if not path.is_file():
            raise ValueError(f"missing_weight:{key}:{path}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != manifest[key]["sha256"]:
            raise ValueError(f"weight_checksum_mismatch:{key}")
        result[key] = str(path.resolve())
    return result


def _tolerant_pickle_module():
    """Unpickler that tolerates classes absent from the vendored inference subset.

    Only the tensor state dict is consumed, so an unimportable class becomes an
    inert placeholder instead of aborting the load. This keeps the original
    training-run checkpoint usable through ``UETRACK_CHECKPOINT``: its pickle
    names ``lib.train.admin.*`` helpers that the vendored subset deliberately
    drops (no training code, no torch.distributed). Key/shape correctness stays
    guarded by the ``load_state_dict`` validation that follows.
    """
    import pickle

    class _TolerantUnpickler(pickle.Unpickler):
        def find_class(self, module, name):
            try:
                return super().find_class(module, name)
            except (ModuleNotFoundError, ImportError, AttributeError):
                return type(name, (), {})

    class _Module:
        Unpickler = _TolerantUnpickler

    return _Module


# Parameters present in the released checkpoint but absent from the inference
# graph: the distillation "adjust layer" that aligned student/teacher features
# during training. Recorded explicitly so the load tolerates exactly these keys
# and still fails closed on a missing key or an unknown extra one.
CHECKPOINT_TRAINING_ONLY_KEYS = frozenset({"adjust_layers.0.weight"})


class UETrackEngine:
    def __init__(self, weights_dir, device="cuda:0"):
        weights = verified_weights(weights_dir)
        import torch

        if not device.startswith("cuda:") or not torch.cuda.is_available():
            raise RuntimeError("uetrack_requires_cuda")
        torch.cuda.set_device(torch.device(device))
        self.torch, self.device = torch, torch.device(device)
        vendor = Path(__file__).parent / "vendor/uetrack"
        sys.path.insert(0, str(vendor))
        from lib.config.uetrack.config import cfg, update_config_from_file
        from lib.models.uetrack import build_uetrack_inference
        from lib.test.tracker.utils import sample_target, transform_image_to_crop
        from lib.test.utils.hann import hann2d
        from lib.utils.box_ops import clip_box

        update_config_from_file(str(vendor / "experiments/uetrack/uetrack_base.yaml"))
        self.cfg = deepcopy(cfg)
        # Inference-only: the checkpoint carries every parameter (encoder, CLIP
        # text encoder, decoders), so the encoder builds with no separate
        # backbone init (see the encoder.py patch in the vendored subset).
        self.cfg.MODEL.ENCODER.PRETRAIN_TYPE = ""
        # Existing factory forwards TYPE to clip.load, which accepts a local file.
        self.cfg.MODEL.TEXT_ENCODER.TYPE = weights["clip"]
        if self.cfg.TRAIN.TEACHER_TYPE != "fastitpnb":
            raise ValueError("unsupported_teacher")
        network = build_uetrack_inference(self.cfg)
        loaded = torch.load(
            weights["checkpoint"],
            map_location="cpu",
            weights_only=False,
            pickle_module=_tolerant_pickle_module(),
        )
        # The inference-only export IS the bare state dict; a training checkpoint
        # wraps it under "net".
        state = loaded["net"] if isinstance(loaded, dict) and "net" in loaded else loaded
        # Fail closed: only the recorded training-only keys are tolerated; a
        # missing key or an unknown extra one aborts startup.
        incompatible = network.load_state_dict(state, strict=False)
        if incompatible.missing_keys:
            raise ValueError(f"checkpoint_missing_keys:{sorted(incompatible.missing_keys)}")
        unknown = sorted(set(incompatible.unexpected_keys) - CHECKPOINT_TRAINING_ONLY_KEYS)
        if unknown:
            raise ValueError(f"checkpoint_unexpected_keys:{unknown}")
        self.network = network.to(self.device).eval()
        self.sample_target, self.transform_crop, self.clip_box = (
            sample_target,
            transform_image_to_crop,
            clip_box,
        )
        size = self.cfg.TEST.SEARCH_SIZE // self.cfg.MODEL.ENCODER.STRIDE
        self.window = hann2d(torch.tensor([size, size]), centered=True).to(self.device)
        self.mean = torch.tensor(self.cfg.DATA.MEAN, device=self.device).view(1, 3, 1, 1)
        self.std = torch.tensor(self.cfg.DATA.STD, device=self.device).view(1, 3, 1, 1)
        self.task = torch.tensor([0], device=self.device)  # RGB tracking task
        self.warmup_steps = 0
        self.clear()

    def warmup(self, steps):
        """Exercise template and search kernels before accepting real sessions."""
        image = np.zeros((480, 640, 3), dtype=np.uint8)
        try:
            self.initialize(image, [240, 180, 400, 300])
            for _ in range(steps):
                self.predict(image)
            self.torch.cuda.synchronize(self.device)
            self.warmup_steps = steps
        finally:
            # Synthetic state must never seed an actual tracking session.
            self.clear()

    def clear(self):
        self.state = self.templates = self.annotations = self.text = None

    def runtime_status(self):
        import cv2
        parameter = next(self.network.parameters())
        return dict(
            cpu_affinity=sorted(os.sched_getaffinity(0)),
            opencv_threads=cv2.getNumThreads(),
            torch_threads=self.torch.get_num_threads(),
            torch_interop_threads=self.torch.get_num_interop_threads(),
            warmup_steps=self.warmup_steps,
            model_device=str(parameter.device),
            model_dtype=str(parameter.dtype),
            cuda_device_name=self.torch.cuda.get_device_name(self.device),
            cuda_memory_allocated_bytes=self.torch.cuda.memory_allocated(self.device),
            cuda_memory_reserved_bytes=self.torch.cuda.memory_reserved(self.device),
        )

    def _crop(self, image, box, factor, size):
        patch, scale = self.sample_target(image, box, factor, output_sz=size)
        tensor = (
            self.torch.from_numpy(np.ascontiguousarray(patch)).to(self.device).float().permute(2, 0, 1)[None]
            / 255
        )
        tensor = (tensor - self.mean) / self.std
        if self.cfg.TEST.MULTI_MODAL_VISION.DEFAULT:
            tensor = self.torch.cat((tensor, tensor), dim=1)
        return tensor, scale

    def initialize(self, image, bbox):
        torch, cfg = self.torch, self.cfg
        x1, y1, x2, y2 = bbox
        state = [x1, y1, x2 - x1, y2 - y1]
        with torch.inference_mode():
            template, scale = self._crop(image, state, cfg.TEST.TEMPLATE_FACTOR, cfg.TEST.TEMPLATE_SIZE)
            anno = self.transform_crop(
                torch.tensor(state),
                torch.tensor(state),
                scale,
                torch.tensor([cfg.TEST.TEMPLATE_SIZE] * 2),
                normalize=True,
            )
            text = self.network.forward_textencoder_inference(
                text_data=torch.zeros((1, 77), dtype=torch.long, device=self.device)
            )
        self.state = state
        self.templates = [template] * cfg.TEST.NUM_TEMPLATES
        self.annotations = [anno.to(self.device)[None]]
        self.text = text

    def predict(self, image):
        torch, cfg = self.torch, self.cfg
        with torch.inference_mode():
            search, scale = self._crop(image, self.state, cfg.TEST.SEARCH_FACTOR, cfg.TEST.SEARCH_SIZE)
            feature, _, _ = self.network.forward_encoder(
                self.templates, [search], self.annotations, self.text, self.task
            )
            output = self.network.forward_decoder(feature=feature)
            raw = output["score_map"]
            score = float(raw.max().item())
            response = raw * self.window if cfg.TEST.WINDOW else raw
            args = [response]
            if "size_map" in output:
                args.append(output["size_map"])
            args.append(output["offset_map"])
            boxes, _ = self.network.decoder.cal_bbox(*args, return_score=True)
            cx, cy, w, h = (boxes.view(-1, 4).mean(0) * cfg.TEST.SEARCH_SIZE / scale).tolist()
        prev_x, prev_y, prev_w, prev_h = self.state
        half = cfg.TEST.SEARCH_SIZE / (2 * scale)
        candidate = [cx + prev_x + prev_w / 2 - half - w / 2, cy + prev_y + prev_h / 2 - half - h / 2, w, h]
        if not np.isfinite(candidate).all() or min(w, h) <= 0:
            return None, score
        x, y, w, h = self.clip_box(candidate, *image.shape[:2], margin=10)
        return [x, y, x + w, y + h], score

    def commit(self, bbox):
        x, y, x2, y2 = bbox
        self.state = [x, y, x2 - x, y2 - y]
