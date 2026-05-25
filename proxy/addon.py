"""
mitmproxy addon — captures HTTP / WebSocket flows and puts them
into a thread-safe queue for the GUI to consume.
"""
from __future__ import annotations

import time
from queue import Queue
from typing import Dict
from urllib.parse import urlparse

from mitmproxy import http

from .models import FlowModel, WSMessage
from .scope import Scope


class ProxymanAddon:
    """Mitmproxy addon that bridges captured flows to the GUI queue."""

    def __init__(self, flow_queue: Queue, scope: Scope | None = None) -> None:
        self.flow_queue = flow_queue
        self.scope = scope or Scope()
        self._start_times: Dict[str, float] = {}

    def clear(self) -> None:
        self._start_times.clear()

    # ------------------------------------------------------------------ #
    # Scope filter
    # ------------------------------------------------------------------ #

    def _in_scope(self, flow: http.HTTPFlow) -> bool:
        try:
            host = flow.request.pretty_host or ""
        except Exception:
            return True
        return self.scope.accepts(host)

    # ------------------------------------------------------------------ #
    # HTTP hooks
    # ------------------------------------------------------------------ #

    def request(self, flow: http.HTTPFlow) -> None:
        self._start_times[flow.id] = time.perf_counter()

    def response(self, flow: http.HTTPFlow) -> None:
        if not self._in_scope(flow):
            self._start_times.pop(flow.id, None)
            return
        try:
            duration = time.perf_counter() - self._start_times.pop(flow.id, time.perf_counter())
            model = self._build_model(flow, duration)
            self.flow_queue.put(("flow", model))
        except Exception as exc:
            self.flow_queue.put(("error", f"Capture error: {exc}"))

    def error(self, flow: http.HTTPFlow) -> None:
        if not self._in_scope(flow):
            self._start_times.pop(flow.id, None)
            return
        try:
            duration = time.perf_counter() - self._start_times.pop(flow.id, time.perf_counter())
            model = self._build_model(flow, duration)
            model.error = str(flow.error) if flow.error else "Unknown error"
            self.flow_queue.put(("flow", model))
        except Exception as exc:
            self.flow_queue.put(("error", f"Capture error: {exc}"))

    # ------------------------------------------------------------------ #
    # WebSocket hooks
    # ------------------------------------------------------------------ #

    def websocket_start(self, flow: http.HTTPFlow) -> None:
        if not self._in_scope(flow):
            return
        try:
            self._start_times[flow.id] = time.perf_counter()
            model = self._build_model(flow, 0.0, flow_type="websocket")
            self.flow_queue.put(("flow", model))
        except Exception as exc:
            self.flow_queue.put(("error", f"Capture error: {exc}"))

    def websocket_message(self, flow: http.HTTPFlow) -> None:
        if not self._in_scope(flow):
            return
        assert flow.websocket is not None
        msg = flow.websocket.messages[-1]
        ws_msg = WSMessage(
            from_client=msg.from_client,
            content=msg.content if isinstance(msg.content, bytes) else msg.content.encode(),
        )
        self.flow_queue.put(("ws_message", flow.id, ws_msg))

    def websocket_end(self, flow: http.HTTPFlow) -> None:
        if flow.id not in self._start_times:
            return
        duration = time.perf_counter() - self._start_times.pop(flow.id, time.perf_counter())
        self.flow_queue.put(("ws_end", flow.id, duration))

    # ------------------------------------------------------------------ #
    # Helper
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_url(req) -> tuple[str, str]:
        """Return (path, query) from a mitmproxy Request."""
        parsed = urlparse(req.url)
        path = parsed.path or "/"
        return path, parsed.query

    def _build_model(
        self,
        flow: http.HTTPFlow,
        duration: float,
        flow_type: str = "http",
    ) -> FlowModel:
        req = flow.request
        resp = flow.response
        path, query = self._parse_url(req)

        resp_headers: dict = {}
        resp_body = b""
        status_code = None
        status_msg = ""

        if resp is not None:
            resp_headers = dict(resp.headers)
            resp_body = resp.content or b""
            status_code = resp.status_code
            status_msg = resp.reason or ""

        return FlowModel(
            id=flow.id,
            flow_type=flow_type,
            method=req.method,
            scheme=req.scheme,
            host=req.pretty_host,
            path=path,
            query=query,
            status_code=status_code,
            status_message=status_msg,
            request_headers=dict(req.headers),
            request_body=req.content or b"",
            response_headers=resp_headers,
            response_body=resp_body,
            duration=duration,
        )
