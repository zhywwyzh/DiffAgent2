#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zenoh-bench routing matrix (tools spec v1): registry -> REAL ROS outputs.

Run INSIDE the l3 amd64 container (ROS + devel sourced). Starts roscore +
mock sensors + mock VLM + mission-goal recorder + topic recorder + the real
composer (dispatcher_node.py hosting ToolControlPlane), then exercises the tools
plane and asserts the REAL executable ROS outputs. No px4ctrl, no planner,
no FCU — the mock mission action server replies success immediately, so
nothing executes physically.

Matrix:
  tools/list          -> exactly the nine registered tools, stable revision
  connection/acquire  -> lease accepted; second acquire connection_busy
  connection/renew    -> owner renew accepted; claim-free status owned
  ownerless / foreign calls -> rejected connection_not_owner
  flight.takeoff      -> /px4ctrl/takeoff_land cmd=1            + done
  flight.land         -> /px4ctrl/takeoff_land cmd=2            + done
  flight.emergency_stop -> /command/emergency_stop + hold goal  + done
  flight.translate x2 -> /mission/task goal waypoints           + done
  flight.rotate x2    -> /mission/task goal yaw                 + done
  flight.return       -> /mission/task goal (0,0,1)             + done
  navigation.vla_reach-> mock VLM -> /mission/task goal         + done
  scene.map_search    -> folder graph object resolved           + done
  scene.navigate      -> object-id goal via /mission/task       + done
  reserved ids        -> tools/call rejected (tool_not_registered / identity)
  task/start|events   -> keys no longer declared (no reply)
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

BENCH_DIR = Path(__file__).resolve().parent
WORKDIR = Path(os.environ.get("BENCH_WORKDIR", "/tmp/zenoh-bench"))
ROUTER = os.environ.get("ZENOH_ROUTER", "tcp/public_zenohd_router:7447")
STACK_ID = os.environ.get("BENCH_STACK_ID", f"real/bench-{uuid.uuid4().hex[:6]}")
PREFIX = f"lx/{STACK_ID}"

TAKEOFF_LAND_SPEC = "quadrotor_msgs/TakeoffLand:/px4ctrl/takeoff_land"
EMERGENCY_SPEC = "std_msgs/Empty:/command/emergency_stop"

EXPECTED_TOOLS = {
    "navigation.vla_reach",
    "scene.map_search",
    "scene.navigate",
    "flight.takeoff",
    "flight.land",
    "flight.translate",
    "flight.rotate",
    "flight.return",
    "flight.emergency_stop",
    "scene_nav.graph.list",
    "scene_nav.graph.select",
    "scene_nav.graph.save",
    "scene_nav.graph.objects",
    "scene_nav.graph.object_pose",
}

FAILURES: list[str] = []


def sh(cmd: list[str], **kw) -> subprocess.Popen:
    env = dict(os.environ)
    master_port = os.environ.get("ROS_MASTER_PORT", "29311")
    env.setdefault("ROS_MASTER_URI", f"http://127.0.0.1:{master_port}")
    env.setdefault("ROS_HOSTNAME", "127.0.0.1")
    env.update(kw.pop("extra_env", {}))
    return subprocess.Popen(
        cmd,
        env=env,
        stdout=open(WORKDIR / (kw.pop("log_name", "node.log")), "w"),
        stderr=subprocess.STDOUT,
        **kw,
    )


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def trunc(path: Path) -> None:
    path.write_text("")


class ToolClient:
    def __init__(self) -> None:
        conf = zenoh.Config()
        conf.insert_json5("mode", '"client"')
        conf.insert_json5("connect/endpoints", json.dumps([ROUTER]))
        conf.insert_json5("scouting/multicast/enabled", "false")
        self.session = zenoh.open(conf)
        self._cursor = 0
        self.identity: dict = {}

    def acquire(self) -> dict:
        reply = self.call(
            "connection/acquire",
            {
                "station_id": "station-bench",
                "station_instance_id": f"stn_{uuid.uuid4().hex[:8]}",
            },
        )
        assert reply is not None and reply.get("__err__") is None, f"acquire failed: {reply}"
        assert reply.get("accepted") is True and reply.get("type") == "connection_lease", reply
        self.identity = {k: reply[k] for k in ("station_id", "station_instance_id", "lease_id")}
        return reply

    def call(self, suffix: str, params: dict, timeout: float = 10.0):
        replies = self.session.get(
            f"{PREFIX}/{suffix}",
            payload=json.dumps(params, ensure_ascii=False).encode(),
            timeout=timeout,
        )
        for reply in replies:
            if reply.ok is not None:
                return json.loads(reply.ok.payload.to_bytes())
            if reply.err is not None:
                return {"__err__": json.loads(reply.err.payload.to_bytes())}
        return None

    def error_reason(self, result: dict) -> str:
        err = result.get("__err__") or {}
        data = err.get("data") or {}
        return str(data.get("reason") or err.get("message") or "")

    def admit(self, name: str, arguments: dict, display: str = "") -> str:
        call_id = f"call-{uuid.uuid4().hex[:8]}"
        ack = self.call(
            "tools/call",
            {
                "call_id": call_id,
                "name": name,
                "arguments": arguments,
                "context": {
                    "flight_session_id": "flight_bench",
                    "step_id": call_id,
                    "display_text": display,
                    **self.identity,
                },
            },
        )
        assert ack is not None, f"{name}: no ack reply"
        assert ack.get("__err__") is None, f"{name}: rejected {ack}"
        assert ack.get("accepted") is True, ack
        assert ack.get("call_id") == call_id, ack
        return call_id

    def wait_terminal(self, call_id: str, timeout: float = 30.0) -> dict | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.call(
                "tools/events",
                {"after_seq": self._cursor, "limit": 200, **self.identity},
            )
            if result and not result.get("__err__"):
                for ev in result.get("events", []):
                    self._cursor = max(self._cursor, int(ev.get("seq", 0)))
                    if ev.get("call_id") == call_id and ev.get("status") in (
                        "done",
                        "fail",
                    ):
                        return ev
            time.sleep(0.3)
        return None


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""), flush=True)
    if not ok:
        FAILURES.append(name)


def mission_goals() -> list[dict]:
    return read_jsonl(WORKDIR / "mission.jsonl")


def topics() -> list[dict]:
    return read_jsonl(WORKDIR / "topics.jsonl")


def wait_mission_goals(n: int, timeout: float = 15.0) -> list[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        goals = mission_goals()
        if len(goals) >= n:
            return goals
        time.sleep(0.3)
    return mission_goals()


def approx(a, b, tol=0.15) -> bool:
    return abs(float(a) - float(b)) <= tol


def write_scene_fixture() -> Path:
    root = WORKDIR / "scene_graph" / "bench_room"
    root.mkdir(parents=True, exist_ok=True)
    graph = {
        "objects": [
            {
                "id": 7,
                "label": "bench_box",
                "pos": [2.0, 0.0, 1.0],
                "is_alive": True,
            }
        ]
    }
    (root / "scene_graph.json").write_text(json.dumps(graph))
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "saved_at": "2026-08-30T00:00:00Z",
                "summary": {"poly_count": 0, "area_count": 0, "object_count": 1},
            }
        )
    )
    return WORKDIR / "scene_graph"


def main() -> int:
    WORKDIR.mkdir(parents=True, exist_ok=True)
    mission_record = WORKDIR / "mission.jsonl"
    topics_record = WORKDIR / "topics.jsonl"
    trunc(mission_record)
    trunc(topics_record)
    scene_dir = write_scene_fixture()

    procs: list[subprocess.Popen] = []
    master_port = os.environ.get("ROS_MASTER_PORT", "29311")
    os.environ["ROS_MASTER_URI"] = f"http://127.0.0.1:{master_port}"
    os.environ.setdefault("ROS_HOSTNAME", "127.0.0.1")

    print(f"[bench] stack={STACK_ID} router={ROUTER}", flush=True)
    procs.append(sh(["roscore", "-p", master_port], log_name="roscore.log"))
    time.sleep(3)

    os.environ["MOCK_MISSION_RECORD"] = str(mission_record)
    procs.append(
        sh(
            [sys.executable, str(BENCH_DIR / "mock_mission_action.py")],
            log_name="mock_mission.log",
        )
    )
    os.environ["RECORDER_RECORD"] = str(topics_record)
    os.environ["RECORDER_TOPICS"] = f"{TAKEOFF_LAND_SPEC},{EMERGENCY_SPEC}"
    procs.append(
        sh(
            [sys.executable, str(BENCH_DIR / "topic_recorder.py")],
            log_name="recorder.log",
        )
    )
    os.environ["MOCK_VLM_PORT"] = "18110"
    procs.append(
        sh(
            [sys.executable, str(BENCH_DIR / "mock_vlm.py")],
            log_name="mock_vlm.log",
        )
    )
    procs.append(
        sh(
            [sys.executable, str(BENCH_DIR.parent / "dry-run" / "mock_sensors.py")],
            log_name="sensors.log",
        )
    )
    time.sleep(2)

    # Agent env: local mock VLM (SiliconFlow disabled), folder scene graph.
    os.environ["SILICONFLOW_API_KEY"] = ""
    os.environ["VLM_BBOX_BASE_URL"] = "http://127.0.0.1:18110/v1"
    os.environ["VLM_IFELSE_BASE_URL"] = "http://127.0.0.1:18110/v1"
    os.environ["L3_SCENE_GRAPH_DIR"] = str(scene_dir)
    os.environ["SCENE_GRAPH_LOAD_NAME"] = "bench_room"
    os.environ["ZENOH_ROUTER"] = ROUTER
    os.environ["LX_STACK_ID"] = STACK_ID
    procs.append(
        sh(
            ["roslaunch", str(BENCH_DIR / "bench.launch")],
            log_name="dispatcher_node.log",
        )
    )

    # Wait for middleware health (composer supervisor retries until zenoh up).
    client = ToolClient()
    deadline = time.monotonic() + 60
    healthy = False
    while time.monotonic() < deadline:
        result = client.call("health", {})
        if result and result.get("ok"):
            healthy = True
            break
        time.sleep(1.0)
    if not healthy:
        print("[bench] FAIL: middleware never became healthy")
        return 1
    print("[bench] middleware healthy", flush=True)
    time.sleep(2.0)  # let the sensor gate settle

    # ---------- tools/list ----------
    listing = client.call("tools/list", {})
    check(
        "tools/list returns the registry",
        bool(listing) and "__err__" not in listing,
        str(listing)[:80],
    )
    listed = {tool["name"] for tool in (listing or {}).get("tools", [])}
    check(
        "tools/list exposes exactly the fourteen tools",
        listed == EXPECTED_TOOLS,
        str(sorted(listed)),
    )
    revision_again = client.call("tools/list", {}) or {}
    check(
        "tools/list revision is stable",
        listing.get("revision") == revision_again.get("revision"),
    )

    # ---------- connection lease (fleet spec v1) ----------
    foreign = {
        "station_id": "station-other",
        "station_instance_id": "stn_other",
        "lease_id": "lease_absent",
    }
    ownerless = client.call(
        "tools/call",
        {
            "call_id": "call-ownerless",
            "name": "flight.takeoff",
            "arguments": {},
            "context": {"flight_session_id": "s", "step_id": "x"},
        },
    )
    check(
        "ownerless tools/call rejected",
        client.error_reason(ownerless or {}) == "connection_not_owner",
        str(ownerless),
    )
    lease = client.acquire()
    check(
        "connection/acquire returns the lease",
        lease.get("ttl_ms") == 15000 and bool(client.identity),
        str(lease),
    )
    busy = client.call(
        "connection/acquire",
        {"station_id": "station-second", "station_instance_id": "stn_second"},
    )
    check(
        "second acquire rejected connection_busy",
        client.error_reason(busy or {}) == "connection_busy",
        str(busy),
    )
    renewed = client.call("connection/renew", {**client.identity})
    check(
        "connection/renew accepted for the owner",
        isinstance(renewed, dict) and renewed.get("accepted") is True,
        str(renewed),
    )
    status = client.call("connection/status", {})
    check(
        "connection/status is claim-free and owned",
        isinstance(status, dict)
        and status.get("owned") is True
        and status.get("station_id") == "station-bench",
        str(status),
    )

    # ---------- protocol negatives ----------
    rejected = client.call(
        "tools/call",
        {
            "call_id": "call-reserved-27",
            "name": "flight.look_around",
            "arguments": {},
            "context": {"flight_session_id": "s", "step_id": "x"},
        },
    )
    check(
        "reserved task id rejected",
        client.error_reason(rejected or {}) == "tool_not_registered",
        str(rejected),
    )

    mismatch = client.call(
        "tools/call",
        {
            "call_id": "call-mismatch",
            "name": "flight.takeoff",
            "arguments": {},
            "context": {"flight_session_id": "s", "step_id": "x"},
        },
    )
    check(
        "identity mismatch rejected",
        client.error_reason(mismatch or {}) == "tool_identity_mismatch",
        str(mismatch),
    )

    cancel_unknown = client.call("tools/cancel", {"call_id": "call-unknown", **client.identity})
    check(
        "cancel unknown call rejected",
        client.error_reason(cancel_unknown or {}) == "call_not_found",
        str(cancel_unknown),
    )

    retired = client.call("task/start", {}, timeout=2.0)
    check("task/start key retired (no reply)", retired is None, str(retired))
    retired = client.call("task/events", {"after_seq": 0, "limit": 1}, timeout=2.0)
    check("task/events key retired (no reply)", retired is None, str(retired))

    non_owner = client.call(
        "tools/call",
        {
            "call_id": "call-foreign",
            "name": "flight.takeoff",
            "arguments": {},
            "context": {"flight_session_id": "s", "step_id": "x", **foreign},
        },
    )
    check(
        "non-owner tools/call rejected",
        client.error_reason(non_owner or {}) == "connection_not_owner",
        str(non_owner),
    )

    # ---------- flight.takeoff ----------
    trunc(topics_record)
    trunc(mission_record)
    call_id = client.admit("flight.takeoff", {}, "Takeoff")
    ev = client.wait_terminal(call_id)
    tl = [t for t in topics() if t["topic"] == "/px4ctrl/takeoff_land"]
    check(
        "TAKEOFF routes to /px4ctrl/takeoff_land cmd=1",
        bool(tl) and tl[-1]["data"].get("takeoff_land_cmd") == 1,
        f"msgs={tl}",
    )
    check("TAKEOFF no mission goal", len(mission_goals()) == 0)
    check("TAKEOFF terminal done", ev is not None and ev["status"] == "done", str(ev))

    # ---------- flight.land ----------
    trunc(topics_record)
    call_id = client.admit("flight.land", {}, "Land")
    ev = client.wait_terminal(call_id)
    tl = [t for t in topics() if t["topic"] == "/px4ctrl/takeoff_land"]
    check(
        "LAND routes to /px4ctrl/takeoff_land cmd=2",
        bool(tl) and tl[-1]["data"].get("takeoff_land_cmd") == 2,
        f"msgs={tl}",
    )
    check("LAND terminal done", ev is not None and ev["status"] == "done", str(ev))

    # ---------- flight.emergency_stop ----------
    trunc(topics_record)
    trunc(mission_record)
    call_id = client.admit("flight.emergency_stop", 25, {}, "Stop")
    ev = client.wait_terminal(call_id)
    est = [t for t in topics() if t["topic"] == "/command/emergency_stop"]
    check(
        "EMERGENCY_STOP routes to /command/emergency_stop",
        len(est) >= 1,
        f"msgs={len(est)}",
    )
    check(
        "EMERGENCY_STOP hold-position goal on /mission/task",
        len(mission_goals()) >= 1,
        f"goals={len(mission_goals())}",
    )
    check(
        "EMERGENCY_STOP terminal done",
        ev is not None and ev["status"] == "done",
        str(ev),
    )

    # ---------- flight.translate ----------
    trunc(mission_record)
    call_id = client.admit(
        "flight.translate",
        {"direction": "forward", "distance_m": 2.0},
        "Forward 2m",
    )
    ev = client.wait_terminal(call_id)
    goals = wait_mission_goals(1)
    wp = goals[-1]["waypoints"][0] if goals else None
    check(
        "TRANSLATE forward 2m -> goal (2,0,1)",
        wp is not None and approx(wp[0], 2.0) and approx(wp[1], 0.0) and approx(wp[2], 1.0),
        f"wp={wp}",
    )
    check("TRANSLATE terminal done", ev is not None and ev["status"] == "done", str(ev))

    trunc(mission_record)
    call_id = client.admit("flight.translate", {"direction": "left", "distance_m": 1.0}, "Left 1m")
    ev = client.wait_terminal(call_id)
    goals = wait_mission_goals(1)
    wp = goals[-1]["waypoints"][0] if goals else None
    check(
        "TRANSLATE left 1m -> goal (0,1,1)",
        wp is not None and approx(wp[0], 0.0) and approx(wp[1], 1.0) and approx(wp[2], 1.0),
        f"wp={wp}",
    )

    # ---------- flight.rotate ----------
    trunc(mission_record)
    call_id = client.admit("flight.rotate", {"yaw_delta_deg": 90}, "Turn left 90")
    ev = client.wait_terminal(call_id)
    goals = wait_mission_goals(1)
    yaw = goals[-1]["yaw"] if goals else []
    check(
        "ROTATE +90 -> goal yaw ~ +pi/2",
        bool(yaw) and approx(yaw[-1], 1.5708, 0.1),
        f"yaw={yaw}",
    )
    check("ROTATE terminal done", ev is not None and ev["status"] == "done", str(ev))

    # ---------- flight.return ----------
    trunc(mission_record)
    call_id = client.admit("flight.return", 24, {"target": "origin"}, "Return origin")
    ev = client.wait_terminal(call_id, timeout=40.0)
    goals = wait_mission_goals(1)
    wp = goals[-1]["waypoints"][0] if goals else None
    check(
        "RETURN origin -> goal (0,0,1)",
        wp is not None and approx(wp[0], 0.0) and approx(wp[1], 0.0) and approx(wp[2], 1.0),
        f"wp={wp}",
    )
    check("RETURN terminal done", ev is not None and ev["status"] == "done", str(ev))

    # ---------- idempotent duplicate call ----------
    dup_payload = {
        "call_id": "call-dup",
        "name": "flight.takeoff",
        "arguments": {},
        "context": {"flight_session_id": "s", "step_id": "dup", **client.identity},
    }
    first_ack = client.call("tools/call", dup_payload)
    ev = client.wait_terminal("call-dup")
    second_ack = client.call("tools/call", dup_payload)
    check(
        "duplicate call_id replays the original ack",
        first_ack == second_ack and ev is not None,
        f"{first_ack} vs {second_ack}",
    )

    # ---------- navigation.vla_reach (mock VLM) ----------
    trunc(mission_record)
    call_id = client.admit(
        "navigation.vla_reach",
        {"object": "bench_box", "prompt": "Reach the bench_box"},
        "Reach the bench_box",
    )
    ev = client.wait_terminal(call_id, timeout=60.0)
    goals = wait_mission_goals(1, timeout=20.0)
    check(
        "VLA_REACH dispatches a mission goal",
        bool(goals) and len(goals[-1]["waypoints"]) >= 1,
        f"goals={len(goals)}",
    )
    check("VLA_REACH terminal done", ev is not None and ev["status"] == "done", str(ev))

    # ---------- scene.map_search ----------
    call_id = client.admit("scene.map_search", {"object": "bench_box"}, "bench_box")
    ev = client.wait_terminal(call_id, timeout=30.0)
    check(
        "MAP_SEARCH resolves folder object and finishes",
        ev is not None and ev["status"] == "done",
        str(ev),
    )

    # ---------- scene.navigate ----------
    trunc(mission_record)
    call_id = client.admit("scene.navigate", {"object_id": 7}, "Navigate to bench_box")
    ev = client.wait_terminal(call_id, timeout=45.0)
    goals = wait_mission_goals(1, timeout=20.0)
    object_goals = [g for g in goals if int(g.get("target_object_id", -1)) >= 0]
    check(
        "SCENE_NAVIGATE dispatches object-id goal",
        bool(object_goals),
        f"goals={goals}",
    )
    check(
        "SCENE_NAVIGATE terminal done",
        ev is not None and ev["status"] == "done",
        str(ev),
    )

    # ---------- cancellation on a live call (best effort) ----------
    trunc(mission_record)
    call_id = client.admit("flight.rotate", {"yaw_delta_deg": -180}, "U-turn")
    cancel_ack = client.call("tools/cancel", {"call_id": call_id, "reason": "bench_cancel"})
    ev = client.wait_terminal(call_id, timeout=15.0)
    cancelled_or_done = ev is not None and ev["status"] in ("done", "fail")
    check(
        "cancel on live call yields one terminal",
        isinstance(cancel_ack, dict) and cancel_ack.get("type") == "tool_cancel_ack" and cancelled_or_done,
        f"ack={cancel_ack} ev={ev}",
    )

    # ---------- summary ----------
    for proc in procs:
        try:
            proc.terminate()
        except Exception:
            pass
    if FAILURES:
        print(f"\n[BENCH] {len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("\n[BENCH] ALL ROUTING MATRIX PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
