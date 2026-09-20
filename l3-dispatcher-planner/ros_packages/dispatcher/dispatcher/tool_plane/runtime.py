"""Call ledger and lifecycle runtime behind the zenoh tool transport."""

from __future__ import annotations

import hashlib
import json
import queue
import threading
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from dispatcher.tool_plane.model import ToolCall, ToolCommand
from dispatcher.tool_plane.protocol import (
    BUSINESS_REJECTED,
    INVALID_PARAMS,
    LEASE_IDENTITY_FIELDS,
    ToolProtocolError,
)
from dispatcher.tool_plane.registry import ToolRegistry


def _same_station_owner(a: ToolCall, b: ToolCall) -> bool:
    """Both calls come from the same station instance (station_id +
    station_instance_id match) → the new instruction may preempt the active
    one (front-end refresh semantics: a fresh AgentPrompt replaces the
    previous task instead of hitting `connection_busy`)."""
    return a.station_id == b.station_id and a.station_instance_id == b.station_instance_id


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class _CallState:
    call: ToolCall
    fingerprint: str
    ack: dict
    terminal: bool = False
    cancel_requested: bool = False


class ToolRuntime:
    """Own admission, exclusivity, cancellation, and replayable events.

    Every owner-scoped operation (admit, events, cancel) is gated by the
    stack's ConnectionLeaseManager; there is no ownerless path.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        command_queue: "queue.Queue[ToolCommand]",
        lease_manager,
        event_history_size: int = 1000,
        event_sink=None,
        safety_stop=None,
    ) -> None:
        self._safety_stop = safety_stop
        self.registry = registry
        self._commands = command_queue
        self._leases = lease_manager
        self._event_sink = event_sink
        self._calls: dict[str, _CallState] = {}
        self._call_by_frame: dict[str, str] = {}
        self._active_call_id = ""
        self._event_history: deque[dict] = deque(maxlen=event_history_size)
        self._event_seq = 0
        self._event_instance = uuid.uuid4().hex[:8]
        self._lock = threading.RLock()

    @property
    def event_sink(self):
        """Event-sink callable set by the transport on startup (P1 push)."""
        return self._event_sink

    @event_sink.setter
    def event_sink(self, sink):
        self._event_sink = sink

    def list_tools(self) -> dict:
        return self.registry.list_tools()

    def can_execute(self, call_id: str) -> bool:
        """拒绝队列中已终结、取消或被抢占的调用。"""
        with self._lock:
            state = self._calls.get(call_id)
            return bool(state is not None and not state.terminal and not state.cancel_requested
                        and self._active_call_id == call_id)

    def admit(self, payload: dict) -> dict:
        call = self.registry.normalize_call(payload)
        fingerprint = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        # Keep lease -> runtime lock ordering, also used by active release checks.
        # Loss cannot slip between owner validation and admission, including replays.
        with self._leases.owner_guard(call.lease_identity), self._lock:
            previous = self._calls.get(call.call_id)
            if previous is not None:
                if previous.fingerprint != fingerprint:
                    raise ToolProtocolError(
                        BUSINESS_REJECTED,
                        "call id already used with different content",
                        {"reason": "call_id_conflict", "call_id": call.call_id},
                    )
                return dict(previous.ack)

            active = self._active_state_locked()
            if active is not None:
                # 同源新指令抢占：同一 station 实例下发的新 AgentPrompt
                # （前端刷新语义）可取代旧 active call——先经完整取消链
                # （skill.on_cancel → 软急停 → cancel_all_goals →
                # mark_cancelled）释放旧技能/action 状态，随即接管
                # _active_call_id 并 admit 新 call。取消命令在命令队列中
                # 先于新 call 的 "call" 命令被消费，旧 call 的异步终态
                # emit 到达时 _active_call_id 已指向新 call（emit 的
                # `_active_call_id == call_id` 条件不满足），不会误伤新 call。
                # 非同源（其他 operator/station）仍按 flight_busy 拒绝。
                if not _same_station_owner(active.call, call):
                    raise ToolProtocolError(
                        BUSINESS_REJECTED,
                        "another flight tool is active",
                        {
                            "reason": "flight_busy",
                            "active_call_id": active.call.call_id,
                            "active_tool": active.call.name,
                        },
                    )
                active.cancel_requested = True
                self._commands.put(
                    ToolCommand("cancel", active.call, "preempted_by_new_instruction")
                )


            ack = {
                "type": "tool_call_ack",
                "accepted": True,
                "call_id": call.call_id,
                "name": call.name,
                "flight_session_id": call.flight_session_id,
                "step_id": call.step_id,
                "station_id": call.station_id,
                "station_instance_id": call.station_instance_id,
                "lease_id": call.lease_id,
                "reason": "admitted",
                "ts": _utc_now_iso(),
            }
            self._calls[call.call_id] = _CallState(call, fingerprint, ack)
            self._call_by_frame[call.frame_id] = call.call_id
            self._active_call_id = call.call_id
            self._append_event_locked(
                call,
                status="running",
                phase="accepted",
                message="tool call admitted",
            )
            self._commands.put(ToolCommand("call", call))
            return dict(ack)

    def cancel(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ToolProtocolError(
                INVALID_PARAMS,
                "invalid cancel request",
                {"reason": "invalid_request"},
            )
        unknown = sorted(set(payload) - {"call_id", "reason", *LEASE_IDENTITY_FIELDS})
        if unknown:
            raise ToolProtocolError(
                INVALID_PARAMS,
                "invalid cancel request",
                {"reason": "unknown_argument", "details": unknown},
            )
        call_id = payload.get("call_id")
        if not isinstance(call_id, str) or not call_id.strip():
            raise ToolProtocolError(
                INVALID_PARAMS,
                "invalid cancel request",
                {"reason": "missing_required_argument", "details": "call_id"},
            )
        reason = payload.get("reason", "operator_cancel")
        if not isinstance(reason, str):
            raise ToolProtocolError(
                INVALID_PARAMS,
                "invalid cancel request",
                {"reason": "argument_out_of_range", "details": "reason"},
            )
        self._leases.require_owner({field: payload.get(field) for field in LEASE_IDENTITY_FIELDS})
        with self._lock:
            state = self._calls.get(call_id)
            if state is None:
                raise ToolProtocolError(
                    BUSINESS_REJECTED,
                    "call not found",
                    {"reason": "call_not_found", "call_id": call_id},
                )
            if state.terminal:
                return {
                    "type": "tool_cancel_ack",
                    "call_id": call_id,
                    "cancelled": False,
                    "reason": "already_terminal",
                    "ts": _utc_now_iso(),
                }
            if not state.cancel_requested:
                state.cancel_requested = True
                self._commands.put(ToolCommand("cancel", state.call, reason.strip()))
            return {
                "type": "tool_cancel_ack",
                "call_id": call_id,
                "cancelled": True,
                "reason": "cancel_requested",
                "ts": _utc_now_iso(),
            }

    def emit(
        self,
        call_id: str,
        *,
        status: str,
        phase: str,
        message: str = "",
        progress=None,
        structured_content: dict | None = None,
        error: dict | None = None,
    ) -> bool:
        if status not in {"running", "done", "fail"}:
            raise ValueError(f"invalid tool status: {status}")
        terminal = status in {"done", "fail"}
        with self._lock:
            state = self._calls.get(call_id)
            if state is None or state.terminal:
                return False
            self._append_event_locked(
                state.call,
                status=status,
                phase=phase,
                message=message,
                progress=progress,
                structured_content=structured_content,
                error=error,
            )
            if terminal:
                state.terminal = True
                if self._active_call_id == call_id:
                    self._active_call_id = ""
            return True

    def call_id_for_frame(self, frame_id: str) -> str:
        """Resolve the call_id that was admitted with the given frame_id.

        The engine emits phase events keyed by ``ToolCall.frame_id``
        (``copaw/<flight_session_id>/<step_id>``), while the ledger is keyed
        by call_id; this mapping (established in ``admit``) lets the bridge
        correlate engine terminal events back to the runtime record.
        """
        with self._lock:
            return self._call_by_frame.get(str(frame_id or ""), "")

    def emit_for_frame(self, frame_id: str, **event) -> bool:
        with self._lock:
            call_id = self._call_by_frame.get(str(frame_id or ""), "")
        return self.emit(call_id, **event) if call_id else False

    def mark_cancelled(self, call_id: str, reason: str) -> bool:
        return self.emit(
            call_id,
            status="fail",
            phase="fail",
            message="tool call cancelled",
            structured_content={"completion": "cancelled"},
            error={"code": "cancelled", "reason": reason or "operator_cancel"},
        )

    def events(self, payload: dict) -> dict:
        """Owner-scoped cursor poll (fleet spec §5).

        Returns only events for the matching lease; `next_seq` is the
        highest scanned sequence (foreign events included) unless the
        matching page is truncated by `limit`.
        """
        if not isinstance(payload, dict):
            raise ToolProtocolError(
                INVALID_PARAMS,
                "invalid event request",
                {"reason": "invalid_request"},
            )
        after_seq = payload.get("after_seq", 0)
        limit = payload.get("limit", 100)
        if isinstance(after_seq, bool) or not isinstance(after_seq, int) or after_seq < 0:
            raise ToolProtocolError(
                INVALID_PARAMS,
                "invalid event cursor",
                {"reason": "invalid_cursor", "details": "after_seq"},
            )
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ToolProtocolError(
                INVALID_PARAMS,
                "invalid event cursor",
                {"reason": "invalid_cursor", "details": "limit"},
            )
        identity = {field: payload.get(field) for field in LEASE_IDENTITY_FIELDS}
        self._leases.require_owner(identity)
        with self._lock:
            history = list(self._event_history)
            current_seq = self._event_seq
        if history and after_seq < int(history[0]["seq"]) - 1:
            return {
                "type": "tool_events",
                "events": [],
                "next_seq": current_seq,
                "has_more": False,
                "cursor_reset": True,
                "reset_reason": "event_history_expired",
            }
        if after_seq > current_seq:
            return {
                "type": "tool_events",
                "events": [],
                "next_seq": current_seq,
                "has_more": False,
                "cursor_reset": True,
                "reset_reason": "client_cursor_ahead",
            }
        scanned = [event for event in history if int(event["seq"]) > after_seq]
        matching = [event for event in scanned if _event_matches(event, identity)]
        page = matching[:limit]
        if page and len(matching) > limit:
            # Truncated matching page: keep the cursor at the last returned
            # event so remaining matches stay retrievable.
            next_seq = int(page[-1]["seq"])
            has_more = True
        else:
            # Advance past every scanned event, foreign ones included.
            next_seq = int(scanned[-1]["seq"]) if scanned else after_seq
            has_more = False
        return {
            "type": "tool_events",
            "events": page,
            "next_seq": next_seq,
            "has_more": has_more,
            "cursor_reset": False,
        }

    def reset(self) -> None:
        with self._lock:
            self._calls.clear()
            self._call_by_frame.clear()
            self._active_call_id = ""

    def has_active_call(self) -> bool:
        """True while a non-terminal call owns the flight exclusivity slot."""
        with self._lock:
            return self._active_state_locked() is not None

    def cancel_active_for_lease_loss(self, reason: str) -> None:
        """Lease-loss step: one terminal `connection_lost` for the active
        call, then the adapter-level cancellation command."""
        with self._lock:
            active = self._active_state_locked()
            if active is None:
                return
            call_id = active.call.call_id
        self.emit(
            call_id,
            status="fail",
            phase="fail",
            message="connection lost: lease expired or station token gone",
            error={"code": "connection_lost", "reason": reason},
        )
        with self._lock:
            state = self._calls.get(call_id)
            if state is not None and not state.cancel_requested:
                state.cancel_requested = True
                self._commands.put(ToolCommand("cancel", state.call, reason))


    def issue_safety_stop(self, reason: str) -> None:
        """租约丢失直接调用安全停止端口，缺失端口或异常由租约状态机保持取消中。"""
        if self._safety_stop is None:
            raise RuntimeError("safety stop port is required")
        self._safety_stop(reason)

    def _active_state_locked(self) -> _CallState | None:
        state = self._calls.get(self._active_call_id)
        return state if state is not None and not state.terminal else None

    def _append_event_locked(
        self,
        call: ToolCall,
        *,
        status: str,
        phase: str,
        message: str = "",
        progress=None,
        structured_content: dict | None = None,
        error: dict | None = None,
    ) -> None:
        self._event_seq += 1
        event = {
            "type": "tool_event",
            "event_id": f"evt_{self._event_instance}_{self._event_seq}",
            "seq": self._event_seq,
            "call_id": call.call_id,
            "name": call.name,
            "flight_session_id": call.flight_session_id,
            "step_id": call.step_id,
            "frame_id": call.frame_id,
            "station_id": call.station_id,
            "station_instance_id": call.station_instance_id,
            "lease_id": call.lease_id,
            "status": status,
            "phase": phase,
            "progress": progress,
            "isError": status == "fail",
            "structuredContent": dict(structured_content or {}),
            "message": message,
            "error": dict(error) if error is not None else None,
            "ts": _utc_now_iso(),
        }
        self._event_history.append(event)
        sink = self._event_sink
        if sink is not None:
            try:
                sink(event)
            except Exception:  # noqa: BLE001 - pushing must never break the runtime
                pass


def _event_matches(event: dict, identity: dict) -> bool:
    return all(event.get(field) == identity[field] for field in LEASE_IDENTITY_FIELDS)
