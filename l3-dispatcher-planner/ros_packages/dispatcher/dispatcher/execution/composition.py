"""组合飞行 / VLA 领域对象；ROS 端口由调用方注入。"""
from dispatcher.execution.skill_host import DispatcherFlightHost, VlaSkillHost
from dispatcher.tools.flight.session import FlightSession
from dispatcher.tools.flight.takeoff_skill import TakeoffSkill
from dispatcher.tools.flight.land_skill import LandSkill
from dispatcher.tools.flight.translate_skill import TranslateSkill
from dispatcher.tools.flight.rotate_skill import RotateSkill
from dispatcher.tools.flight.return_skill import ReturnSkill
from dispatcher.tools.flight.emergency_stop_skill import EmergencyStopSkill
from dispatcher.tools.vla.vla_skill import VlaSkill


def install_flight(engine, execution):
    host = DispatcherFlightHost(engine, execution, FlightSession(execution.config))
    engine.lifecycle_tick = execution.tick
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
        for inverse in reversed(disposers):
            inverse()

    return host, dispose


def install_vla(engine, execution, host_config):
    """VLA 和飞行共用动作会话，技能拥有各自多腿流程。"""
    host = VlaSkillHost(engine, execution, host_config)
    skill = VlaSkill(
        host,
        emit=engine.runlog.emit,
    )
    dispose_skill = engine.skills.register(skill.name, skill)

    def dispose():
        dispose_skill()

    return host, dispose
