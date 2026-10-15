#!/usr/bin/env python3
# Entity: station-host
# Invoked: python3 deployment/tools/station-host-sim.py <action>
"""本工作区 Unity 仿真栈的配置、制品与 k3s 生命周期入口。"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

DEPLOYMENT = Path(__file__).resolve().parents[1]
ROOT = DEPLOYMENT.parent
L3 = ROOT / "drone_projects/l3-dispatcher-planner"
ASSETS = DEPLOYMENT / "k3s/unity"
OWNER_KEY = "diffagent.io/workspace"
CONFIG_KEY = "diffagent.io/config"
OWNER = hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]
ARTIFACTS = DEPLOYMENT / ".artifacts/k3s-unity"
SERVICES = ("l4-app", "agent-station-bridge", "agent-station-visualizer", "agent-station-vla")
BUSINESS = ("sim-roscore", "sim-dynamics", "sim-unity", "sim-l3", "sim-telemetry", "sim-logs")


def run(argv, **kwargs):
    return subprocess.run([str(arg) for arg in argv], check=True, **kwargs)


def read_env(path):
    result = {}
    if not path.exists():
        return result
    for number, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in result:
            raise ValueError(f"{path.name}:{number}: 配置键非法或重复")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if any(ord(char) < 32 for char in value):
            raise ValueError(f"{key}: 配置值含控制字符")
        result[key] = value
    return result


def config():
    c = read_env(ASSETS / "runtime.defaults.env")
    local = read_env(ROOT / ".local.env")
    unknown = sorted(key for key in local if key.startswith("SIM_") and key not in c)
    if unknown:
        raise ValueError("未知仿真配置键: " + ", ".join(unknown))
    c.update({key: value for key, value in local.items() if key in c})
    c["LX_STACK_ID"] = c["LX_STACK_ID"] or "sim/unity-" + OWNER
    c["SIM_NAMESPACE"] = c["SIM_NAMESPACE"] or "sim-unity-" + OWNER
    required = ("PUBLIC_ZENOHD_ROUTER",
                "SIM_L2_IMAGE", "SIM_L3_IMAGE", "SIM_FLUENT_IMAGE", "SIM_RELAY_IMAGE")
    missing = [key for key in required if not c[key]]
    if missing:
        raise ValueError("请在根 .local.env 配置: " + ", ".join(missing))
    for key in ("SIM_L2_IMAGE", "SIM_L3_IMAGE", "SIM_FLUENT_IMAGE", "SIM_RELAY_IMAGE"):
        if c[key].startswith("image-registry/"):
            registry = c["SIM_REGISTRY"]
            if not registry or not re.fullmatch(r"[A-Za-z0-9_.:-]+", registry):
                raise ValueError("请在根 .local.env 配置 SIM_REGISTRY 为参考镜像仓库的主机及端口")
            c[key] = registry + c[key][len("image-registry"):]
    for key in ("SIM_NODE", "SIM_NAMESPACE"):
        if key == "SIM_NODE" and not c[key]:
            continue
        if len(c[key]) > 63 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", c[key]):
            raise ValueError(f"{key}: 非法 Kubernetes 名称")
    if c["SIM_NAMESPACE"] in ("default", "kube-system", "kube-public", "kube-node-lease"):
        raise ValueError("SIM_NAMESPACE 必须为专用 namespace")
    if not re.fullmatch(r"sim/[A-Za-z0-9_.-]+", c["LX_STACK_ID"]):
        raise ValueError("LX_STACK_ID 必须为独立的 sim/<instance>")
    if not re.fullmatch(r"tcp/[A-Za-z0-9_.:\[\]-]+:[0-9]+", c["PUBLIC_ZENOHD_ROUTER"]):
        raise ValueError("PUBLIC_ZENOHD_ROUTER 必须为 tcp/<router>:<port>")
    for key in ("SIM_L2_IMAGE", "SIM_L3_IMAGE", "SIM_FLUENT_IMAGE", "SIM_RELAY_IMAGE"):
        if not re.fullmatch(r"[A-Za-z0-9_./:@-]+", c[key]) or "/" not in c[key] or "://" in c[key]:
            raise ValueError(f"{key}: 请提供不带凭据的完整镜像引用")
        if "@" in c[key] and not re.fullmatch(r"[^@]+@sha256:[0-9a-f]{64}", c[key]):
            raise ValueError(f"{key}: @ 仅允许用于镜像摘要，不得包含凭据")
    for key in ("SIM_UNITY_TCP_BIND", "SIM_UNITY_TCP_HOST"):
        if c[key] != "127.0.0.1":
            raise ValueError(f"{key}: 首期仅支持同机回环连接")
    for key in ("SIM_ROS_MASTER_PORT", "SIM_UNITY_TCP_PORT", "SIM_READY_TIMEOUT_S", "SIM_BUILD_TIMEOUT_S",
                "SIM_UNITY_CAMERA_WIDTH", "SIM_UNITY_CAMERA_HEIGHT", "SIM_CLOUD_MAX_POINTS",
                "SIM_BUILD_MEMORY_MIB", "SIM_BUILD_JOBS"):
        value = int(c[key])
        maximum = 65535 if "PORT" in key else 100000
        if not 1 <= value <= maximum:
            raise ValueError(f"{key}: 超出范围")
    if c["SIM_ROS_MASTER_PORT"] == c["SIM_UNITY_TCP_PORT"]:
        raise ValueError("ROS master 和 Unity TCP 端口不能相同")
    if min(int(c["SIM_ROS_MASTER_PORT"]), int(c["SIM_UNITY_TCP_PORT"])) < 1024:
        raise ValueError("仿真端口必须大于等于 1024")
    if any(int(c[key]) > 4096 for key in ("SIM_UNITY_CAMERA_WIDTH", "SIM_UNITY_CAMERA_HEIGHT")):
        raise ValueError("相机尺寸不能超过 4096")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", c["SIM_UNITY_SCENE_ID"]):
        raise ValueError("SIM_UNITY_SCENE_ID 必须为便携场景标识")
    for key in ("SIM_GROUND_Z", "SIM_INITIAL_X", "SIM_INITIAL_Y", "SIM_INITIAL_Z", "SIM_UNITY_DEPTH_RANGE_M",
                "SIM_UNITY_CAMERA_VERTICAL_FOV", "SIM_CAMERA_MAX_HZ", "SIM_DEPTH_MAX_HZ", "SIM_CLOUD_MAX_HZ",
                "SIM_ODOM_MAX_HZ", "SIM_TELEMETRY_MBIT", "SIM_CLOUD_LEAF_M"):
        if key == "SIM_GROUND_Z" and not c[key]:
            continue
        value = float(c[key])
        if not math.isfinite(value) or (key not in ("SIM_GROUND_Z", "SIM_INITIAL_X", "SIM_INITIAL_Y", "SIM_INITIAL_Z") and value <= 0):
            raise ValueError(f"{key}: 非法有限数值")
    if not 1 <= float(c["SIM_UNITY_CAMERA_VERTICAL_FOV"]) < 179 or float(c["SIM_UNITY_DEPTH_RANGE_M"]) > 65.535:
        raise ValueError("相机视角或深度量程非法")
    if float(c["SIM_CAMERA_MAX_HZ"]) > 15:
        raise ValueError("SIM_CAMERA_MAX_HZ 不能超过 15")
    t = [float(value) for value in c["SIM_UNITY_CAMERA_TRANSLATION_FLU"].split(",")]
    if len(t) != 3 or not all(math.isfinite(value) for value in t):
        raise ValueError("SIM_UNITY_CAMERA_TRANSLATION_FLU 必须为三个有限数")
    if (c["SIM_UNITY_SENSOR_SOURCE"], c["SIM_UNITY_MODE"]) not in (("original", "editor"), ("native", "player")):
        raise ValueError("仅支持 original/editor 或 native/player")
    for key in ("SIM_L2_ROOT", "SIM_L4_ROOT"):
        c[key] = str((ROOT / c[key]).resolve())
    if c["SIM_UNITY_MODE"] == "player":
        path = (ROOT / c["SIM_UNITY_PLAYER_PATH"]).resolve()
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError("SIM_UNITY_PLAYER_PATH 必须为已有可执行 Player")
        c["SIM_UNITY_PLAYER_PATH"] = str(path)
    if not c["SIM_PYTHON_EXECUTABLE"].startswith("/"):
        raise ValueError("SIM_PYTHON_EXECUTABLE 必须为镜像内绝对路径")
    if not c["SIM_NODE"]:
        nodes = Stack(c).get("nodes", namespaced=False).get("items", [])
        local_addresses = local_node_addresses()
        candidates = [node["metadata"]["name"] for node in nodes
                      if node["metadata"].get("labels", {}).get("kubernetes.io/arch") == "amd64"
                      and any(item["address"] in local_addresses
                              for item in node.get("status", {}).get("addresses", []))]
        if len(candidates) != 1:
            raise RuntimeError("无法唯一识别本机 amd64 节点，请在根 .local.env 显式配置 SIM_NODE")
        c["SIM_NODE"] = candidates[0]
    return c


def local_node_addresses():
    addresses = set(run(["hostname", "-I"], capture_output=True, text=True).stdout.split())
    return addresses | {socket.gethostname(), socket.getfqdn()}


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temp.replace(path)


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def component_sources(c, component):
    if component == "l3":
        packages = ("utils/quadrotor_msgs", "utils/traj_utils", "utils/vis_utils",
                    "planner/ego_planner/plan_manage", "planner/elastic_tracker",
                    "planner/planner_execution", "dispatcher", "telemetry_bridge")
        return [L3 / "ros_packages" / name for name in packages] + [
            L3 / "tools/build_ego.sh", ASSETS / "runtime_probe_ros.py"]
    l2 = Path(c["SIM_L2_ROOT"])
    if component == "unity":
        return [l2 / "projects/unity-simulator" / name for name in
                ("ros_packages/ros_tcp_endpoint", "bringup")]
    if component == "l2-wire":
        return [l2 / "projects/uav-simulator/ros_packages/quadrotor_msgs/msg/PositionCommand.msg"]
    raise ValueError("未知编译组件: " + component)


def component_source_digest(c, component):
    h = hashlib.sha256()
    for index, root in enumerate(component_sources(c, component)):
        if not root.exists():
            raise ValueError(f"构建输入缺失: {root}")
        h.update(str(root.resolve()).encode())
        paths = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in paths:
            relative = Path(path.name) if root.is_file() else path.relative_to(root)
            if any(part in (".git", ".artifacts", "__pycache__", "tests", "test", "Library", "Temp")
                   for part in relative.parts):
                continue
            if path.is_file() and path.suffix.lower() not in (".pyc", ".md", ".rst"):
                h.update(f"{index}/{relative}\0".encode())
                h.update(path.read_bytes())
    return h.hexdigest()


def env_list(values):
    return [{"name": key, "value": str(value)} for key, value in values.items()]


class Stack:
    def __init__(self, c):
        self.c = c
        self.ns = c["SIM_NAMESPACE"]
        self.fingerprint = digest(c)
        self.kube_prefix = None
        self.created = []
        self.prepared = read_json(ARTIFACTS / "prepared.json", {})

    def kube(self, *args, **kwargs):
        if self.kube_prefix is None:
            for prefix in (["kubectl"], ["sudo", "-n", "kubectl"], ["sudo", "-n", "k3s", "kubectl"]):
                try:
                    result = subprocess.run(prefix + ["get", "--raw=/readyz"], capture_output=True, timeout=10)
                    if result.returncode == 0:
                        self.kube_prefix = prefix
                        break
                except (OSError, subprocess.TimeoutExpired):
                    continue
            if self.kube_prefix is None:
                raise RuntimeError("无法访问 k3s API；请配置 kubectl 或 sudo -n kubectl")
        return run(self.kube_prefix + list(args), **kwargs)

    def get(self, kind, name=None, namespaced=True):
        args = (["-n", self.ns] if namespaced else []) + ["get", kind]
        if name:
            args += [name, "--ignore-not-found"]
        result = self.kube(*args, "-o", "json", capture_output=True, text=True, timeout=20)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def metadata(self, name):
        return {"name": name, "namespace": self.ns, "labels": {OWNER_KEY: OWNER},
                "annotations": {CONFIG_KEY: self.fingerprint}}

    def assert_owner(self, obj):
        if obj["metadata"].get("labels", {}).get(OWNER_KEY) != OWNER:
            raise RuntimeError(f"拒绝接管其他工作区资源: {obj['kind']}/{obj['metadata']['name']}")

    def claim(self):
        node = self.get("node", self.c["SIM_NODE"], namespaced=False)
        if not node or node["metadata"].get("labels", {}).get("kubernetes.io/arch") != "amd64":
            raise RuntimeError("SIM_NODE 必须为当前主机上的 amd64 k3s 节点")
        addresses = {item["address"] for item in node.get("status", {}).get("addresses", [])}
        if not (addresses & local_node_addresses()):
            raise RuntimeError("目标节点不是当前主机；hostPath 仅支持同机部署")
        ns = self.get("namespace", self.ns, namespaced=False)
        if ns is None:
            ns = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": self.ns, "labels": {OWNER_KEY: OWNER}}}
            self.kube("create", "-f", "-", input=json.dumps(ns), text=True, capture_output=True)
        else:
            self.assert_owner(ns)
        for kind in ("deployment", "job", "configmap", "pod"):
            for obj in self.get(kind).get("items", []):
                if kind == "configmap" and obj["metadata"]["name"] == "kube-root-ca.crt":
                    continue
                self.assert_owner(obj)

    def create(self, obj):
        old = self.get(obj["kind"], obj["metadata"]["name"])
        if old:
            self.assert_owner(old)
            if old["metadata"].get("annotations", {}).get(CONFIG_KEY) != self.fingerprint:
                raise RuntimeError("配置已改变；请先使用原配置 down 后重新 prepare/up")
            return False
        self.kube("create", "-f", "-", input=json.dumps(obj), text=True, capture_output=True)
        self.created.append((obj["kind"], obj["metadata"]["name"]))
        return True

    def delete(self, kind, name):
        obj = self.get(kind, name)
        if obj:
            self.assert_owner(obj)
            plural = {"deployment": "deployments", "job": "jobs", "configmap": "configmaps"}[kind.lower()]
            api = "/apis/" + obj["apiVersion"] if "/" in obj["apiVersion"] else "/api/" + obj["apiVersion"]
            url = f"{api}/namespaces/{self.ns}/{plural}/{name}"
            options = {"apiVersion": "v1", "kind": "DeleteOptions", "propagationPolicy": "Foreground",
                       "preconditions": {"uid": obj["metadata"]["uid"]}}
            self.kube("delete", "--raw", url, "-f", "-", input=json.dumps(options), text=True, capture_output=True)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                current = self.get(kind, name)
                if current is None:
                    return
                if current["metadata"]["uid"] != obj["metadata"]["uid"]:
                    raise RuntimeError("资源在删除期间被替换，停止后续操作")
                time.sleep(1)
            raise RuntimeError(f"删除 {kind}/{name} 超时")

    def shell(self, command, setup="l3"):
        prefix = "source /opt/ros/noetic/setup.bash && "
        if setup in ("l3", "unity"):
            prefix += f"source /work/{setup}/devel/setup.bash && "
        elif setup == "dynamics":
            prefix += "source /workspace/devel/setup.bash && export ROS_PACKAGE_PATH=/source/l2/projects/uav-simulator:$ROS_PACKAGE_PATH && "
        return ["bash", "-c", prefix + command]

    def pod(self, containers, work="l3"):
        c = self.c
        values = {"ROS_MASTER_URI": f"http://127.0.0.1:{c['SIM_ROS_MASTER_PORT']}",
                  "ROS_IP": "127.0.0.1", "ROS_HOSTNAME": "localhost", "LX_ROSCORE_OWNER": "false",
                  "LX_STACK_ID": c["LX_STACK_ID"], "ZENOH_ROUTER": c["PUBLIC_ZENOHD_ROUTER"],
                  "PYTHONUNBUFFERED": "1", "ROSCONSOLE_FORMAT": "[${node}] [${severity}] [${time}]: ${message}"}
        mounts = [(L3, "/source/l3", True), (Path(c["SIM_L2_ROOT"]), "/source/l2", True),
                  (DEPLOYMENT, "/source/deployment", True),
                  (ARTIFACTS / "l3", "/work/l3", work != "compile"),
                  (ARTIFACTS / "unity", "/work/unity", work != "compile"),
                  (ARTIFACTS / "config", "/sim-config", True)]
        for container in containers:
            container.setdefault("image", self.image("SIM_L3_IMAGE"))
            container["imagePullPolicy"] = "IfNotPresent"
            container["env"] = env_list(values) + container.get("env", [])
            if work != "compile":
                container["command"] = ["bash", "/source/deployment/k3s/unity/drone-container-run.sh"] + container["command"]
                container["env"] += env_list({"SIM_COMPONENT": container["name"]})
            container["volumeMounts"] = [{"name": f"v{i}", "mountPath": dest, "readOnly": readonly}
                                           for i, (_, dest, readonly) in enumerate(mounts)]
            container.setdefault("resources", {"requests": {"cpu": "100m", "memory": "128Mi"},
                                                 "limits": {"cpu": "4", "memory": "4Gi"}})
        return {"hostNetwork": True, "dnsPolicy": "ClusterFirstWithHostNet", "terminationGracePeriodSeconds": 30,
                "nodeName": c["SIM_NODE"], "nodeSelector": {"kubernetes.io/arch": "amd64"},
                "automountServiceAccountToken": False, "containers": containers,
                "volumes": [{"name": f"v{i}", "hostPath": {"path": str(src), "type": "Directory"}}
                            for i, (src, _, _) in enumerate(mounts)]}

    def image(self, key):
        return self.prepared.get("images", {}).get(key, self.c[key])

    def manifest(self, filename, command, setup="l3", image_key="SIM_L3_IMAGE", probe=None):
        obj = json.loads((ASSETS / filename).read_text())
        name = obj["metadata"]["name"]
        obj["metadata"] = self.metadata(name)
        labels = {"app": name, OWNER_KEY: OWNER}
        obj["spec"]["selector"] = {"matchLabels": labels}
        container = obj["spec"]["template"]["spec"]["containers"][0]
        container.update(image=self.image(image_key), command=self.shell(command, setup))
        if probe:
            container["readinessProbe"] = {"exec": {"command": self.shell(probe, setup)},
                                            "periodSeconds": 10, "timeoutSeconds": 8, "failureThreshold": 3}
        obj["spec"]["template"] = {"metadata": {"labels": labels, "annotations": {
            CONFIG_KEY: self.fingerprint, "diffagent.io/source": digest(self.prepared["components"]) if self.prepared.get("components") else "unprepared"}},
            "spec": self.pod([container])}
        return obj

    def manifests(self):
        c = self.c
        py = shlex.quote(c["SIM_PYTHON_EXECUTABLE"])
        probe = f"{py} /source/deployment/k3s/unity/runtime_probe_ros.py"
        dynamics = "exec roslaunch /source/l2/projects/uav-simulator/bringup/launch/uav_simulator.launch enable_lidar:=false gsplat_bridge:=false "
        dynamics += " ".join(f"init_{axis}:={shlex.quote(c['SIM_INITIAL_' + axis.upper()])}" for axis in "xyz")
        sensors = "exec roslaunch unity_simulator unity_simulator.launch " + " ".join(
            f"{arg}:={shlex.quote(c[key])}" for arg, key in (("tcp_ip", "SIM_UNITY_TCP_BIND"), ("tcp_port", "SIM_UNITY_TCP_PORT"),
                    ("sensor_source", "SIM_UNITY_SENSOR_SOURCE"), ("depth_range_m", "SIM_UNITY_DEPTH_RANGE_M")))
        ground_arg = f"ground_z:={shlex.quote(c['SIM_GROUND_Z'])} " if c["SIM_GROUND_Z"] else ""
        return [
            self.manifest("roscore.deployment.yaml", f"exec roscore -p {c['SIM_ROS_MASTER_PORT']}", "ros", "SIM_L2_IMAGE",
                          "python3 /source/deployment/k3s/unity/runtime_probe_ros.py master"),
            self.manifest("dynamics.deployment.yaml", dynamics, "dynamics", "SIM_L2_IMAGE",
                          "python3 /source/deployment/k3s/unity/runtime_probe_ros.py odom"),
            self.manifest("sensors.deployment.yaml", sensors, "unity", probe="rosnode ping -c 1 /unity_endpoint >/dev/null"),
            self.manifest("l3.deployment.yaml", "exec roslaunch /source/l3/bringup/launch/basic_flight.launch "
                          + ground_arg + f"python_executable:={py}", probe=probe + " planner"),
            self.manifest("telemetry.deployment.yaml", "exec roslaunch telemetry_bridge telemetry.launch "
                          f"python_executable:={py}", probe=probe + " telemetry"),
        ]

    def render(self):
        target = ARTIFACTS / "rendered"
        for obj in self.manifests() + self.logs_manifests():
            atomic_json(target / f"{obj['metadata']['name']}.yaml", obj)
        for component in ("l3", "unity", "l2-wire"):
            atomic_json(target / f"compile-{component}.yaml", self.compile_manifest(component))
        print(f"清单已生成: {target}（仅生成清单，不部署资源）", flush=True)

    def write_config(self):
        c = self.c
        camera = {"width": int(c["SIM_UNITY_CAMERA_WIDTH"]), "height": int(c["SIM_UNITY_CAMERA_HEIGHT"]),
                  "vertical_fov_deg": float(c["SIM_UNITY_CAMERA_VERTICAL_FOV"]), "rate_hz": float(c["SIM_CAMERA_MAX_HZ"]),
                  "max_range_m": float(c["SIM_UNITY_DEPTH_RANGE_M"]), "flip_image_rows": True,
                  "translation_flu": [float(v) for v in c["SIM_UNITY_CAMERA_TRANSLATION_FLU"].split(",")],
                  "rotation_rpy_deg": [0, 0, 0]}
        atomic_json(ARTIFACTS / "config/player.json", {"schema_version": 1, "scene_id": c["SIM_UNITY_SCENE_ID"],
                    "tcp_host": c["SIM_UNITY_TCP_HOST"], "tcp_port": int(c["SIM_UNITY_TCP_PORT"]), "camera": camera,
                    "lidar": {"horizontal_rays": 360, "vertical_rays": 16, "vertical_fov_deg": 90}})
        atomic_json(ARTIFACTS / "config/telemetry.json", {
            "rates": {"meta": 1, "drone_status": float(c["SIM_ODOM_MAX_HZ"]), "camera": float(c["SIM_CAMERA_MAX_HZ"]),
                      "depth": float(c["SIM_DEPTH_MAX_HZ"]), "cloud": float(c["SIM_CLOUD_MAX_HZ"])},
            "mbit": float(c["SIM_TELEMETRY_MBIT"]), "cloud_leaf": float(c["SIM_CLOUD_LEAF_M"]),
            "cloud_max_points": int(c["SIM_CLOUD_MAX_POINTS"])})

    def compile_manifest(self, component):
        obj = json.loads((ASSETS / "compile.job.yaml").read_text())
        obj["metadata"] = self.metadata("sim-compile-" + component)
        if component == "l3":
            command = f"L3_BUILD_JOBS={self.c['SIM_BUILD_JOBS']} bash /source/l3/tools/build_ego.sh /work/l3 --with-telemetry && "
            py = shlex.quote(self.c["SIM_PYTHON_EXECUTABLE"])
            command += f"source /work/l3/devel/setup.bash && {py} /source/deployment/k3s/unity/runtime_probe_ros.py dependencies"
        elif component == "unity":
            command = "mkdir -p /work/unity/src && "
            command += "ln -sfn /source/l2/projects/unity-simulator/ros_packages/ros_tcp_endpoint /work/unity/src/ros_tcp_endpoint && "
            command += "ln -sfn /source/l2/projects/unity-simulator/bringup /work/unity/src/unity_simulator && "
            command += f"catkin_make -C /work/unity -j{self.c['SIM_BUILD_JOBS']} -DPYTHON_EXECUTABLE=/usr/bin/python3 && "
            command += "python3 -c 'import cv2, cv_bridge, rospy'"
        else:
            command = "python3 -c 'from quadrotor_msgs.msg import PositionCommand; print(\"POSITION_COMMAND_MD5=\" + PositionCommand._md5sum)'"
        container = {"name": "compile", "command": self.shell(command, "dynamics" if component == "l2-wire" else "ros"),
                     "image": self.image("SIM_L2_IMAGE" if component == "l2-wire" else "SIM_L3_IMAGE"),
                     "resources": {"requests": {"cpu": "1", "memory": "1Gi"},
                                   "limits": {"cpu": "4", "memory": self.c["SIM_BUILD_MEMORY_MIB"] + "Mi"}}}
        obj["spec"]["activeDeadlineSeconds"] = int(self.c["SIM_BUILD_TIMEOUT_S"])
        obj["spec"]["template"] = {"metadata": {"labels": {OWNER_KEY: OWNER}}, "spec": self.pod([container], "compile")}
        obj["spec"]["template"]["spec"]["restartPolicy"] = "Never"
        return obj

    def resolve_images(self):
        containerd = Path("/run/k3s/containerd/containerd.sock").is_socket()
        if containerd:
            if shutil.which("crictl"):
                runtime = ["sudo", "-n", "crictl", "--runtime-endpoint", "unix:///run/k3s/containerd/containerd.sock"]
            else:
                runtime = ["sudo", "-n", "k3s", "crictl"]
        else:
            if not shutil.which("docker"):
                raise RuntimeError("未发现参考流程所需的 containerd socket 或 docker 命令")
            runtime = ["docker"]
        images = {}
        for key in ("SIM_L2_IMAGE", "SIM_L3_IMAGE", "SIM_FLUENT_IMAGE", "SIM_RELAY_IMAGE"):
            ref = self.c[key]
            run(runtime + ["pull", ref], capture_output=True, text=True, timeout=300)
            if containerd:
                inspected = json.loads(run(runtime + ["inspecti", ref], capture_output=True, text=True, timeout=30).stdout)
                candidates = inspected["status"].get("repoDigests", [])
            else:
                inspected = json.loads(run(runtime + ["image", "inspect", ref], capture_output=True, text=True, timeout=30).stdout)
                candidates = inspected[0].get("RepoDigests", [])
            repository = ref.split("@")[0]
            if ":" in repository.rsplit("/", 1)[-1]:
                repository = repository.rsplit(":", 1)[0]
            matches = [item for item in candidates if item.split("@")[0] == repository]
            if len(matches) != 1:
                raise RuntimeError(f"无法唯一解析 {key} 的镜像摘要")
            images[key] = matches[0]
        return images

    def component_signature(self, component, obj):
        container = obj["spec"]["template"]["spec"]["containers"][0]
        image_key = "SIM_L2_IMAGE" if component == "l2-wire" else "SIM_L3_IMAGE"
        generated = ARTIFACTS / "l3/devel/lib/python3/dist-packages/quadrotor_msgs/msg/_PositionCommand.py"
        wire_definition = (hashlib.sha256(generated.read_bytes()).hexdigest()
                           if component == "l2-wire" and generated.is_file() else None)
        return digest({"schema": 2, "source": component_source_digest(self.c, component),
                       "generated_wire": wire_definition,
                       "image": container["image"], "requested_image": self.c[image_key],
                       "command": container["command"],
                       "mounts": {"l3": str(L3), "l2": self.c["SIM_L2_ROOT"],
                                  "artifacts": str(ARTIFACTS), "deployment": str(DEPLOYMENT)}})

    def component_artifacts_present(self, component):
        if component == "l3":
            return all((ARTIFACTS / "l3" / path).is_file() for path in (
                "devel/setup.bash", "devel/lib/ego_planner/ego_planner_node",
                "devel/lib/libego_planner.so", "devel/lib/libplanner_execution.so",
                "devel/lib/libelastic_tracker.so",
                "devel/lib/python3/dist-packages/quadrotor_msgs/msg/_PositionCommand.py"))
        if component == "unity":
            return (ARTIFACTS / "unity/devel/setup.bash").is_file()
        return True

    def prepare(self):
        self.claim()
        if any(self.get("deployment", name) for name in BUSINESS):
            raise RuntimeError("请先 down 业务栈，再准备制品")
        l2_message = Path(self.c["SIM_L2_ROOT"]) / "projects/uav-simulator/ros_packages/quadrotor_msgs/msg/PositionCommand.msg"
        l3_message = L3 / "ros_packages/utils/quadrotor_msgs/msg/PositionCommand.msg"
        def fields(path):
            return [line.partition("#")[0].strip() for line in path.read_text().splitlines() if line.partition("#")[0].strip()]
        if fields(l2_message) != fields(l3_message):
            raise RuntimeError("L2/L3 PositionCommand 定义不一致，不能建立控制闭环")
        mark = ARTIFACTS / "prepared.json"
        mark.unlink(missing_ok=True)
        self.prepared = {"schema": 2, "images": self.resolve_images(), "components": {}}
        self.write_config()
        for component in ("l3", "unity"):
            (ARTIFACTS / component).mkdir(parents=True, exist_ok=True)
        for component in ("l3", "unity", "l2-wire"):
            obj = self.compile_manifest(component)
            signature = self.component_signature(component, obj)
            cache_path = ARTIFACTS / f"compile-{component}.json"
            saved = read_json(cache_path, {})
            if (saved.get("schema") == 2 and saved.get("owner") == OWNER
                    and saved.get("signature") == signature and self.component_artifacts_present(component)):
                self.prepared["components"][component] = saved
                print(f"{component} 构建输入及产物有效，复用成功记录", flush=True)
                continue
            cache_path.unlink(missing_ok=True)
            name = obj["metadata"]["name"]
            self.delete("job", name)
            self.create(obj)
            deadline = time.monotonic() + int(self.c["SIM_BUILD_TIMEOUT_S"]) + 30
            while time.monotonic() < deadline:
                status = self.get("job", name).get("status", {})
                if status.get("succeeded") or status.get("failed"):
                    result = self.kube("-n", self.ns, "logs", "job/" + name, capture_output=True, text=True, timeout=20)
                    (ARTIFACTS / f"compile-{component}.log").write_text(result.stdout + result.stderr)
                    if not status.get("succeeded"):
                        pods = self.kube("-n", self.ns, "get", "pods", "-l", "job-name=" + name,
                                         "-o", "json", capture_output=True, text=True, timeout=10)
                        endings = []
                        for pod in json.loads(pods.stdout).get("items", []):
                            for item in pod.get("status", {}).get("containerStatuses", []):
                                end = item.get("state", {}).get("terminated", {})
                                if end:
                                    endings.append(f"{item['name']}: {end.get('reason', 'unknown')} exit={end.get('exitCode')}")
                        detail = "; ".join(endings) or "Job failed"
                        raise RuntimeError(f"{name} 编译失败（{detail}），见 deployment/.artifacts/k3s-unity/compile-{component}.log")
                    if component == "l2-wire":
                        generated = ARTIFACTS / "l3/devel/lib/python3/dist-packages/quadrotor_msgs/msg/_PositionCommand.py"
                        match = re.search(r'_md5sum\s*=\s*[\"\x27]([0-9a-f]{32})', generated.read_text())
                        if not match or "POSITION_COMMAND_MD5=" + match.group(1) not in result.stdout:
                            raise RuntimeError("L2 镜像与新版生成的 PositionCommand MD5 不一致")
                    if self.component_signature(component, obj) != signature:
                        raise RuntimeError(f"{component} 编译期间输入变化，请重新 prepare")
                    if not self.component_artifacts_present(component):
                        raise RuntimeError(f"{component} 必要编译产物缺失，请 prepare")
                    record = {"schema": 2, "owner": OWNER, "signature": signature}
                    atomic_json(cache_path, record)
                    self.prepared["components"][component] = record
                    break
                time.sleep(2)
            else:
                raise RuntimeError(f"{name} 超时；Job 和日志保留供诊断")
        self.check_component_records()
        self.prepared.update(owner=OWNER,
                             mounts={"l3": "/work/l3", "unity": "/work/unity"},
                             revisions={"orchestrator": run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
                                        "l2": run(["git", "-C", self.c["SIM_L2_ROOT"], "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()})
        atomic_json(mark, self.prepared)
        self.render()
        print("制品准备完成；业务栈尚未启动", flush=True)

    def check_component_records(self):
        for component in ("l3", "unity", "l2-wire"):
            record = self.prepared.get("components", {}).get(component, {})
            signature = self.component_signature(component, self.compile_manifest(component))
            if (record.get("schema") != 2 or record.get("owner") != OWNER
                    or record.get("signature") != signature or not self.component_artifacts_present(component)):
                raise RuntimeError(f"{component} 构建输入变化或产物缺失，请显式 prepare")

    def check_prepared(self):
        if self.prepared.get("owner") != OWNER or self.prepared.get("schema") != 2:
            raise RuntimeError("缺少当前版本的制品记录，请显式 prepare（已有编译缓存保留）")
        self.check_component_records()

    def exec_probe(self, action, deployment="sim-l3", setup="l3", required=True):
        python = "python3" if deployment in ("sim-roscore", "sim-dynamics", "sim-unity") else self.c["SIM_PYTHON_EXECUTABLE"]
        command = self.shell(f"{shlex.quote(python)} /source/deployment/k3s/unity/runtime_probe_ros.py {action}", setup)
        try:
            result = self.kube("-n", self.ns, "exec", "deployment/" + deployment, "--", *command,
                               capture_output=True, text=True, timeout=25)
            return json.loads(result.stdout.strip().splitlines()[-1])
        except (subprocess.SubprocessError, ValueError, IndexError) as exc:
            if required:
                raise RuntimeError(f"{deployment}/{action} 未就绪: {getattr(exc, 'stderr', '') or exc}") from exc
            return {"ok": False, "reason": str(getattr(exc, "stderr", "") or exc)}

    def wait_probe(self, action, deployment, setup):
        deadline = time.monotonic() + int(self.c["SIM_READY_TIMEOUT_S"])
        last = {}
        while time.monotonic() < deadline:
            last = self.exec_probe(action, deployment, setup, required=False)
            if last.get("ok"):
                return
            print(f"等待 {action}: {last.get('reason', last)}", flush=True)
            time.sleep(3)
        raise RuntimeError(f"等待 {action} 超时: {last}")

    def port_free(self, port):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", int(port)))
            except OSError as exc:
                raise RuntimeError(f"端口 {port} 已占用，拒绝接管") from exc

    def up(self):
        self.claim()
        self.check_prepared()
        for name, key in (("sim-roscore", "SIM_ROS_MASTER_PORT"), ("sim-unity", "SIM_UNITY_TCP_PORT")):
            if not self.get("deployment", name):
                self.port_free(self.c[key])
        self.created.clear()
        player_created = False
        active = read_json(ARTIFACTS / "active-config.json", {})
        if active and (active.get("owner") != OWNER or active.get("config") != self.c):
            raise RuntimeError("仍有另一份活动配置，请先 down，再按是否涉及构建输入决定 prepare/up")
        self.write_config()
        atomic_json(ARTIFACTS / "active-config.json", {"owner": OWNER, "config": self.c})
        try:
            manifests = self.manifests()
            self.create(manifests[0])
            self.wait_probe("master", "sim-roscore", "ros")
            self.create(manifests[1])
            self.create(manifests[2])
            self.wait_probe("odom", "sim-dynamics", "dynamics")
            player_created = self.player_start()
            print("original/editor 模式请保持原 Unity 场景 Play 并连接配置端口", flush=True)
            self.wait_probe("sensors", "sim-unity", "unity")
            self.create(manifests[3])
            self.wait_probe("planner", "sim-l3", "l3")
            self.wait_probe("task", "sim-l3", "l3")
            self.create(manifests[4])
            self.wait_probe("telemetry", "sim-telemetry", "l3")
            for obj in self.logs_manifests():
                self.create(obj)
            self.kube("-n", self.ns, "rollout", "status", "deployment/sim-logs", "--timeout=" + self.c["SIM_READY_TIMEOUT_S"] + "s")
            self.wait_probe("logs", "sim-l3", "l3")
            saved = read_json(ARTIFACTS / "running.json", {})
            atomic_json(ARTIFACTS / "running.json", {"owner": OWNER, "config": self.fingerprint,
                        "stack": self.c["LX_STACK_ID"], "instance": saved.get("instance") or uuid.uuid4().hex,
                        "resources": [[obj["kind"], obj["metadata"]["name"]] for obj in manifests + self.logs_manifests()]})
            print("仿真业务栈已就绪；start 可一并启动当前工作区站端", flush=True)
        except Exception:
            # 已暴露控制面时先走相同的安全关闭门；不能把启动失败当作强制删除授权。
            if ("Deployment", "sim-l3") in self.created:
                try:
                    self.guard_shutdown()
                except Exception as error:
                    print(f"安全关闭未确认，保留已建资源供处理: {error}", file=sys.stderr)
                    raise
            if player_created:
                self.player_stop()
            for kind, name in reversed(self.created):
                self.delete(kind, name)
            if not any(self.get("deployment", name) for name in BUSINESS):
                (ARTIFACTS / "active-config.json").unlink(missing_ok=True)
            raise

    def guard_shutdown(self):
        if not self.get("deployment", "sim-l3"):
            return
        state = self.exec_probe("shutdown", required=True)
        if not state.get("safe"):
            raise RuntimeError("planner 尚未动态停稳或仍有运动；请先通过当前站端取消/急停并等待")
        claim = state["claim"]
        if claim.get("owned"):
            snapshot = self.http("/api/stacks?claims=1")
            lease = snapshot.get("connection") or {}
            if lease.get("stack_id") != self.c["LX_STACK_ID"] or lease.get("station_id") != claim.get("station_id"):
                raise RuntimeError("仿真栈被其他站端占用，拒绝关闭")
            self.http("/api/connection/release", post=True)
            state = self.exec_probe("shutdown")
            if state["claim"].get("owned") or not state.get("safe"):
                raise RuntimeError("租约未释放或 planner 未停稳，拒绝关闭")

    def down(self):
        self.claim()
        self.guard_shutdown()
        for name in reversed(BUSINESS):
            self.delete("deployment", name)
        self.delete("configmap", "sim-log-config")
        self.player_stop()
        (ARTIFACTS / "running.json").unlink(missing_ok=True)
        (ARTIFACTS / "active-config.json").unlink(missing_ok=True)
        print("本工作区仿真资源已停止；namespace 和编译产物保留", flush=True)

    def http(self, path, post=False):
        request = urllib.request.Request("http://127.0.0.1:8088" + path, data=b"" if post else None,
                                         method="POST" if post else "GET")
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.load(response)

    def station_owner(self):
        for service in SERVICES:
            result = subprocess.run(["systemctl", "--user", "show", service + ".service", "--property=WorkingDirectory", "--value"],
                                    capture_output=True, text=True)
            directory = result.stdout.strip()
            if self.station_active(service) and not directory:
                raise RuntimeError(f"无法确认正在运行的 {service} 的源码归属")
            if directory and Path(directory).resolve() != Path(self.c["SIM_L4_ROOT"]):
                raise RuntimeError(f"{service} 属于其他检出，拒绝改写或停止")
            dropins = Path.home() / ".config/systemd/user" / (service + ".service.d")
            for path in dropins.glob("50-diffagent-*.conf"):
                if path.name != "50-diffagent-" + OWNER + ".conf":
                    raise RuntimeError(f"{service} 存在其他工作区相机配置，拒绝接管")
        for service in ("l4-visualizer", "agent-station-vlm"):
            result = subprocess.run(["systemctl", "--user", "is-active", service + ".service"], capture_output=True, text=True)
            if result.returncode == 0:
                raise RuntimeError(f"存在旧站端服务 {service}，请由原工作区停止")

    def station_preflight(self):
        self.station_owner()
        root = Path(self.c["SIM_L4_ROOT"])
        for entry in ("python", "copaw", "agent-station-bridge", "agent-station-visualizer", "agent-station-vla"):
            path = root / ".venv/bin" / entry
            if not path.is_file() or not os.access(path, os.X_OK):
                raise RuntimeError(f"站端入口缺失或不可执行: {path}；请先 make station-setup")
        for path in (root / "console/dist/index.html",
                     root / "src/copaw/station_sidecar/visualizer/web/dist/index.html"):
            if not path.is_file():
                raise RuntimeError(f"站端前端产物缺失: {path}；请先 make station-setup")
        router = run([root / ".venv/bin/copaw", "kv", "get", "lx_zenoh_router"], cwd=root,
                     capture_output=True, text=True, timeout=15).stdout.strip()
        if router != self.c["PUBLIC_ZENOHD_ROUTER"]:
            raise RuntimeError("L4 config-db 的 lx_zenoh_router 与仿真 PUBLIC_ZENOHD_ROUTER 不一致；请先在配置库统一")
        station_id = run([root / ".venv/bin/copaw", "kv", "get", "lx_station_id"], cwd=root,
                         capture_output=True, text=True, timeout=15).stdout.strip()
        if not station_id:
            raise RuntimeError("L4 config-db 尚未配置 lx_station_id")
        was_active = any(self.station_active(service) for service in SERVICES)
        if was_active:
            snapshot = self.http("/api/stacks?claims=1")
            if snapshot.get("connection"):
                raise RuntimeError("本站端仍持有租约；请先断开后 station-start，使相机配置随重启生效")
        for port in (8088, 8092, 8391, 8093, 9876, 9877):
            # 已运行的本站端可重入；来源由 systemd 的 WorkingDirectory 与进程属主确认。
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    self.port_owner(port, root)
        return was_active

    def station_stop(self):
        # 完整关闭固定本机站端；用户授权覆盖跨检出及无登记的启动残留。
        if self.station_active("l4-app"):
            snapshot = self.http("/api/stacks?claims=1")
            if snapshot.get("connection"):
                released = self.http("/api/connection/release", post=True)
                if not released.get("released") and released.get("reason") != "not_connected":
                    raise RuntimeError(f"站端连接未安全释放，拒绝关闭: {released}")
        services = SERVICES + ("l4-visualizer", "agent-station-vlm")
        units = []
        for service in services:
            result = subprocess.run(["systemctl", "--user", "show", service + ".service",
                                     "--property=LoadState", "--value"], capture_output=True, text=True)
            if result.returncode and result.stdout.strip() != "not-found":
                raise RuntimeError(f"无法查询站端服务 {service}: {result.stderr.strip()}")
            if result.stdout.strip() not in ("", "not-found"):
                units.append(service + ".service")
        if units:
            run(["systemctl", "--user", "stop", *units])
            run(["systemctl", "--user", "disable", *units])
        directory = Path.home() / ".config/systemd/user"
        for service in services:
            (directory / (service + ".service")).unlink(missing_ok=True)
            for dropin in (directory / (service + ".service.d")).glob("50-diffagent-*.conf"):
                dropin.unlink()
        run(["systemctl", "--user", "daemon-reload"])
        deadline = time.monotonic() + 15
        while True:
            busy = []
            for port in (8088, 8092, 8391, 8093, 9876, 9877):
                with socket.socket() as sock:
                    sock.settimeout(0.2)
                    if sock.connect_ex(("127.0.0.1", port)) == 0:
                        busy.append(port)
            if not busy:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError(f"站端服务已停止但端口仍占用: {busy}；未强杀未知进程")
            time.sleep(1)
        (ARTIFACTS / "station.json").unlink(missing_ok=True)
        print("本机 L4 站端服务已全部停止，用户单元和仿真相机配置已清理", flush=True)

    def station(self, action):
        if action == "stop":
            self.station_stop()
            return
        was_active = self.station_preflight()
        marker = ARTIFACTS / "station.json"
        root = Path(self.c["SIM_L4_ROOT"])
        self.station_dropins()
        atomic_json(marker, {"owner": OWNER, "root": str(root), "phase": "starting"})
        try:
            run(["make", "-C", root, "l4-app", "start"], env=dict(os.environ, L4_ROOT=str(root)))
        except subprocess.CalledProcessError as error:
            raise RuntimeError("站端部分启动失败，登记已保留；make down 会清理本机站端服务") from error
        if was_active:
            # 已运行服务需要重启才能读取本次相机标定；只能操作确认属于本站端的服务。
            run(["systemctl", "--user", "restart", *[service + ".service" for service in SERVICES]])
        deadline = time.monotonic() + int(self.c["SIM_READY_TIMEOUT_S"])
        while time.monotonic() < deadline:
            if all(self.station_active(service) for service in SERVICES):
                try:
                    snapshot = self.http("/api/stacks?claims=1")
                    if snapshot.get("ready"):
                        break
                except (OSError, ValueError):
                    pass
            time.sleep(2)
        else:
            raise RuntimeError("站端启动超时，仿真栈与站端日志保留；使用 status 定位")
        atomic_json(marker, {"owner": OWNER, "root": str(root), "phase": "ready"})
        print("站端启动命令已执行: http://127.0.0.1:8088 ，可视化 :8391", flush=True)

    def station_active(self, service):
        return subprocess.run(["systemctl", "--user", "is-active", service + ".service"], capture_output=True).returncode == 0

    def port_owner(self, port, root):
        result = run(["ss", "-ltnp", f"sport = :{port}"], capture_output=True, text=True)
        pids = re.findall(r"pid=(\d+)", result.stdout)
        if not pids:
            raise RuntimeError(f"无法判定端口 {port} 的进程归属")
        for pid in pids:
            try:
                cwd = (Path("/proc") / pid / "cwd").resolve(strict=True)
            except OSError as exc:
                raise RuntimeError(f"无法判定端口 {port} 归属") from exc
            if cwd != root and root not in cwd.parents:
                raise RuntimeError(f"端口 {port} 属于其他工作区")

    def station_dropins(self, remove=False):
        # 不覆盖身份/router；仅同步仿真相机标定到当前 L4 已有环境入口。
        for service in SERVICES:
            directory = Path.home() / ".config/systemd/user" / (service + ".service.d")
            path = directory / ("50-diffagent-" + OWNER + ".conf")
            if remove:
                path.unlink(missing_ok=True)
            else:
                directory.mkdir(parents=True, exist_ok=True)
                path.write_text("[Service]\nEnvironment=\"LX_CAMERA_MOUNT_T_M=" + self.c["SIM_UNITY_CAMERA_TRANSLATION_FLU"] +
                                "\"\nEnvironment=\"LX_CAMERA_MOUNT_RPY_DEG=0,0,0\"\n")
        run(["systemctl", "--user", "daemon-reload"])

    def player_start(self):
        if self.c["SIM_UNITY_MODE"] != "player":
            return False
        unit = "diffagent-unity-" + OWNER
        result = subprocess.run(["systemctl", "--user", "is-active", unit], capture_output=True)
        if result.returncode == 0:
            record = read_json(ARTIFACTS / "player.json", {})
            if record.get("owner") != OWNER or record.get("unit") != unit:
                raise RuntimeError("同名 Player 服务未登记，拒绝复用")
            return False
        argv = ["systemd-run", "--user", "--unit=" + unit, "--collect",
                "--property=WorkingDirectory=" + str(ROOT), "--property=Restart=on-failure",
                ]
        for key in ("DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR"):
            if os.environ.get(key):
                argv.append("--setenv=" + key + "=" + os.environ[key])
        argv += [self.c["SIM_UNITY_PLAYER_PATH"], "-lx-config", str(ARTIFACTS / "config/player.json"),
                 "-logFile", str(ARTIFACTS / "unity-player.log")]
        run(argv)
        atomic_json(ARTIFACTS / "player.json", {"owner": OWNER, "unit": unit})
        return True

    def player_stop(self):
        path = ARTIFACTS / "player.json"
        record = read_json(path, {})
        if record.get("owner") == OWNER:
            if record.get("unit") != "diffagent-unity-" + OWNER:
                raise RuntimeError("Player 服务记录不匹配，拒绝停止")
            run(["systemctl", "--user", "stop", record["unit"]])
            path.unlink(missing_ok=True)

    def logs_manifests(self):
        # 仅匹配本栈业务部署，排除采集器本身避免日志循环。namespace 已独占。
        paths = ",".join(f"/var/log/containers/{name}-*_{self.ns}_*.log" for name in BUSINESS if name != "sim-logs")
        fluent = """[SERVICE]
    Flush 1
    Log_Level info
    Parsers_File parsers.conf
    storage.path /buffer
[INPUT]
    Name tail
    Path PATHS
    DB /buffer/tail.db
    Path_Key filename
    Mem_Buf_Limit 20MB
    storage.type filesystem
    Skip_Long_Lines Off
    Tag sim
[FILTER]
    Name parser
    Match *
    Key_Name log
    Parser cri
    Reserve_Data On
[FILTER]
    Name parser
    Match *
    Key_Name log
    Parser docker
    Reserve_Data On
[FILTER]
    Name lua
    Match *
    Script /fluent-bit/etc/identity.lua
    call identify
[FILTER]
    Name modify
    Match *
    Remove stream
    Remove flags
    Remove filename
[OUTPUT]
    Name tcp
    Match *
    Host 127.0.0.1
    Port 18391
    Format json_lines
    Retry_Limit False
""".replace("PATHS", paths)
        parsers = """[PARSER]
    Name cri
    Format regex
    Regex ^(?<time>[^ ]+) (?<stream>stdout|stderr) (?<flags>[^ ]*) (?<message>.*)$
    Time_Key time
    Time_Format %Y-%m-%dT%H:%M:%S.%L%z
    Time_Keep On
[PARSER]
    Name docker
    Format json
    Time_Key time
    Time_Format %Y-%m-%dT%H:%M:%S.%L
    Time_Keep On
"""
        lua = """function identify(tag, timestamp, record)
  local file = record.filename or ''
  local pod, ns, container = file:match('/([^/]+)_([^_]+)_([^/]+)%-[a-f0-9]+%.log$')
  if pod then record.kubernetes = {pod_name=pod, namespace_name=ns, container_name=container} end
  return 1, timestamp, record
end
"""
        cm = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": self.metadata("sim-log-config"),
              "data": {"fluent-bit.conf": fluent, "parsers.conf": parsers, "identity.lua": lua}}
        deployment = json.loads((ASSETS / "logs.yaml").read_text())
        deployment["metadata"] = self.metadata("sim-logs")
        labels = {"app": "sim-logs", OWNER_KEY: OWNER}
        deployment["spec"]["selector"] = {"matchLabels": labels}
        # 私有 Pod 网络允许不同栈的 relay 使用相同 loopback 端口。
        pod = {"nodeName": self.c["SIM_NODE"], "nodeSelector": {"kubernetes.io/arch": "amd64"},
               "automountServiceAccountToken": False, "containers": [
                   {"name": "fluent-bit", "image": self.image("SIM_FLUENT_IMAGE"),
                    "args": ["-c", "/fluent-bit/etc/fluent-bit.conf"],
                    "volumeMounts": [{"name": "logs", "mountPath": "/var/log", "readOnly": True},
                                     {"name": "config", "mountPath": "/fluent-bit/etc", "readOnly": True},
                                     {"name": "buffer", "mountPath": "/buffer"}]},
                   {"name": "lx-log-relay", "image": self.image("SIM_RELAY_IMAGE"),
                    "env": env_list({"LX_STACK_ID": self.c["LX_STACK_ID"], "ZENOH_ROUTER": self.c["PUBLIC_ZENOHD_ROUTER"]}),
                    "volumeMounts": [{"name": "relay-state", "mountPath": "/run/lx-log-relay"}]}],
               "volumes": [{"name": "logs", "hostPath": {"path": "/var/log", "type": "Directory"}},
                           {"name": "config", "configMap": {"name": "sim-log-config"}},
                           {"name": "buffer", "hostPath": {"path": str(ARTIFACTS / "log-buffer"), "type": "DirectoryOrCreate"}},
                           {"name": "relay-state", "emptyDir": {}}]}
        deployment["spec"]["template"] = {"metadata": {"labels": labels,
                    "annotations": {CONFIG_KEY: self.fingerprint}}, "spec": pod}
        return [cm, deployment]

    def status(self):
        ns = self.get("namespace", self.ns, namespaced=False)
        if not ns:
            print(json.dumps({"namespace": self.ns, "state": "absent"}, ensure_ascii=False))
            return
        self.assert_owner(ns)
        result = {"owner": OWNER, "stack": self.c["LX_STACK_ID"], "namespace": self.ns, "pods": [],
                  "station": {service: self.station_active(service) for service in SERVICES}}
        for pod in self.get("pod").get("items", []):
            self.assert_owner(pod)
            result["pods"].append({"name": pod["metadata"]["name"], "phase": pod.get("status", {}).get("phase"),
                                  "containers": pod.get("status", {}).get("containerStatuses", [])})
        result["planes"] = {}
        for action, deployment, setup in (("odom", "sim-dynamics", "dynamics"), ("sensors", "sim-unity", "unity"),
                                           ("planner", "sim-l3", "l3"), ("planes", "sim-l3", "l3"), ("logs", "sim-l3", "l3"),
                                           ("telemetry", "sim-telemetry", "l3")):
            if self.get("deployment", deployment):
                result["planes"][action] = self.exec_probe(action, deployment, setup, required=False)
        print(json.dumps(result, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("render", "prepare", "up", "down", "reset", "status", "start", "stop", "station-start", "station-stop"))
    args = parser.parse_args()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with (ARTIFACTS / "operation.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("当前工作区已有编排操作正在执行") from exc
        active = read_json(ARTIFACTS / "active-config.json", {})
        if args.action in ("down", "stop", "status") and active:
            if active.get("owner") != OWNER:
                raise RuntimeError("活动配置记录不属于本工作区")
            stack = Stack(active["config"])
        else:
            stack = Stack(config())
        if args.action in ("station-start", "station-stop"):
            stack.station(args.action.split("-")[1])
        elif args.action == "reset":
            stack.down()
            stack.up()
        elif args.action == "start":
            stack.station_preflight()
            stack.up()
            stack.station("start")
        elif args.action == "stop":
            stack.down()
            stack.station("stop")
        else:
            getattr(stack, args.action)()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(f"[station-host-sim] {error}", file=sys.stderr)
        sys.exit(1)
