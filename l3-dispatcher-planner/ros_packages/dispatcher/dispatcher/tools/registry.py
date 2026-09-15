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


def _object_schema(properties: dict | None = None, required: list | None = None) -> dict:
    schema = {
        "type": "object",
        "properties": dict(properties or {}),
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return schema


def _specs() -> tuple[ToolSpec, ...]:
    empty = _object_schema()
    generic_output = _object_schema()
    object_arg = {"type": "string", "minLength": 1}
    return (
        ToolSpec(
            "navigation.vla_reach",
            "Reach a visual target",
            "Locate a described target with VLM perception and execute a mission goal.",
            _object_schema(
                {
                    "object": object_arg,
                    "prompt": {"type": "string", "minLength": 1},
                    "side": {"enum": ["front", "left", "right", "above"]},
                    "distance_m": {"type": "number", "exclusiveMinimum": 0},
                },
                ["object", "prompt"],
            ),
            generic_output,
            "workflow_result",
            "vla",
            requires_perception=True,
        ),
        ToolSpec(
            "scene.map_search",
            "Resolve a scene object",
            "Resolve an object against the active scene graph.",
            _object_schema({"object": object_arg}, ["object"]),
            generic_output,
            "workflow_result",
            "scene",
        ),
        ToolSpec(
            "scene.navigate",
            "Navigate to a scene object",
            "Execute scene-graph object navigation to the given object id.",
            _object_schema({"object_id": {"type": "integer"}}, ["object_id"]),
            generic_output,
            "workflow_result",
            "scene",
        ),
        ToolSpec(
            "flight.takeoff",
            "Take off",
            "Forward the aircraft takeoff command.",
            empty,
            generic_output,
            "forwarded",
            "flight",
        ),
        ToolSpec(
            "flight.land",
            "Land",
            "Forward the aircraft landing command.",
            empty,
            generic_output,
            "forwarded",
            "flight",
        ),
        ToolSpec(
            "flight.translate",
            "Translate aircraft",
            "Move in the current aircraft body frame.",
            _object_schema(
                {
                    "direction": {"enum": ["forward", "backward", "left", "right"]},
                    "distance_m": {"type": "number", "exclusiveMinimum": 0},
                },
                ["direction", "distance_m"],
            ),
            generic_output,
            "action_result",
            "flight",
        ),
        ToolSpec(
            "flight.rotate",
            "Rotate aircraft",
            "Rotate in place by a body yaw delta.",
            _object_schema(
                {
                    "yaw_delta_deg": {
                        "type": "number",
                        "exclusiveMinimum": -360,
                        "maximum": 360,
                    }
                },
                ["yaw_delta_deg"],
            ),
            generic_output,
            "action_result",
            "flight",
        ),
        ToolSpec(
            "flight.return",
            "Return aircraft",
            "Return to the launch origin or previous recorded position.",
            _object_schema({"target": {"enum": ["origin", "previous"]}}, ["target"]),
            generic_output,
            "action_result",
            "flight",
        ),
        ToolSpec(
            "flight.emergency_stop",
            "Emergency stop",
            "Cancel current motion and forward the emergency stop outputs.",
            empty,
            generic_output,
            "forwarded",
            "flight",
        ),
        ToolSpec(
            "scene_nav.graph.list",
            "List scene graph gallery",
            "List archived scene graphs and the active one.",
            empty,
            generic_output,
            "workflow_result",
            "scene_graph_edit",
            destructive=False,
            idempotent=True,
        ),
        ToolSpec(
            "scene_nav.graph.select",
            "Activate scene graph",
            "Load an archived scene graph via fsm/sg_load.",
            _object_schema({"graph": object_arg}, ["graph"]),
            generic_output,
            "workflow_result",
            "scene_graph_edit",
        ),
        ToolSpec(
            "scene_nav.graph.save",
            "Save scene graph",
            "Archive the currently loaded graph via fsm/sg_save.",
            _object_schema({"graph": object_arg}),
            generic_output,
            "workflow_result",
            "scene_graph_edit",
        ),
        ToolSpec(
            "scene_nav.graph.objects",
            "Query scene graph objects",
            "Resolve object ids, labels, and poses in an archived graph.",
            _object_schema(
                {
                    "graph": object_arg,
                    "label": object_arg,
                }
            ),
            generic_output,
            "workflow_result",
            "scene_graph_edit",
            destructive=False,
            idempotent=True,
        ),
        ToolSpec(
            "scene_nav.graph.object_pose",
            "Edit object pose",
            "Patch an archived object pose and hot-reload the graph with rollback on refusal.",
            _object_schema(
                {
                    "graph": object_arg,
                    "object_id": {"type": "integer"},
                    "pos": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                    "yaw": {"type": "number"},
                    "delta_pos_local": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                    "delta_rot_local_xyzw": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "apply": {"type": "boolean"},
                },
                ["object_id"],
            ),
            generic_output,
            "workflow_result",
            "scene_graph_edit",
        ),
    )


class ToolRegistry:
    """Index, discover, and validate executable tools."""

    def __init__(self, specs: tuple[ToolSpec, ...]) -> None:
        self._ordered = tuple(specs)
        self._by_name = {spec.name: spec for spec in specs}
        if len(self._by_name) != len(specs):
            raise ValueError("tool names must be unique")

    @classmethod
    def default(cls) -> "ToolRegistry":
        return cls(_specs())

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
