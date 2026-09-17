"""基础飞行数据和能力端口；不依赖 ROS。"""
import math
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class FlightConfig:
    ground_z: float | None = None
    world_frame: str = "world"
    min_height: float = 0.3
    max_height: float = 3.0
    state_timeout: float = 1.0
    action_timeout: float = 60.0
    max_rotation_deg: float = 3600.0
    ground_tolerance: float = 0.15
    airborne_height: float = 0.3


    def __post_init__(self):
        if not isinstance(self.world_frame, str) or not self.world_frame:
            raise ValueError("invalid_world_frame")
        values = (self.min_height, self.max_height, self.state_timeout, self.action_timeout,
                  self.max_rotation_deg, self.ground_tolerance, self.airborne_height)
        if not all(math.isfinite(v) for v in values) or self.min_height > self.max_height:
            raise ValueError('invalid_flight_config')
        if any(v <= 0 for v in values[2:]):
            raise ValueError('flight_limits_must_be_positive')
        if self.ground_z is not None and not math.isfinite(self.ground_z):
            raise ValueError('invalid_ground_height')


@dataclass(frozen=True)
class FlightState:
    position: tuple[float, float, float]
    yaw: float
    speed: float
    received: float
    source_stamp: float
    frame: str
    source_age: float = 0.0


@dataclass(frozen=True)
class Goal:
    position: tuple[float, float, float]
    yaw: float
    look_forward: bool = False


@dataclass(frozen=True)
class Progress:
    batch: int
    all_consumed: bool
    skipped_mask: int = 0


@dataclass(frozen=True)
class ActionResult:
    success: bool
    reason: str = ''


class FlightPorts(Protocol):
    def snapshot(self) -> FlightState | None: ...
    def progress(self) -> tuple[Progress, ...]: ...
    def send_goal(self, batch: int, goal: Goal) -> None: ...
    def takeoff(self) -> None: ...
    def land(self) -> None: ...
    def stop(self) -> None: ...


class FlightHost(Protocol):
    config: FlightConfig
    def state(self) -> FlightState: ...
    def origin(self) -> tuple[float, float, float]: ...
    def start_goal(self, owner, goal: Goal) -> None: ...
    def poll_result(self) -> ActionResult | None: ...
    def cancel_execution(self, owner=None) -> None: ...
    def request_takeoff(self) -> None: ...
    def request_land(self) -> None: ...
    def request_safety_stop(self) -> None: ...
    def publish_phase(self, phase: str, **kwargs) -> None: ...
    def fail_sequence(self, reason: str) -> None: ...
    def stash_task_result(self, result: dict) -> None: ...
