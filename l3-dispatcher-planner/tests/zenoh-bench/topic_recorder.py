#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Record every message on a list of ROS topics to a JSONL file.

Env:
  RECORDER_TOPICS  comma-separated "pkg/MsgType:topic" pairs, e.g.
                   "quadrotor_msgs/TakeoffLand:/px4ctrl/takeoff_land,std_msgs/Empty:/command/emergency_stop"
  RECORDER_RECORD  output JSONL path
"""

import json
import os
import time

import rospy
from roslib.message import get_message_class


def _msg_to_dict(msg) -> dict:
    data = {}
    for slot in getattr(msg, "__slots__", []):
        value = getattr(msg, slot)
        if hasattr(value, "__slots__"):
            continue  # skip nested headers/objects — scalars only
        if isinstance(value, (int, float, str, bool)) or value is None:
            data[slot] = value
        elif isinstance(value, (list, tuple)):
            data[slot] = [
                v if isinstance(v, (int, float, str, bool)) else str(v) for v in value
            ]
    return data


def main() -> None:
    rospy.init_node("topic_recorder")
    record_path = os.environ["RECORDER_RECORD"]
    spec = os.environ["RECORDER_TOPICS"]
    for item in spec.split(","):
        msg_type, topic = item.split(":", 1)
        msg_class = get_message_class(msg_type)
        if msg_class is None:
            raise SystemExit(f"unknown message type: {msg_type}")

        def make_cb(topic_name: str, type_name: str):
            def cb(msg) -> None:
                entry = {
                    "topic": topic_name,
                    "type": type_name,
                    "ts": time.time(),
                    "data": _msg_to_dict(msg),
                }
                with open(record_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry) + "\n")

            return cb

        rospy.Subscriber(topic, msg_class, make_cb(topic, msg_type), queue_size=20)
        rospy.loginfo("[recorder] %s (%s) -> %s", topic, msg_type, record_path)
    rospy.spin()


if __name__ == "__main__":
    main()
