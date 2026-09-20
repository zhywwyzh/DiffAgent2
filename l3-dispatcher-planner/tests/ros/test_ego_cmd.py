"""隔离 ROS master，真实 EGO 输入到 cmd 的集成验收；不启动 cmd 下游。"""
import math
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'ros_packages/dispatcher'), str(ROOT / 'tests/core-boundary'), str(ROOT / 'tests/tool-registry')]
from test_l4_rpc_contract import station


def wait_for(predicate, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.02)
    assert predicate(), 'integration condition timed out'


def test_real_ego_generates_cmd_and_cancels_current_batch(tmp_path, station):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    os.environ['ROS_MASTER_URI'] = f'http://127.0.0.1:{port}'
    os.environ['ROS_IP'] = '127.0.0.1'
    os.environ['ROS_HOME'] = str(tmp_path / 'ros')
    os.environ['ROS_LOG_DIR'] = str(tmp_path / 'logs')
    log = (tmp_path / 'ros-processes.log').open('w')
    processes = []
    stop = threading.Event()
    driver = None
    ports = None
    fleet = bridge = router = None
    try:
        processes.append(subprocess.Popen(['roscore', '-p', str(port)], stdout=log, stderr=log, start_new_session=True))
        import rosgraph
        wait_for(lambda: rosgraph.is_master_online(), 10)
        import rospy
        from nav_msgs.msg import Odometry
        from sensor_msgs import point_cloud2
        from std_msgs.msg import Header
        from sensor_msgs.msg import PointCloud2
        from quadrotor_msgs.msg import PositionCommand
        from dispatcher.ros_adapter.planner_execution_ros import RosFlightPorts
        from dispatcher.execution.ports import Goal, FlightConfig
        from dispatcher.execution.waypoint import WaypointExecution

        rospy.init_node('cmd_boundary_test', anonymous=True, disable_signals=True)
        odometry = rospy.Publisher('/test/odom', Odometry, queue_size=1)
        cloud = rospy.Publisher('/test/cloud', PointCloud2, queue_size=1)
        state = {'position': (0., 0., 1.), 'yaw': 0., 'follow': True}
        commands = []
        def receive(message):
            commands.append(message)
            if state['follow']:
                state['position'] = (message.position.x, message.position.y, message.position.z)
                state['yaw'] = message.yaw
        subscriber = rospy.Subscriber('/setpoint_cmd', PositionCommand, receive, queue_size=100)
        processes.append(subprocess.Popen(['roslaunch', str(ROOT / 'bringup/launch/ego.launch'),
                                           'odometry_topic:=/test/odom', 'cloud_topic:=/test/cloud'],
                                          stdout=log, stderr=log, start_new_session=True))
        points = [(x*.25, y*.25, 0.) for x in range(-16, 17) for y in range(-16, 17)]
        def feed():
            while not stop.wait(.05):
                message = Odometry()
                message.header.stamp = rospy.Time.now()
                message.header.frame_id = 'world'
                message.pose.pose.position.x, message.pose.pose.position.y, message.pose.pose.position.z = state['position']
                message.pose.pose.orientation.z = math.sin(state['yaw']/2)
                message.pose.pose.orientation.w = math.cos(state['yaw']/2)
                odometry.publish(message)
                cloud.publish(point_cloud2.create_cloud_xyz32(Header(stamp=message.header.stamp, frame_id='world'), points))
        driver = threading.Thread(target=feed)
        driver.start()
        ports = RosFlightPorts(odometry_topic='/test/odom')
        wait_for(lambda: ports.snapshot() is not None and ports._goal.get_num_connections() > 0)
        time.sleep(2)
        execution = WaypointExecution(ports, FlightConfig(action_timeout=35))
        batch = execution.start(Goal((0., 0., 1.), math.pi/2))
        result = []
        def finished():
            value = execution.poll()
            if value is not None:
                result.append(value)
            return bool(result)
        wait_for(finished, 40)
        assert result[-1].success, result[-1]
        assert any(abs(message.yaw) > .5 for message in commands)
        assert any(p.batch == batch and p.all_consumed for p in ports.progress())
        # A translation must result in actual trajectory commands from EGO.
        execution.start(Goal((1.5, 0., 1.), math.pi/2))
        result.clear()
        wait_for(finished, 40)
        assert result[-1].success, result[-1]
        assert any(message.position.x > .5 for message in commands)
        # Dispatcher replaces the moving batch with a hold goal through the same goal inlet.
        state['follow'] = False
        execution.start(Goal((3., 0., 1.), math.pi/2))
        time.sleep(.3)
        execution.cancel()
        start = len(commands)
        wait_for(lambda: len(commands) >= start + 10)
        assert execution.poll() is None
        recent = commands[-5:]
        assert all(math.isfinite(message.position.x) and abs(message.velocity.x) < .1
                   and abs(message.velocity.y) < .1 and abs(message.yaw_dot) < .1 for message in recent)
        execution.stop()
        start = len(commands)
        wait_for(lambda: len(commands) >= start + 10)
        assert all(abs(message.velocity.x) < .1 and abs(message.velocity.y) < .1 for message in commands[-5:])
        # Run all six concrete skills through the actual dispatcher FSM and ROS ports.
        from dispatcher.engine import DispatcherEngine
        from dispatcher.execution.composition import install_flight
        from dispatcher.tool_plane.model import ToolCall, SkillCommand
        from quadrotor_msgs.msg import TakeoffLand
        from test_core_boundary import Channels, Log

        class Clock:
            def __init__(self):
                self.stopped = threading.Event()
            def rate(self, hz):
                return self
            def sleep(self):
                self.stopped.wait(.02)
            def is_shutdown(self):
                return self.stopped.is_set()
            def request_shutdown(self, reason):
                self.stopped.set()

        channels = Channels()
        clock = Clock()
        engine = DispatcherEngine(headless=True, telemetry_node_name='flight-test',
            telemetry_level='error', telemetry_stdout_en=False, log_dir_root=tmp_path,
            channels=channels, clock=clock, log=Log(), get_frame_snapshot=lambda: None,
            get_sensor_input_health=lambda: {})
        host, dispose = install_flight(engine, ports, FlightConfig(ground_z=0, action_timeout=35))
        flight_commands = []
        flight_sub = rospy.Subscriber('/px4ctrl/takeoff_land', TakeoffLand,
                                      lambda message: flight_commands.append(message.takeoff_land_cmd), queue_size=10)
        wait_for(lambda: ports._flight.get_num_connections() > 0)
        fsm = threading.Thread(target=engine.run_inference)
        fsm.start()
        try:
            def invoke(name, arguments):
                channels.phases.clear()
                call = ToolCall(name, 'basic_flight.' + name, arguments, 'test', name)
                engine.tools.start_tool_workflow(call, SkillCommand(call))
                wait_for(lambda: any(p['phase'] in ('done', 'fail') for p in channels.phases), 40)
                terminal = [p for p in channels.phases if p['phase'] in ('done', 'fail')]
                assert len(terminal) == 1 and terminal[0]['phase'] == 'done', terminal

            origin_xy = state['position'][:2]
            state['position'] = (*origin_xy, 0.)
            wait_for(lambda: ports.snapshot().position[2] == 0.)
            invoke('takeoff', {})
            wait_for(lambda: flight_commands == [TakeoffLand.TAKEOFF])
            # Controlled airborne input, not a PX4/controller under test.
            state['position'] = (*origin_xy, 1.)
            wait_for(lambda: ports.snapshot().position[2] == 1.)
            host.state()
            state['follow'] = True
            invoke('translate', {'direction': 'forward', 'distance_m': 1.2})
            invoke('rotate', {'yaw_delta_deg': -90})
            invoke('return', {})
            assert math.dist(state['position'][:2], origin_xy) < .6
            invoke('emergency_stop', {})
            invoke('land', {})
            wait_for(lambda: flight_commands[-1] == TakeoffLand.LAND)
        finally:
            clock.request_shutdown('test completed')
            fsm.join(timeout=3)
            dispose()
            flight_sub.unregister()
        # Finally exercise the production composition, default registry and real l4 wire.
        os.killpg(processes[-1].pid, signal.SIGINT)
        processes[-1].wait(timeout=8)
        import json
        import zenoh
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            router_port = sock.getsockname()[1]
        endpoint = f'tcp/127.0.0.1:{router_port}'
        config = zenoh.Config()
        config.insert_json5('mode', '"peer"')
        config.insert_json5('listen/endpoints', json.dumps([endpoint]))
        config.insert_json5('scouting/multicast/enabled', 'false')
        router = zenoh.open(config)
        environment = dict(os.environ, LX_STACK_ID='test/basic-flight', ZENOH_ROUTER=endpoint)
        rospy.set_param('/dispatcher/log_dir', str(tmp_path / 'dispatcher'))
        state['follow'] = False
        state['position'] = (0., 0., 0.)
        state['yaw'] = 0.
        flight_commands.clear()
        flight_sub = rospy.Subscriber('/px4ctrl/takeoff_land', TakeoffLand,
            lambda message: flight_commands.append(message.takeoff_land_cmd), queue_size=10)
        processes.append(subprocess.Popen(['roslaunch', str(ROOT / 'bringup/launch/basic_flight.launch'),
            'ground_z:=0', 'odometry_topic:=/test/odom', 'cloud_topic:=/test/cloud',
            'python_executable:=' + sys.executable], env=environment,
            stdout=log, stderr=log, start_new_session=True))
        fleet = station['fleet'].FleetController(station_id='flight-station', router=endpoint,
                                                renew_interval_s=1, query_timeout_s=2)
        fleet.start()
        wait_for(lambda: 'test/basic-flight' in fleet._inventory, 20)
        lease = fleet.acquire('test/basic-flight')
        bridge = station['rpc_bridge'].RpcFlightBridge(lambda *args: None)
        bridge._router = endpoint
        bridge.bind_connection('test/basic-flight', **{key: lease[key] for key in
            ('station_id', 'station_instance_id', 'lease_id')})
        time.sleep(2)
        def rpc(name, arguments):
            record = station['models'].ExecutionRecord(call_id='rpc-' + name,
                method='basic_flight.' + name, params=arguments, approved=True)
            bridge.register([record])
            assert bridge.publish_call(record.call_id, chat_id='integration'), bridge.last_publish_error
            wait_for(lambda: record.phase == 'done', 40)
            assert record.outcome.ok, record.outcome
        rpc('takeoff', {})
        wait_for(lambda: flight_commands == [TakeoffLand.TAKEOFF])
        state['position'] = (0., 0., 1.)
        time.sleep(.2)
        state['follow'] = True
        rpc('translate', {'direction': 'forward', 'distance_m': 1.2})
        rpc('rotate', {'yaw_delta_deg': 90})
        rpc('return', {})
        rpc('emergency_stop', {})
        rpc('land', {})
        wait_for(lambda: flight_commands[-1] == TakeoffLand.LAND)
        flight_sub.unregister()
        subscriber.unregister()
    finally:
        stop.set()
        if driver:
            driver.join(timeout=2)
        if fleet:
            fleet.stop()
        if bridge:
            bridge.stop()
        if router:
            router.close()
        if ports:
            ports.close()
        for process in reversed(processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
        log.close()
