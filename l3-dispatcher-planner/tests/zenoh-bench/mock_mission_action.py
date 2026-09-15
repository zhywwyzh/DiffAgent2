#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Record /mission/task goals and reply success immediately (bench stand-in
for the real mission exec). Every goal is appended as one JSON line to
MOCK_MISSION_RECORD (env). Nothing executes physically — no planner, no FCU.
"""

import json
import os

import actionlib
import rospy
from quadrotor_msgs.msg import TaskActionAction, TaskActionGoal, TaskActionResult


def goal_to_dict(goal: TaskActionGoal) -> dict:
    return {
        "prompt": str(getattr(goal, "prompt", "")),
        "frame_id": str(getattr(goal, "frame_id", "")),
        "waypoints": [
            [round(p.x, 4), round(p.y, 4), round(p.z, 4)]
            for p in getattr(goal, "waypoints", [])
        ],
        "yaw": [round(float(y), 4) for y in getattr(goal, "yaw", [])],
        "target_object_id": int(getattr(goal, "target_object_id", 0)),
    }


def main() -> None:
    rospy.init_node("mock_mission_action")
    record_path = os.environ["MOCK_MISSION_RECORD"]
    from std_msgs.msg import String

    fsm_pub = rospy.Publisher("/planner/fsm_state", String, queue_size=5)

    def execute_cb(goal: TaskActionGoal) -> None:
        entry = goal_to_dict(goal)
        with open(record_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        rospy.loginfo("[mock-mission] goal recorded: %s", entry)
        # Mirror the real mission FSM lifecycle so FSM-edge completion
        # gates (smart_nav / return topo) observe EXECING -> FINISH.
        fsm_pub.publish(String(data="EXECING"))

        def finish() -> None:
            fsm_pub.publish(String(data="FINISH"))

        import threading

        threading.Timer(1.0, finish).start()
        result = TaskActionResult()
        result.success = True
        result.reason = 0  # REACHED
        result.detail = "bench mock mission reached"
        server.set_succeeded(result)

    server = actionlib.SimpleActionServer(
        "/mission/task", TaskActionAction, execute_cb, auto_start=False
    )
    server.start()
    rospy.loginfo("[mock-mission] /mission/task recorder up -> %s", record_path)
    rospy.spin()


if __name__ == "__main__":
    main()
