"""
Breakpoint rules — which flows to pause for interactive editing.

A flow is held (paused) when the master switch is enabled AND its URL matches one
of the patterns. Patterns are fnmatch-style and matched case-insensitively
against ``request.pretty_url`` (so they can target host *and* path, e.g.
``*.example.com/api/*`` or ``*/login``). ``on_request`` / ``on_response`` decide
which side(s) of a matching flow get held.

Mirrors :class:`proxy.scope.Scope` for structure and persistence.
"""
from __future__ import annotations

import fnmatch
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

BREAKPOINTS_FILE = Path.home() / ".glimpse" / "breakpoints.json"


@dataclass
class BreakpointRules:
    """Thread-safe set of URL patterns deciding which flows to intercept."""

    enabled: bool = False
    patterns: List[str] = field(default_factory=list)
    on_request: bool = True
    on_response: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    # ------------------------------------------------------------------ #
    # Mutation
    # ------------------------------------------------------------------ #

    def update(
        self,
        *,
        patterns: List[str] | None = None,
        on_request: bool | None = None,
        on_response: bool | None = None,
        enabled: bool | None = None,
    ) -> None:
        with self._lock:
            if patterns is not None:
                self.patterns = self._clean(patterns)
            if on_request is not None:
                self.on_request = on_request
            if on_response is not None:
                self.on_response = on_response
            if enabled is not None:
                self.enabled = enabled

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self.enabled = enabled

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

    def snapshot(self) -> tuple[bool, List[str], bool, bool]:
        with self._lock:
            return self.enabled, list(self.patterns), self.on_request, self.on_response

    def is_active(self) -> bool:
        with self._lock:
            return self.enabled and bool(self.patterns)

    def _matches(self, url: str) -> bool:
        if not url:
            return False
        url = url.lower()
        with self._lock:
            if not self.enabled or not self.patterns:
                return False
            patterns = list(self.patterns)
        for pattern in patterns:
            # Bare patterns with no wildcard are treated as substrings so users
            # can type a host fragment without remembering to add stars.
            if "*" in pattern or "?" in pattern or "[" in pattern:
                if fnmatch.fnmatchcase(url, pattern):
                    return True
            elif pattern in url:
                return True
        return False

    def matches_request(self, url: str) -> bool:
        with self._lock:
            on_req = self.on_request
        return on_req and self._matches(url)

    def matches_response(self, url: str) -> bool:
        with self._lock:
            on_resp = self.on_response
        return on_resp and self._matches(url)

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    def save(self, path: Path = BREAKPOINTS_FILE) -> None:
        enabled, patterns, on_request, on_response = self.snapshot()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "enabled": enabled,
                    "patterns": patterns,
                    "on_request": on_request,
                    "on_response": on_response,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path = BREAKPOINTS_FILE) -> "BreakpointRules":
        rules = cls()
        if not path.exists():
            return rules
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return rules
        if not isinstance(data, dict):
            return rules
        rules.update(
            patterns=data.get("patterns") or [],
            on_request=bool(data.get("on_request", True)),
            on_response=bool(data.get("on_response", False)),
            enabled=bool(data.get("enabled", False)),
        )
        return rules
