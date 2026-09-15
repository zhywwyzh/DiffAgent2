"""工具/RPC 协议词表单一来源。

S2 包拓扑归位（方案 §4.7）：承载执行平面与支撑面共享的协议词汇——
异常类型 ToolProtocolError 与错误码 METHOD_NOT_FOUND / INVALID_PARAMS /
BUSINESS_REJECTED、租约身份字段词表 LEASE_IDENTITY_FIELDS。各定义自
tools/model.py、tools/registry.py、tools/runtime.py 迁入，旧位置定义
已直接删除（无 from-import 转发桩）。
"""

from __future__ import annotations


class ToolProtocolError(Exception):
    """Reject a tool request before it enters the execution runtime."""

    def __init__(self, code: int, message: str, data: dict | None = None) -> None:
        super().__init__(message)
        self.code = int(code)
        self.message = str(message)
        self.data = dict(data or {})

    def to_dict(self) -> dict:
        result = {"code": self.code, "message": self.message}
        if self.data:
            result["data"] = dict(self.data)
        return result


METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

BUSINESS_REJECTED = -32000

# Fleet-spec connection identity fields (agent-station-fleet.spec.md §5).
LEASE_IDENTITY_FIELDS = ("station_id", "station_instance_id", "lease_id")
