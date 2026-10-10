"""跟踪领域数据及只读配置，不依赖 ROS。"""
import math
from dataclasses import dataclass


from dispatcher.support.tracking_data import EncodedRGB, TrackingFrame, ros_seconds

@dataclass(frozen=True)
class TrackConfig:
    api_url: str = "http://127.0.0.1:2250"
    request_timeout_s: float = 5.0
    init_timeout_s: float = 30.0
    seed_max_age_s: float = 15.0
    observation_timeout_s: float = 0.5
    loss_timeout_s: float = 5.0
    session_timeout_s: float = 600.0
    follow_distance_m: float = 2.5
    distance_tolerance_m: float = 0.3
    yaw_tolerance_rad: float = 0.2
    aircraft_speed_m_s: float = 0.1
    target_speed_m_s: float = 0.2
    finish_hold_s: float = 3.0
    target_height_m: float = 1.0

    def __post_init__(self):
        for name, value in vars(self).items():
            if name not in ('api_url', 'target_height_m') and (not math.isfinite(value) or value <= 0):
                raise ValueError('invalid_tracking_config:' + name)
        if self.session_timeout_s > 600:
            raise ValueError('tracking_session_limit_exceeded')
        if not math.isfinite(self.target_height_m) or self.yaw_tolerance_rad >= math.pi:
            raise ValueError('invalid_tracking_geometry')

@dataclass(frozen=True)
class Observation:
    stamp_ns: int
    sequence: int
    bbox: tuple
    width: int
    height: int
    intrinsics: tuple
    rotation: tuple
    translation: tuple

@dataclass(frozen=True)
class TrackingFeedback:
    received: float
    stamp: float
    sequence: int
    valid: bool
    position: tuple
    velocity: tuple
    phase: str
