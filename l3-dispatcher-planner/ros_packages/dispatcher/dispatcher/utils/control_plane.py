"""Compose the tool runtime, zenoh transport, and ROS execution host."""

from __future__ import annotations

import logging
import queue
import threading

from dispatcher.utils.zenoh_rpc import ZenohTaskMiddleware

from dispatcher.tools.executor import ToolExecutor


class _LocalShutdown:
    """shutdown 端口的本地回退：未注入时关停探测恒 False（S4a P1）。"""

    def is_shutdown(self) -> bool:
        return False


class _LocalLog:
    """log 端口的本地回退：未注入时日志走 stdlib logging（S4a P1）。"""

    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

    def err(self, msg: str, *args: object) -> None:
        self._logger.error(msg, *args)


class ToolControlPlane:
    """Own generic tool-plane threads; contain no task-specific behavior."""

    def __init__(
        self,
        host,
        queue_size: int = 32,
        *,
        log=None,
        shutdown=None,
        feedback_factory=None,
    ) -> None:
        self._host = host
        self._commands = queue.Queue(maxsize=queue_size)
        # 端口注入（S4a P1/P3）：日志/关停/反馈面由组合根注入；
        # 未注入时本地回退（关停恒 False、日志走 stdlib logging）。
        self._log = log if log is not None else _LocalLog()
        self._shutdown = shutdown if shutdown is not None else _LocalShutdown()
        self.middleware = ZenohTaskMiddleware(
            self._commands,
            log=log,
            shutdown=shutdown,
            feedback_factory=feedback_factory,
            safety_stop=lambda reason: host.enter_global_stop(reason, shutdown_program=False),
        )
        self._executor = ToolExecutor(self.middleware.registry, host)
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        host.bind_tool_middleware(self.middleware)

    def start(self) -> None:
        if any(thread.is_alive() for thread in self._threads):
            return
        self._stop.clear()
        self._threads = [
            threading.Thread(
                target=self._consume,
                name="tool-command-consumer",
                daemon=True,
            ),
            threading.Thread(
                target=self._serve,
                name="zenoh-tool-server",
                daemon=True,
            ),
        ]
        for thread in self._threads:
            thread.start()

    def close(self) -> None:
        self._stop.set()
        for thread in self._threads:
            if thread is not threading.current_thread():
                thread.join()
        self._threads.clear()
        self.middleware.close()

    def _consume(self) -> None:
        while not self._stop.is_set() and not self._shutdown.is_shutdown():
            try:
                command = self._commands.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if command.kind == "call":
                    if not self.middleware.runtime.can_execute(command.call.call_id):
                        continue
                    self._executor.execute(command.call)
                elif command.kind == "cancel":
                    self._host.cancel_tool_call(command.call, command.reason)
                else:
                    raise ValueError(f"unknown tool command: {command.kind}")
            except Exception as exc:  # noqa: BLE001 - keep the worker alive
                self._log.err(
                    "[tool_runtime] %s %s failed: %s",
                    command.kind,
                    command.call.name,
                    exc,
                )
                self.middleware.runtime.emit(
                    command.call.call_id,
                    status="fail",
                    phase="fail",
                    message=f"tool execution failed: {exc}",
                    error={"code": "execution_error", "message": str(exc)},
                )

    def _serve(self) -> None:
        while not self._stop.is_set() and not self._shutdown.is_shutdown():
            try:
                self.middleware.start()
                return
            except Exception as exc:  # noqa: BLE001 - reconnect supervisor
                self.middleware.close()
                self._log.err(
                    "[zenoh_rpc] middleware start failed (%s); retry in 5s", exc
                )
                self._stop.wait(5.0)
