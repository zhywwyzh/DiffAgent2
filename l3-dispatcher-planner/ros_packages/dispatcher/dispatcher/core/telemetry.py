"""运行遥测对象（S3 方案 §2.4/§5）：slog 事件、trace 落盘、监控发布、等待诊断。

自 engine.py 迁出（零语义变更：slog 事件名/键集、trace 文件格式、
dispatcher_started 键集、monitor/command_content payload、等待诊断串格式
「channel=topic:age / never」字节级一致）。运行日志经注入的 LogSink 端口
提供（engine/core 零 rospy，G7）；命令内容监控经 CoreChannels 端口发布。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from dispatcher.core.ports import CoreChannels, LogSink
from dispatcher.utils.slog import StructuredLogger


class RunTelemetry:
    """运行遥测：slog/trace 封装 + 命令内容监控 + 等待诊断格式化。"""

    def __init__(
        self,
        node_name: str,
        level: str,
        stdout_en: bool,
        log_root: Path,
        headless: bool,
        log: LogSink,
        channels: CoreChannels,
    ) -> None:
        # 运行日志端口（S3 §5：原 engine 全部 rospy 日志调用经 LogSink）：
        # 绑定 sink 方法为本对象属性，engine 调用点统一走 self.runlog.*。
        self.info = log.info
        self.warn = log.warn
        self.err = log.err
        self.warn_throttle = log.warn_throttle

        # 四类 core 通道端口（命令内容监控发布用）
        self.channels = channels

        self.telemetry = StructuredLogger(
            node_name,
            level,
            stdout_en,
        )

        # lx patch: log root is ~log_dir (default ~/.ros/log/dispatcher) because the
        # install location (devel space) is mounted read-only at runtime.
        # （~log_dir 由 composition root 解析为普通值注入，S3 §4.7）
        log_dir = log_root / "dispatcher"
        log_dir.mkdir(parents=True, exist_ok=True)
        session_tag = time.strftime("%Y%m%d_%H%M%S")
        self.log_session_tag = session_tag
        # Decision trace sink (replay/attribution source of truth): one
        # append-only JSONL per session under ~log_dir/trace.
        self.telemetry.attach_trace(
            log_dir / "trace" / f"trace_{session_tag}.jsonl",
            session_tag=session_tag,
        )
        self.emit(
            "info",
            "dispatcher_started",
            headless=bool(headless),
            log_dir=str(log_root),
        )

    def emit(self, level: str, event: str, **fields) -> None:
        """Emit a slog-compatible dispatcher decision event."""
        self.telemetry.emit(level, event, **fields)

    def publish_command_content(self, command_content):
        """发布当前指令内容（保持字符串列表 schema，从队列元组中取 prompt）"""
        prompts = [entry[0] for entry in command_content]
        self.channels.publish_command_content(json.dumps(prompts, ensure_ascii=False))

    @staticmethod
    def fmt_wait_age(age) -> str:
        """健康年龄格式化：None = 从未收到（区别于慢）。"""
        return "never" if age is None else f"{age:.1f}s"

    def wait_diag(self, health, *, stale_after: float = 2.0) -> str:
        """决策链输入通道的诊断串：channel=topic:age 逐路点名。

        未启用的可选通道不进入健康表，也不在此
        显示——缺席即关闭，区别于“在但死”。
        health 由外部传入（S3 §5）：engine 侧负责调 get_sensor_input_health
        并对取值异常兜底为 input_health_unavailable（与迁移前 try/except
        包裹的语义一致）。
        """
        return " ".join(
            f"{channel}={topic}:{self.fmt_wait_age(age)}"
            + (":stale" if age is not None and age > stale_after else "")
            for channel, (topic, age) in health.items()
        ) or "no_input_channels"
