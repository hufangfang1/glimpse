"""
httpx client factory that follows macOS system proxy rules.

httpx defaults to ``trust_env=True``, which reads HTTP_PROXY but ignores the
macOS "Bypass proxy settings for these Hosts & Domains" list (ExceptionsList).
Apps like Shadowrocket / Surge populate that list via ``scutil --proxy``; this
module mirrors the same bypass logic so editor sends match the browser.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import subprocess
import sys
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

import httpx

_SCUTIL_ARRAY_ITEM = re.compile(r"^\s*\d+\s*:\s*(.+?)\s*$")


@lru_cache(maxsize=1)
def _load_macos_proxy_settings() -> dict[str, Any]:
    """Read the active system proxy dictionary via ``scutil --proxy``."""
    try:
        proc = subprocess.run(
            ["scutil", "--proxy"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    text = proc.stdout
    settings: dict[str, Any] = {}
    exceptions: list[str] = []
    in_exceptions = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line == "<dictionary> {":
            continue

        if in_exceptions:
            if line == "}":
                in_exceptions = False
                continue
            m = _SCUTIL_ARRAY_ITEM.match(line)
            if m:
                exceptions.append(m.group(1))
            continue

        if line == "}":
            continue

        if line.startswith("ExceptionsList"):
            in_exceptions = "array" in line
            continue

        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.isdigit():
            settings[key] = int(value)
        else:
            settings[key] = value

    if exceptions:
        settings["ExceptionsList"] = exceptions
    return settings


def _host_in_cidr(host: str, cidr: str) -> bool:
    try:
        network = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False
    try:
        addr = ipaddress.ip_address(host)
        return addr in network
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return False
    for info in infos:
        ip = info[4][0]
        try:
            if ipaddress.ip_address(ip) in network:
                return True
        except ValueError:
            continue
    return False


def _host_matches_exception(host: str, pattern: str) -> bool:
    """Match a host against one macOS proxy-bypass entry."""
    host = host.lower().rstrip(".")
    pattern = pattern.lower().rstrip(".")

    if "/" in pattern:
        return _host_in_cidr(host, pattern)

    if pattern == "localhost":
        return host in ("localhost", "127.0.0.1", "::1")

    if pattern.startswith("*."):
        suffix = pattern[1:]  # ".example.com"
        base = pattern[2:]
        return host == base or host.endswith(suffix)

    if pattern.startswith("*"):
        return host.endswith(pattern[1:])

    return host == pattern or host.endswith("." + pattern)


def should_bypass_system_proxy(host: str, settings: dict[str, Any] | None = None) -> bool:
    """Return True when the host should connect directly (no HTTP proxy)."""
    if not host:
        return True

    cfg = settings if settings is not None else _load_macos_proxy_settings()
    if not cfg:
        return True

    if cfg.get("ExcludeSimpleHostnames") and "." not in host:
        return True

    for pattern in cfg.get("ExceptionsList") or []:
        if _host_matches_exception(host, str(pattern)):
            return True
    return False


def resolve_system_proxy(url: str) -> str | None:
    """Return an httpx proxy URL for *url*, or None for a direct connection."""
    if sys.platform != "darwin":
        return None

    cfg = _load_macos_proxy_settings()
    if not cfg:
        return None

    if cfg.get("ProxyAutoConfigEnable"):
        # PAC evaluation is out of scope; leave proxy unset (direct).
        return None

    parsed = urlparse(url)
    host = parsed.hostname or ""
    if should_bypass_system_proxy(host, cfg):
        return None

    scheme = (parsed.scheme or "http").lower()
    if scheme == "https" and cfg.get("HTTPSEnable"):
        return f"http://{cfg['HTTPSProxy']}:{cfg['HTTPSPort']}"
    if cfg.get("HTTPEnable"):
        return f"http://{cfg['HTTPProxy']}:{cfg['HTTPPort']}"
    return None


def make_client(url: str, **kwargs: Any) -> httpx.Client:
    """Build an httpx client that follows macOS system proxy bypass rules."""
    options: dict[str, Any] = {
        "verify": False,
        "follow_redirects": True,
        "timeout": 30,
        "trust_env": False,
    }
    options.update(kwargs)

    proxy = resolve_system_proxy(url)
    if proxy is not None:
        options["proxy"] = proxy
    return httpx.Client(**options)
