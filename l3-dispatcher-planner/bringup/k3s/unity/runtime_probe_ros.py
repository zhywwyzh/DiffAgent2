#!/usr/bin/env python3
# Entity: drone-container
# Invoked: station-host-sim.py and Kubernetes readiness probes
"""只读运行状态探针；不申请租约、不发送运动或重置信号。"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import runpy
from pathlib import Path
import socket
import sys
import threading
import time
import xmlrpc.client


def session():
    import zenoh
    config = zenoh.Config()
    config.insert_json5("mode", '"client"')
    config.insert_json5("connect/endpoints", json.dumps([os.environ["ZENOH_ROUTER"]]))
    config.insert_json5("scouting/multicast/enabled", "false")
    return zenoh.open(config)


def claim_status(s):
    key = "lx/" + os.environ["LX_STACK_ID"] + "/rpc"
    replies = s.get(key, payload=json.dumps({"method": "connection.status", "params": {}}).encode(), timeout=3.0)
    results = []
    for reply in replies:
        if reply.ok is not None:
            body = json.loads(reply.ok.payload.to_bytes())
            if body.get("type") == "rpc_result":
                results.append(body["result"])
    if len(results) != 1:
        raise RuntimeError("connection.status 无唯一有效应答")
    return results[0]


def planes():
    s = session()
    try:
        key = "lx/" + os.environ["LX_STACK_ID"] + "/presence/*/*"
        tokens = [str(reply.ok.key_expr) for reply in s.liveliness().get(key, timeout=3.0) if reply.ok is not None]
        result = {plane: [token for token in tokens if "/presence/" + plane + "/" in token]
                  for plane in ("task", "telemetry", "logs")}
        try:
            result.update(claim=claim_status(s))
            result["ok"] = len(result["task"]) == 1
        except RuntimeError as error:
            result.update(ok=False, claim={"reachable": False, "reason": str(error)})
        return result
    finally:
        s.close()


def ros_snapshot(action):
    import rospy
    from nav_msgs.msg import Odometry
    from sensor_msgs.msg import CameraInfo, Image, PointCloud2

    rospy.init_node("sim_runtime_probe", anonymous=True, disable_signals=True)
    seen = {}
    lock = threading.Lock()
    topics = {"odom": ("/ekf_quat/ekf_odom", Odometry)}
    if action == "sensors":
        topics.update(camera=("/camera/color/image_raw", Image),
                      depth=("/camera/aligned_depth_to_color/image_raw", Image),
                      cloud=("/cloud_registered", PointCloud2), info=("/camera/color/camera_info", CameraInfo))
    if action in ("planner", "shutdown"):
        from quadrotor_msgs.msg import ExecutionState
        topics["execution"] = ("/planner/execution_state", ExecutionState)

    def receive(key, msg):
        stamp = msg.header.stamp.to_sec()
        now = time.time()
        valid = math.isfinite(stamp) and -0.1 <= now - stamp <= 1.5
        if key == "odom":
            p, q, v = msg.pose.pose.position, msg.pose.pose.orientation, msg.twist.twist.linear
            valid = valid and msg.header.frame_id == "world" and all(math.isfinite(value) for value in
                (p.x, p.y, p.z, q.x, q.y, q.z, q.w, v.x, v.y, v.z))
        elif key == "cloud":
            valid = valid and msg.header.frame_id == "world" and msg.width * msg.height > 0
        elif key in ("camera", "depth"):
            valid = valid and msg.width > 0 and msg.height > 0 and bool(msg.data)
        elif key == "info":
            # 标定允许是 latched 静态消息；数据流本身仍须连续且新鲜。
            valid = msg.width > 0 and msg.height > 0 and all(math.isfinite(value) for value in msg.K) and msg.K[0] > 0 and msg.K[4] > 0
        with lock:
            previous = seen.get(key)
            increasing = key == "info" or (previous is not None and stamp > previous["stamp"])
            seen[key] = {"stamp": stamp, "received": time.monotonic(), "valid": bool(valid),
                         "increasing": increasing, "message": msg}

    subscriptions = [rospy.Subscriber(topic, message_type, lambda msg, key=key: receive(key, msg), queue_size=1)
                     for key, (topic, message_type) in topics.items()]
    deadline = time.monotonic() + 4
    try:
        while time.monotonic() < deadline:
            with lock:
                if all(key in seen and seen[key]["valid"] and seen[key]["increasing"] for key in topics):
                    break
            time.sleep(0.05)
        with lock:
            result = {key: {"received": key in seen, "valid": seen.get(key, {}).get("valid", False),
                            "increasing": seen.get(key, {}).get("increasing", False),
                            "age_s": round(time.monotonic() - seen[key]["received"], 3) if key in seen else None}
                      for key in topics}
            ok = all(value["valid"] and value["increasing"] and (key == "info" or value["age_s"] < 1.5)
                     for key, value in result.items())
            state = seen.get("execution", {}).get("message")
        answer = {"ok": ok, "inputs": result}
        if state is not None:
            answer["execution"] = {key: getattr(state, key) for key in
                                   ("ready", "stop_confirmed", "motion_enabled", "phase", "boot_id")}
            answer["ok"] = ok and bool(state.ready)
        if action in ("planner", "shutdown"):
            import rosgraph
            publishers, subscribers, _ = rosgraph.Master(rospy.get_name()).getSystemState()
            subscribers = dict(subscribers)
            answer["action_server"] = all(subscribers.get("/planner/execute_waypoints/" + suffix)
                                           for suffix in ("cancel", "goal"))
            # Action 的订阅端与 status 生产者共同确认，不以任意同名 topic 作为服务端。
            publishers = dict(publishers)
            answer["action_server"] = answer["action_server"] and bool(publishers.get("/planner/execute_waypoints/status"))
            answer["ok"] = answer["ok"] and answer["action_server"]
        if action == "shutdown":
            s = session()
            try:
                answer["claim"] = claim_status(s)
            finally:
                s.close()
            answer["safe"] = bool(ok and state is not None and state.stop_confirmed and not state.motion_enabled)
        return answer
    finally:
        for subscription in subscriptions:
            subscription.unregister()
        rospy.signal_shutdown("只读探针完成")


def main(action):
    socket.setdefaulttimeout(5)
    if action == "dependencies":
        for name in ("rospy", "actionlib", "cv2", "zenoh", "numpy", "yaml", "requests", "telemetry_bridge.encoding",
                     "dispatcher.tool_plane.zenoh_transport", "dispatcher.execution.composition",
                     "dispatcher.ros_adapter.planner_execution_ros"):
            try:
                importlib.import_module(name)
            except Exception as error:
                raise RuntimeError(f"Python {sys.version.split()[0]} 导入 {name} 失败: {error}") from error
        from quadrotor_msgs.msg import ExecuteWaypointsAction, ExecutionState
        # 导入真实入口但不调用 main，不创建节点、租约、订阅或运动请求。
        try:
            runpy.run_path("/source/l3/ros_packages/dispatcher/dispatcher_node.py", run_name="dispatcher_dependency_probe")
        except Exception as error:
            raise RuntimeError(f"Python {sys.version.split()[0]} 导入 dispatcher_node.py 失败: {error}") from error
        return {"ok": True, "python": sys.version.split()[0]}
    if action == "master":
        proxy = xmlrpc.client.ServerProxy(os.environ["ROS_MASTER_URI"])
        code, _, pid = proxy.getPid("/sim_runtime_probe")
        return {"ok": code == 1, "pid": pid}
    if action in ("planes", "task"):
        return planes()
    if action == "logs":
        s = session()
        received = threading.Event()
        latest = {}
        def receive(sample):
            try:
                record = json.loads(sample.payload.to_bytes())
                if isinstance(record, dict) and ("message" in record or "log" in record):
                    latest.update(record)
                    received.set()
            except (ValueError, UnicodeError):
                return
        subscriber = s.declare_subscriber("lx/" + os.environ["LX_STACK_ID"] + "/logs", receive)
        try:
            received.wait(12)
            return {"ok": received.is_set(), "received": received.is_set(), "source": latest.get("kubernetes")}
        finally:
            subscriber.undeclare()
            s.close()
    if action == "telemetry":
        path = Path("/tmp/diffagent-telemetry.json")
        body = json.loads(path.read_text())
        age = time.time() - body["epoch"]
        body["ok"] = age < 5 and all(value is not None and value < 5 for value in body["sent_age_s"].values())
        return body
    return ros_snapshot(action)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("dependencies", "master", "odom", "sensors", "planner", "shutdown", "planes", "task", "telemetry", "logs"))
    args = parser.parse_args()
    try:
        result = main(args.action)
    except Exception as error:
        result = {"ok": False, "reason": str(error)}
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result.get("ok") else 1)
