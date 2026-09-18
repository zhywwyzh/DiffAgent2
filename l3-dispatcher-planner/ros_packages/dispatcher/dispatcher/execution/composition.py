"""组合飞行 / VLA 领域对象；ROS 端口由调用方注入。"""
from dispatcher.utils.state import MISSION_TYPE
from dispatcher.execution.skill_host import DispatcherFlightHost, VlaSkillHost
from dispatcher.execution.waypoint_execution import WaypointExecution
from dispatcher.services.flight_session import FlightSession
from dispatcher.tools.flight.takeoff_skill import TakeoffSkill
from dispatcher.tools.flight.land_skill import LandSkill
from dispatcher.tools.flight.translate_skill import TranslateSkill
from dispatcher.tools.flight.rotate_skill import RotateSkill
from dispatcher.tools.flight.return_skill import ReturnSkill
from dispatcher.tools.flight.emergency_stop_skill import EmergencyStopSkill
from dispatcher.tools.vla.vla_skill import VlaSkill


def install_flight(engine, ports, config):
    execution = WaypointExecution(ports, config)
    host = DispatcherFlightHost(engine, execution, FlightSession(config))
    disposers = []
    try:
        for kind in (TakeoffSkill, LandSkill, TranslateSkill, RotateSkill, ReturnSkill, EmergencyStopSkill):
            skill = kind(host)
            disposers.append(engine.skills.register(skill.name, skill))
    except Exception:
        for dispose in reversed(disposers):
            dispose()
        raise

    def dispose():
        execution.cancel()
        for inverse in reversed(disposers):
            inverse()

    return host, dispose


def install_vla(
    engine, ports, execution_config, host_config, perception,
    *, geometry_config=None, search_success_distance_thresh=0.3,
    far_push_distance_m=5.0,
):
    """组合 VLA 领域对象（与 install_flight 同构），注册 navigation.vla_nav。

    - 动作出海复用 WaypointExecution（与飞行共享同一 FlightPorts 出站口，
      独立实例：batch 随机起始互不冲突；飞行独占由 tool-plane 单活动调用
      与 engine 动作账务（owner 门 / 代次）保证）；
    - 几何原语源为 perception（base_policy 实例，经 VlaSkillHost 组合注入），
      技能层 slog 出站回调接 engine.runlog.emit；
    - VLA 几何/阈值配置唯一权威为调用方显式注入的 geometry_config 与两个
      技能层阈值（装配层经 ~vla/* 私有参数读取，默认值=旧库值）；perception
      侧同名属性（behind_dist/is_stable/stable_height 等）属 perception
      自有，VLA 几何不依赖——避免双存储假象；
    - mission_type 接入（旧语义，装配侧）：旧链 vla_skill.plan_tick 每轮置
      host.mission_type=MISSION_TYPE.NAVIGATION，消费方为几何原语
      _finalize_waypoint_candidate 的 NAVIGATION 分支（side/above/front 腿的
      目标偏移组合）。新库 mission_type 唯一写点是 base_policy 初始化
      NOT_MISSION（无其他写者），装配时一次性置位与旧链每轮置位等价；
      disposer 恢复原值。if_safe_mode 旧库仅剩留壳写、零读取，不接入。
    """
    execution = WaypointExecution(ports, execution_config)
    host = VlaSkillHost(engine, execution, perception, host_config)
    disposers = []
    previous_mission_type = getattr(perception, "mission_type", MISSION_TYPE.NOT_MISSION)
    try:
        skill = VlaSkill(
            host,
            geometry_config=geometry_config,
            emit=engine.runlog.emit,
            search_success_distance_thresh=search_success_distance_thresh,
            far_push_distance_m=far_push_distance_m,
        )
        perception.mission_type = MISSION_TYPE.NAVIGATION
        disposers.append(engine.skills.register(skill.name, skill))
    except Exception:
        perception.mission_type = previous_mission_type
        for dispose in reversed(disposers):
            dispose()
        raise

    def dispose():
        execution.cancel()
        for inverse in reversed(disposers):
            inverse()
        perception.mission_type = previous_mission_type

    return host, dispose
