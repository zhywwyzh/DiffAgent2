#!/usr/bin/env python3
# Entity: drone-container
# Invoked: drone-host-runtime.py 与 k3s readiness
"""真机只读状态观测；不发送飞行指令或申请租约。"""
from __future__ import annotations

import importlib
import json
import math
import os
import runpy
import sys
import threading
import time


def control():
    import zenoh
    cfg = zenoh.Config()
    cfg.insert_json5('mode', '"client"')
    cfg.insert_json5('connect/endpoints', json.dumps([os.environ['ZENOH_ROUTER']]))
    cfg.insert_json5('scouting/multicast/enabled', 'false')
    session = zenoh.open(cfg)
    try:
        values = []
        for reply in session.get('lx/' + os.environ['LX_STACK_ID'] + '/rpc',
                                 payload=b'{"method":"connection.status","params":{}}', timeout=3):
            if reply.ok is not None:
                body = json.loads(reply.ok.payload.to_bytes())
                if body.get('type') == 'rpc_result':
                    values.append(body['result'])
        if len(values) != 1:
            raise RuntimeError('控制面无唯一回复')
        return values[0]
    finally:
        session.close()


def main(action):
    if action == 'dependencies':
        for name in ('rospy', 'actionlib', 'zenoh', 'numpy', 'yaml', 'requests',
                     'dispatcher.tool_plane.zenoh_transport', 'dispatcher.execution.composition'):
            importlib.import_module(name)
        from quadrotor_msgs.msg import ExecuteWaypointsAction, ExecutionState, PositionCommand
        runpy.run_path('/source/l3/ros_packages/dispatcher/dispatcher_node.py', run_name='dependency_probe')
        return {'ok': True, 'position_command_md5': PositionCommand._md5sum}
    import rospy
    import rosgraph
    rospy.init_node('new_l3_runtime_probe', anonymous=True, disable_signals=True)
    master = rosgraph.Master(rospy.get_name())
    if action == 'conflicts':
        publishers, subscribers, _ = master.getSystemState()
        nodes = {node for _, names in publishers + subscribers for node in names}
        conflicts = [node for node in nodes if any(word in node.lower() for word in ('ego_planner', 'dispatcher', 'mission_executive', 'traj_server', 'super_planner', 'diff_planner'))]
        command_publishers = dict(publishers).get(os.environ['DRONE_COMMAND_TOPIC'], [])
        if conflicts or command_publishers:
            raise RuntimeError('已有 L3 或运动输出发布者: ' + repr(sorted(set(conflicts + command_publishers))))
        return {'ok': True, 'conflicts': []}
    topics = {}
    if action == 'maintenance':
        from mavros_msgs.msg import State, ExtendedState
        topics = {'state': (os.environ['DRONE_STATE_TOPIC'], State),
                  'landed': (os.environ['DRONE_EXTENDED_STATE_TOPIC'], ExtendedState)}
    elif action in ('inputs', 'ready', 'shutdown'):
        from nav_msgs.msg import Odometry
        from sensor_msgs.msg import PointCloud2
        topics = {'odom': (os.environ['DRONE_ODOMETRY_TOPIC'], Odometry),
                  'cloud': (os.environ['DRONE_CLOUD_TOPIC'], PointCloud2)}
        if action in ('ready', 'shutdown'):
            from quadrotor_msgs.msg import ExecutionState
            topics['execution'] = ('/planner/execution_state', ExecutionState)
    else:
        raise RuntimeError('未知探针')
    seen = {}
    lock = threading.Lock()

    def receive(key, msg):
        now = time.monotonic()
        stamp = msg.header.stamp.to_sec()
        fresh = math.isfinite(stamp) and -0.2 <= time.time() - stamp < 1.5
        valid = fresh
        if key == 'state':
            valid = fresh and msg.connected and not msg.armed
        elif key == 'landed':
            valid = fresh and msg.landed_state == msg.LANDED_STATE_ON_GROUND
        elif key == 'odom':
            p, v = msg.pose.pose.position, msg.twist.twist.linear
            q = msg.pose.pose.orientation
            valid = fresh and msg.header.frame_id == os.environ['DRONE_WORLD_FRAME'] and all(
                math.isfinite(n) for n in (p.x, p.y, p.z, v.x, v.y, v.z, q.x, q.y, q.z, q.w))
        elif key == 'cloud':
            valid = fresh and msg.header.frame_id == os.environ['DRONE_WORLD_FRAME'] and msg.width * msg.height > 0
        elif key == 'execution':
            valid = fresh and msg.ready
            if action == 'shutdown':
                valid = valid and msg.stop_confirmed and not msg.motion_enabled
        with lock:
            old = seen.get(key)
            count = old['count'] + 1 if old and valid and stamp > old['stamp'] else 0
            since = old['since'] if old and count else now
            seen[key] = {'valid': bool(valid), 'stamp': stamp, 'count': count, 'since': since, 'received': now}

    subscriptions = [rospy.Subscriber(topic, kind, lambda msg, key=key: receive(key, msg), queue_size=1)
                     for key, (topic, kind) in topics.items()]
    publisher = None
    try:
        deadline = time.monotonic() + 8
        ok = False
        while time.monotonic() < deadline:
            with lock:
                now = time.monotonic()
                ok = all(k in seen and seen[k]['valid'] and seen[k]['count'] >= 2 and
                         now - seen[k]['received'] < 1.5 and now - seen[k]['since'] >= 1 for k in topics)
            if ok:
                break
            time.sleep(.05)
        if not ok:
            raise RuntimeError('缺少连续、新鲜、有效输入: ' + repr(seen))
        if action == 'inputs':
            from quadrotor_msgs.msg import PositionCommand
            # 只做 TCPROS 消费握手，不调用 publish，不发任何运动命令。
            publisher = rospy.Publisher(os.environ['DRONE_COMMAND_TOPIC'], PositionCommand, queue_size=1)
            deadline = time.monotonic() + 4
            while publisher.get_num_connections() < 1 and time.monotonic() < deadline:
                time.sleep(.1)
            if publisher.get_num_connections() < 1:
                raise RuntimeError('L2 PositionCommand 消费端未连接或 MD5 不兼容')
            consumers = dict(master.getSystemState()[1]).get(os.environ['DRONE_COMMAND_TOPIC'], [])
            return {'ok': True, 'inputs': seen, 'command_consumers': consumers, 'md5': PositionCommand._md5sum}
        if action in ('ready', 'shutdown'):
            publishers, subscribers, _ = master.getSystemState()
            if not all(dict(subscribers).get('/planner/execute_waypoints/' + suffix) for suffix in ('goal', 'cancel')) or not dict(publishers).get('/planner/execute_waypoints/status'):
                raise RuntimeError('原生 planner action 未就绪')
            claim = control()
            if action == 'shutdown' and (claim.get('owned') or claim.get('state') != 'unowned'):
                raise RuntimeError('关闭前须当前站端释放租约且控制面空闲: ' + repr(claim))
            return {'ok': True, 'inputs': seen, 'control': claim}
        return {'ok': True, 'maintenance': 'landed_disarmed', 'inputs': seen}
    finally:
        if publisher is not None:
            publisher.unregister()
        for sub in subscriptions:
            sub.unregister()
        rospy.signal_shutdown('观测完成')


if __name__ == '__main__':
    try:
        print(json.dumps(main(sys.argv[1]), ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'ok': False, 'reason': str(error)}, ensure_ascii=False))
        sys.exit(1)
