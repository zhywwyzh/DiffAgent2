#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zenoh transport adapter for the in-process executable tool runtime.

Declares queryables under `lx/<stack-id>/...` and delegates executable-tool
discovery, admission, events, and cancellation to ToolRuntime. Resource
queryables remain here because they are transport resources, not tools.

Addressing (§1.0): zenoh client mode connecting to the topology bootstrap
router; multicast scouting DISABLED (ZeroTier does not relay it reliably —
P0 spike 2026-08-30). No fixed IPs anywhere.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import uuid
from datetime import datetime, timezone

import zenoh

from dispatcher.utils.connection_lease import ConnectionLeaseManager
from dispatcher.tools import ToolProtocolError, ToolRegistry, ToolRuntime
from dispatcher.tools.protocol import BUSINESS_REJECTED, INVALID_PARAMS, LEASE_IDENTITY_FIELDS

INTERNAL_ERROR = -32603
TASK_REJECTED = BUSINESS_REJECTED


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _default_router() -> str:
    # Inert name form: real deployments get ZENOH_ROUTER rendered from
    # drone_projects/auto_deployer/endpoints.local.env (the single endpoint source).
    return "tcp/public_zenohd_router:7447"


class ZenohTaskMiddleware:
    """Zenoh queryables plus non-tool resource handlers."""

    def __init__(
        self,
        command_queue: "queue.Queue",
        stack_id: str | None = None,
        router: str | None = None,
        lease_ttl_s: float | None = None,
        lease_watchdog_interval_s: float = 1.0,
        *,
        log=None,
        shutdown=None,
        feedback_factory=None,
        safety_stop=None,
    ) -> None:
        self.registry = ToolRegistry.default()
        self.stack_id = (stack_id or os.environ.get("LX_STACK_ID", "")).strip().strip("/")
        if not self.stack_id:
            raise RuntimeError("LX_STACK_ID or stack_id is required")
        self.router = router or os.environ.get("ZENOH_ROUTER") or _default_router()
        self.prefix = f"lx/{self.stack_id}"
        self.instance_id = uuid.uuid4().hex[:12]
        manager_kwargs = {} if lease_ttl_s is None else {"ttl_s": lease_ttl_s}
        self.leases = ConnectionLeaseManager(self.stack_id, **manager_kwargs)
        self.runtime = ToolRuntime(self.registry, command_queue, self.leases, safety_stop=safety_stop)
        self.leases.set_active_call_probe(self.runtime.has_active_call)
        self.leases.bind_loss_handlers(
            self.runtime.cancel_active_for_lease_loss,
            self.runtime.issue_safety_stop,
            self._forget_owner_watch,
        )
        self._watchdog_interval_s = float(lease_watchdog_interval_s)
        self._watchdog_stop = threading.Event()
        self._watchdog_thread: threading.Thread | None = None
        self._zenoh_session = None
        self._queryables = []
        self._presence_token = None
        self._owner_watch: tuple[str, str, object] | None = None
        self.rpc_plane = None

        # 端口注入（S4a P1/P3）：日志/关停由组合根经 control_plane 透传；
        # 反馈面由 factory 在此构造（或 bind_feedback 显式注入），
        self._log = log
        self._shutdown = shutdown
        self._feedback = feedback_factory(self) if feedback_factory is not None else None
        self._started_at = utc_now_iso()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def bind_feedback(self, feedback) -> None:
        """显式注入反馈面（覆盖 factory 构造结果；供组合根/测试直连）。"""
        self._feedback = feedback

    def queryable_suffixes(self) -> tuple[str, ...]:
        """Declared resource key suffixes under lx/<stack-id>/ (testable surface).

        The task plane lives on `lx/<stack-id>/rpc` + `lx/<stack-id>/rpc_outcome`
        and is declared by `RpcPlane`; only resources remain here.
        """
        return (
            "sim/reset",
            "health",
        )

    @property
    def presence_token_key(self) -> str:
        """Task-plane liveliness token (fleet spec §3)."""
        return f"lx/{self.stack_id}/presence/task/{self.instance_id}"

    def owner_watch_key(self, station_id: str, lease_id: str) -> str:
        """Owner connection token this stack watches while leased."""
        return f"lx/stations/{station_id}/connection/{lease_id}/{self.stack_id}"

    def start(self) -> None:
        """Open the zenoh session, declare queryables, subscribe feedback."""
        conf = zenoh.Config()
        conf.insert_json5("mode", '"client"')
        conf.insert_json5("connect/endpoints", json.dumps([self.router]))
        conf.insert_json5("scouting/multicast/enabled", "false")
        self._zenoh_session = zenoh.open(conf)
        for suffix, handler in (
            ("sim/reset", self._on_sim_reset),
            ("health", self._on_health),
        ):
            # complete=True is REQUIRED: without it the router waits for the
            # query aggregation window (up to the client timeout) before
            # forwarding replies (verified 2026-08-31 — 10 s latency).
            self._queryables.append(
                self._zenoh_session.declare_queryable(f"{self.prefix}/{suffix}", handler, complete=True)
            )
        self.runtime.event_sink = self._publish_event
        # RPC plane is the task plane (lockstep adoption): always on.
        from dispatcher.utils.rpc_plane import RpcPlane

        self.rpc_plane = RpcPlane(self)
        self.rpc_plane.start()
        self._presence_token = self._zenoh_session.liveliness().declare_token(self.presence_token_key)
        # 反馈面订阅位点（原 _start_ros_subscriptions 调用点）：由组合根注入的
        # FeedbackPlane 承担 ROS 订阅，启动序列顺序不变（方案 §5.1）。
        self._start_lease_watchdog()
        print(
            f"[zenoh_rpc] rpc plane up: lx/{self.stack_id}/rpc via {self.router}",
            flush=True,
        )

    def close(self) -> None:
        self._stop_lease_watchdog()
        if self.rpc_plane is not None:
            self.rpc_plane.close()
            self.rpc_plane = None
        if self._zenoh_session is not None:
            self._forget_owner_watch()
            if self._presence_token is not None:
                self._presence_token.undeclare()
                self._presence_token = None
            self.runtime.event_sink = None
            self._zenoh_session.close()
            self._zenoh_session = None
            self._queryables.clear()

    # ------------------------------------------------------------------
    # lease watchdog (fleet spec §7 — TTL is the hard authority)
    # ------------------------------------------------------------------

    def _start_lease_watchdog(self) -> None:
        """Own lease expiry: reap silently expired leases and retry any
        loss interrupted mid safety-dispatch, with no incoming request."""
        self._stop_lease_watchdog()  # idempotent across _serve restarts
        self._watchdog_stop = threading.Event()
        self._watchdog_thread = threading.Thread(
            target=self._watch_leases,
            name="lease-watchdog",
            daemon=True,
        )
        self._watchdog_thread.start()

    def _stop_lease_watchdog(self) -> None:
        self._watchdog_stop.set()
        thread = self._watchdog_thread
        self._watchdog_thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5.0)

    def _watch_leases(self) -> None:
        while not self._watchdog_stop.wait(self._watchdog_interval_s):
            try:
                if not self.leases.expire_if_due():
                    self.leases.resume_pending_loss()
            except Exception as exc:  # noqa: BLE001 — watchdog must survive
                print(f"[zenoh_rpc] lease watchdog error: {exc}", flush=True)

    # ------------------------------------------------------------------
    # queryable handlers
    # ------------------------------------------------------------------

    def _publish_event(self, event: dict) -> None:
        """Feed one runtime lifecycle event to the RPC outcome bridge."""
        if self.rpc_plane is not None:
            self.rpc_plane.on_event(event)

    def _reply_ok(self, query, result) -> None:
        try:
            if isinstance(result, (dict, list)):
                query.reply(
                    query.key_expr,
                    json.dumps(result, ensure_ascii=False).encode(),
                )
            else:
                query.reply(query.key_expr, bytes(result))
            print(f"[zenoh_rpc] reply ok on {query.key_expr}", flush=True)
        except Exception as exc:  # noqa: BLE001 — never kill the zenoh thread
            print(f"[zenoh_rpc] reply FAILED on {query.key_expr}: {exc}", flush=True)

    def _reply_err(self, query, err: ToolProtocolError) -> None:
        query.reply_err(json.dumps(err.to_dict(), ensure_ascii=False).encode())

    def _guarded(self, query, fn) -> None:
        try:
            self._reply_ok(query, fn())
        except ToolProtocolError as err:
            self._reply_err(query, err)
        except Exception as exc:  # noqa: BLE001 — surface as -32603
            self._reply_err(
                query,
                ToolProtocolError(
                    INTERNAL_ERROR,
                    f"internal error: {exc}",
                    {"reason": "internal_error"},
                ),
            )

    def _params_of(self, query) -> dict:
        payload = query.payload
        raw = payload.to_bytes() if hasattr(payload, "to_bytes") else bytes(payload or b"")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except ValueError:
            raise ToolProtocolError(
                INVALID_PARAMS,
                "invalid params: payload is not JSON",
                {"reason": "invalid_request"},
            )
        if not isinstance(data, dict):
            raise ToolProtocolError(
                INVALID_PARAMS,
                "invalid params: payload must be an object",
                {"reason": "invalid_request"},
            )
        return data

    # ------------------------------------------------------------------
    # resource query surface (fleet spec §4)
    # ------------------------------------------------------------------

    @staticmethod
    def _connection_identity(params: dict) -> dict:
        return {field: params.get(field) for field in LEASE_IDENTITY_FIELDS}

    # ------------------------------------------------------------------
    # owner connection-token watch (fleet spec §4/§7)
    # ------------------------------------------------------------------

    def _watch_owner_token(self, station_id: str, lease_id: str) -> None:
        """Watch the station's connection token; DELETE ends the lease."""
        self._forget_owner_watch()
        key = self.owner_watch_key(station_id, lease_id)
        try:
            watch = self._zenoh_session.liveliness().declare_subscriber(
                key, self._on_owner_token_sample, history=True
            )
        except Exception as exc:  # noqa: BLE001 — TTL stays the hard authority
            print(
                f"[zenoh_rpc] owner-token watch unavailable on {key}: {exc}; TTL remains the hard authority",
                flush=True,
            )
            watch = None
        self._owner_watch = (station_id, lease_id, watch)

    def _forget_owner_watch(self, station_id: str = "", lease_id: str = "") -> None:
        watch = self._owner_watch
        self._owner_watch = None
        if watch is not None and watch[2] is not None:
            try:
                watch[2].undeclare()
            except Exception as exc:  # noqa: BLE001 — teardown best effort
                print(f"[zenoh_rpc] owner-token watch undeclare failed: {exc}", flush=True)

    def _on_owner_token_sample(self, sample) -> None:
        if getattr(sample, "kind", None) != zenoh.SampleKind.DELETE:
            return
        print("[zenoh_rpc] owner connection token lost; stopping admission", flush=True)
        self.leases.notify_owner_lost("station_connection_token_lost")

    def _on_sim_reset(self, query) -> None:
        def handle():
            # Owner-scoped like the tool plane (fleet spec §5).
            self.leases.require_owner(self._connection_identity(self._params_of(query)))
            success, message = self._feedback.reset_stack()
            if not success:
                raise ToolProtocolError(
                    TASK_REJECTED,
                    f"reset_sim failed: {message}",
                    {"reason": "reset_failed"},
                )
            self.runtime.reset()
            return {
                "type": "reset_result",
                "status": "running",
                "phase": "accepted",
                "message": "reset_sim ok",
                "ts": utc_now_iso(),
            }

        self._guarded(query, handle)


    def _on_health(self, query) -> None:
        def handle():
            return {
                "ok": True,
                "stack": self.stack_id,
                "started_at": self._started_at,
                "ts": utc_now_iso(),
            }

        self._guarded(query, handle)


    # ------------------------------------------------------------------
    # feedback plane seams (ROS-free; ROS side lives in ros_adapter/feedback_ros.py)
    # ------------------------------------------------------------------


    def on_tool_phase(self, data: dict) -> None:
        """Accept one in-process phase emission from the dispatcher."""
        if not isinstance(data, dict):
            return
        call_id = str(data.get("call_id") or "")
        if not call_id:
            # 引擎 _publish_task_phase 只携带 frame_id（copaw/<session>/<step>），
            # 不携带 call_id。缺失时经 runtime 的 frame→call_id 映射回退解析，
            # 否则终态（done/fail）被静默丢弃 → _active_call_id 永不释放 →
            # 后续工具调用被 flight_busy 拒绝（前端显示 connection_busy）。
            call_id = self.runtime.call_id_for_frame(str(data.get("frame_id") or ""))
        if not call_id:
            return
        phase = str(data.get("phase") or "")
        progress = data.get("progress")
        detail = str(data.get("detail") or "")
        result = data.get("result")
        error = data.get("error")
        message = data.get("message")
        explicit_status = str(data.get("status") or "").strip()
        if explicit_status in {"running", "done", "fail"}:
            status = explicit_status
        elif phase == "fail":
            status = "fail"
        elif phase in {"done", "result_ready"}:
            status = "done"
        else:
            status = "running"
        structured_content = result if isinstance(result, dict) else None
        self.runtime.emit(
            call_id,
            status=status,
            phase=phase or ("done" if status == "done" else "fail"),
            progress=progress,
            structured_content=structured_content,
            error=error if isinstance(error, dict) else None,
            message=str(message or detail),
        )
