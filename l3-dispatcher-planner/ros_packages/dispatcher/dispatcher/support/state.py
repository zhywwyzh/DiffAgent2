"""核心六态、任务状态及感知算法使用的几何模式。"""

from __future__ import annotations


class COMMAND_TYPE:
    WAIT = 0
    STOP = 1



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
