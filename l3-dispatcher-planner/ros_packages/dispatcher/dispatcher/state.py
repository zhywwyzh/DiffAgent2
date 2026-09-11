"""Dispatcher state: command/dispatcher mission state enums.

These enums drive the dispatcher engine FSM and its base_policy/grasp
siblings. The YAML config-loading utilities live in dispatcher/config.py.
"""

from __future__ import annotations


class COMMAND_TYPE:
    WAIT = 0
    STOP = 1
    GO = 2
    NEXT = 3
    GO_ORIGIN = 4
    AGAIN = 5
    EMERGENCY_STOP = 6
    RESTART = 7
    GET_PRE = 8
    REPLAN = 9
    TAKEOFFLAND = 10
    COMMUNICATE = 11


class DISPATCHER_STATE:
    INIT = 0
    WAIT_FOR_MISSION = 1
    DISPATCH = 2
    WAIT_ACTION_FINISH = 4
    STOP = 5
    POST_ACTION = 8


class COMMAND_STATUS:
    RUNNING = 0
    MISSION_DONE = 1
    ADVANCE_READY = 2


class MISSION_TYPE:
    NOT_MISSION = 0
    NAVIGATION = 1
    TRACK = 2
    BYPASS = 2
    PASS_THROUGH = 3
