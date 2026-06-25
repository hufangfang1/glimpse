"""
Capture scope — allow / block host patterns.

The scope decides whether a captured flow is shown to the user. Both lists
accept fnmatch-style host patterns (``*.example.com``, ``api.*``, etc.) and
are matched case-insensitively against ``request.pretty_host``.

Rules:
    - block list is checked first; matching hosts are dropped.
    - empty allow list means "accept everything that isn't blocked".
    - non-empty allow list means "only accept hosts that match".
"""
from __future__ import annotations

import fnmatch
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

SCOPE_FILE = Path.home() / ".glimpse" / "scope.json"
# Pre-rename location — loaded transparently so existing users don't lose
# their config when the app is renamed.
LEGACY_SCOPE_FILE = Path.home() / ".proxyman" / "scope.json"


@dataclass
class Scope:
    """Thread-safe allow/block host patterns."""

    allow: List[str] = field(default_factory=list)
    block: List[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    # ------------------------------------------------------------------ #
    # Mutation
    # ------------------------------------------------------------------ #

    def update(self, allow: List[str], block: List[str]) -> None:
        cleaned_allow = self._clean(allow)
        cleaned_block = self._clean(block)
        with self._lock:
            self.allow = cleaned_allow
            self.block = cleaned_block

    @staticmethod
    def _clean(patterns: List[str]) -> List[str]:
        out: List[str] = []
        seen: set[str] = set()
        for raw in patterns or []:
            p = (raw or "").strip().lower()
            if not p or p.startswith("#"):
                continue
            if p in seen:
                continue
            seen.add(p)
            out.append(p)
        return out

    # ------------------------------------------------------------------ #
    # Query
    # ------------------------------------------------------------------ #

    def is_active(self) -> bool:
        with self._lock:
            return bool(self.allow) or bool(self.block)

    def snapshot(self) -> tuple[List[str], List[str]]:
        with self._lock:
            return list(self.allow), list(self.block)

    def to_mitm_patterns(self) -> tuple[List[str], List[str]]:
        """Convert allow/block patterns to mitmproxy-compatible regexes.

        mitmproxy matches ``allow_hosts`` / ``ignore_hosts`` against the
        ``host[:port]`` string with ``re.search``. We anchor both ends and
        make the port optional so e.g. ``*.example.com`` matches both
        ``api.example.com`` and ``api.example.com:443``.
        """
        allow, block = self.snapshot()
        return (
            [self._fnmatch_to_regex(p) for p in allow],
            [self._fnmatch_to_regex(p) for p in block],
        )

    def to_mitm_options(self) -> tuple[List[str], List[str]]:
        """Return mutually-exclusive ``allow_hosts`` / ``ignore_hosts`` values.

        mitmproxy rejects configurations where both options are populated.
        Glimpse, however, supports Allow and Block at the same time with Block
        taking precedence. When Allow is active we therefore fold Block into a
        negative lookahead and only populate ``allow_hosts``. With no Allow
        list, Block maps directly to ``ignore_hosts``.
        """
        allow, block = self.snapshot()
        if not allow:
            return [], [self._fnmatch_to_regex(p) for p in block]

        allow_bodies = [self._fnmatch_body(p) for p in allow]
        if not block:
            return [
                "^" + body + r"(?::\d+)?$"
                for body in allow_bodies
            ], []

        blocked = "|".join(
            "(?:" + self._fnmatch_body(p) + ")"
            for p in block
        )
        return [
            r"^(?!(?:" + blocked + r")(?::\d+)?$)"
            + body
            + r"(?::\d+)?$"
            for body in allow_bodies
        ], []

    @staticmethod
    def _fnmatch_body(pattern: str) -> str:
        out: List[str] = []
        for ch in pattern:
            if ch == "*":
                out.append(".*")
            elif ch == "?":
                out.append(".")
            elif ch in r".+()[]{}|^$\\":
                out.append("\\" + ch)
            else:
                out.append(ch)
        return "".join(out)

    @classmethod
    def _fnmatch_to_regex(cls, pattern: str) -> str:
        return "^" + cls._fnmatch_body(pattern) + r"(?::\d+)?$"

    def accepts(self, host: str) -> bool:
        """Return True if a flow for *host* should be captured/shown."""
        if not host:
            return True
        host = host.lower()
        with self._lock:
            allow = self.allow
            block = self.block

        if block and self._any_match(host, block):
            return False
        if allow:
            return self._any_match(host, allow)
        return True

    @staticmethod
    def _any_match(host: str, patterns: List[str]) -> bool:
        for pattern in patterns:
            if "*" in pattern or "?" in pattern or "[" in pattern:
                if fnmatch.fnmatchcase(host, pattern):
                    return True
            elif host == pattern:
                return True
        return False

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    def save(self, path: Path = SCOPE_FILE) -> None:
        allow, block = self.snapshot()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"allow": allow, "block": block}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path = SCOPE_FILE) -> "Scope":
        scope = cls()
        # Fall back to legacy path so configs survive the rename.
        if not path.exists() and LEGACY_SCOPE_FILE.exists():
            path = LEGACY_SCOPE_FILE
        if not path.exists():
            return scope
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return scope
        scope.update(
            allow=data.get("allow") or [],
            block=data.get("block") or [],
        )
        return scope
