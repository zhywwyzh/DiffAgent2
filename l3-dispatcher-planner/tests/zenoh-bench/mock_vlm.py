#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic OpenAI-compatible VLM mock for the zenoh-bench container.

Serves GET /v1/models and POST /v1/chat/completions. The completion content
is a fixed 0-1000-space bbox JSON so pixel_to_world geometry is
deterministic. Env: MOCK_VLM_PORT (default 18110),
MOCK_VLM_BBOX="x1,y1,x2,y2" (default "400,300,600,500").
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("MOCK_VLM_PORT", "18110"))
BBOX = [int(v) for v in os.environ.get("MOCK_VLM_BBOX", "400,300,600,500").split(",")]


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/") == "/v1/models":
            self._send(200, {"object": "list", "data": [{"id": "mock-vlm"}]})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if self.path.rstrip("/") == "/v1/chat/completions":
            content = json.dumps({"bbox_2d": BBOX})
            self._send(
                200,
                {
                    "id": "chatcmpl-mock",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": content},
                        }
                    ],
                },
            )
            return
        self._send(404, {"error": "not found"})

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
