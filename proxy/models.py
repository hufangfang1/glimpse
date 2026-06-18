"""
Flow data models for Glimpse.
"""
from __future__ import annotations

import gzip
import json
import re
import shlex
import zlib
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, unquote_plus


class _ReadableHtmlParser(HTMLParser):
    """Extract visible text from an HTML error page without the CSS/JS noise."""

    _SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}
    _BLOCK_TAGS = {
        "address", "article", "aside", "blockquote", "br", "dd", "div", "dl",
        "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2",
        "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p",
        "pre", "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr",
        "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self._title_parts: list[str] = []
        self._parts: list[str] = []

    @property
    def title(self) -> str:
        return self._clean_text(" ".join(self._title_parts))

    @property
    def body_text(self) -> str:
        text = self._clean_text(" ".join(self._parts))
        return self._dedupe_lines(text)

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
            return
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "title":
            self._in_title = False
            return
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self._title_parts.append(data)
        else:
            self._parts.append(data)

    @staticmethod
    def _clean_text(text: str) -> str:
        text = unescape(text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t\f\v]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _dedupe_lines(text: str) -> str:
        lines: list[str] = []
        previous = ""
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                if lines and lines[-1]:
                    lines.append("")
                continue
            if stripped == previous:
                continue
            lines.append(stripped)
            previous = stripped
        return "\n".join(lines).strip()


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
    # Cookies parsed at capture time, before lossy dict() flattening. On HTTP/2
    # browsers split Cookie into one field per crumb; dict(headers) joins them
    # with ", " which can't be re-split reliably (cookie values may contain
    # commas). Keeping the parsed pairs here preserves every cookie for the
    # editor. Empty for replayed/composed flows.
    request_cookies: List[Tuple[str, str]] = field(default_factory=list)
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

    @staticmethod
    def _body_looks_like_html(text: str) -> bool:
        stripped = text.lstrip()[:512].lower()
        if stripped.startswith(("<!doctype html", "<html")):
            return True
        return bool(re.search(r"<(html|head|body|title|h1|div|span|p)\b", stripped))

    @classmethod
    def _readable_html(cls, text: str) -> str:
        parser = _ReadableHtmlParser()
        try:
            parser.feed(text)
            parser.close()
        except Exception:
            return text

        parts: list[str] = []
        summary = cls._html_error_summary(text, parser.body_text)
        if summary:
            parts.append(summary)
        if parser.title:
            parts.append(f"HTML error title:\n{parser.title}")
        if parser.body_text:
            parts.append(f"HTML error text:\n{parser.body_text}")

        if not parts:
            return text

        summary = "\n\n".join(parts)
        return f"{summary}\n\n----- Raw HTML -----\n{text}"

    @classmethod
    def _html_error_summary(cls, html_text: str, body_text: str) -> str:
        """Put the useful framework exception bits before the full text dump."""
        fragments: list[str] = []

        exception = cls._first_html_class_text(html_text, "exception_title")
        message = cls._first_html_class_text(html_text, "exception_message")

        if exception:
            fragments.append(exception.rstrip(":").strip())
        if message and message not in fragments:
            fragments.append(message.strip())

        if not fragments:
            lines = [line.strip() for line in body_text.splitlines() if line.strip()]
            for idx, line in enumerate(lines):
                if re.search(r"\b(Error|Exception|Throwable)\b", line):
                    fragments.append(line.rstrip(":").strip())
                    if idx + 1 < len(lines):
                        next_line = lines[idx + 1].strip()
                        if next_line and not next_line.lower().startswith("at "):
                            fragments.append(next_line)
                    break

        if not fragments:
            return ""

        trace_lines = cls._first_stack_lines(body_text, limit=5)
        out = ["HTML error summary:", *fragments]
        if trace_lines:
            out.extend(["", "First stack lines:", *trace_lines])
        return "\n".join(out)

    @classmethod
    def _first_html_class_text(cls, html_text: str, class_name: str) -> str:
        pattern = (
            rf"<(?P<tag>[a-z0-9]+)[^>]*\bclass=[\"'][^\"']*\b{re.escape(class_name)}\b"
            rf"[^\"']*[\"'][^>]*>(.*?)</(?P=tag)>"
        )
        match = re.search(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return ""
        return cls._strip_html_fragment(match.group(2))

    @staticmethod
    def _strip_html_fragment(fragment: str) -> str:
        fragment = re.sub(r"<(script|style|noscript|template)\b.*?</\1>", "", fragment,
                          flags=re.IGNORECASE | re.DOTALL)
        fragment = re.sub(r"<[^>]+>", " ", fragment)
        fragment = unescape(fragment)
        fragment = re.sub(r"\s+", " ", fragment)
        return fragment.strip()

    @staticmethod
    def _first_stack_lines(body_text: str, limit: int = 5) -> list[str]:
        trace: list[str] = []
        for line in body_text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.lower().startswith(("at ", "in ")):
                trace.append(line)
            if len(trace) >= limit:
                break
        return trace

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

        if self._is_html_content_type(content_type) or self._body_looks_like_html(text):
            return self._readable_html(text), False

        if "application/x-www-form-urlencoded" in content_type or self._body_looks_like_form(text):
            return self._decode_form(text), False

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

    def get_request_body_raw_text(self) -> str:
        """Decoded request body WITHOUT form/JSON prettification.

        Used when loading a captured request into the editor, where the raw
        wire text (e.g. ``a=1&b=2``) is needed so the Body editor can parse it
        into its own form grid instead of re-parsing prettified output.
        """
        if not self.request_body:
            return ""
        enc = self._header_value(self.request_headers, "content-encoding")
        body = self._decompress(self.request_body, enc)
        return body.decode("utf-8", errors="replace")

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

    @staticmethod
    def _is_html_content_type(content_type: str) -> bool:
        return "html" in content_type.lower()

    @staticmethod
    def _body_looks_like_form(text: str) -> bool:
        """Heuristic: key=value(&key=value)* with percent-encoding."""
        if not text or "\n" in text or " " in text.split("=")[0]:
            return False
        return "=" in text and "%" in text

    @staticmethod
    def _decode_form(text: str) -> str:
        pairs = parse_qsl(text, keep_blank_values=True)
        if pairs:
            return "\n".join(f"{k} = {v}" for k, v in pairs)
        return unquote_plus(text)

    def is_image(self) -> bool:
        return self.content_type.startswith("image/")

    def is_json(self) -> bool:
        return self._is_json_content_type(self.content_type)

    def is_request_json(self) -> bool:
        return self._is_json_content_type(self.request_content_type)

    def is_html(self) -> bool:
        return self._is_html_content_type(self.content_type)

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

    def export_headers(self) -> List[tuple[str, str]]:
        """Headers suitable for replay / curl export, as ordered (key, value) pairs.

        Rebuilds the Cookie header from :attr:`request_cookies` (parsed at
        capture time) instead of trusting ``request_headers["cookie"]`` — on
        HTTP/2 the browser splits Cookie into multiple fields, which
        ``dict(req.headers)`` flattens with ", " into a value the server can't
        parse. Using the wrong Cookie on replay shows up as "not logged in".
        """
        out: List[tuple[str, str]] = []
        for key, value in self.request_headers.items():
            low = key.lower()
            if low in self._SKIP_EXPORT_HEADERS:
                continue
            if low == "cookie":
                continue   # re-emitted below from the structured cookies
            out.append((key, value))

        cookie = self.cookie_header()
        if cookie:
            out.append(("Cookie", cookie))
        return out

    def cookie_header(self) -> str:
        """Return a valid ``name=value; ...`` Cookie string for this request.

        Prefers cookies parsed at capture time; falls back to the raw header
        only when the structured list is absent (e.g. replayed/composed flows),
        re-splitting it on ", " to undo HTTP/2 field flattening as best we can.
        """
        if self.request_cookies:
            return "; ".join(f"{n}={v}" for n, v in self.request_cookies)
        raw = self._header_value(self.request_headers, "cookie")
        if not raw:
            return ""
        # Best-effort un-flatten: split on ", " only between "crumb=" boundaries.
        return raw.replace(", ", "; ")

    def to_curl(self, multiline: bool = True) -> str:
        """Render this flow's request as a runnable curl command."""
        parts: List[str] = ["curl"]
        if self.method.upper() != "GET":
            parts.append(f"-X {self.method}")
        parts.append(shlex.quote(self.url))

        for key, value in self.export_headers():
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
