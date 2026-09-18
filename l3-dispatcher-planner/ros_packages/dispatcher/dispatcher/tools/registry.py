"""Canonical executable-tool registry and JSON Schema discovery surface."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone

from dispatcher.tools.model import ToolCall, ToolSpec
from dispatcher.tools.protocol import (
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    ToolProtocolError,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")






class ToolRegistry:
    """Index, discover, and validate executable tools."""

    def __init__(self, specs: tuple[ToolSpec, ...]) -> None:
        self._ordered = tuple(specs)
        self._by_name = {spec.name: spec for spec in specs}
        if len(self._by_name) != len(specs):
            raise ValueError("tool names must be unique")

    @classmethod
    def default(cls) -> "ToolRegistry":
        # 生产工具集合：六个 basic_flight.* + navigation.vla_nav（顺序固定，
        # revision 随之锁定；权威记录 specs/implemented/inner/l3-tool-plane.spec.md §1）。
        from dispatcher.tools.flight.catalog import flight_specs
        from dispatcher.tools.vla.catalog import vla_specs
        return cls(tuple(flight_specs()) + tuple(vla_specs()))

    def list_tools(self) -> dict:
        tools = [spec.public_dict() for spec in self._ordered]
        canonical = json.dumps(tools, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        revision = "sha256:" + hashlib.sha256(canonical).hexdigest()
        return {
            "type": "tool_list",
            "revision": revision,
            "tools": tools,
            "ts": _utc_now_iso(),
        }

    def tool_for_name(self, name: str) -> ToolSpec:
        spec = self._by_name.get(str(name or ""))
        if spec is None:
            raise ToolProtocolError(
                METHOD_NOT_FOUND,
                f"tool not registered: {name}",
                {"reason": "tool_not_registered", "name": str(name or "")},
            )
        return spec

    def normalize_call(self, payload: dict) -> ToolCall:
        if not isinstance(payload, dict):
            raise _invalid("invalid_request", "tools/call payload must be an object")
        allowed = {"call_id", "name", "arguments", "context"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise _invalid("unknown_argument", f"unknown call fields: {unknown}")

        call_id = _non_empty_string(payload.get("call_id"), "call_id")
        name = _non_empty_string(payload.get("name"), "name")
        spec = self.tool_for_name(name)

        arguments = _validate_object(payload.get("arguments"), spec.input_schema)
        context = payload.get("context")
        if not isinstance(context, dict):
            raise _invalid("invalid_request", "context must be an object")
        context_unknown = sorted(
            set(context)
            - {
                "flight_session_id",
                "step_id",
                "display_text",
                "station_id",
                "station_instance_id",
                "lease_id",
            }
        )
        if context_unknown:
            raise _invalid("unknown_argument", f"unknown context fields: {context_unknown}")
        flight_session_id = _non_empty_string(context.get("flight_session_id"), "context.flight_session_id")
        step_id = _non_empty_string(context.get("step_id"), "context.step_id")
        display_text = context.get("display_text", "")
        if not isinstance(display_text, str):
            raise _invalid("argument_out_of_range", "context.display_text must be a string")
        # Lease identity presence is enforced by the runtime gate (fleet spec
        # §5: missing/mismatched lease is -32000 connection_not_owner, not a
        # schema error); the registry only validates types when present.
        station_id = _identity_field(context, "station_id")
        station_instance_id = _identity_field(context, "station_instance_id")
        lease_id = _identity_field(context, "lease_id")

        return ToolCall(
            call_id=call_id,
            name=name,
            arguments=arguments,
            flight_session_id=flight_session_id,
            step_id=step_id,
            display_text=display_text,
            station_id=station_id,
            station_instance_id=station_instance_id,
            lease_id=lease_id,
        )


def _invalid(reason: str, details: str) -> ToolProtocolError:
    return ToolProtocolError(
        INVALID_PARAMS,
        "invalid tool call",
        {"reason": reason, "details": details},
    )


def _non_empty_string(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid("missing_required_argument", field)
    return value.strip()


def _identity_field(context: dict, field: str) -> str:
    """Type-check an optional lease-identity context field."""
    value = context.get(field, "")
    if not isinstance(value, str):
        raise _invalid("argument_out_of_range", f"context.{field} must be a string")
    return value.strip()


def _validate_object(value, schema: dict) -> dict:
    if not isinstance(value, dict):
        raise _invalid("invalid_request", "arguments must be an object")
    properties = schema.get("properties") or {}
    unknown = sorted(set(value) - set(properties))
    if unknown:
        raise _invalid("unknown_argument", f"unknown arguments: {unknown}")
    for field in schema.get("required") or []:
        if field not in value:
            raise _invalid("missing_required_argument", field)

    clean = {}
    for field, raw in value.items():
        rule = properties[field]
        if "enum" in rule:
            if raw not in rule["enum"]:
                raise _invalid("argument_out_of_range", f"{field} must be one of {rule['enum']}")
            clean[field] = raw
            continue
        if rule.get("type") == "string":
            if not isinstance(raw, str) or (rule.get("minLength", 0) > 0 and not raw.strip()):
                raise _invalid("argument_out_of_range", f"{field} must be non-empty")
            clean[field] = raw.strip()
            continue
        if rule.get("type") == "number":
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise _invalid("argument_out_of_range", f"{field} must be a number")
            number = float(raw)
            if not math.isfinite(number):
                raise _invalid("argument_out_of_range", f"{field} must be finite")
            if "exclusiveMinimum" in rule and number <= float(rule["exclusiveMinimum"]):
                raise _invalid(
                    "argument_out_of_range",
                    f"{field} must be greater than {rule['exclusiveMinimum']}",
                )
            if "maximum" in rule and number > float(rule["maximum"]):
                raise _invalid(
                    "argument_out_of_range",
                    f"{field} must not exceed {rule['maximum']}",
                )
            clean[field] = number
            continue
        if rule.get("type") == "integer":
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise _invalid("argument_out_of_range", f"{field} must be an integer")
            clean[field] = raw
            continue
        if rule.get("type") == "boolean":
            if not isinstance(raw, bool):
                raise _invalid("argument_out_of_range", f"{field} must be a boolean")
            clean[field] = raw
            continue
        if rule.get("type") == "array":
            if not isinstance(raw, list):
                raise _invalid("argument_out_of_range", f"{field} must be an array")
            if "minItems" in rule and len(raw) < rule["minItems"]:
                raise _invalid(
                    "argument_out_of_range",
                    f"{field} must have at least {rule['minItems']} items",
                )
            if "maxItems" in rule and len(raw) > rule["maxItems"]:
                raise _invalid(
                    "argument_out_of_range",
                    f"{field} must have at most {rule['maxItems']} items",
                )
            item_type = (rule.get("items") or {}).get("type")
            for item in raw:
                if item_type == "integer" and (isinstance(item, bool) or not isinstance(item, int)):
                    raise _invalid("argument_out_of_range", f"{field} items must be integers")
                if item_type == "number" and (
                    isinstance(item, bool)
                    or not isinstance(item, (int, float))
                    or not math.isfinite(float(item))
                ):
                    raise _invalid(
                        "argument_out_of_range",
                        f"{field} items must be finite numbers",
                    )
            clean[field] = list(raw)
            continue
        clean[field] = raw
    return clean
