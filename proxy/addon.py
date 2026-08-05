"""
mitmproxy addon — captures HTTP / WebSocket flows and puts them
into a thread-safe queue for the GUI to consume.

It also implements interactive **breakpoints**: when a flow matches the
breakpoint rules, the relevant addon hook (``request`` / ``response``) blocks on
an ``asyncio.Event`` running in mitmproxy's loop thread while the GUI shows an
edit panel. On release the GUI's edits — passed as a plain JSON-able dict, never
a live mitmproxy object — are written back onto the real flow *inside the loop
coroutine* (the only thread-safe place to touch a live flow) and the hook
resumes, forwarding the mutated flow.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from mitmproxy import connection, http, tls

from .breakpoints import BreakpointRules
from .models import FlowModel, WSMessage
from .rules import RuleEngine
from .scope import Scope

# Default seconds to hold a flow before auto-releasing it unedited, so a
# forgotten breakpoint never wedges a client connection indefinitely.
INTERCEPT_TIMEOUT = 120.0


@dataclass
class HeldFlow:
    """A flow paused at a breakpoint, awaiting release from the GUI."""

    flow: http.HTTPFlow
    event: asyncio.Event
    direction: str                       # "request" | "response"
    edits: Optional[dict] = None         # set by release(); applied on resume
    aborted: bool = False


class GlimpseAddon:
    """Mitmproxy addon that bridges captured flows to the GUI queue."""

    def __init__(
        self,
        flow_queue: Queue,
        scope: Scope | None = None,
        breakpoints: BreakpointRules | None = None,
        rules: RuleEngine | None = None,
        wireguard_mode: bool = False,
    ) -> None:
        self.flow_queue = flow_queue
        self.scope = scope or Scope()
        self.breakpoints = breakpoints or BreakpointRules()
        self.rules = rules or RuleEngine()
        self.wireguard_mode = wireguard_mode
        self.intercept_timeout = INTERCEPT_TIMEOUT
        self._start_times: Dict[str, float] = {}
        # flow.id -> HeldFlow for every currently-paused flow. Keyed per id so N
        # flows can be held simultaneously, each with its own Event.
        self._held: Dict[str, HeldFlow] = {}
        # Flipped to False by ProxyServer.stop() so the addon stops pushing
        # flows the instant the user hits Stop, instead of waiting for
        # mitmproxy's asynchronous shutdown (which leaves in-flight requests
        # and keep-alive connections firing hooks for hundreds of ms).
        self._capturing = True
        self._scope_reconnect_generation: int | None = None
        self._scope_reconnect_revision: int | None = None
        self._scope_reconnect_patterns: list[str] = []
        self._wireguard_passthrough_hosts: Dict[str, str] = {}

    def clear(self) -> None:
        self._start_times.clear()

    def pause_capture(self) -> None:
        """Stop pushing new flows to the queue (called on shutdown).

        Thread-safe: a plain bool assignment is atomic under the GIL, and
        the hooks read it on the loop thread while stop() writes it on the
        UI thread. Once False it stays False for the rest of the session.
        """
        self._capturing = False

    # ------------------------------------------------------------------ #
    # Scope filter
    # ------------------------------------------------------------------ #

    def begin_scope_reconnect(
        self,
        generation: int,
        revision: int,
        patterns: list[str],
    ) -> None:
        """Wait for a fresh connection that matches the updated allow list."""
        self._scope_reconnect_generation = generation
        self._scope_reconnect_revision = revision
        self._scope_reconnect_patterns = list(patterns)

    def expire_scope_reconnect(self, revision: int) -> bool:
        """Stop waiting for *revision* and report whether it was still pending."""
        if self._scope_reconnect_revision != revision:
            return False
        self._scope_reconnect_generation = None
        self._scope_reconnect_revision = None
        self._scope_reconnect_patterns = []
        return True

    def cancel_scope_reconnect(self) -> None:
        self._scope_reconnect_generation = None
        self._scope_reconnect_revision = None
        self._scope_reconnect_patterns = []

    def _confirm_scope_reconnect(self, host: str) -> None:
        generation = self._scope_reconnect_generation
        revision = self._scope_reconnect_revision
        if generation is None or revision is None:
            return
        host = (host or "").lower().rstrip(".")
        if not host or not self.scope.accepts(host):
            return
        patterns = self._scope_reconnect_patterns
        if patterns and not Scope._any_match(host, patterns):
            return
        self._scope_reconnect_generation = None
        self._scope_reconnect_revision = None
        self._scope_reconnect_patterns = []
        self.flow_queue.put(("scope_reconnected", generation, revision, host))

    def tls_established_client(self, data: tls.TlsData) -> None:
        """Confirm that a newly intercepted TLS connection is usable."""
        host = data.context.client.sni or ""
        if not host and data.context.server.address:
            host = data.context.server.address[0]
        self._confirm_scope_reconnect(host)

    def tls_clienthello(self, data: tls.ClientHelloData) -> None:
        """Apply WireGuard scope after SNI is available.

        mitmproxy's global allow_hosts/ignore_hosts check happens too early for
        WireGuard's virtual destination addresses and can leave passthrough
        traffic unroutable. At ClientHello time the real hostname is available,
        so deciding here preserves connectivity for non-matching hosts.
        """
        if not self.wireguard_mode:
            return
        host = data.client_hello.sni or ""
        if not host and data.context.server.address:
            host = data.context.server.address[0]
        allow, _ = self.scope.snapshot()
        if (allow and not host) or not self.scope.accepts(host):
            data.ignore_connection = True
            if host:
                self._wireguard_passthrough_hosts[data.context.client.id] = (
                    host.lower().rstrip(".")
                )

    def client_disconnected(self, client: connection.Client) -> None:
        self._wireguard_passthrough_hosts.pop(client.id, None)

    def passthrough_client_ids(self, patterns: list[str]) -> set[str]:
        """Return WireGuard passthrough connections newly covered by patterns."""
        return {
            client_id
            for client_id, host in self._wireguard_passthrough_hosts.items()
            if Scope._any_match(host, patterns)
        }

    def _in_scope(self, flow: http.HTTPFlow) -> bool:
        try:
            host = flow.request.pretty_host or ""
        except Exception:
            return True
        return self.scope.accepts(host)

    # ------------------------------------------------------------------ #
    # Breakpoint handshake (runs in mitmproxy's loop thread)
    # ------------------------------------------------------------------ #

    async def _hold(self, flow: http.HTTPFlow, direction: str) -> None:
        """Pause *flow* until the GUI releases it; apply any edits on resume."""
        event = asyncio.Event()
        held = HeldFlow(flow=flow, event=event, direction=direction)
        self._held[flow.id] = held
        try:
            model = self._build_model(flow, 0.0)
            self.flow_queue.put(("intercept", direction, flow.id, model))
        except Exception as exc:
            # If we can't even announce the hold, don't strand the connection.
            self._held.pop(flow.id, None)
            self.flow_queue.put(("error", f"Capture error: intercept failed: {exc}"))
            return

        try:
            await asyncio.wait_for(event.wait(), timeout=self.intercept_timeout)
        except asyncio.TimeoutError:
            self.flow_queue.put(("intercept_done", flow.id, "timeout"))

        held = self._held.pop(flow.id, None)
        if held is None:
            return
        if held.aborted:
            try:
                flow.kill()
            except Exception:
                pass
            return
        if held.edits:
            try:
                if direction == "request":
                    self._apply_request_edits(flow, held.edits)
                else:
                    self._apply_response_edits(flow, held.edits)
            except Exception as exc:
                self.flow_queue.put(("error", f"Capture error: apply edits failed: {exc}"))

    def release(self, flow_id: str, edits: Optional[dict]) -> None:
        """Resume a held flow, optionally with edits. Runs on the loop thread."""
        held = self._held.get(flow_id)
        if held is None:
            return
        held.edits = edits
        held.event.set()

    def abort(self, flow_id: str) -> None:
        """Kill a held flow (drop the connection). Runs on the loop thread."""
        held = self._held.get(flow_id)
        if held is None:
            return
        held.aborted = True
        held.event.set()

    def drain(self) -> None:
        """Release every held flow (called on shutdown so stop never hangs)."""
        for held in list(self._held.values()):
            held.event.set()

    @staticmethod
    def _apply_request_edits(flow: http.HTTPFlow, edits: dict) -> None:
        req = flow.request
        if "method" in edits and edits["method"]:
            req.method = edits["method"]
        if "url" in edits and edits["url"]:
            req.url = edits["url"]
        if "headers" in edits and edits["headers"] is not None:
            req.headers.clear()
            for key, value in edits["headers"]:
                req.headers.add(key, value)
        if "body" in edits and edits["body"] is not None:
            req.content = edits["body"]

    @staticmethod
    def _apply_response_edits(flow: http.HTTPFlow, edits: dict) -> None:
        resp = flow.response
        if resp is None:
            return
        if "status_code" in edits and edits["status_code"] is not None:
            resp.status_code = int(edits["status_code"])
        if "headers" in edits and edits["headers"] is not None:
            resp.headers.clear()
            for key, value in edits["headers"]:
                resp.headers.add(key, value)
        if "body" in edits and edits["body"] is not None:
            resp.content = edits["body"]

    # ------------------------------------------------------------------ #
    # Mock / rewrite rules (runs in mitmproxy's loop thread)
    # ------------------------------------------------------------------ #

    def _apply_request_rules(self, flow: http.HTTPFlow, url: str) -> None:
        for rule in self.rules.matching("request_rewrite", url):
            self._rewrite_request(flow, rule)

    def _apply_mock_rules(self, flow: http.HTTPFlow, url: str) -> bool:
        for rule in self.rules.matching("mock", url):
            status = self._int(rule.get("status") or rule.get("status_code"), 200)
            body = self._body_from_rule(rule)
            headers = self._mock_headers(flow, rule)
            flow.response = http.Response.make(status, body, headers)
            self.flow_queue.put(("rule_applied", "mock", rule.get("name") or rule.get("match")))
            return True
        return False

    def _apply_response_rules(self, flow: http.HTTPFlow, url: str) -> None:
        if flow.response is None:
            return
        for rule in self.rules.matching("response_rewrite", url):
            self._rewrite_response(flow, rule)

    def _rewrite_request(self, flow: http.HTTPFlow, rule: Dict[str, Any]) -> None:
        req = flow.request
        redirect = str(rule.get("url") or rule.get("redirect_url") or "").strip()
        if redirect:
            req.url = redirect
        self._apply_header_ops(req.headers, rule)
        body = self._replace_body(req.content or b"", rule, req.headers.get("content-type", ""))
        if body is not None:
            req.content = body
        self.flow_queue.put(("rule_applied", "request_rewrite", rule.get("name") or rule.get("match")))

    def _rewrite_response(self, flow: http.HTTPFlow, rule: Dict[str, Any]) -> None:
        resp = flow.response
        if resp is None:
            return
        status = rule.get("status") or rule.get("status_code")
        if status is not None:
            resp.status_code = self._int(status, resp.status_code)
        self._apply_header_ops(resp.headers, rule)
        body = self._replace_body(resp.content or b"", rule, resp.headers.get("content-type", ""))
        if body is not None:
            resp.content = body
        self.flow_queue.put(("rule_applied", "response_rewrite", rule.get("name") or rule.get("match")))

    @staticmethod
    def _headers(value: Any) -> Dict[str, str]:
        if isinstance(value, dict):
            return {str(k): str(v) for k, v in value.items()}
        if isinstance(value, list):
            out: Dict[str, str] = {}
            for row in value:
                if isinstance(row, (list, tuple)) and len(row) >= 2:
                    out[str(row[0])] = str(row[1])
            return out
        return {}

    @classmethod
    def _mock_headers(cls, flow: http.HTTPFlow, rule: Dict[str, Any]) -> Dict[str, str]:
        headers = cls._headers(rule.get("headers"))
        lower = {key.lower() for key in headers}

        body = rule.get("body")
        if isinstance(body, (dict, list)) and "content-type" not in lower:
            headers["content-type"] = "application/json; charset=utf-8"

        # Browser/WebView requests often rely on CORS headers that a breakpoint
        # edit preserves from upstream, but a mock response would otherwise lose.
        origin = flow.request.headers.get("origin")
        if origin and "access-control-allow-origin" not in lower:
            headers["access-control-allow-origin"] = origin
            headers.setdefault("access-control-allow-credentials", "true")
            headers.setdefault("vary", "Origin")

        req_headers = flow.request.headers.get("access-control-request-headers")
        if req_headers and "access-control-allow-headers" not in lower:
            headers["access-control-allow-headers"] = req_headers
        if "access-control-allow-methods" not in lower:
            headers.setdefault(
                "access-control-allow-methods",
                "GET, POST, PUT, PATCH, DELETE, OPTIONS",
            )
        return headers

    @classmethod
    def _apply_header_ops(cls, headers, rule: Dict[str, Any]) -> None:
        remove = rule.get("remove_headers") or []
        if isinstance(remove, str):
            remove = [remove]
        for name in remove if isinstance(remove, list) else []:
            if name:
                try:
                    del headers[str(name)]
                except KeyError:
                    pass

        set_headers = rule.get("set_headers")
        if set_headers is None:
            set_headers = rule.get("headers")
        for key, value in cls._headers(set_headers).items():
            headers[key] = value

    @staticmethod
    def _int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _body_from_rule(rule: Dict[str, Any]) -> bytes:
        file_path = str(rule.get("file") or "").strip()
        if file_path:
            try:
                return Path(os.path.expanduser(file_path)).read_bytes()
            except OSError:
                return b""
        body = rule.get("body", b"")
        if isinstance(body, bytes):
            return body
        if isinstance(body, (dict, list)):
            return json.dumps(body, ensure_ascii=False).encode("utf-8")
        if body is None:
            return b""
        return str(body).encode("utf-8")

    @staticmethod
    def _replace_body(body: bytes, rule: Dict[str, Any], content_type: str) -> Optional[bytes]:
        if "body" in rule and rule.get("kind") != "mock":
            value = rule.get("body")
            if isinstance(value, bytes):
                return value
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False).encode("utf-8")
            return ("" if value is None else str(value)).encode("utf-8")

        find = rule.get("body_find") or rule.get("find")
        if find is None:
            return None
        replace = rule.get("body_replace")
        if replace is None:
            replace = rule.get("replace", "")

        encoding = "utf-8"
        if "charset=" in (content_type or "").lower():
            encoding = content_type.lower().split("charset=", 1)[1].split(";", 1)[0].strip()
        try:
            text = body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            text = body.decode("utf-8", errors="replace")
            encoding = "utf-8"
        return text.replace(str(find), str(replace)).encode(encoding, errors="replace")

    # ------------------------------------------------------------------ #
    # HTTP hooks
    # ------------------------------------------------------------------ #

    async def request(self, flow: http.HTTPFlow) -> None:
        self._start_times[flow.id] = time.perf_counter()
        if not self._capturing:
            return
        try:
            self._confirm_scope_reconnect(flow.request.pretty_host or "")
        except Exception:
            pass
        if not self._in_scope(flow):
            return
        try:
            url = flow.request.pretty_url
        except Exception:
            url = ""
        try:
            self._apply_request_rules(flow, url)
            try:
                url = flow.request.pretty_url
            except Exception:
                pass
            mocked = self._apply_mock_rules(flow, url)
        except Exception as exc:
            mocked = False
            self.flow_queue.put(("error", f"Capture error: rule failed: {exc}"))
        if self.breakpoints.matches_request(url):
            await self._hold(flow, "request")
        if mocked:
            return

    async def response(self, flow: http.HTTPFlow) -> None:
        if not self._capturing:
            self._start_times.pop(flow.id, None)
            return
        try:
            url = flow.request.pretty_url
        except Exception:
            url = ""
        try:
            self._apply_response_rules(flow, url)
        except Exception as exc:
            self.flow_queue.put(("error", f"Capture error: rule failed: {exc}"))
        if self.breakpoints.matches_response(url):
            await self._hold(flow, "response")

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
        if not self._capturing or not self._in_scope(flow):
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
        if not self._capturing or not self._in_scope(flow):
            return
        try:
            self._start_times[flow.id] = time.perf_counter()
            model = self._build_model(flow, 0.0, flow_type="websocket")
            self.flow_queue.put(("flow", model))
        except Exception as exc:
            self.flow_queue.put(("error", f"Capture error: {exc}"))

    def websocket_message(self, flow: http.HTTPFlow) -> None:
        if not self._capturing or not self._in_scope(flow):
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

        # Parse cookies before dict(req.headers) flattens duplicate cookie
        # fields (HTTP/2 splits Cookie into one field per crumb). mitmproxy's
        # req.cookies handles both HTTP/1.1 and HTTP/2 forms correctly.
        try:
            request_cookies = list(req.cookies.items(multi=True))
        except Exception:
            request_cookies = []

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
            request_cookies=request_cookies,
            response_headers=resp_headers,
            response_body=resp_body,
            duration=duration,
        )
