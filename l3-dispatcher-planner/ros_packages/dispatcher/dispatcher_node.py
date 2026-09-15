#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dispatcher composition root (agent-station-tools.spec.md §5).

Wires the task-0 engine, the tool runtime, and the zenoh transport into one
process and owns process lifecycle only: node init, config bootstrap, worker
threads, and ROS spin. It contains NO task-id dispatch, NO decision workflow, and
NO VLM code — executable behavior lives behind the ToolRegistry adapters
(dispatcher/tools/) and the DispatcherEngine (dispatcher/engine.py).

S3 起（design-dispatcher-engine-relocate-non-core.md §4.8）：启动装配函数
create_dispatcher_engine / start_dispatcher_workers 自 engine.py 迁入本文件，
并在此构造四类 core 通道端口与最小运行端口（§4.7 组合根注入）——engine 与
dispatcher/core/ 因此零 rospy（G7/G8）。
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from dispatcher.utils.control_plane import ToolControlPlane
from dispatcher.engine import DispatcherEngine
from dispatcher.utils.config import (
    CONFIG_KEY_ALIASES,
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

    variant = str(cfg.get("variant", "real")).strip().lower()
    ros_params = {}
    ros_params.update(merge_config_sections(cfg, ["ros.topics", "ros.sync", "ros.publishers", "ros.camera"]))
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

    node = DispatcherEngine(
        headless=bool(params_ros.get_private_param("headless", False)),
        telemetry_node_name=params_ros.get_node_name(),
        telemetry_level=params_ros.get_private_param("telemetry/level", "info"),
        telemetry_stdout_en=params_ros.get_private_param("telemetry/stdout_en", True),
        log_dir_root=Path(
            params_ros.get_private_param("log_dir", str(Path.home() / ".ros" / "log" / "dispatcher"))
        ),
        channels=channels,
        clock=clock,
        log=log,
    )
    apply_config(
        node,
        merge_config_sections(cfg, ["base_policy", "policy.base"]),
        section_name="base_policy",
        key_aliases=CONFIG_KEY_ALIASES,
        log=config_log,
    )
    apply_config(
        node,
        merge_config_sections(
            cfg,
            [
                "uav_policy",
                "policy.mission",
                "policy.motion",
                "policy.safety",
                "policy.search",
                "policy.planner",
                "policy.scene_nav",
                "policy.overdepth",
            ],
        ),
        section_name="uav_policy",
        key_aliases=CONFIG_KEY_ALIASES,
        log=config_log,
    )
    node.sync_task_buffers_from_prepare()
    return node


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

    # host 由 engine 换 engine.tools（S3 §4.8）：ToolControlPlane /
    # ToolExecutor 的 duck-typed 三缝宿主为 core/workflow.py 的
    # ToolWorkflowHost（bind_tool_middleware / start_tool_workflow /
    # cancel_tool_call），FakeHost 契约不变。
    # 端口注入（S4a P1/P3/P4）：日志/关停/反馈面在此装配，
    # 经 control_plane 透传给 middleware；未注入不会发生（组合根是唯一生产装配点）。
    control_plane = ToolControlPlane(
        engine.tools,
        log=RosLog(),
        shutdown=RosShutdown(),
        feedback_factory=FeedbackPlane,
    )
    control_plane.start()

    inference_thread = start_dispatcher_workers(engine)

    # Main thread runs the ROS1 spin; workers are daemon threads.
    node.spin()

    inference_thread.join()
    control_plane.close()


if __name__ == "__main__":
    main()
