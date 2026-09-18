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
    # perception（几何原语源）一并透出：VLA 装配（create_vla_runtime）经
    # VlaSkillHost 组合注入；headless 时为 None。
    return node, perception


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
    # ports/config 一并返回：VLA 与飞行共享同一出站口（flight-exclusive），
    # 执行配置（state_timeout/action_timeout/高度界）同源。
    return host, dispose, ports.close, ports, config


def create_vla_runtime(engine, perception, ports, execution_config):
    """装配 VLA 技能（navigation.vla_nav），返回资源逆操作。

    - 技能层 slog 出站回调（emit）在 install_vla 内接 engine.runlog.emit；
    - publish_mode_burst 的出站回调：EGO 直连栈当前没有规划器模式触发通道
      （旧链 planner_mode_topic=/uav_planner/trigger 的 Int32 发布器在新栈
      ros_adapter 各端口均无对应口），此处提供受控空实现——保留脉冲调用
      形态与次数语义，通道接入时替换为真实发布器；装配时留痕一次。
      未接线时 VlaSkillHost.publish_mode_burst 会直接失败（不静默降级），
      空实现仅免除该失败，不引入其他行为漂移。
    - 宿主只读配置经 ROS 私有参数 ~vla/* 覆盖（同 ~flight/* 机制），
      默认值与旧库 config 逐项核对一致（VlaHostConfig）。
    - VLA 几何/阈值配置同样经 ~vla/* 覆盖（默认值=旧库 config.py
      UAV_POLICY_DEFAULTS + base_policy 默认，逐项核对一致）：技能层两阈值
      search_success_distance_thresh(0.3)/far_push_distance_m(5.0) 与
      VlaGeometryConfig 全字段（safe_dis_radius_m 0.4 / if_safe_dis True /
      behind_dist 2.0 / d_side 0.7 / d_forward 0.0 / depth_source "cloud" /
      is_stable False / stable_height 0.4 / geometry_agree_safe_dis_radius_m
      0.8）。~vla/* 为 VLA 几何/阈值的唯一权威；perception 侧同名属性属
      perception 自有（base_policy 段配置），VLA 几何不依赖。
    """
    from dispatcher.tools.vla.geometry import VlaGeometryConfig
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
    values = {
        field.name: params_ros.get_private_param("vla/" + field.name, field.default)
        for field in fields(VlaHostConfig)
        if field.name != "publish_planner_mode"
    }
    geometry_values = {
        field.name: params_ros.get_private_param("vla/" + field.name, field.default)
        for field in fields(VlaGeometryConfig)
    }
    _, dispose = install_vla(
        engine, ports, execution_config,
        VlaHostConfig(publish_planner_mode=planner_mode_sink_no_channel, **values),
        perception,
        geometry_config=VlaGeometryConfig(**geometry_values),
        search_success_distance_thresh=params_ros.get_private_param(
            "vla/search_success_distance_thresh", 0.3),
        far_push_distance_m=params_ros.get_private_param(
            "vla/far_push_distance_m", 5.0),
    )
    return dispose


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
    engine, perception = create_dispatcher_engine(config_path)

    flight_host, dispose_flight, close_flight_ports, flight_ports, flight_config = (
        create_flight_runtime(engine)
    )
    dispose_vla = None
    if perception is not None:
        # VLA 需要感知几何原语源；headless（无传感器）不装配——
        # navigation.vla_nav 调用经 core 未注册路径 fail-closed
        # （tool_not_registered 终态），不静默降级。
        dispose_vla = create_vla_runtime(engine, perception, flight_ports, flight_config)
    with ExitStack() as resources:
        resources.callback(close_flight_ports)
        if dispose_vla is not None:
            resources.callback(dispose_vla)
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
