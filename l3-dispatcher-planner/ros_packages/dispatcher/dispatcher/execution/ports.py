"""执行缝共享动作端口：意图、状态、进度与配置；不依赖 ROS。"""
import math
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class FlightConfig:
    ground_z: float | None = None
    world_frame: str = "world"
    min_height: float = 0.3
    max_height: float = 3.0
    state_timeout_s: float = 1.0
    action_timeout_s: float = 60.0
    stop_timeout_s: float = 5.0
    connect_timeout_s: float = 5.0
    admission_timeout_s: float = 5.0
    max_rotation_deg: float = 3600.0
    ground_tolerance: float = 0.15
    airborne_height: float = 0.3
    settle_position_m: float = 0.30
    settle_speed_m_s: float = 0.15
    settle_acceleration_m_s2: float = 0.30
    settle_yaw_rate_rad_s: float = 0.20
    settle_hold_s: float = 0.20
    settle_yaw_deg: float = 10.0


    def __post_init__(self):
        if not isinstance(self.world_frame, str) or not self.world_frame:
            raise ValueError("invalid_world_frame")
        values = (self.min_height, self.max_height, self.state_timeout_s, self.action_timeout_s, self.stop_timeout_s,
                  self.connect_timeout_s, self.admission_timeout_s,
                  self.max_rotation_deg, self.ground_tolerance, self.airborne_height,
                  self.settle_position_m, self.settle_speed_m_s,
                  self.settle_acceleration_m_s2, self.settle_yaw_rate_rad_s,
                  self.settle_hold_s, self.settle_yaw_deg)
        if not all(math.isfinite(v) for v in values) or self.min_height > self.max_height:
            raise ValueError('invalid_flight_config')
        if any(v <= 0 for v in values[2:]):
            raise ValueError('flight_limits_must_be_positive')
        if self.settle_yaw_deg >= 90:
            raise ValueError('settle_yaw_must_be_less_than_segment')
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
    velocity: tuple[float, float, float] | None = None
    yaw_rate_rad_s: float | None = None


@dataclass(frozen=True)
class Goal:
    position: tuple[float, float, float]
    yaw: float
    look_forward: bool = False
    ground_approach: bool = False
    yaw_low_speed: bool = False


@dataclass(frozen=True)
class ActionKey:
    generation: int
    owner: object


@dataclass(frozen=True)
class ActionResult:
    success: bool
    reason: str = ''
    stop_confirmed: bool = False


@dataclass(frozen=True)
class ActionEvent:
    token: str
    status: str
    result: ActionResult | None = None


@dataclass(frozen=True)
class ExecutionState:
    boot_id: int
    recovery_generation: int
    ready: bool
    stop_confirmed: bool
    phase: str
    received: float


class PlannerActionPort(Protocol):
    def connected(self, goal=None) -> bool: ...
    def send(self, token: str, goal: Goal): ...
    def cancel(self, handle) -> None: ...
    def events(self) -> tuple[ActionEvent, ...]: ...
    def readiness(self) -> ExecutionState | None: ...


@dataclass(frozen=True)
class StopRecord:
    started: float
    boot_id: int | None
    recovery_generation: int
    token: str | None
    handle: object | None
    request_sent: bool = False
    last_attempt: float = 0.0


@dataclass(frozen=True)
class TrackingGoal:
    session_id: str
    execution_id: str
    follow_distance_m: float
    distance_tolerance_m: float
    target_height_m: float
    observation_timeout_s: float
    duration_s: float
