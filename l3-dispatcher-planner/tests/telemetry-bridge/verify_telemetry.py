#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""telemetry-bridge verification (agent-station-channels.spec.md v8): REAL
ROS inputs -> zenoh telemetry plane outputs.

Run INSIDE the l3 amd64 container (ROS + devel sourced). Starts roscore +
the real drone_bridge.py (LX_STACK_ID=telemetry-test), publishes canonical
ROS topics locally, and asserts every telemetry channel on the zenoh
subscriber side: meta / drone_status / scenegraph / camera / cloud /
grid_map / trajectory. No ground station, no router dependency beyond the
topology bootstrap endpoint (keys are unique per run).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import zenoh

WORKDIR = Path(os.environ.get("BENCH_WORKDIR", "/tmp/telemetry-bridge"))
WORKDIR.mkdir(parents=True, exist_ok=True)

ROUTER = os.environ.get("ZENOH_ROUTER", "tcp/public_zenohd_router:7447")
STACK_ID = f"telemetry-test-{uuid.uuid4().hex[:6]}"
PREFIX = f"lx/{STACK_ID}/telemetry"

FAILURES: list[str] = []


def sh(cmd: list[str], **kw) -> subprocess.Popen:
    env = dict(os.environ)
    master_port = os.environ.get("ROS_MASTER_PORT", "29511")
    env.setdefault("ROS_MASTER_URI", f"http://127.0.0.1:{master_port}")
    env.setdefault("ROS_HOSTNAME", "127.0.0.1")
    env.update(kw.pop("extra_env", {}))
    return subprocess.Popen(
        cmd,
        env=env,
        stdout=open(WORKDIR / (kw.pop("log_name", "node.log")), "w"),
        stderr=subprocess.STDOUT,
    )


def wait_roscore(timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = subprocess.run(
            ["rosnode", "list"],
            capture_output=True,
            env={**os.environ, "ROS_MASTER_URI": os.environ.get("ROS_MASTER_URI", "")},
        )
        if r.returncode == 0:
            return True
        time.sleep(0.5)
    return False


def wait_param_server(timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = subprocess.run(["rosparam", "list"], capture_output=True)
        if r.returncode == 0:
            return True
        time.sleep(0.5)
    return False


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {name}{(' — ' + detail) if detail and not cond else ''}")
    if not cond:
        FAILURES.append(name)


def main() -> int:
    master_port = os.environ.get("ROS_MASTER_PORT", "29511")
    os.environ.setdefault("ROS_MASTER_URI", f"http://127.0.0.1:{master_port}")

    procs: list[subprocess.Popen] = []
    procs.append(sh(["roscore", "-p", master_port], log_name="roscore.log"))
    assert wait_roscore(), "roscore did not come up"

    import rospy
    from geometry_msgs.msg import PoseStamped
    from mavros_msgs.msg import State as StateMsg
    from nav_msgs.msg import Odometry, Path
    from quadrotor_msgs.msg import PiecewisePolynomial
    from sensor_msgs.msg import BatteryState, CompressedImage, PointCloud2
    from sensor_msgs.point_cloud2 import create_cloud_xyz32
    from std_msgs.msg import Header, String

    rospy.init_node("telemetry_verify", anonymous=True, disable_signals=True)

    os.environ["LX_STACK_ID"] = STACK_ID
    os.environ["ZENOH_ROUTER"] = ROUTER
    node = sh(
        [
            "python3",
            "/workspace/src/ros_packages/bridges/scripts/drone_bridge.py",
            "_odom_topic:=/telemetry_test/odom",
            "_scenegraph_topic:=/telemetry_test/sg",
            "_camera_topic:=/telemetry_test/image_raw/compressed",
            "_battery_topic:=/telemetry_test/battery",
            "_state_topic:=/telemetry_test/state",
            "_cloud_topic:=/telemetry_test/cloud",
            "_grid_map_topic:=/telemetry_test/grid_map",
            "_search_path_topic:=/telemetry_test/search_path",
            "_optimized_traj_topic:=/telemetry_test/optimized_traj",
            "_cloud_max_hz:=5",
        ],
        extra_env={"LX_STACK_ID": STACK_ID, "ZENOH_ROUTER": ROUTER},
        log_name="drone_bridge.log",
    )
    procs.append(node)
    assert wait_param_server(), "param server unreachable"

    # -- zenoh subscriber (its OWN session, like the station) ---------------
    received: dict[str, list] = {}

    def on_sample(sample):
        key = str(sample.key_expr).rsplit("/", 1)[-1]
        received.setdefault(key, []).append(bytes(sample.payload))

    conf = zenoh.Config()
    conf.insert_json5("mode", '"client"')
    conf.insert_json5("connect/endpoints", json.dumps([ROUTER]))
    conf.insert_json5("scouting/multicast/enabled", "false")
    session = zenoh.open(conf)
    _ = session.declare_subscriber(f"{PREFIX}/**", on_sample)

    # -- publish canonical ROS topics ---------------------------------------
    pub_odom = rospy.Publisher("/telemetry_test/odom", Odometry, queue_size=1)
    pub_sg = rospy.Publisher("/telemetry_test/sg", String, queue_size=1)
    pub_cam = rospy.Publisher("/telemetry_test/image_raw/compressed", CompressedImage, queue_size=1)
    pub_cloud = rospy.Publisher("/telemetry_test/cloud", PointCloud2, queue_size=1)
    pub_grid = rospy.Publisher("/telemetry_test/grid_map", PointCloud2, queue_size=1)
    pub_path = rospy.Publisher("/telemetry_test/search_path", Path, queue_size=1)
    pub_traj = rospy.Publisher("/telemetry_test/optimized_traj", PiecewisePolynomial, queue_size=1)
    pub_bat = rospy.Publisher("/telemetry_test/battery", BatteryState, queue_size=1)
    pub_state = rospy.Publisher("/telemetry_test/state", StateMsg, queue_size=1)

    time.sleep(1.0)  # let subscriber + pubs connect

    # -- zenoh: assert channels ------------------------------------------------
    SCENEGRAPH_TEXT = json.dumps({"objects": [{"id": 1, "label": "test_object"}]})
    JPEG_BYTES = b"\xff\xd8\xff\xe0" + bytes(range(256))  # SOI + payload (passthrough)
    CLOUD_PTS = [(float(i), float(i) * 2.0, float(i) * 3.0) for i in range(10)]
    GRID_PTS = [(float(i) + 100.0, 1.0, 2.0) for i in range(4)]
    TRAJ_COEFFS = [float(i + 1) for i in range(12)]  # n_seg=1, order=3

    pub_odom.publish(_make_odom(rospy, 1.0, 2.0, 0.9))
    pub_sg.publish(String(data=SCENEGRAPH_TEXT))
    cam = CompressedImage()
    cam.header.stamp = rospy.Time.now()
    cam.format = "jpeg"
    cam.data = JPEG_BYTES
    pub_cam.publish(cam)
    pub_cloud.publish(create_cloud_xyz32(Header(stamp=rospy.Time.now()), CLOUD_PTS))
    pub_grid.publish(create_cloud_xyz32(Header(stamp=rospy.Time.now()), GRID_PTS))
    path = Path()
    path.header.stamp = rospy.Time.now()
    for x in (0.0, 1.0):
        ps = PoseStamped()
        ps.pose.position.x = x
        path.poses.append(ps)
    pub_path.publish(path)
    traj = PiecewisePolynomial()
    traj.n_seg = 1
    traj.order = 3
    traj.durations = [1.0]
    traj.coeffs = TRAJ_COEFFS
    pub_traj.publish(traj)
    bat = BatteryState()
    bat.percentage = 0.87
    bat.voltage = 16.2
    pub_bat.publish(bat)
    st = StateMsg()
    st.mode = "POSCTL"
    pub_state.publish(st)

    def has_latched_battery() -> bool:
        for f in received.get("drone_status", []):
            if isinstance(json.loads(f).get("battery"), dict):
                return True
        return False

    deadline = time.time() + 12.0
    while time.time() < deadline and (len(received) < 7 or not has_latched_battery()):
        # republish everything so late subscriber/pub connections still see
        # every channel (queue_size=1, no latching)
        pub_odom.publish(_make_odom(rospy, 1.0, 2.0, 0.9))
        pub_sg.publish(String(data=SCENEGRAPH_TEXT))
        pub_cam.publish(cam)
        pub_cloud.publish(create_cloud_xyz32(Header(stamp=rospy.Time.now()), CLOUD_PTS))
        pub_grid.publish(create_cloud_xyz32(Header(stamp=rospy.Time.now()), GRID_PTS))
        pub_path.publish(path)
        pub_traj.publish(traj)
        pub_bat.publish(bat)
        pub_state.publish(st)
        time.sleep(0.2)

    def payload_of(channel: str):
        frames = received.get(channel) or []
        return frames[-1] if frames else None

    # meta
    meta_raw = payload_of("meta")
    check("meta received", meta_raw is not None)
    if meta_raw:
        meta = json.loads(meta_raw)
        check(
            "meta hello v2",
            meta.get("type") == "hello" and meta.get("version") == 2 and meta.get("role") == "drone_bridge",
            str(meta),
        )
        check(
            "meta announces grid_map",
            "grid_map_leaf" in meta.get("params", {}),
            str(meta),
        )

    # drone_status
    status_frames = received.get("drone_status", [])
    check("drone_status received", bool(status_frames))
    status_raw = next(
        (f for f in status_frames if isinstance(json.loads(f).get("battery"), dict)),
        None,
    )
    check("drone_status battery latched", status_raw is not None)
    if status_raw:
        status = json.loads(status_raw)
        odom = status.get("odom", {})
        check(
            "drone_status odom fields",
            abs(odom.get("x", 0) - 1.0) < 1e-6
            and abs(odom.get("y", 0) - 2.0) < 1e-6
            and abs(odom.get("z", 0) - 0.9) < 1e-6
            and odom.get("qw") == 1.0,
            str(odom),
        )
        check(
            "drone_status mode unknown (POSCTL)",
            status.get("mode") == "unknown",
            str(status.get("mode")),
        )
        check(
            "drone_status battery value",
            abs(status["battery"]["percentage"] - 0.87) < 1e-6,
            str(status.get("battery")),
        )

    # scenegraph
    check("scenegraph passthrough", payload_of("scenegraph") == SCENEGRAPH_TEXT.encode())

    # camera
    check("camera jpeg passthrough", payload_of("camera") == JPEG_BYTES)

    # cloud
    cloud_raw = payload_of("cloud")
    check("cloud received", cloud_raw is not None)
    if cloud_raw:
        import struct

        codec = cloud_raw[0]
        (count,) = struct.unpack_from("<I", cloud_raw, 1)
        body = cloud_raw[5:]
        check("cloud codec 0", codec == 0)
        check("cloud count 10", count == 10, str(count))
        xyz = struct.unpack(f"<{count * 3}f", body[: count * 12])
        check(
            "cloud xyz roundtrip",
            count == 10
            and abs(xyz[3] - 1.0) < 1e-5
            and abs(xyz[4] - 2.0) < 1e-5
            and abs(xyz[5] - 3.0) < 1e-5
            and abs(xyz[29] - 27.0) < 1e-4,
            str(xyz[:6]),
        )

    # grid_map
    grid_raw = payload_of("grid_map")
    check("grid_map received", grid_raw is not None)
    if grid_raw:
        import struct

        (gcount,) = struct.unpack_from("<I", grid_raw, 1)
        check("grid_map count 4", gcount == 4, str(gcount))

    # trajectory
    traj_raw = payload_of("trajectory")
    check("trajectory received", traj_raw is not None)
    if traj_raw:
        env = json.loads(traj_raw)
        check(
            "trajectory search_path",
            env.get("search_path") == [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
            str(env.get("search_path")),
        )
        opt = env.get("optimized") or {}
        segs = opt.get("segments") or []
        check(
            "trajectory optimized envelope",
            opt.get("order") == 3
            and len(segs) == 1
            and abs(segs[0]["t"] - 1.0) < 1e-6
            and segs[0]["cz"] == [9.0, 10.0, 11.0, 12.0],
            str(opt),
        )

    session.close()
    for p in procs:
        p.terminate()
    time.sleep(0.5)
    for p in procs:
        p.kill()

    print()
    if FAILURES:
        print(f"telemetry-bridge: {len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("telemetry-bridge: ALL PASS")
    return 0


def _make_odom(rospy, x, y, z):
    from nav_msgs.msg import Odometry

    m = Odometry()
    m.header.stamp = rospy.Time.now()
    m.pose.pose.position.x = x
    m.pose.pose.position.y = y
    m.pose.pose.position.z = z
    m.pose.pose.orientation.w = 1.0
    return m


if __name__ == "__main__":
    sys.exit(main())
