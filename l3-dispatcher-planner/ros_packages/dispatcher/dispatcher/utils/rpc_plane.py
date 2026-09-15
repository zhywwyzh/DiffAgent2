#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Static-method RPC plane over the tool runtime (Phase B preparation).

Serves ONE queryable `lx/<stack-id>/rpc` with the JSON-RPC-style envelope
from `agent-station-rpc.spec.md` (proposed): connection.* methods answer
fully synchronously; execution methods answer the query with the
admission result only (`{accepted, call_id}`) and publish their outcome
exactly once on `lx/<stack-id>/rpc_outcome` keyed by `call_id`.

PREPARED, NOT ACTIVATED (spec §4.3): the plane is env-gated behind
`L3_RPC_PLANE` and stays off in every deployment until lockstep
adoption retires the tools/* plane. It is a thin transport over
ToolRuntime — admission exclusivity, lease gating, cancellation, and the
event stream remain owned by the runtime; the lease ledger remains
owned by ConnectionLeaseManager.

Legacy l4 callers still send the `basic_flight.*` names; `_WIRE_ALIASES`
normalizes them onto the canonical `flight.*` registry names, resolved by
name from the registry (no task ids exist).
`params` minus `call_id` and `context` are the tool arguments; `context`
carries only lease identity — `flight_session_id`/`step_id` are derived on
this side when the caller omits them.

Admission rejections map synchronously onto the spec reason vocabulary;
execution-time failures arrive on `rpc_outcome` as `wrong_state` (the
vocabulary has no per-failure classes yet — messages carry the detail;
widening the vocabulary is a flight/actions change).
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

# Legacy l4 wire names -> canonical registry names. Kept on the l3 side so
# l4 does not need a coordinated rollout of the `flight.*` / navigation
# renames. The 1:1 flight family aliases directly; the navigation surface
# differs in argument schema, so its canonical mapping is paired with an
# argument transform in `_normalize_legacy_call` (vla_nav → vla_reach and
# scene_graph_nav → scene.navigate, the latter with a local object-id
# resolution).
_WIRE_ALIASES = {
    "basic_flight.takeoff": "flight.takeoff",
    "basic_flight.land": "flight.land",
    "basic_flight.translate": "flight.translate",
    "basic_flight.rotate": "flight.rotate",
    "basic_flight.return": "flight.return",
    "basic_flight.emergency_stop": "flight.emergency_stop",
    "navigation.vla_nav": "navigation.vla_reach",
    "navigation.scene_graph_nav": "scene.navigate",
}

# legacy `basic_flight.return` 语义是“返回起飞点”（l4 空参），而 canonical
# `flight.return` 要求显式 `target`；此处按语义补默认值，不覆盖 caller 显式字段。
_WIRE_ARG_DEFAULTS = {
    "basic_flight.return": {"target": "origin"},
}

# legacy l4 `navigation.vla_nav {object, bearing}` 的 bearing 枚举比 canonical
# `navigation.vla_reach` 的 `side` 枚举更宽（behind/below/none）；仅转发
# canonical 支持的子集，其余方位回退为不带 side 的方向无关接近。
_BEARING_TO_SIDE = {
    "front": "front",
    "left": "left",
    "right": "right",
    "above": "above",
}


def _normalize_legacy_call(method: str, canonical: str, arguments: dict) -> tuple[str, dict]:
    """Map legacy l4 navigation wire arguments onto the canonical schema.

    1:1 aliases keep the canonical name from `_WIRE_ALIASES`;
    `navigation.scene_graph_nav` additionally swaps the user-facing `object`
    for the locally resolved `object_id` before `scene.navigate` admission.
    Returns (canonical, normalized arguments).
    """
    if method == "navigation.vla_nav":
        obj = str(arguments.get("object") or "").strip()
        normalized = {"object": obj, "prompt": obj}
        side = _BEARING_TO_SIDE.get(str(arguments.get("bearing") or "").strip().lower())
        if side:
            normalized["side"] = side
        if "distance_m" in arguments:
            normalized["distance_m"] = arguments["distance_m"]
        return canonical, normalized
    if method == "navigation.scene_graph_nav":
        obj = str(arguments.get("object") or "").strip()
        object_id = _resolve_scene_object_id(obj)
        if object_id is None:
            raise ToolProtocolError(
                INVALID_PARAMS,
                f"scene graph object not resolved: '{obj}'",
                {"reason": "object_not_resolved", "details": obj},
            )
        return canonical, {"object_id": object_id}
    return canonical, arguments


def _resolve_scene_object_id(object_name: str) -> int | None:
    """Resolve a legacy l4 object name to a scene-graph object id.

    本地精确匹配：先按归一化 label 全等，再退化为唯一子串命中（任一向）。
    匹配缺失/歧义返回 None。数据源与 scene.map_search 同源
    （graph_source 的 transient projection），因此一步旧调用与两步新流程
    看到的场景一致。
    """
    query = str(object_name or "").strip().lower()
    if not query:
        return None
    try:
        from dispatcher.tools.scene_nav.graph_source import load_objects_summary

        _active, objects = load_objects_summary()
    except Exception:
        return None
    labels = [str(obj.get("label") or "").strip().lower() for obj in objects]
    pool = [obj for obj, label in zip(objects, labels) if label == query]
    if not pool:
        pool = [
            obj
            for obj, label in zip(objects, labels)
            if label and (query in label or label in query)
        ]
    if len(pool) != 1:
        return None
    try:
        return int(pool[0]["id"])
    except (KeyError, TypeError, ValueError):
        return None

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
        # Normalize the legacy `basic_flight.*` / `navigation.*` wire name
        # onto the canonical registry key, resolved by name from the
        # registry (no task ids exist). Argument normalization
        # runs BEFORE spec lookup — scene_graph_nav swaps `object` for the
        # locally resolved `object_id`, so the schema check must see the
        # canonical arguments. Unknown names still raise METHOD_NOT_FOUND
        # here, before reaching the runtime.
        canonical = _WIRE_ALIASES.get(method, method)
        arguments = {k: v for k, v in params.items() if k not in TRANSPORT_FIELDS}
        canonical, arguments = _normalize_legacy_call(method, canonical, arguments)
        spec = self._mw.runtime.registry.tool_for_name(canonical)
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
        if method == "navigation.scene_graph_nav":
            # 一步旧调用：把用户指认的对象名作为 mission prompt（对齐两步
            # 流程中 map_search 步骤的 user_prompt 语义）。
            context_fields["display_text"] = str(params.get("object") or "")
        # 补齐 legacy 参数语义（不覆盖 caller 显式给出的字段）。
        for field, default in _WIRE_ARG_DEFAULTS.get(method, {}).items():
            arguments.setdefault(field, default)
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
