"""核心边界门禁及真实 FSM 的无 ROS 回归。"""

from __future__ import annotations

import ast
import importlib
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "l3-dispatcher-planner/ros_packages/dispatcher"
sys.path.insert(0, str(PACKAGE))

from dispatcher.engine import DispatcherEngine
from dispatcher.core.telemetry import RunTelemetry
from dispatcher.tools.model import SkillCommand, ToolCall
from dispatcher.tools.skill_api import SkillBase, SkillVerdict
from dispatcher.utils.state import COMMAND_STATUS, DISPATCHER_STATE


class Channels:
    def __init__(self):
        self.phases = []
        self.commands = []
        self.stops = 0

    def publish_task_phase(self, payload):
        self.phases.append(json.loads(payload))

    def publish_command_content(self, payload):
        self.commands.append(json.loads(payload))

    def publish_emergency_stop(self):
        self.stops += 1

    def publish_if_handle_yaw(self, enabled):
        pass


class Log:
    def __init__(self):
        self.messages = []

    def info(self, message, *args):
        self.messages.append(message % args if args else message)

    warn = err = info

    def warn_throttle(self, period, message, *args):
        self.info(message, *args)


class Clock:
    def __init__(self):
        self.polls = 0
        self.stopped = False

    def rate(self, hz):
        assert hz == 20
        return self

    def sleep(self):
        pass

    def is_shutdown(self):
        self.polls += 1
        return self.stopped or self.polls > 30

    def request_shutdown(self, reason):
        self.stopped = True


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr("dispatcher.engine.time.sleep", lambda _: None)
    node = DispatcherEngine(
        headless=True, telemetry_node_name="test", telemetry_level="error",
        telemetry_stdout_en=False, log_dir_root=tmp_path,
        channels=Channels(), clock=Clock(), log=Log(),
        get_frame_snapshot=lambda: None,
        get_sensor_input_health=lambda: {"rgb": ("rgb", None), "cloud": ("cloud", 8.0)},
    )
    node.events = []
    node.runlog.emit = lambda level, event, **fields: node.events.append((event, fields))
    return node


def command(name="test.tool", step="first"):
    return SkillCommand(ToolCall(
        call_id=step, name=name, arguments={}, flight_session_id="test", step_id=step,
    ))


def prepare(engine, entries):
    config = [(entry.call.name, entry) for entry in entries]
    engine.prompt_queue.sync_task_buffers_from_prepare(config)
    engine.tools._activate_tool_call(entries[0].call)
    engine.prompt_queue.pop_next_task()
    return config


def bind_owner(engine, *, verdict=SkillVerdict.IDLE, gate=None):
    owner = SimpleNamespace(
        synchronous=False, plan_tick=lambda cmd: True,
        action_done_gate=lambda: gate, on_action_result=lambda result: verdict,
        wait_action_tick=lambda: None, on_global_stop=lambda: None, on_cancel=lambda: None,
    )
    engine.skills.register("test.tool", owner)
    engine.skills.dispatch_plan(command())
    engine.skills.snapshot_owner()
    return owner


def test_core_def_whitelist_and_six_states():
    spec = (ROOT / "specs/implemented/inner/l3-core-boundary.spec.md").read_text()
    allowed = {}
    for row in spec.splitlines():
        if row.startswith("| `") and ".py`" in row:
            module, methods = row.split("|")[1:3]
            allowed[re.search(r"`([^`]+)`", module)[1]] = {
                name.rsplit(".", 1)[-1] for name in re.findall(r"`([^`]+)`", methods)
            }
    paths = [PACKAGE / "dispatcher/engine.py", *(PACKAGE / "dispatcher/core").glob("*.py")]
    for path in paths:
        relative = str(path.relative_to(PACKAGE / "dispatcher"))
        tree = ast.parse(path.read_text())
        functions = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert functions <= allowed.get(relative, set()), (relative, functions - allowed.get(relative, set()))
        for function in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            nested = [n.name for stmt in function.body for n in ast.walk(stmt) if isinstance(n, ast.FunctionDef)]
            assert not nested or (relative == "core/state_ledger.py" and function.name == "set_state" and nested == ["_state_name"]) or (relative == "core/skill_router.py" and function.name == "register" and nested == ["dispose"])
    assert len([key for key in vars(DISPATCHER_STATE) if not key.startswith("_")]) == 6


def test_import_closure_has_no_domain_or_ros():
    pending = [PACKAGE / "dispatcher/engine.py", *(PACKAGE / "dispatcher/core").glob("*.py")]
    visited = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        for node in ast.walk(ast.parse(path.read_text())):
            imports = []
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, (path, "相对导入必须先纳入闭包解析")
                imports = [node.module or ""]
            for name in imports:
                assert not any(part.endswith("_msgs") for part in name.split(".")), (path, name)
                assert not name.startswith(("rospy", "cv_bridge", "dispatcher.perception", "dispatcher.ros_adapter",
                                            "dispatcher.skills", "dispatcher.tools.vla", "dispatcher.tools.flight",
                                            "dispatcher.tools.scene_nav")), (path, name)
                if name.startswith("dispatcher."):
                    dependency = PACKAGE / (name.replace(".", "/") + ".py")
                    if not dependency.exists():
                        dependency = PACKAGE / name.replace(".", "/") / "__init__.py"
                    assert dependency.is_file(), (path, name)
                    pending.append(dependency)


def test_core_imports_in_process_without_ros():
    subprocess.run([
        sys.executable, "-c",
        "import sys; sys.path.insert(0, sys.argv[1]); import dispatcher.engine; "
        "assert not any(n == 'rospy' or '_msgs' in n for n in sys.modules)", str(PACKAGE),
    ], check=True)


def test_core_channels_and_dispatcher_numbering():
    allowed = {"publish_emergency_stop", "publish_if_handle_yaw", "publish_command_content", "publish_task_phase"}
    for path in [PACKAGE / "dispatcher/engine.py", *(PACKAGE / "dispatcher/core").glob("*.py")]:
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "channels"):
                assert node.func.attr in allowed, (path, node.func.attr)
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""
            assert not re.search(r"(?:task|mission)_?(?:id|num|number)$", name, re.I), (path, name)


@pytest.mark.parametrize("registered,handled", [(False, False), (True, False)])
def test_real_fsm_unregistered_never_succeeds(engine, registered, handled):
    entry = command()
    prepare(engine, [entry])
    if registered:
        engine.skills.register(entry.call.name, SimpleNamespace(synchronous=False, requires_perception=False,
                                                                plan_tick=lambda cmd: handled))
    engine._run_inference_loop()
    assert engine.dispatcher_state == DISPATCHER_STATE.WAIT_FOR_MISSION
    assert engine.prompt_queue.head_command()[1] is entry
    assert engine.ledger.failed
    assert [p["phase"] for p in engine.channels.phases] == ["fail"]
    assert entry.call.name in engine.channels.phases[0]["error"]["message"]
    transitions = [fields for event, fields in engine.events if event == "dispatcher_state_transition"]
    assert transitions[-1]["reason"] == "plan:tool_not_registered"
    assert all(fields["reason"] and fields["from_state"] and fields["to_state"] for fields in transitions)
    engine.prompt_queue.prepare_content.clear()
    engine.prompt_queue.load_next_prompt()
    assert [p["phase"] for p in engine.channels.phases] == ["fail"]


def test_router_uses_call_name_and_owner_snapshot(engine):
    owner = bind_owner(engine)
    engine.tools._active_tool_name = "test.tool"
    assert engine.skills.validate_active_tool(command().call)
    assert not engine.skills.validate_active_tool(command("missing").call)
    assert not engine.skills.dispatch_plan(command(""))
    engine.skills.register("test.tool", object())
    assert engine.skills.owner_skill() is owner
    engine.skills._action_owner_skill = None
    assert engine.skills.owner_skill() is None


def test_queue_configuration_snapshot_and_stop(engine):
    entries = [command(step="first"), command(step="second")]
    config = prepare(engine, entries)
    assert len(config) == 2
    assert len(engine.prompt_queue.prepare_content) == 1
    engine.action_in_progress = True
    engine.action_finish = True
    engine.action_gate.pending_action.waypoint = [1, 2, 3]
    generation = engine.ledger.task_generation
    engine._enter_global_stop("test", shutdown_program=False, publish_hold=False)
    assert engine.ledger.task_generation == generation + 1
    assert engine.prompt_queue.is_command_empty() and engine.prompt_queue.is_prepared_empty()
    assert not engine.action_in_progress and not engine.action_finish
    assert engine.action_gate.pending_action.waypoint is None
    assert engine.dispatcher_state == DISPATCHER_STATE.WAIT_FOR_MISSION
    assert engine.channels.stops == 0 and len(config) == 2


def test_hard_stop_before_loop_start_is_preserved(engine):
    prepare(engine, [command()])
    engine._enter_global_stop("operator")
    generation = engine.ledger.task_generation
    assert engine.dispatcher_state == DISPATCHER_STATE.STOP
    assert engine.channels.stops == 1
    engine._enter_global_stop("operator")
    assert engine.ledger.task_generation == generation and engine.channels.stops == 1
    engine._run_inference_loop()
    assert engine.clock.stopped


def test_retained_stop_switches_remain_independent(engine):
    prepare(engine, [command()])
    messages = engine.runlog.info.__self__.messages
    engine._enter_global_stop(
        "override", shutdown_program=False, emit_soft_stop_log=False,
        record_stop_event=False, publish_hold=False,
    )
    assert not any("Emergency stop:" in message for message in messages)
    assert engine.channels.stops == 0 and not engine.clock.stopped
    assert engine.dispatcher_state == DISPATCHER_STATE.WAIT_FOR_MISSION
    engine._enter_global_stop("lease_lost", shutdown_program=False)
    assert any("Emergency stop:" in message for message in messages)
    assert engine.channels.stops == 1 and not engine.clock.stopped


def test_return_snapshot_and_prompt_context_survive_queue_simplification(engine):
    state = [1.0, 2.0, 3.0, 0.0, 0.0, 0.5]
    engine.frame = SimpleNamespace(current_state=state)
    first, second = command(step="first"), command(step="second")
    config = prepare(engine, [first, second])
    assert engine.ledger.last_state == state
    assert engine.ledger.last_state is not state
    state[0] = 9.0
    assert engine.ledger.last_state[0] == 1.0
    assert engine.prompt_queue.replan_content[1] is first
    assert engine.prompt_queue.prepare_content[0][1] is second
    assert engine.prompt_queue.load_next_prompt()
    assert engine.ledger.last_state[0] == 9.0
    assert engine.prompt_queue.replan_content[1] is second
    assert engine.prompt_queue.head_command()[1] is second
    engine.prompt_queue.previous_return_record_cursor = 4
    engine._enter_global_stop("cancel", shutdown_program=False, publish_hold=False)
    assert engine.prompt_queue.previous_return_record_cursor is None
    assert engine.prompt_queue.replan_content is None
    assert len(config) == 2


@pytest.mark.parametrize("verdict", list(SkillVerdict))
def test_four_verdicts(engine, verdict):
    prepare(engine, [command(), command(step="next")])
    bind_owner(engine, verdict=verdict)
    engine.ledger.set_state(DISPATCHER_STATE.POST_ACTION, reason="test")
    engine.action_gate.pending_action.replan_cmd = "again"
    engine.action_gate.handle_post_action()
    if verdict is SkillVerdict.REPLAN:
        assert engine.dispatcher_state == DISPATCHER_STATE.DISPATCH
        assert engine.action_gate.pending_action.replan_cmd is None and engine.if_plan
    elif verdict is SkillVerdict.ADVANCE:
        assert engine.dispatcher_state == DISPATCHER_STATE.DISPATCH
        assert engine.prompt_queue.head_command()[1].call.step_id == "next"
    elif verdict is SkillVerdict.IDLE:
        assert engine.dispatcher_state == DISPATCHER_STATE.WAIT_FOR_MISSION
        assert [p["phase"] for p in engine.channels.phases] == ["done"]
    else:
        assert engine.dispatcher_state == DISPATCHER_STATE.POST_ACTION
    if verdict is not SkillVerdict.IDLE:
        assert not engine.channels.phases


def test_advance_empty_queue_finishes_once(engine):
    prepare(engine, [command()])
    bind_owner(engine, verdict=SkillVerdict.ADVANCE)
    engine.ledger.set_state(DISPATCHER_STATE.POST_ACTION, reason="test")
    engine.action_gate.handle_post_action()
    assert engine.dispatcher_state == DISPATCHER_STATE.WAIT_FOR_MISSION
    assert [p["phase"] for p in engine.channels.phases] == ["done"]


def test_real_fsm_executes_two_actions_and_one_terminal(engine):
    class SequenceSkill(SkillBase):
        name = "test.tool"

        def __init__(self):
            self.seen = []
            self.results = 0

        def plan_tick(self, cmd):
            self.seen.append(cmd.call.step_id)
            engine.skills.snapshot_owner()
            engine.action_in_progress = True
            engine.action_finish = True
            engine.action_start_time = 0.0
            engine.action_gate._action_generation += 1
            engine.action_gate._action_finish_generation = engine.action_gate._action_generation
            engine.ledger.set_state(DISPATCHER_STATE.WAIT_ACTION_FINISH, reason="test:armed")
            return True

        def on_action_result(self, result):
            self.results += 1
            return SkillVerdict.ADVANCE

    skill = SequenceSkill()
    engine.skills.register(skill.name, skill)
    prepare(engine, [command(step="first"), command(step="second")])
    engine._run_inference_loop()
    assert skill.seen == ["first", "second"] and skill.results == 2
    assert [p["phase"] for p in engine.channels.phases] == ["done"]
    assert engine.dispatcher_state == DISPATCHER_STATE.WAIT_FOR_MISSION
    assert not engine.action_in_progress


def test_no_perception_skill_dispatches_without_sensor_frame(engine):
    engine.headless = False
    calls = []
    skill = SkillBase(None)
    skill.plan_tick = lambda cmd: calls.append(cmd) or False
    engine.skills.register("test.tool", skill)
    cmd = command()
    engine.tools.start_tool_workflow(cmd.call, cmd)
    engine._run_inference_loop()
    assert calls == [cmd]
    assert engine.channels.phases[-1]["phase"] == "fail"


def test_ledger_reads_actual_host_state(engine):
    engine.dispatcher_state = DISPATCHER_STATE.WAIT_ACTION_FINISH
    engine.ledger.set_state(DISPATCHER_STATE.POST_ACTION, reason="test:result")
    assert engine.events[-1][1]["from_state"] == "WAIT_ACTION_FINISH"
    assert engine.events[-1][1]["to_state"] == "POST_ACTION"


def test_workflow_uses_real_queue_and_resets_failure(engine):
    skill = SkillBase(None)
    engine.skills.register("test.tool", skill)
    engine.ledger.fail_sequence()
    cmd = command()
    engine.tools.start_tool_workflow(cmd.call, cmd)
    assert engine.prompt_queue.head_command()[1] is cmd
    assert engine.if_plan and not engine.ledger.failed
    assert [p["phase"] for p in engine.channels.phases] == ["planning"]


def test_workflow_rejects_missing_skill_and_stale_perception(engine):
    cmd = command()
    engine.tools.start_tool_workflow(cmd.call, cmd)
    assert engine.channels.phases[-1]["error"]["code"] == "tool_not_registered"
    assert engine.prompt_queue.is_command_empty()
    skill = SkillBase(None)
    skill.requires_perception = True
    engine.skills.register("test.tool", skill)
    engine.tools.start_tool_workflow(cmd.call, cmd)
    assert engine.channels.phases[-1]["error"]["code"] == "chain_not_ready"
    assert engine.prompt_queue.is_command_empty() and not engine.tools._active_tool_name


def test_synchronous_skill_bypasses_perception_and_queue(engine):
    calls = []
    skill = SkillBase(None)
    skill.synchronous = skill.requires_perception = True
    skill.on_start = calls.append
    engine.skills.register("test.tool", skill)
    cmd = command()
    engine.tools.start_tool_workflow(cmd.call, cmd)
    assert calls == [cmd] and engine.prompt_queue.is_command_empty()
    assert not engine.channels.phases


def test_recovery_survives_broken_input_diagnostics(engine, monkeypatch):
    def broken():
        raise RuntimeError("input offline")

    monkeypatch.setattr(engine, "_run_inference_loop", broken)
    engine.get_sensor_input_health = broken
    engine.clock.is_shutdown = iter([False, True]).__next__
    engine.run_inference()
    assert engine.dispatcher_state == DISPATCHER_STATE.WAIT_FOR_MISSION
    assert any("input_health_unavailable" in m for m in engine.runlog.info.__self__.messages)


def test_action_gate_rejects_late_result_and_respects_skill(engine, monkeypatch):
    bind_owner(engine)
    engine.action_in_progress = True
    engine.action_finish = True
    engine.action_gate._action_generation = 3
    engine.action_gate._action_finish_generation = 2
    assert not engine.action_gate.action_done()
    assert not engine.action_finish
    assert engine.events[-1][0] == "task_action_result_ignored"
    engine.action_finish = True
    engine.action_gate._action_finish_generation = 3
    engine.action_start_time = 100
    monkeypatch.setattr("dispatcher.core.action_gate.time.time", lambda: 100.1)
    assert not engine.action_gate.action_done()
    monkeypatch.setattr("dispatcher.core.action_gate.time.time", lambda: 101)
    assert engine.action_gate.action_done()
    bind_owner(engine, gate=False)
    assert not engine.action_gate.action_done()


def test_exception_recovery_clears_domains_and_fails(engine):
    prepare(engine, [command(), command(step="next")])
    engine.action_in_progress = True
    engine._recover_inference_after_exception(RuntimeError("broken skill"))
    assert engine.dispatcher_state == DISPATCHER_STATE.WAIT_FOR_MISSION
    assert engine.ledger.failed and engine.ledger.command_status == COMMAND_STATUS.RUNNING
    assert engine.prompt_queue.is_command_empty() and engine.prompt_queue.is_prepared_empty()
    assert not engine.action_in_progress
    assert [p["phase"] for p in engine.channels.phases] == ["fail"]


@pytest.mark.parametrize("verdict", [None, "idle"])
def test_invalid_verdict_never_means_success(engine, verdict):
    bind_owner(engine, verdict=verdict)
    with pytest.raises(ValueError):
        engine.action_gate.handle_post_action()
    assert not engine.channels.phases


def test_diagnostics_distinguish_never_and_stale(engine):
    diag = engine.runlog.wait_diag({"rgb": ("rgb", None), "cloud": ("cloud", 8.0)})
    assert "rgb=rgb:never" in diag and "cloud=cloud:8.0s:stale" in diag
    assert RunTelemetry.fmt_wait_age(0.0) == "0.0s"
    engine._run_inference_loop()
    sink = engine.runlog.info.__self__
    assert any("reason=mission_or_action_release" in message and "8.0s:stale" in message for message in sink.messages)


def test_renamed_module_is_only_workflow_entry():
    assert not (PACKAGE / "dispatcher/core/workflow.py").exists()
    assert (PACKAGE / "dispatcher/core/tool_workflow.py").exists()
    assert not (PACKAGE / "dispatcher/core/__init__.py").read_text().strip()
    for path in PACKAGE.rglob("*.py"):
        assert "dispatcher.core.workflow" not in path.read_text()


def test_composition_preserves_configuration_on_perception_owner(tmp_path, monkeypatch):
    class Perception:
        def __init__(self):
            self.geometry_agree_safe_dis_radius_m = 0.8
            self.perception_only = 1

        def get_frame_snapshot(self):
            return None

        def get_sensor_input_health(self):
            return {}

    # 既有基线修复（评审修复轮登记）：dispatcher_node 顶部 import 链拖
    # utils.control_plane → zenoh_rpc → zenoh（本环境缺 zenoh，与全量门禁
    # 四个 ignore 的既有基线同源）；本测试只调 create_dispatcher_engine，
    # 不消费 ToolControlPlane（main 专属），以 stub 顶替其模块级导入。
    fake_modules = {
        "dispatcher.utils.control_plane": SimpleNamespace(ToolControlPlane=object),
        "dispatcher.perception.base_policy": SimpleNamespace(BasePolicyNode=Perception),
        "dispatcher.ros_adapter.clock_ros": SimpleNamespace(RosLog=Log, RosNode=object, RosShutdown=object),
        "dispatcher.ros_adapter.core_channels_ros": SimpleNamespace(
            RosCoreChannels=Channels, RosRuntimeClock=Clock, RosLogSink=Log),
        "dispatcher.ros_adapter.params_ros": SimpleNamespace(
            set_ros_params=lambda params: None, get_node_name=lambda: "test",
            get_private_param=lambda key, default: str(tmp_path) if key == "log_dir" else default),
    }
    for name, module in fake_modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delitem(sys.modules, "dispatcher_node", raising=False)
    module = importlib.import_module("dispatcher_node")
    monkeypatch.setattr(module, "load_yaml", lambda *args, **kwargs: {
        "ros": {"pointcloud": {"mode": "cloud"}},
        "base_policy": {"geometry_agree_safe_dis_radius_m": 1.2, "perception_only": 2},
        "uav_policy": {"geometry_agree_safe_dis_radius_m": 1.5, "min_action_wait": 0.7},
    })
    try:
        node, _ = module.create_dispatcher_engine("")
        perception = node.get_frame_snapshot.__self__
        assert isinstance(perception, Perception)
        assert perception.geometry_agree_safe_dis_radius_m == node.geometry_agree_safe_dis_radius_m == 1.5
        assert perception.perception_only == 2 and node._min_action_wait == 0.7
    finally:
        sys.modules.pop("dispatcher_node", None)
