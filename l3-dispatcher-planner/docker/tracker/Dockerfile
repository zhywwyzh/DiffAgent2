# Native build, context l3-dispatcher-planner. Supply fixed image refs and CLIP commit.
ARG TRACKER_BASE_IMAGE
ARG UV_IMAGE
FROM ${UV_IMAGE} AS uv_binary
FROM ${TRACKER_BASE_IMAGE}
USER root
COPY --from=uv_binary /uv /uvx /usr/local/bin/
RUN python3 -c 'import sys, torch, torchvision; assert sys.version_info >= (3,10); print(torch.__version__, torchvision.__version__)'
RUN command -v git >/dev/null || (apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*)
ENV UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/uetrack-venv UV_PYTHON_DOWNLOADS=never
ARG CLIP_COMMIT
COPY docker/tracker/requirements.txt /tmp/tracking-requirements.txt
RUN test "${#CLIP_COMMIT}" -eq 40 \
 && uv venv --system-site-packages --python "$(command -v python3)" "$UV_PROJECT_ENVIRONMENT" \
 && uv pip install --python "$UV_PROJECT_ENVIRONMENT/bin/python" --no-cache --reinstall-package pip -r /tmp/tracking-requirements.txt \
 && uv pip install --python "$UV_PROJECT_ENVIRONMENT/bin/python" --no-cache --no-deps \
      "timm==1.0.30" "clip @ git+https://github.com/openai/CLIP.git@${CLIP_COMMIT}" \
 && rm -f /tmp/tracking-requirements.txt
ENV VIRTUAL_ENV=/opt/uetrack-venv
ENV PATH="/opt/uetrack-venv/bin:${PATH}"
RUN python -m pip --version \
 && python -c 'import torch, torchvision, timm, clip, einops; assert "/opt/uetrack-venv/" not in torch.__file__; assert "/opt/uetrack-venv/" not in torchvision.__file__'
COPY ros_packages/dispatcher/dispatcher/tools/track/service /opt/tracking
ENV TRACK_WEIGHTS_DIR=/weights/track PYTHONDONTWRITEBYTECODE=1 UETRACK_DEVICE=cuda:0 UETRACK_SCORE_FLOOR=0.3 UETRACK_LOSS_TIMEOUT=5.0 UETRACK_RECOVERY_FRAMES=3 UETRACK_RECOVERY_DISTANCE=0
WORKDIR /opt/tracking
EXPOSE 2250
CMD ["bash", "/opt/tracking/start_uetrack.sh"]
