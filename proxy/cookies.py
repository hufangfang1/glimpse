"""
Cookie sources for the request editor.

Three independent ways to obtain cookies for a host:

1. :class:`CapturedCookieJar` — accumulates cookies seen in *captured traffic*
   (request ``Cookie:`` headers and response ``Set-Cookie:`` headers). This is
   the most reliable source for a proxy tool: if the browser sent it through us,
   we have it, no decryption or OS permissions needed.

2. :func:`read_chrome_cookies` — reads Chrome's local cookie store on macOS.
   Cookies are AES-128-CBC encrypted with a key derived from a secret kept in
   the login keychain (``Chrome Safe Storage``). We read it via ``security``.

3. :func:`read_safari_cookies` — parses Safari's ``Cookies.binarycookies`` file,
   a documented little/big-endian binary format (no external deps needed).

Every reader is best-effort and never raises: on any failure it returns an
empty list so the UI can fall back to another source.
"""
from __future__ import annotations

import struct
import subprocess
import threading
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Literal, Tuple

ChromeCookieError = Literal[
    "keychain_denied", "keychain_unavailable", "no_database", "decrypt_unavailable"
]

# (key, value) cookie pairs.
CookiePair = Tuple[str, str]


def normalize_cookie_value(value: str) -> str:
    """Strip control chars only — never re-encode (preserves Chrome's wire form)."""
    if not value:
        return ""
    value = value.replace("\x00", "")
    value = "".join(c for c in value if ord(c) >= 32 or c in "\t")
    return value.strip()


def cookie_value_for_wire(value: str) -> str:
    """Encode a cookie value for httpx (latin-1 / percent-escape non-latin-1)."""
    value = normalize_cookie_value(value)
    if not value:
        return ""
    try:
        value.encode("latin-1")
        return value
    except UnicodeEncodeError:
        from urllib.parse import quote
        return quote(value, safe="!#$%&'*+-.^_`|~")


# Back-compat alias used by older call sites.
sanitize_cookie_value = normalize_cookie_value


def _plausible_cookie_value(text: str) -> bool:
    """Reject obvious decryption garbage."""
    if not text:
        return False
    if "\ufffd" in text:
        return False
    if any(ord(c) < 32 and c not in "\t" for c in text):
        return False
    # High ratio of non-ASCII letters often means a failed v20/v10 decrypt.
    weird = sum(1 for c in text if ord(c) > 127)
    if weird > max(3, len(text) // 4):
        return False
    return True


def _cookie_blob(raw) -> bytes:
    if raw is None:
        return b""
    if isinstance(raw, memoryview):
        return raw.tobytes()
    if isinstance(raw, str):
        return raw.encode("latin-1", errors="ignore")
    return bytes(raw)


def _host_matches_cookie(host: str, host_key: str) -> bool:
    host = (host or "").lower()
    hk = (host_key or "").lstrip(".").lower()
    if not host or not hk:
        return False
    return host == hk or host.endswith("." + hk) or hk.endswith("." + host)


# ────────────────────────────────────────────────────────────────────────────
# Source 1 — cookies extracted from captured traffic
# ────────────────────────────────────────────────────────────────────────────

class CapturedCookieJar:
    """Accumulates the latest cookie value per (host, name) seen in traffic.

    Thread-safe: the proxy feeds flows from the GUI thread, but the editor may
    read from a worker. The jar keeps only the most recent value for each name
    under each registrable host, so re-logins overwrite stale cookies.
    """

    def __init__(self) -> None:
        # host -> { cookie_name -> cookie_value }
        self._by_host: Dict[str, Dict[str, str]] = {}
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._by_host.clear()

    def ingest_flow(self, flow) -> None:
        """Pull cookies out of a captured :class:`FlowModel`.

        Reads both the request ``Cookie`` header (what the client sent) and any
        response ``Set-Cookie`` headers (what the server just issued).
        """
        host = (getattr(flow, "host", "") or "").lower()
        if not host:
            return

        pairs: List[CookiePair] = []
        req_headers = getattr(flow, "request_headers", {}) or {}
        resp_headers = getattr(flow, "response_headers", {}) or {}

        # Prefer cookies parsed at capture time (correct for HTTP/2 split fields);
        # fall back to splitting the flattened Cookie header for older flows.
        structured = getattr(flow, "request_cookies", None)
        if structured:
            pairs.extend((str(n), str(v)) for n, v in structured)
        else:
            for key, value in req_headers.items():
                if key.lower() == "cookie":
                    pairs.extend(self._parse_cookie_header(value))

        for key, value in resp_headers.items():
            if key.lower() == "set-cookie":
                pair = self._parse_set_cookie(value)
                if pair is not None:
                    pairs.append(pair)

        if not pairs:
            return

        with self._lock:
            bucket = self._by_host.setdefault(host, {})
            for name, val in pairs:
                bucket[name] = val

    def cookies_for(self, host: str) -> List[CookiePair]:
        """Return accumulated cookies for *host*, including parent-domain matches.

        A request to ``api.example.com`` should also receive cookies captured on
        ``example.com`` (domain cookies), so we match any stored host that is a
        suffix of, or equal to, the requested host.
        """
        host = (host or "").lower()
        if not host:
            return []
        merged: Dict[str, str] = {}
        with self._lock:
            for stored_host, bucket in self._by_host.items():
                if host == stored_host or host.endswith("." + stored_host) \
                        or stored_host.endswith("." + host):
                    merged.update(bucket)
        return sorted(merged.items())

    @staticmethod
    def _parse_cookie_header(value: str) -> List[CookiePair]:
        pairs: List[CookiePair] = []
        for chunk in (value or "").split(";"):
            chunk = chunk.strip()
            if not chunk or "=" not in chunk:
                continue
            name, _, val = chunk.partition("=")
            name = name.strip()
            if name:
                pairs.append((name, val.strip()))
        return pairs

    @staticmethod
    def _parse_set_cookie(value: str) -> CookiePair | None:
        # The cookie name=value is always the first segment; the rest are
        # attributes (Path, Domain, Expires, HttpOnly, …) we don't need here.
        first = (value or "").split(";", 1)[0].strip()
        if "=" not in first:
            return None
        name, _, val = first.partition("=")
        name = name.strip()
        if not name:
            return None
        return name, val.strip()


# ────────────────────────────────────────────────────────────────────────────
# Source 2 — Chrome local cookie store (macOS)
# ────────────────────────────────────────────────────────────────────────────

# Browser label -> login-keychain service name (``<name> Safe Storage``).
_CHROME_KEYCHAIN_SERVICES = ("Chrome", "Chromium", "Microsoft Edge")

# Session cache: service name -> derived AES-16 key. Avoids re-prompting every sync.
_chrome_aes_key_cache: Dict[str, bytes] = {}

# How long to wait for the user to approve the macOS keychain dialog (seconds).
_KEYCHAIN_TIMEOUT = 180


@dataclass(frozen=True)
class ChromeCookieRead:
    """Result of a Chrome cookie read — pairs plus an optional error code for the UI."""

    pairs: List[CookiePair]
    error: ChromeCookieError | None = None


def _chrome_cookie_db_paths() -> List[Path]:
    """Discover Chromium-style ``Cookies`` SQLite DBs (all profiles)."""
    roots = [
        Path.home() / "Library" / "Application Support" / "Google" / "Chrome",
        Path.home() / "Library" / "Application Support" / "Chromium",
        Path.home() / "Library" / "Application Support" / "Microsoft Edge",
    ]
    found: List[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for db in sorted(root.glob("*/Cookies")):
            if db.is_file():
                found.append(db)
    return found


def _chrome_safe_storage_key(service: str = "Chrome") -> tuple[bytes | None, ChromeCookieError | None]:
    """Fetch the ``<service> Safe Storage`` secret from the login keychain.

    Returns ``(secret, error)``. On success ``error`` is None. The macOS security
    dialog can take a while — we wait up to :data:`_KEYCHAIN_TIMEOUT` seconds and
    cache the derived AES key for the rest of the process lifetime.
    """
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", f"{service} Safe Storage"],
            capture_output=True,
            text=True,
            timeout=_KEYCHAIN_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None, "keychain_unavailable"
    except (OSError, subprocess.SubprocessError):
        return None, "keychain_unavailable"

    if result.returncode != 0:
        err = (result.stderr or "").lower()
        if "user canceled" in err or "canceled" in err or "cancelled" in err:
            return None, "keychain_denied"
        return None, "keychain_denied"

    password = result.stdout.strip()
    if not password:
        return None, "keychain_unavailable"
    return password.encode("utf-8"), None


def _chrome_aes_key() -> tuple[bytes | None, ChromeCookieError | None]:
    """Return a cached or freshly derived Chrome AES key (tries Chrome/Chromium/Edge)."""
    if _chrome_aes_key_cache:
        return next(iter(_chrome_aes_key_cache.values())), None

    last_err: ChromeCookieError | None = "keychain_unavailable"
    for service in _CHROME_KEYCHAIN_SERVICES:
        secret, err = _chrome_safe_storage_key(service)
        if secret is None:
            if err is not None:
                last_err = err
            continue
        key = _derive_chrome_key(secret)
        _chrome_aes_key_cache[service] = key
        return key, None
    return None, last_err


def _derive_chrome_key(secret: bytes) -> bytes:
    """Derive the AES key the way Chrome does on macOS (PBKDF2, 1003 iters)."""
    import hashlib
    return hashlib.pbkdf2_hmac("sha1", secret, b"saltysalt", 1003, dklen=16)


def _decrypt_chrome_value(encrypted, key: bytes) -> str:
    """Decrypt a Chrome v10 cookie blob (AES-128-CBC, 16-byte space IV)."""
    blob = _cookie_blob(encrypted)
    if not blob:
        return ""
    prefix = blob[:3]
    # Chrome 127+ app-bound cookies — offline tools cannot decrypt these.
    if prefix in (b"v20", b"v11"):
        return ""
    if prefix != b"v10":
        try:
            text = normalize_cookie_value(blob.decode("utf-8"))
        except UnicodeDecodeError:
            return ""
        return text if _plausible_cookie_value(text) else ""
    try:
        from Crypto.Cipher import AES  # pycryptodome
    except ImportError:
        return ""
    try:
        iv = b" " * 16
        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(blob[3:])
        pad = decrypted[-1]
        if 1 <= pad <= 16 and pad <= len(decrypted):
            decrypted = decrypted[:-pad]
        candidates: list[bytes] = []
        if len(decrypted) > 32:
            candidates.append(decrypted[32:])
        candidates.append(decrypted)
        for raw in candidates:
            for enc in ("utf-8", "latin-1"):
                try:
                    text = normalize_cookie_value(raw.decode(enc))
                except UnicodeDecodeError:
                    continue
                if _plausible_cookie_value(text):
                    return text
        return ""
    except Exception:
        return ""


def read_chrome_cookies_detail(host: str) -> ChromeCookieRead:
    """Read Chrome-family cookies for *host* with structured errors for the UI."""
    host = (host or "").lower()
    if not host:
        return ChromeCookieRead([], None)

    db_paths = _chrome_cookie_db_paths()
    if not db_paths:
        return ChromeCookieRead([], "no_database")

    try:
        from Crypto.Cipher import AES  # noqa: F401 — pycryptodome
    except ImportError:
        return ChromeCookieRead([], "decrypt_unavailable")

    key, key_err = _chrome_aes_key()
    if key is None:
        return ChromeCookieRead([], key_err or "keychain_unavailable")

    import shutil
    import sqlite3
    import tempfile

    merged: Dict[str, str] = {}
    matched_rows = 0
    decrypted_any = False
    skipped_v20 = 0

    for db_path in db_paths:
        with tempfile.TemporaryDirectory() as tmp:
            copy_path = Path(tmp) / "Cookies"
            try:
                shutil.copy2(db_path, copy_path)
            except OSError:
                continue

            try:
                conn = sqlite3.connect(f"file:{copy_path}?mode=ro", uri=True)
            except sqlite3.Error:
                continue

            try:
                rows = conn.execute(
                    "SELECT name, value, encrypted_value, host_key FROM cookies"
                ).fetchall()
            except sqlite3.Error:
                continue
            finally:
                conn.close()

        for name, value, encrypted_value, host_key in rows:
            if not _host_matches_cookie(host, host_key):
                continue
            matched_rows += 1
            blob = _cookie_blob(encrypted_value)
            if blob[:3] in (b"v20", b"v11") and not (value or "").strip():
                skipped_v20 += 1
                continue

            from_value = normalize_cookie_value((value or "").strip())
            from_enc = _decrypt_chrome_value(encrypted_value, key) if blob else ""

            plain = ""
            if from_value and _plausible_cookie_value(from_value):
                plain = from_value
            elif from_enc:
                plain = from_enc

            if plain:
                decrypted_any = True
                if name:
                    # Prefer the longer plausible value when both sources exist.
                    prev = merged.get(name, "")
                    if len(plain) >= len(prev):
                        merged[name] = plain

    if merged:
        return ChromeCookieRead(sorted(merged.items()), None)
    if skipped_v20 > 0 and matched_rows > 0:
        return ChromeCookieRead([], "decrypt_unavailable")
    if matched_rows > 0 and not decrypted_any:
        return ChromeCookieRead([], "decrypt_unavailable")
    return ChromeCookieRead([], None)


def read_chrome_cookies(host: str, service: str = "Chrome") -> List[CookiePair]:
    """Best-effort read of Chrome cookies for *host*. Returns [] on any failure."""
    _ = service  # kept for API compat; all Chromium browsers are tried internally
    return read_chrome_cookies_detail(host).pairs


# ────────────────────────────────────────────────────────────────────────────
# Source 3 — Safari Cookies.binarycookies
# ────────────────────────────────────────────────────────────────────────────

_SAFARI_COOKIE_PATHS = [
    Path.home() / "Library" / "Cookies" / "Cookies.binarycookies",
    Path.home() / "Library" / "Containers" / "com.apple.Safari" / "Data"
    / "Library" / "Cookies" / "Cookies.binarycookies",
]


def read_safari_cookies(host: str) -> List[CookiePair]:
    """Parse Safari's binarycookies file for *host*. Returns [] on any failure."""
    host = (host or "").lower()
    if not host:
        return []

    path = next((p for p in _SAFARI_COOKIE_PATHS if p.exists()), None)
    if path is None:
        return []

    try:
        data = path.read_bytes()
    except OSError:
        return []

    try:
        return _parse_binarycookies(data, host)
    except Exception:
        return []


def _parse_binarycookies(data: bytes, host: str) -> List[CookiePair]:
    """Decode the ``Cookies.binarycookies`` container.

    Layout: magic ``cook`` + page count (BE), then each page's size (BE), then
    the concatenated pages. Each page holds cookies with little-endian offsets.
    """
    if data[:4] != b"cook":
        return []

    num_pages = struct.unpack(">i", data[4:8])[0]
    page_sizes = [
        struct.unpack(">i", data[8 + i * 4:12 + i * 4])[0] for i in range(num_pages)
    ]

    merged: Dict[str, str] = {}
    offset = 8 + num_pages * 4
    for size in page_sizes:
        page = data[offset:offset + size]
        offset += size
        _parse_cookie_page(page, host, merged)
    return sorted(merged.items())


def _parse_cookie_page(page: bytes, host: str, merged: Dict[str, str]) -> None:
    if page[:4] != b"\x00\x00\x01\x00":
        return
    num_cookies = struct.unpack("<i", page[4:8])[0]
    cookie_offsets = [
        struct.unpack("<i", page[8 + i * 4:12 + i * 4])[0] for i in range(num_cookies)
    ]

    for c_off in cookie_offsets:
        try:
            _parse_one_cookie(page[c_off:], host, merged)
        except (struct.error, IndexError):
            continue


def _parse_one_cookie(blob: bytes, host: str, merged: Dict[str, str]) -> None:
    # Each cookie record carries relative offsets to its NUL-terminated strings.
    url_off = struct.unpack("<i", blob[16:20])[0]
    name_off = struct.unpack("<i", blob[20:24])[0]
    path_off = struct.unpack("<i", blob[24:28])[0]
    value_off = struct.unpack("<i", blob[28:32])[0]

    domain = _read_cstring(blob, url_off).lstrip(".").lower()
    if not domain:
        return
    if not (host == domain or host.endswith("." + domain) or domain.endswith("." + host)):
        return

    name = _read_cstring(blob, name_off)
    value = _read_cstring(blob, value_off)
    if name:
        merged[name] = value


def _read_cstring(blob: bytes, start: int) -> str:
    if start <= 0 or start >= len(blob):
        return ""
    end = blob.find(b"\x00", start)
    if end == -1:
        end = len(blob)
    return blob[start:end].decode("utf-8", errors="replace")
