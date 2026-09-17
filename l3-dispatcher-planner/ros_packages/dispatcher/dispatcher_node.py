#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""装配六态 dispatcher、飞行端口和 RPC；流程语义归技能与执行领域模块。"""

from __future__ import annotations

import logging
from contextlib import ExitStack
from dataclasses import fields
import threading
from pathlib import Path

from dispatcher.utils.control_plane import ToolControlPlane
from dispatcher.engine import DispatcherEngine
from dispatcher.utils.config import (
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
    return node


def create_flight_runtime(engine):
    """装配直连端口与六技能，返回资源逆操作；不含领域判定。"""
    from dispatcher.tools.flight.ports import FlightConfig
    from dispatcher.ros_adapter.planner_execution_ros import RosFlightPorts
    from dispatcher.execution.composition import install_flight

    config = FlightConfig(**{
        field.name: params_ros.get_private_param("flight/" + field.name, field.default)
        for field in fields(FlightConfig)
    })
    ports = RosFlightPorts(
        drone_id=params_ros.get_private_param("drone_id", 0),
        odometry_topic=params_ros.get_private_param("odometry_topic", "/ekf_quat/ekf_odom"),
    )
    try:
        host, dispose = install_flight(engine, ports, config)
    except Exception:
        ports.close()
        raise
    return host, dispose, ports.close


def start_dispatcher_workers(node):
    """Start task-0 workflow workers and return the non-daemon inference thread."""
    inference_thread = threading.Thread(target=node.run_inference)
    inference_thread.start()
    return inference_thread


def main():
    """Node entry: bootstrap config, compose the tool plane, spin ROS."""
    logging.basicConfig(level=logging.INFO)
    node = RosNode()
    node.init_node("uav_policy_node", anonymous=True)

    config_path = params_ros.get_private_param("config_path", "")

    print("Program starting...")
    engine = create_dispatcher_engine(config_path)

    flight_host, dispose_flight, close_flight_ports = create_flight_runtime(engine)
    with ExitStack() as resources:
        resources.callback(close_flight_ports)
        resources.callback(dispose_flight)
        control_plane = ToolControlPlane(
            engine.tools, log=RosLog(), shutdown=RosShutdown(),
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
    main()
