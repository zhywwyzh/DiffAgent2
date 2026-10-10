#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""装配六态 dispatcher、飞行端口和 RPC；流程语义归技能与执行领域模块。"""

from __future__ import annotations

import logging
import sys
from contextlib import ExitStack
from dataclasses import fields
import threading
from pathlib import Path

from dispatcher.tool_plane.control_plane import ToolControlPlane
from dispatcher.engine import DispatcherEngine
from dispatcher.support.config import (
    CONFIG_KEY_ALIASES,
    UAV_POLICY_DEFAULTS,
    set_defaults,
    load_yaml,
    apply_config,
    merge_config_sections,
    get_nested_config,
    flatten_leaf_params,
    merge_pointcloud_mode_params,
)
from dispatcher.ros_adapter import params_ros
from dispatcher.ros_adapter.clock_ros import RosLog, RosNode, RosShutdown
from dispatcher.ros_adapter.core_channels_ros import (
    RosCoreChannels,
    RosRuntimeClock,
    RosLogSink,
)
from dispatcher.ros_adapter.feedback_ros import FeedbackPlane


def create_dispatcher_engine(config_path: str):
    """Build and configure the task-0 engine without starting process lifecycle."""
    # config 面的日志端口（S4a P2）：组合根注入 RosLog，告警文本不变。
    config_log = RosLog()
    cfg = load_yaml(config_path, log=config_log)

    headless = bool(params_ros.get_private_param("headless", False))
    variant = str(cfg.get("variant", "real")).strip().lower()
    ros_params = {}
    ros_params.update(merge_config_sections(cfg, ["ros.topics", "ros.sync", "ros.publishers", "ros.camera"]))
    if not headless:
        ros_params.update(
            merge_pointcloud_mode_params(get_nested_config(cfg, "ros.pointcloud"), log=config_log)
        )
    ros_params.update(flatten_leaf_params(get_nested_config(cfg, "policy.mission"), log=config_log))
    ros_params["variant"] = variant

    if ros_params:
        params_ros.set_ros_params(ros_params)

    # 端口构造与注入（S3 §4.7）：四类 core 通道的 ROS 实现 + 最小运行端口
    # （节律/关停/日志）在组合根一次构造；~telemetry/*、~log_dir、~headless
    # 与节点名也在此解析为普通值注入，engine/core 零 rospy。
    channels = RosCoreChannels()
    clock = RosRuntimeClock()
    log = RosLogSink()

    perception = None
    if not headless:
        from dispatcher.perception.base_policy import BasePolicyNode
        perception = BasePolicyNode()
    # 原继承对象先装默认值；分离后感知实际使用的同名配置保持该顺序。
    if perception is not None:
        set_defaults(perception, {
            key: value for key, value in UAV_POLICY_DEFAULTS.items() if hasattr(perception, key)
        })
    node = DispatcherEngine(
        headless=headless,
        telemetry_node_name=params_ros.get_node_name(),
        telemetry_level=params_ros.get_private_param("telemetry/level", "info"),
        telemetry_stdout_en=params_ros.get_private_param("telemetry/stdout_en", True),
        log_dir_root=Path(
            params_ros.get_private_param("log_dir", str(Path.home() / ".ros" / "log" / "dispatcher"))
        ),
        channels=channels,
        clock=clock,
        log=log,
        get_frame_snapshot=perception.get_frame_snapshot if perception is not None else lambda: None,
        get_sensor_input_health=perception.get_sensor_input_health if perception is not None else lambda: {},
    )
    sections = (
        ("base_policy", merge_config_sections(cfg, ["base_policy", "policy.base"])),
        ("uav_policy", merge_config_sections(
            cfg,
            [
                "uav_policy",
                "policy.mission",
                "policy.motion",
                "policy.safety",
                "policy.search",
                "policy.planner",
                "policy.overdepth",
            ],
        )),
    )
    for section_name, values in sections:
        for target in (node, perception):
            if target is None:
                continue
            owned_values = {
                key: value for key, value in values.items()
                if hasattr(target, CONFIG_KEY_ALIASES.get(key, key))
                or (target is node and not hasattr(perception, CONFIG_KEY_ALIASES.get(key, key)))
            }
            apply_config(
                target, owned_values, section_name=section_name,
                key_aliases=CONFIG_KEY_ALIASES, log=config_log,
            )
    node.prompt_queue.sync_task_buffers_from_prepare(node.prepare_content)
    # perception 实例一并透出（装配根持有，供需要直连实例的调用方；headless 时为 None）。
    return node, perception


def create_flight_runtime(engine):
    """装配共用 action 会话；资源按逆序释放。"""
    from dispatcher.execution.ports import FlightConfig
    from dispatcher.execution.action_session import ActionSession
    from dispatcher.ros_adapter.planner_action_ros import RosPlannerActionClient
    from dispatcher.ros_adapter.flight_state_ros import RosFlightState
    from dispatcher.ros_adapter.flight_commands_ros import RosFlightCommands
    from dispatcher.execution.composition import install_flight

    local = {"max_rotation_deg", "ground_tolerance", "airborne_height"}
    values = {}
    for field in fields(FlightConfig):
        if field.name in local:
            values[field.name] = params_ros.get_private_param("flight/" + field.name, field.default)
        else:
            old_name = field.name.removesuffix("_s") if field.name in {"state_timeout_s", "action_timeout_s"} else field.name
            marker = object()
            if params_ros.get_private_param("flight/" + old_name, marker) is not marker:
                raise ValueError(f"retired parameter flight/{old_name}: use /planner_execution/{field.name}")
            values[field.name] = params_ros.get_shared_execution_param(field.name, field.default)
    config = FlightConfig(**values)
    resources = ExitStack()
    try:
        states = RosFlightState(params_ros.get_shared_execution_param("odometry_topic"))
        resources.callback(states.close)
        commands = RosFlightCommands()
        resources.callback(commands.close)
        actions = RosPlannerActionClient(config.world_frame)
        resources.callback(actions.close)
        execution = ActionSession(actions, states, commands, config, emit=engine.runlog.emit, can_send=engine.tools.call_is_current)
        resources.callback(execution.close)
        host, dispose = install_flight(engine, execution)
    except Exception:
        resources.close()
        raise
    return host, dispose, resources.close, execution


def create_vla_runtime(engine, execution):
    """装配 VLA 技能（navigation.vla_nav），返回资源逆操作。

    - 技能层 slog 出站回调（emit）在 install_vla 内接 engine.runlog.emit；
    - publish_mode_burst 的出站回调：EGO 直连栈当前没有规划器模式触发通道
      （ros_adapter 各端口均无对应口），此处提供受控空实现——保留脉冲调用
      形态与次数语义，通道接入时替换为真实发布器；装配时留痕一次。
      未接线时 VlaSkillHost.publish_mode_burst 会直接失败（不静默降级），
      空实现仅免除该失败，不引入其他行为漂移。
    - VLA 专属配置经 ~vla/* 装载；高度与完成门共用 /planner_execution/*。
    - waypoint_world 由站端解算随调用下行：机上无几何配置、无感知注入，
      headless 亦可装配。
    """
    from dispatcher.tools.vla.ports import VlaHostConfig
    from dispatcher.execution.composition import install_vla

    def planner_mode_sink_no_channel(mode_value: int) -> None:
        """受控空实现：EGO 直连栈无规划器模式触发通道（见函数头注）。"""
        return None

    engine.runlog.emit(
        "info",
        "vla_planner_mode_channel_absent",
        note="ego stack has no planner mode trigger channel; mode burst is a no-op",
    )
    for retired in ("vla/min_height", "vla/max_height", "vla/search_success_distance_thresh"):
        marker = object()
        if params_ros.get_private_param(retired, marker) is not marker:
            raise ValueError(f"retired parameter {retired}: use /planner_execution height/settle configuration")
    values = {
        field.name: params_ros.get_private_param("vla/" + field.name, field.default)
        for field in fields(VlaHostConfig)
        if field.name != "publish_planner_mode"
    }
    _, dispose = install_vla(
        engine, execution,
        VlaHostConfig(publish_planner_mode=planner_mode_sink_no_channel, **values),
    )
    return dispose


def create_tracking_runtime(engine, execution):
    from dispatcher.tools.track.ports import TrackConfig
    from dispatcher.tools.track.track_skill import TrackSkill
    from dispatcher.execution.skill_host import TrackHost, TrackingFrames
    from dispatcher.perception.tracking_frames import FrameStore
    from dispatcher.ros_adapter.tracking_frames_ros import TrackingFramesRos
    from dispatcher.ros_adapter.tracking_observation_ros import TrackingObservationRos
    resources = ExitStack()
    try:
        config = TrackConfig(**{f.name: params_ros.get_private_param('track/'+f.name, f.default) for f in fields(TrackConfig)})
        store = FrameStore(max_age=config.seed_max_age_s)
        frames = TrackingFramesRos(store)
        resources.callback(frames.close)
        output = TrackingObservationRos()
        resources.callback(output.close)
        host = TrackHost(engine, execution, config, TrackingFrames(store, frames.now), output,
            params_ros.get_private_param('track/camera_rotation'),
            params_ros.get_private_param('track/camera_translation'))
        skill = TrackSkill(host)
        resources.callback(skill.close)
        resources.callback(engine.skills.register(skill.name, skill))
    except Exception:
        resources.close()
        raise
    return resources.close


def start_dispatcher_workers(node):
    """Start task-0 workflow workers and return the non-daemon inference thread."""
    inference_thread = threading.Thread(target=node.run_inference)
    inference_thread.start()
    return inference_thread


def main(*, tracking=False):
    """Node entry: bootstrap config, compose the tool plane, spin ROS."""
    logging.basicConfig(level=logging.INFO)
    node = RosNode()
    node.init_node("uav_policy_node", anonymous=True)

    config_path = params_ros.get_private_param("config_path", "")

    print("Program starting...")
    engine, _perception = create_dispatcher_engine(config_path)

    flight_host, dispose_flight, close_flight_ports, execution = (
        create_flight_runtime(engine)
    )
    with ExitStack() as resources:
        resources.callback(close_flight_ports)
        resources.callback(dispose_flight)
        # 参数拒绝或 VLA 装配失败时也释放已创建的飞行资源。
        dispose_vla = create_vla_runtime(engine, execution)
        resources.callback(dispose_vla)
        registry = None
        if tracking:
            from dispatcher.tool_plane.registry import ToolRegistry
            from dispatcher.tools.flight.catalog import flight_specs
            from dispatcher.tools.vla.catalog import vla_specs
            from dispatcher.tools.track.catalog import track_specs
            resources.callback(create_tracking_runtime(engine, execution))
            registry = ToolRegistry(tuple(flight_specs()) + tuple(vla_specs()) + tuple(track_specs()))
        control_plane = ToolControlPlane(
            engine.tools, registry=registry, interrupt=execution.request_stop, interrupt_tools={"basic_flight.emergency_stop"}, log=RosLog(), shutdown=RosShutdown(),
            feedback_factory=lambda middleware: FeedbackPlane(middleware, on_reset=flight_host.reset_session),
        )
        resources.callback(control_plane.close)
        control_plane.start()
        inference_thread = start_dispatcher_workers(engine)
        try:
            node.spin()
        finally:
            engine.clock.request_shutdown("dispatcher closing")
            inference_thread.join()


if __name__ == "__main__":
    main(tracking="--tracking-profile" in sys.argv[1:])
