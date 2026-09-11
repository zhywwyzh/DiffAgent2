#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Engine config loading: YAML extends-chain, ROS private-param application.

Single consumer: DispatcherEngine (`apply_config` boot path). The former
`utils/policy` vocabulary helpers are removed — nothing references them.
"""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any, Dict, Iterable

import rospy
import yaml


def merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """递归合并字典，override 中字段优先。"""
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_yaml(path: str, _seen: set = None, base_dir: str = None) -> Dict[str, Any]:
    """加载 YAML 配置并处理 extends 继承链。"""
    if not path:
        return {}
    if not os.path.isabs(path):
        # 当前文件位于 dispatcher，下探二级回到 catkin 包根
        root_dir = base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root_dir, path)
    if not os.path.exists(path):
        rospy.logwarn(f"config_path not found: {path}")
        return {}
    if _seen is None:
        _seen = set()
    if path in _seen:
        raise ValueError(f"Cyclic extends detected for config: {path}")
    _seen.add(path)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("YAML root must be a dict")
    base_ref = data.pop("extends", None)
    if base_ref:
        if not os.path.isabs(base_ref):
            base_ref = os.path.join(os.path.dirname(path), base_ref)
        base_data = load_yaml(base_ref, _seen=_seen, base_dir=base_dir)
        data = merge_dicts(base_data, data)
    return data


def set_ros_params(params: Dict[str, Any]) -> None:
    """把字典写入当前节点私有参数空间(~key)。"""
    for key, value in params.items():
        rospy.set_param(f"~{key}", value)


def flatten_leaf_params(cfg: Dict[str, Any], *, _path: str = "") -> Dict[str, Any]:
    """递归展开结构化配置，使用叶子字段名作为最终参数名。

    该函数用于把 YAML 中的功能分组配置转换为现有 ROS 私有参数格式。
    例如 tracking.kalman.tracking_kalman_enabled 会展开为
    ~tracking_kalman_enabled，避免业务代码到处改 rospy.get_param 名称。
    """
    if not isinstance(cfg, dict):
        return {}

    flat: Dict[str, Any] = {}
    for key, value in cfg.items():
        key = str(key)
        next_path = key if not _path else f"{_path}.{key}"
        if isinstance(value, dict):
            nested = flatten_leaf_params(value, _path=next_path)
            for leaf_key, leaf_value in nested.items():
                if leaf_key in flat:
                    rospy.logwarn(
                        "Duplicate flattened config key %s from %s overrides previous value.",
                        leaf_key,
                        next_path,
                    )
                flat[leaf_key] = leaf_value
            continue
        if key in flat:
            rospy.logwarn(
                "Duplicate flattened config key %s from %s overrides previous value.",
                key,
                next_path,
            )
        flat[key] = value
    return flat


def merge_pointcloud_mode_params(pointcloud_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """合并 pointcloud.common 与当前 mode 专属参数。

    新配置中 ros.pointcloud.mode 决定 waypoint 几何源。只加载 common 和
    当前模式参数，避免 cloud/depth/mix 的互斥参数同时进入运行时。
    """
    if not isinstance(pointcloud_cfg, dict):
        return {}

    mode = str(pointcloud_cfg.get("mode", "")).strip().lower()
    if not mode:
        raise ValueError("ros.pointcloud.mode is required")
    if mode not in {"depth", "cloud", "mix"}:
        raise ValueError(f"unsupported ros.pointcloud.mode: {mode}")

    common = pointcloud_cfg.get("common", {})
    mode_cfg = pointcloud_cfg.get(mode, {})
    if not isinstance(common, dict):
        raise ValueError("ros.pointcloud.common must be a dict")
    if not isinstance(mode_cfg, dict):
        raise ValueError(f"ros.pointcloud.{mode} must be a dict")

    params = merge_dicts(deepcopy(common), deepcopy(mode_cfg))
    params["depth_source"] = str(params.get("depth_source", mode)).strip().lower() or mode
    return flatten_leaf_params(params)


def set_defaults(obj: Any, defaults: Dict[str, Any]) -> None:
    """将默认配置深拷贝后写入对象属性。"""
    for key, value in defaults.items():
        setattr(obj, key, deepcopy(value))


def apply_config(
    obj: Any,
    cfg: Dict[str, Any],
    section_name: str = "config",
    key_aliases: Dict[str, str] = None,
) -> None:
    """将配置块应用到对象，并处理字段别名映射。"""
    key_aliases = key_aliases or {}
    for key, value in cfg.items():
        target_key = key
        if not hasattr(obj, target_key):
            alias = key_aliases.get(key)
            if alias and hasattr(obj, alias):
                target_key = alias
            else:
                rospy.logwarn(f"Unknown {section_name} key skipped: {key}")
                continue
        if isinstance(value, dict):
            cur = getattr(obj, target_key, None)
            if isinstance(cur, dict):
                cur.update(value)
            else:
                setattr(obj, target_key, value)
        else:
            setattr(obj, target_key, value)


def get_nested_config(cfg: Dict[str, Any], path: str) -> Dict[str, Any]:
    """按 `a.b.c` 路径读取嵌套配置块，缺失时返回空字典。"""
    if not isinstance(cfg, dict) or not path:
        return {}
    cur = cfg
    for part in str(path).split("."):
        if not isinstance(cur, dict):
            return {}
        cur = cur.get(part, {})
    return cur if isinstance(cur, dict) else {}


def merge_config_sections(cfg: Dict[str, Any], section_paths: Iterable[str]) -> Dict[str, Any]:
    """按顺序合并多个配置块，后出现的块覆盖前面的同名字段。"""
    merged: Dict[str, Any] = {}
    for path in section_paths:
        block = get_nested_config(cfg, path)
        if block:
            merged = merge_dicts(merged, deepcopy(block))
    return merged


# 配置字段别名：YAML 键名 → 节点属性名。供 apply_config 在字段名不一致时回退。
CONFIG_KEY_ALIASES = {
    "min_action_wait": "_min_action_wait",
}


# 节点默认参数（可在 YAML 或 ROS 参数中覆盖）。
# 由 set_defaults 深拷贝写入 DispatcherEngine 属性，模块级可变值（如列表）
# 不会在实例间共享状态。
UAV_POLICY_DEFAULTS = {
    "prepare_content": [],  # 预置任务列表
    "nav_tools": "bbox",  # 导航感知工具：bbox / segment
    "segment_nav_enabled": False,  # 是否启用 segment(mask) 导航感知；false 时强制 bbox
    "search_thinking_enabled": False,  # 偏航搜索耗尽后是否进入多图 thinking 路径；false 时直接结束任务
    "inference_timeout": 5.0,  # 感知/推理超时（秒）
    "task_generation_guard_enabled": True,  # 是否丢弃 prompt 覆盖/急停前返回的旧阻塞推理结果
    "_min_action_wait": 0.2,  # 动作最小等待时间（秒）
    "return_publish_mode": "waypoint_nav",  # return 发布模式：waypoint_nav / goal
    "return_start_timeout_s": 5.0,  # return 下发后等待下游进入 EXECING 的超时（秒），超时视为规划失败/不可达
    "return_finish_timeout_s": 5.0,  # return 到 FSM FINISH 后等待 action result 确认的超时（秒）
    "sleep_for_turn": 0.5,  # 搜索转向后等待稳定时间（秒）
    "action_reach_threshold": 0.0,  # 动作到达判定阈值（米，当前未启用）
    "search_success_distance_thresh": 0.3,  # 近距离视为到达阈值（米）
    "geometry_agree_safe_dis_radius_m": 0.8,  # 几何结果一致或仅单源有效时的安全距离（米）
    "geometry_mismatch_safe_dis_radius_m": 1.2,  # 几何结果不一致时的安全距离（米）
    "if_safe_mode": True,  # 是否启用安全模式开关
    "max_yaw_search": 20,  # 每层最大偏航搜索步数
    "search_rot_yaw": 40,  # 单次搜索旋转角（度）
    "max_z_search": 0,  # 最大升高搜索层数
    "search_pos_z": 0.6,  # 每次升高搜索高度增量（米）
    "d_side": 0.7,  # 侧向偏移基准距离（米）
    "d_forward": 0.0,  # 前向附加偏移距离（米）
    "stable_height": 0.4,  # 稳定飞行高度（米）
    "min_height": 0.0,  # 最低允许飞行高度（米）
    "max_height": 1.8,  # 最高允许飞行高度（米）
    "is_stable": False,  # 是否强制保持 stable_height
    "behind_dist": 2.0,  # “后方”目标点偏移距离（米）
    "bypass_dist": 2.0,  # 绕行任务前向补偿距离（米）
    "reacquire_interval": 1.0,  # 远/稀疏目标推进后重启 VLA 搜索的间隔（秒，不等到达）
    "partial_bbox_recenter_enabled": False,  # bbox 触碰左右图像边缘时是否先转向居中再重感知
    "partial_bbox_edge_margin_px": 12,  # 判定 bbox 接近左右边缘的像素余量
    "partial_bbox_max_attempts": 2,  # 单条 search prompt 最大居中重试次数
    "partial_bbox_max_yaw_step_deg": 30.0,  # 单次 bbox 居中转向的最大角度（度）
    "llm_stamp_match_tolerance": 0.3,  # LLM 时间戳对齐容忍误差（秒）
    "planner_mode_topic": "/uav_planner/trigger",  # 规划器模式切换话题
    "planner_mode_repeat": 3,  # 规划器模式切换重复发送次数
    "planner_mode_interval": 0.03,  # 模式切换重复发送间隔（秒）
    "planner_ego_mode_value": 1,  # ego 模式枚举值
    "if_handle_yaw": True,  # 是否允许底层 ego planner 处理 yaw；tracking 会临时关闭
    "start_yaw_deg": 0.0,  # 起始偏航角度（度）
    # SCENE_NAV：场景图 + 按 object id 导航（Instruction 下发 / 订阅 scene graph 与 FSM）
    "scene_nav_request_instruction_type": 11,  # rostopic 测试用 instruction_type
    "scene_nav_to_drone_ids": [1],  # Instruction.to_drone_ids
    "scene_graph_json_topic": "/scene_graph/json_text",
    "planner_fsm_state_topic": "/planner/fsm_state",
    "scene_nav_json_wait_timeout_s": 3.0,
    "scene_nav_trigger_timeout_s": 5.0,  # FSM FINISH 后等待 action result 确认的超时（秒）；接通 real.yaml policy.scene_nav 同名配置
}
