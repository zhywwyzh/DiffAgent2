"""独立遥测会话、有界最新值槽、频率与总带宽限制。"""
import json
from pathlib import Path
import threading
import time
import uuid

import zenoh


class Uplink:
    def __init__(self, stack, router, settings, encode, log):
        self.settings = settings
        self.encode = encode
        self.log = log
        self.started = time.monotonic()
        self._lock = threading.Lock()
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
            for channel in settings["rates"]:
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
        with self._lock:
            self._latest[channel] = value
            self._received[channel] = time.monotonic()

    def _health(self):
        now = time.monotonic()
        with self._lock:
            data = {"epoch": time.time(), "input_age_s": {key: round(now - stamp, 3) for key, stamp in self._received.items()},
                    "sent_age_s": {key: round(now - self._sent[key], 3) if key in self._sent else None
                                   for key in self.settings["rates"]}}
        path = Path("/tmp/diffagent-telemetry.json")
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data))
        temp.replace(path)

    def _loop(self):
        next_wire = 0.0
        next_health = 0.0
        rate = self.settings["mbit"] * 1e6 / 8
        while not self._stop.wait(0.02):
            now = time.monotonic()
            if now >= next_health:
                self._health()
                next_health = now + 1
            for channel, hz in self.settings["rates"].items():
                if hz <= 0 or now - self._sent.get(channel, 0) < 1.0 / hz:
                    continue
                with self._lock:
                    value = self._latest.pop(channel, None)
                if value is None:
                    continue
                try:
                    payload = self.encode(channel, value)
                    if self._stop.wait(max(0, next_wire - time.monotonic())):
                        return
                    self._publishers[channel].put(payload)
                    now = time.monotonic()
                    self._sent[channel] = now
                    next_wire = now + len(payload) / rate
                except Exception as error:
                    if now - self._last_error.get(channel, 0) >= 5:
                        self.log(f"{channel} 编码或发送失败: {error}")
                        self._last_error[channel] = now

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        for handle in [self._token, *self._publishers.values()]:
            if handle is not None:
                handle.undeclare()
        if self._session is not None:
            self._session.close()
