"""组合飞行领域对象；ROS 端口由调用方注入。"""
from dispatcher.execution.skill_host import DispatcherFlightHost
from dispatcher.execution.waypoint_execution import WaypointExecution
from dispatcher.services.flight_session import FlightSession
from dispatcher.tools.flight.takeoff_skill import TakeoffSkill
from dispatcher.tools.flight.land_skill import LandSkill
from dispatcher.tools.flight.translate_skill import TranslateSkill
from dispatcher.tools.flight.rotate_skill import RotateSkill
from dispatcher.tools.flight.return_skill import ReturnSkill
from dispatcher.tools.flight.emergency_stop_skill import EmergencyStopSkill


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
