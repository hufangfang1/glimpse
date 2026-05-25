"""
Flow data models for Glimpse.
"""
from __future__ import annotations

import gzip
import json
import shlex
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class WSMessage:
    """Single WebSocket message."""
    from_client: bool
    content: bytes
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def direction(self) -> str:
        return "↑ Client" if self.from_client else "↓ Server"

    @property
    def text(self) -> str:
        try:
            return self.content.decode("utf-8")
        except Exception:
            return repr(self.content)


@dataclass
class FlowModel:
    """Captured HTTP/WebSocket flow."""

    id: str
    flow_type: str          # "http" | "websocket"
    method: str
    scheme: str
    host: str
    path: str
    query: str = ""
    status_code: Optional[int] = None
    status_message: str = ""
    request_headers: Dict[str, str] = field(default_factory=dict)
    request_body: bytes = b""
    response_headers: Dict[str, str] = field(default_factory=dict)
    response_body: bytes = b""
    timestamp: datetime = field(default_factory=datetime.now)
    duration: float = 0.0
    error: Optional[str] = None
    ws_messages: List[WSMessage] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Computed properties
    # ------------------------------------------------------------------ #

    @staticmethod
    def _header_value(headers: Dict[str, str], name: str) -> str:
        name_lower = name.lower()
        for key, value in headers.items():
            if key.lower() == name_lower:
                return value
        return ""

    @property
    def url(self) -> str:
        qs = f"?{self.query}" if self.query else ""
        return f"{self.scheme}://{self.host}{self.path}{qs}"

    @property
    def response_size(self) -> int:
        return len(self.response_body)

    @property
    def content_type(self) -> str:
        ct = self._header_value(self.response_headers, "content-type")
        return ct.split(";")[0].strip()

    @property
    def request_content_type(self) -> str:
        ct = self._header_value(self.request_headers, "content-type")
        return ct.split(";")[0].strip()

    def display_type(self) -> str:
        ct = self.content_type or self.request_content_type
        if ct:
            return ct
        if self.response_body and self._body_looks_like_json(self.response_body):
            return "application/json"
        if self.request_body and self._body_looks_like_json(self.request_body):
            return "application/json"
        return ""

    def format_size(self) -> str:
        size = self.response_size
        if size == 0:
            return "-"
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.1f} MB"

    def format_duration(self) -> str:
        if self.duration <= 0:
            return "-"
        if self.duration < 1:
            return f"{self.duration * 1000:.0f} ms"
        return f"{self.duration:.2f} s"

    # ------------------------------------------------------------------ #
    # Body decoding helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _decompress(raw: bytes, encoding_header: str) -> bytes:
        body = raw
        enc = encoding_header.lower()
        try:
            if "gzip" in enc:
                body = gzip.decompress(body)
            elif "deflate" in enc:
                try:
                    body = zlib.decompress(body)
                except zlib.error:
                    body = zlib.decompress(body, -15)
            elif "br" in enc:
                import brotli
                body = brotli.decompress(body)
            elif "zstd" in enc:
                import zstandard
                body = zstandard.ZstdDecompressor().decompress(body)
        except Exception:
            pass
        return body

    @staticmethod
    def _try_pretty_json(text: str) -> tuple[str, bool]:
        """If *text* is JSON, return an indented string and True."""
        stripped = text.strip()
        if not stripped or stripped[0] not in "{[":
            return text, False
        try:
            parsed = json.loads(stripped)
            return json.dumps(parsed, indent=2, ensure_ascii=False), True
        except Exception:
            return text, False

    def _decode_body(self, raw: bytes, encoding_header: str, content_type: str) -> tuple[str, bool]:
        body = self._decompress(raw, encoding_header)
        text = body.decode("utf-8", errors="replace")

        formatted, is_json = self._try_pretty_json(text)
        if is_json:
            return formatted, True

        if self._is_json_content_type(content_type):
            try:
                parsed = json.loads(text)
                return json.dumps(parsed, indent=2, ensure_ascii=False), True
            except Exception:
                pass

        return text, False

    def get_request_body_text(self) -> str:
        text, _ = self.get_request_body_display()
        return text

    def get_request_body_display(self) -> tuple[str, bool]:
        if not self.request_body:
            return "", False
        ct = self._header_value(self.request_headers, "content-type")
        enc = self._header_value(self.request_headers, "content-encoding")
        return self._decode_body(self.request_body, enc, ct)

    def get_response_body_text(self) -> str:
        text, _ = self.get_response_body_display()
        return text

    def get_response_body_display(self) -> tuple[str, bool]:
        if not self.response_body:
            return "", False
        ct = self._header_value(self.response_headers, "content-type")
        enc = self._header_value(self.response_headers, "content-encoding")
        return self._decode_body(self.response_body, enc, ct)

    @staticmethod
    def _body_looks_like_json(raw: bytes) -> bool:
        try:
            text = raw.decode("utf-8").strip()
        except Exception:
            return False
        if not text:
            return False
        return text[0] in ("{", "[")

    @staticmethod
    def _is_json_content_type(content_type: str) -> bool:
        return "json" in content_type.lower()

    def is_image(self) -> bool:
        return self.content_type.startswith("image/")

    def is_json(self) -> bool:
        return self._is_json_content_type(self.content_type)

    def is_request_json(self) -> bool:
        return self._is_json_content_type(self.request_content_type)

    def is_html(self) -> bool:
        return "html" in self.content_type

    # ------------------------------------------------------------------ #
    # Export helpers
    # ------------------------------------------------------------------ #

    # Headers we drop when exporting / replaying — they're either recomputed
    # by curl/httpx, or carry transport-level state that shouldn't be reused.
    _SKIP_EXPORT_HEADERS = {
        "content-length",
        "host",
        "connection",
        "proxy-connection",
        "transfer-encoding",
    }

    def to_curl(self, multiline: bool = True) -> str:
        """Render this flow's request as a runnable curl command."""
        parts: List[str] = ["curl"]
        if self.method.upper() != "GET":
            parts.append(f"-X {self.method}")
        parts.append(shlex.quote(self.url))

        for key, value in self.request_headers.items():
            if key.lower() in self._SKIP_EXPORT_HEADERS:
                continue
            parts.append(f"-H {shlex.quote(f'{key}: {value}')}")

        if self.request_body:
            try:
                body_text = self.request_body.decode("utf-8")
                parts.append(f"--data-raw {shlex.quote(body_text)}")
            except UnicodeDecodeError:
                # Binary body — fall back to a base64 pipeline so the command
                # is still copy-paste runnable in a POSIX shell.
                import base64
                b64 = base64.b64encode(self.request_body).decode("ascii")
                parts.append(
                    f'--data-binary "$(echo {b64} | base64 -d)"'
                )

        sep = " \\\n  " if multiline else " "
        return sep.join(parts)
