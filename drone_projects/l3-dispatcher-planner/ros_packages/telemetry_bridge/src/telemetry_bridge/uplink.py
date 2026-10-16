"""Unity 独立遥测会话与有界最新值槽，新值到达即唤醒发送。"""
import json
from pathlib import Path
import threading
import time
import uuid

import zenoh


CHANNELS = ("meta", "drone_status", "camera", "depth", "cloud")


class Uplink:
    def __init__(self, stack, router, encode, log):
        self.encode = encode
        self.log = log
        self.started = time.monotonic()
        self._condition = threading.Condition()
        self._latest = {}
        self._received = {}
        self._sent = {}
        self._last_error = {}
        self._stop = threading.Event()
        self._session = None
        self._publishers = {}
        self._token = None
        self._thread = None
        config = zenoh.Config()
        config.insert_json5("mode", '"client"')
        config.insert_json5("connect/endpoints", json.dumps([router]))
        config.insert_json5("scouting/multicast/enabled", "false")
        try:
            self._session = zenoh.open(config)
            for channel in CHANNELS:
                self._publishers[channel] = self._session.declare_publisher(
                    f"lx/{stack}/telemetry/{channel}", reliability=zenoh.Reliability.BEST_EFFORT,
                    congestion_control=zenoh.CongestionControl.DROP)
            self._token = self._session.liveliness().declare_token(f"lx/{stack}/presence/telemetry/{uuid.uuid4().hex[:12]}")
            self._thread = threading.Thread(target=self._loop, name="telemetry-uplink", daemon=True)
            self._thread.start()
        except Exception:
            self.close()
            raise

    def submit(self, channel, value):
        if channel not in CHANNELS:
            raise ValueError(f"未知遥测频道: {channel}")
        with self._condition:
            if self._stop.is_set():
                return
            self._latest[channel] = value
            self._received[channel] = time.monotonic()
            self._condition.notify()

    def _health(self):
        now = time.monotonic()
        with self._condition:
            data = {"epoch": time.time(), "input_age_s": {key: round(now - stamp, 3) for key, stamp in self._received.items()},
                    "sent_age_s": {key: round(now - self._sent[key], 3) if key in self._sent else None
                                   for key in CHANNELS}}
        path = Path("/tmp/diffagent-telemetry.json")
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data))
        temp.replace(path)

    def _loop(self):
        next_health = 0.0
        while not self._stop.is_set():
            with self._condition:
                if not self._latest:
                    self._condition.wait(timeout=max(0, next_health - time.monotonic()))
                if self._stop.is_set():
                    return
            now = time.monotonic()
            if now >= next_health:
                self._health()
                next_health = now + 1
            for channel in CHANNELS:
                if self._stop.is_set():
                    return
                with self._condition:
                    value = self._latest.pop(channel, None)
                if value is None:
                    continue
                try:
                    payload = self.encode(channel, value)
                    if self._stop.is_set():
                        return
                    self._publishers[channel].put(payload)
                    with self._condition:
                        self._sent[channel] = time.monotonic()
                except Exception as error:
                    now = time.monotonic()
                    if now - self._last_error.get(channel, 0) >= 5:
                        self.log(f"{channel} 编码或发送失败: {error}")
                        self._last_error[channel] = now

    def close(self):
        with self._condition:
            self._stop.set()
            self._condition.notify_all()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                raise RuntimeError("遥测发送线程尚未停止，保留 Zenoh 资源")
        for handle in [self._token, *self._publishers.values()]:
            if handle is not None:
                handle.undeclare()
        if self._session is not None:
            self._session.close()
