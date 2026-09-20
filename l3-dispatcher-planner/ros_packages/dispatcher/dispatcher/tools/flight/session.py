"""原点由确认的飞行会话拥有，任务覆盖不重写原点。"""
import math
import threading
from dispatcher.execution.ports import FlightConfig, FlightState


class FlightSession:
    def __init__(self, config: FlightConfig):
        self.config = config
        self._candidate = None
        self._origin = None
        self._last = None
        self._lock = threading.RLock()

    def observe(self, state: FlightState):
        with self._lock:
            if self._last and (state.frame != self._last.frame
                               or state.source_stamp < self._last.source_stamp):
                self._origin = self._candidate = None
            self._last = state
            ground = self.config.ground_z
            if ground is None:
                return
            if self._candidate and state.position[2] - ground >= self.config.airborne_height:
                self._origin, self._candidate = self._candidate, None
            if self._origin and abs(state.position[2] - ground) <= self.config.ground_tolerance and state.speed < .1:
                self._origin = None

    def prepare_takeoff(self, state: FlightState):
        with self._lock:
            self.observe(state)
            ground = self.config.ground_z
            if ground is None or not math.isfinite(ground):
                raise RuntimeError('ground_height_unconfigured')
            if self._origin or abs(state.position[2] - ground) > self.config.ground_tolerance or state.speed >= .1:
                raise RuntimeError('takeoff_requires_ground_state')
            self._candidate = tuple(state.position)

    def reject_takeoff(self):
        with self._lock:
            self._candidate = None

    def origin(self, state: FlightState):
        with self._lock:
            self.observe(state)
            if self._origin is None:
                raise RuntimeError('origin_unavailable')
            return self._origin

    def reset(self):
        with self._lock:
            self._candidate = self._origin = self._last = None
