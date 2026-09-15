"""Exclusive station-to-stack connection lease manager (fleet spec v1).

Owns the strictly one-to-one station/stack mapping for one stack: acquire,
renew, release, status, plus the ordered lease-loss transition
OWNED -> LEASE_LOST -> CANCELLING -> SAFETY_REQUESTED -> UNOWNED.
Transport-independent: time is an injected monotonic clock and the loss
side effects are injected handlers, so the manager is fully testable
without ROS or zenoh.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Callable

from dispatcher.tools.protocol import INVALID_PARAMS, ToolProtocolError

BUSINESS_REJECTED = -32000

DEFAULT_TTL_S = 15.0

# Lease-loss state machine states (fleet spec §7).
UNOWNED = "unowned"
OWNED = "owned"
LEASE_LOST = "lease_lost"
CANCELLING = "cancelling"
SAFETY_REQUESTED = "safety_requested"

# A new acquire is refused while the previous lease ledger is not terminal.
LOSS_IN_PROGRESS = frozenset({LEASE_LOST, CANCELLING, SAFETY_REQUESTED})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _non_empty(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolProtocolError(
            INVALID_PARAMS,
            "invalid connection request",
            {"reason": "missing_required_argument", "details": field},
        )
    return value.strip()


def _identity_fields(identity) -> tuple[str, str, str]:
    """Validate the owner identity triple (station_id, instance, lease)."""
    if not isinstance(identity, dict):
        raise _not_owner("connection identity missing")
    return (
        _non_empty(identity.get("station_id"), "station_id"),
        _non_empty(identity.get("station_instance_id"), "station_instance_id"),
        _non_empty(identity.get("lease_id"), "lease_id"),
    )


def _identity_fields_or_not_owner(identity) -> tuple[str, str, str]:
    """Tool-plane gate: a missing lease identity is connection_not_owner."""
    if not isinstance(identity, dict):
        raise _not_owner("connection identity missing")
    fields = []
    for field in ("station_id", "station_instance_id", "lease_id"):
        value = identity.get(field)
        if not isinstance(value, str) or not value.strip():
            raise _not_owner(f"missing {field}")
        fields.append(value.strip())
    return fields[0], fields[1], fields[2]


def _not_owner(details: str) -> ToolProtocolError:
    return ToolProtocolError(
        BUSINESS_REJECTED,
        "request requires the current connection lease",
        {"reason": "connection_not_owner", "details": details},
    )


def _busy(details: str, **extra) -> ToolProtocolError:
    data = {"reason": "connection_busy", "details": details}
    data.update(extra)
    return ToolProtocolError(BUSINESS_REJECTED, "stack connection is busy", data)


class ConnectionLeaseManager:
    """Single authoritative lease ledger for one stack."""

    def __init__(
        self,
        stack_id: str,
        *,
        ttl_s: float = DEFAULT_TTL_S,
        clock: Callable[[], float] | None = None,
        wall_clock: Callable[[], float] | None = None,
        iso_now: Callable[[], str] | None = None,
        lease_id_factory: Callable[[], str] | None = None,
        active_call_probe: Callable[[], bool] | None = None,
    ) -> None:
        self._stack_id = str(stack_id)
        self._ttl_s = float(ttl_s)
        if self._ttl_s <= 0:
            raise ValueError("ttl_s must be positive")
        self._clock = clock or time.monotonic
        self._wall_clock = wall_clock or time.time
        self._iso_now = iso_now or _utc_now_iso
        self._lease_id_factory = lease_id_factory or (lambda: f"lease_{uuid.uuid4().hex[:12]}")
        self._active_call_probe = active_call_probe
        self._lock = threading.RLock()
        self._state = UNOWNED
        self._lease: dict | None = None
        self._pending_loss: dict | None = None
        self._loss_handlers: tuple[Callable, Callable, Callable] | None = None
        self._last_loss_reason = ""

    # ------------------------------------------------------------------
    # wiring
    # ------------------------------------------------------------------

    def bind_loss_handlers(
        self,
        cancel_active: Callable[[str], None],
        issue_safety_stop: Callable[[str], None],
        on_released: Callable[[str, str], None],
    ) -> None:
        """Bind the lease-loss side effects (injected, never inherited).

        cancel_active(reason) cancels the active call and emits the
        connection_lost terminal; issue_safety_stop(reason) issues the
        emergency/safety-stop request; on_released(station_id, lease_id)
        runs after the lease is fully terminal (watch teardown).
        """
        with self._lock:
            self._loss_handlers = (cancel_active, issue_safety_stop, on_released)

    def set_active_call_probe(self, probe: Callable[[], bool]) -> None:
        """Bind the runtime probe used to reject release-while-active."""
        with self._lock:
            self._active_call_probe = probe

    # ------------------------------------------------------------------
    # connection query surface (fleet spec §4)
    # ------------------------------------------------------------------

    def acquire(self, station_id, station_instance_id) -> dict:
        sid = _non_empty(station_id, "station_id")
        inst = _non_empty(station_instance_id, "station_instance_id")
        self.expire_if_due()
        with self._lock:
            if self._state in LOSS_IN_PROGRESS:
                raise _busy(
                    "lease loss in progress; retry after the safety stop",
                    state=self._state,
                )
            if self._state == OWNED:
                lease = self._lease
                if lease["station_id"] == sid and lease["station_instance_id"] == inst:
                    return self._lease_reply(lease)  # idempotent re-acquire
                raise _busy(
                    "stack already owned by another station",
                    owner_station_id=lease["station_id"],
                    expires_at=lease["expires_at"],
                )
            lease = {
                "station_id": sid,
                "station_instance_id": inst,
                "lease_id": self._lease_id_factory(),
                "expires_at": self._clock() + self._ttl_s,
            }
            self._lease = lease
            self._state = OWNED
            return self._lease_reply(lease)

    def renew(self, station_id, station_instance_id, lease_id) -> dict:
        identity = {
            "station_id": station_id,
            "station_instance_id": station_instance_id,
            "lease_id": lease_id,
        }
        sid, inst, lid = _identity_fields(identity)
        self.expire_if_due()
        with self._lock:
            lease = self._require_owner_locked(sid, inst, lid)
            lease["expires_at"] = self._clock() + self._ttl_s
            return self._lease_reply(lease)

    def release(self, station_id, station_instance_id, lease_id) -> dict:
        identity = {
            "station_id": station_id,
            "station_instance_id": station_instance_id,
            "lease_id": lease_id,
        }
        sid, inst, lid = _identity_fields(identity)
        self.expire_if_due()
        with self._lock:
            lease = self._require_owner_locked(sid, inst, lid)
            if self._active_call_probe is not None and self._active_call_probe():
                raise ToolProtocolError(
                    BUSINESS_REJECTED,
                    "lease owns an active tool call; cancel it first",
                    {"reason": "connection_active", "lease_id": lid},
                )
            self._drop_lease_locked()
        self._notify_released(sid, lid)
        return {
            "type": "connection_release",
            "released": True,
            "station_id": sid,
            "station_instance_id": inst,
            "lease_id": lid,
            "ts": self._iso_now(),
        }

    def status(self) -> dict:
        """Claim-free ownership/expiry snapshot for discovery cards."""
        self.expire_if_due()
        with self._lock:
            result = {
                "type": "connection_status",
                "stack_id": self._stack_id,
                "owned": self._state == OWNED,
                "state": self._state,
                "ttl_ms": int(self._ttl_s * 1000),
                "ts": self._iso_now(),
            }
            if self._state == OWNED and self._lease is not None:
                result["station_id"] = self._lease["station_id"]
                result["expires_at"] = self._iso_from_wall(self._lease["expires_at"])
            return result

    # ------------------------------------------------------------------
    # owner gate for the tool plane (fleet spec §5)
    # ------------------------------------------------------------------

    def require_owner(self, identity) -> dict:
        """Return the current lease for a verified owner identity triple."""
        sid, inst, lid = _identity_fields_or_not_owner(identity)
        self.expire_if_due()
        with self._lock:
            return dict(self._require_owner_locked(sid, inst, lid))

    # ------------------------------------------------------------------
    # loss handling (fleet spec §7)
    # ------------------------------------------------------------------

    def expire_if_due(self) -> bool:
        """TTL is the hard authority: reap an expired lease on any touch."""
        with self._lock:
            due = (
                self._state == OWNED
                and self._lease is not None
                and self._clock() >= self._lease["expires_at"]
            )
        return self.mark_lost("lease_expired") if due else False

    def notify_owner_lost(self, reason: str = "station_connection_token_lost") -> bool:
        """Owner connection-token loss reported by the liveliness watch."""
        with self._lock:
            owned = self._state == OWNED
        return self.mark_lost(reason) if owned else False

    def mark_lost(self, reason: str) -> bool:
        """Ordered transition OWNED -> LEASE_LOST -> CANCELLING ->
        SAFETY_REQUESTED -> UNOWNED; admission stops immediately and the
        lease is free again only after the safety request is issued.

        Each state is entered BEFORE its side effect runs, so concurrent
        observers see the spec order. A safety-dispatch failure is
        fail-closed: the state reverts to CANCELLING (never UNOWNED) and
        the exception propagates; resume_pending_loss retries.
        """
        with self._lock:
            if self._state != OWNED:
                return False
            lease = dict(self._lease or {})
            self._state = LEASE_LOST
            self._lease = None
            self._last_loss_reason = str(reason)
            self._pending_loss = {"reason": str(reason), "lease": lease}
            cancel_active, issue_safety_stop, on_released = self._loss_handlers or (None, None, None)
        with self._lock:
            self._state = CANCELLING
        if cancel_active is not None:
            cancel_active(reason)
        return self._complete_loss(reason, lease, issue_safety_stop, on_released)

    def resume_pending_loss(self) -> bool:
        """Retry the safety step of a loss interrupted during dispatch.

        No-op unless a previous mark_lost left the ledger in CANCELLING
        (safety requested but not issued); fail-closed until it lands.
        """
        with self._lock:
            if self._state != CANCELLING or self._pending_loss is None:
                return False
            pending = dict(self._pending_loss)
            _, issue_safety_stop, on_released = self._loss_handlers or (None, None, None)
        if issue_safety_stop is None:
            return False
        return self._complete_loss(pending["reason"], pending["lease"], issue_safety_stop, on_released)

    def _complete_loss(self, reason: str, lease: dict, issue_safety_stop, on_released) -> bool:
        """Safety phase: enter SAFETY_REQUESTED, dispatch, then release."""
        with self._lock:
            self._state = SAFETY_REQUESTED
        try:
            if issue_safety_stop is not None:
                issue_safety_stop(reason)
        except Exception:
            # Fail closed: the safety request was not issued, so the stack
            # must not become acquirable; retry via resume_pending_loss.
            with self._lock:
                self._state = CANCELLING
            raise
        if on_released is not None and lease:
            on_released(lease.get("station_id", ""), lease.get("lease_id", ""))
        with self._lock:
            self._state = UNOWNED
            self._pending_loss = None
        return True

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def last_loss_reason(self) -> str:
        with self._lock:
            return self._last_loss_reason

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _require_owner_locked(self, sid: str, inst: str, lid: str) -> dict:
        lease = self._lease
        if (
            self._state != OWNED
            or lease is None
            or lease["station_id"] != sid
            or lease["station_instance_id"] != inst
            or lease["lease_id"] != lid
        ):
            owner = lease.get("station_id", "") if lease else ""
            details = "no active lease" if lease is None else f"lease does not match (owner={owner})"
            raise _not_owner(details)
        return lease

    def _drop_lease_locked(self) -> None:
        self._lease = None
        self._state = UNOWNED

    def _lease_reply(self, lease: dict) -> dict:
        return {
            "type": "connection_lease",
            "accepted": True,
            "stack_id": self._stack_id,
            "station_id": lease["station_id"],
            "station_instance_id": lease["station_instance_id"],
            "lease_id": lease["lease_id"],
            "ttl_ms": int(self._ttl_s * 1000),
            "expires_at": self._iso_from_wall(lease["expires_at"]),
        }

    def _iso_from_wall(self, expires_at_mono: float) -> str:
        """Render the lease expiry as wall-clock ISO from the monotonic due."""
        remaining = max(0.0, expires_at_mono - self._clock())
        stamp = datetime.fromtimestamp(self._wall_clock() + remaining, tz=timezone.utc)
        return stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _notify_released(self, sid: str, lid: str) -> None:
        with self._lock:
            on_released = self._loss_handlers[2] if self._loss_handlers else None
        if on_released is not None:
            on_released(sid, lid)
