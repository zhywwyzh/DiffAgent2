"""组合飞行 / VLA 领域对象；ROS 端口由调用方注入。"""
from dispatcher.execution.skill_host import DispatcherFlightHost, VlaSkillHost
from dispatcher.tools.flight.flight_waypoint import FlightWaypointExecution
from dispatcher.tools.vla.vla_waypoint import VlaWaypointExecution
from dispatcher.tools.flight.session import FlightSession
from dispatcher.tools.flight.takeoff_skill import TakeoffSkill
from dispatcher.tools.flight.land_skill import LandSkill
from dispatcher.tools.flight.translate_skill import TranslateSkill
from dispatcher.tools.flight.rotate_skill import RotateSkill
from dispatcher.tools.flight.return_skill import ReturnSkill
from dispatcher.tools.flight.emergency_stop_skill import EmergencyStopSkill
from dispatcher.tools.vla.vla_skill import VlaSkill


def install_flight(engine, ports, config):
    execution = FlightWaypointExecution(ports, config)
    host = DispatcherFlightHost(engine, execution, FlightSession(config))
    disposers = []
    try:
        for kind in (TakeoffSkill, LandSkill, TranslateSkill, RotateSkill, ReturnSkill, EmergencyStopSkill):
            skill = kind(host)
            disposers.append(engine.skills.register(skill.name, skill))
            if kind is RotateSkill:
                # VLA 家族自有旋转腿（站端 visible=false 重扫）：复用 flight.rotate
                # 的原地旋转机制，同一技能实例双名注册（对齐 DiffAgent2 旧版
                # engine._skills）；发现面元数据归 tools/vla/catalog.py。
                disposers.append(engine.skills.register('navigation.vla_rotate', skill))
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
    engine, ports, execution_config, host_config,
    *, search_success_distance_thresh=0.3,
):
    """组合 VLA 领域对象（与 install_flight 同构），注册 navigation.vla_nav。

    - 动作出海用 VLA 家族自己的航点执行（`tools/vla/vla_waypoint.py`；与飞行
      共用同一 FlightPorts 出站口，独立实例：batch 随机起始互不冲突；
      飞行独占由 tool-plane 单活动调用与 engine 动作账务（owner 门 / 代次）
      保证）；
    - waypoint_world 由站端解算随调用下行（「累积点云 + 位姿@帧时戳 +
      VLM bbox」在 station 完成），机上无几何/感知注入；
    - 技能层 slog 出站回调接 engine.runlog.emit；技能层阈值
      search_success_distance_thresh（距离过近判定）经装配层 ~vla/* 注入。
    """
    execution = VlaWaypointExecution(ports, execution_config)
    host = VlaSkillHost(engine, execution, host_config)
    skill = VlaSkill(
        host,
        emit=engine.runlog.emit,
        search_success_distance_thresh=search_success_distance_thresh,
    )
    dispose_skill = engine.skills.register(skill.name, skill)

    def dispose():
        execution.cancel()
        dispose_skill()

    return host, dispose
