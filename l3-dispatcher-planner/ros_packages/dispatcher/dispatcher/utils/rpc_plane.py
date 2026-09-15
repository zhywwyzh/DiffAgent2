"""单入口 RPC 控制面：连接管理与按原始工具名准入。

连接同步应答，工具调用只返回准入结果；终态经 rpc_outcome 上报。
不存在旧工具别名、参数转换或领域查询。
"""

from __future__ import annotations

import json
import threading

from dispatcher.tools.protocol import (
    BUSINESS_REJECTED,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    ToolProtocolError,
)

CONNECTION_METHODS = frozenset(
    {"connection.acquire", "connection.renew", "connection.release", "connection.status"}
)

TRANSPORT_FIELDS = frozenset({"call_id", "context"})

# tool-runtime event error codes -> rpc reason vocabulary
_FAIL_REASONS = {
    "connection_lost": "connection_not_owner",
    "cancelled": "wrong_state",
}


def _rpc_result(method: str, result: dict) -> dict:
    return {"type": "rpc_result", "method": method, "result": result}


def _rpc_error(method: str, reason: str, message: str) -> dict:
    return {
        "type": "rpc_error",
        "method": method,
        "reason": reason,
        "message": message,
    }


def _admission_reason(err: ToolProtocolError) -> str:
    """Map a ToolProtocolError onto the rpc reason vocabulary."""
    reason = str(err.data.get("reason") or "")
    if err.code == METHOD_NOT_FOUND:
        return "method_not_found"
    if err.code == INVALID_PARAMS or reason == "call_id_conflict":
        return "invalid_arguments"
    if err.code == BUSINESS_REJECTED:
        if reason == "connection_not_owner":
            return "connection_not_owner"
        return "connection_busy"
    return "internal_error"


class RpcPlane:
    """`lx/<stack>/rpc` queryable + `lx/<stack>/rpc_outcome` publisher."""

    def __init__(self, middleware) -> None:
        self._mw = middleware
        self._session = middleware._zenoh_session
        if self._session is None:
            raise RuntimeError("RpcPlane requires an open zenoh session")
        self._queryable = None
        self._outcome = None
        self._lock = threading.Lock()
        # call_id -> wire method, registered at admission, consumed at done
        self._method_by_call: dict[str, str] = {}

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._outcome = self._session.declare_publisher(f"{self._mw.prefix}/rpc_outcome")
        self._queryable = self._session.declare_queryable(
            f"{self._mw.prefix}/rpc", self._on_rpc, complete=True
        )
        print(
            f"[rpc_plane] rpc plane up (prepared): lx/{self._mw.stack_id}/rpc",
            flush=True,
        )

    def close(self) -> None:
        for handle in (self._queryable, self._outcome):
            if handle is not None:
                try:
                    handle.undeclare()
                except Exception:  # noqa: BLE001 — teardown best effort
                    pass
        self._queryable = None
        self._outcome = None
        with self._lock:
            self._method_by_call.clear()

    # ------------------------------------------------------------------
    # outcome bridge (chained from the middleware event sink)
    # ------------------------------------------------------------------

    def on_event(self, event: dict) -> None:
        """Publish the `rpc_outcome` for one rpc-admitted call."""
        if not isinstance(event, dict) or event.get("status") not in {"done", "fail"}:
            return
        call_id = str(event.get("call_id") or "")
        with self._lock:
            method = self._method_by_call.pop(call_id, "")
        if not method:
            return  # tools/* call, not ours
        if event.get("status") == "done":
            outcome = {
                "ok": True,
                "result": dict(event.get("structuredContent") or {"completion": "done"}),
            }
        else:
            error = event.get("error") or {}
            code = str(error.get("code") or "")
            outcome = {
                "ok": False,
                "reason": _FAIL_REASONS.get(code, "wrong_state"),
                "message": str(event.get("message") or error.get("message") or code or "failed"),
            }
        self._publish(
            {
                "type": "rpc_outcome",
                "method": method,
                "call_id": call_id,
                "outcome": outcome,
            }
        )

    def _publish(self, outcome: dict) -> None:
        publisher = self._outcome
        if publisher is None:
            return
        try:
            publisher.put(json.dumps(outcome, ensure_ascii=False).encode())
        except Exception as exc:  # noqa: BLE001 — never kill the emitter thread
            print(f"[rpc_plane] outcome publish FAILED: {exc}", flush=True)

    # ------------------------------------------------------------------
    # queryable handler
    # ------------------------------------------------------------------

    def _reply(self, query, payload: dict) -> None:
        query.reply(query.key_expr, json.dumps(payload, ensure_ascii=False).encode())

    def _payload_of(self, query) -> dict:
        raw = query.payload.to_bytes() if hasattr(query.payload, "to_bytes") else bytes(query.payload or b"")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except ValueError:
            return {}

    def _on_rpc(self, query) -> None:
        payload = self._payload_of(query)
        method = str(payload.get("method") or "")
        params = payload.get("params")
        if not isinstance(params, dict):
            self._reply(query, _rpc_error(method, "invalid_arguments", "params must be an object"))
            return
        try:
            if method in CONNECTION_METHODS:
                self._reply(query, self._connection_call(method, params))
                return
            self._reply(query, self._execution_call(method, params))
            return
        except ToolProtocolError as err:
            self._reply(query, _rpc_error(method, _admission_reason(err), err.message))
            return
        except Exception as exc:  # noqa: BLE001 — surface as internal_error
            self._reply(query, _rpc_error(method, "internal_error", f"internal error: {exc}"))
            return

    # ------------------------------------------------------------------
    # connection plane (fully synchronous)
    # ------------------------------------------------------------------

    def _connection_call(self, method: str, params: dict) -> dict:
        leases = self._mw.leases
        if method == "connection.acquire":
            return _rpc_result(
                method,
                leases.acquire(params.get("station_id"), params.get("station_instance_id")),
            )
        if method == "connection.renew":
            return _rpc_result(
                method,
                leases.renew(
                    params.get("station_id"),
                    params.get("station_instance_id"),
                    params.get("lease_id"),
                ),
            )
        if method == "connection.release":
            return _rpc_result(
                method,
                leases.release(
                    params.get("station_id"),
                    params.get("station_instance_id"),
                    params.get("lease_id"),
                ),
            )
        return _rpc_result(method, leases.status())

    # ------------------------------------------------------------------
    # execution plane (admission sync, outcome on rpc_outcome)
    # ------------------------------------------------------------------

    def _execution_call(self, method: str, params: dict) -> dict:
        # agent-station-rpc.spec.md §2: execution methods MUST carry
        # params.call_id (caller-supplied); the carrier never mints one.
        call_id = params.get("call_id")
        if not isinstance(call_id, str) or not call_id.strip():
            raise ToolProtocolError(
                INVALID_PARAMS,
                "call_id is required for execution methods",
                {"reason": "invalid_arguments", "details": "call_id"},
            )
        call_id = call_id.strip()
        context = params.get("context")
        if not isinstance(context, dict):
            context = {}
        canonical = method
        arguments = {k: v for k, v in params.items() if k not in TRANSPORT_FIELDS}
        self._mw.runtime.registry.tool_for_name(canonical)
        station_id = str(context.get("station_id") or "")
        station_instance_id = str(context.get("station_instance_id") or "")
        lease_id = str(context.get("lease_id") or "")
        # RPC callers carry no station-side session/step notion; derive
        # stable non-empty values so ToolCall.frame_id and event fields stay
        # populated (the runtime correlates outcomes by call_id, not by them).
        flight_session_id = str(context.get("flight_session_id") or "").strip()
        step_id = str(context.get("step_id") or "").strip()
        if not flight_session_id:
            flight_session_id = lease_id or "rpc"
        if not step_id:
            step_id = call_id
        context_fields = {
            "flight_session_id": flight_session_id,
            "step_id": step_id,
            "station_id": station_id,
            "station_instance_id": station_instance_id,
            "lease_id": lease_id,
        }
        self._mw.runtime.admit(
            {
                "call_id": call_id,
                "name": canonical,
                "arguments": arguments,
                "context": context_fields,
            }
        )
        with self._lock:
            # Keep the wire (legacy) method for rpc_outcome so l4 matches the
            # call it issued; execution dispatches on `canonical`.
            self._method_by_call[call_id] = method
        return _rpc_result(method, {"accepted": True, "call_id": call_id})
