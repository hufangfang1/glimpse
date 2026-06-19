"""
Rule engine for mock / local-map / rewrite behavior.

Rules are intentionally plain JSON so the first UI can be a compact editor while
the proxy-side behavior is already durable and testable. Each rule is matched
against the full request URL with fnmatch semantics; bare patterns act as
substrings, matching the breakpoint ergonomics.

Supported rule shape::

    {
      "enabled": true,
      "name": "mock health",
      "kind": "mock",
      "match": "*/api/health",
      "status": 200,
      "headers": {"content-type": "application/json"},
      "body": "{\"ok\": true}"
    }

Kinds:
    mock              short-circuit upstream with a canned response
    request_rewrite   rewrite request URL / headers / body text
    response_rewrite  rewrite response status / headers / body text
"""
from __future__ import annotations

import fnmatch
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

RULES_FILE = Path.home() / ".glimpse" / "rules.json"

VALID_KINDS = {"mock", "request_rewrite", "response_rewrite"}


@dataclass
class RuleEngine:
    """Thread-safe rule list used by the mitmproxy addon."""

    rules: List[Dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    # ------------------------------------------------------------------ #
    # Mutation / snapshots
    # ------------------------------------------------------------------ #

    def update(self, rules: List[Dict[str, Any]]) -> None:
        with self._lock:
            self.rules = self._clean_rules(rules)

    def snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(rule) for rule in self.rules]

    def is_active(self) -> bool:
        with self._lock:
            return any(rule.get("enabled", True) for rule in self.rules)

    # ------------------------------------------------------------------ #
    # Matching
    # ------------------------------------------------------------------ #

    def matching(self, kind: str, url: str) -> List[Dict[str, Any]]:
        if kind not in VALID_KINDS or not url:
            return []
        url_l = url.lower()
        out: List[Dict[str, Any]] = []
        with self._lock:
            rules = [dict(rule) for rule in self.rules]
        for rule in rules:
            if not rule.get("enabled", True):
                continue
            if rule.get("kind") != kind:
                continue
            pattern = str(rule.get("match") or rule.get("url_pattern") or "").strip().lower()
            if not pattern:
                continue
            if self._matches(url_l, pattern):
                out.append(rule)
        return out

    @staticmethod
    def _matches(url: str, pattern: str) -> bool:
        if "*" in pattern or "?" in pattern or "[" in pattern:
            return fnmatch.fnmatchcase(url, pattern)
        return pattern in url

    # ------------------------------------------------------------------ #
    # Normalization / persistence
    # ------------------------------------------------------------------ #

    @classmethod
    def _clean_rules(cls, rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for raw in rules or []:
            if not isinstance(raw, dict):
                continue
            rule = dict(raw)
            kind = str(rule.get("kind") or "").strip().lower()
            if kind not in VALID_KINDS:
                continue
            match = str(rule.get("match") or rule.get("url_pattern") or "").strip()
            if not match:
                continue
            rule["kind"] = kind
            rule["match"] = match
            rule["enabled"] = bool(rule.get("enabled", True))
            out.append(rule)
        return out

    def save(self, path: Path = RULES_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"rules": self.snapshot()}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path = RULES_FILE) -> "RuleEngine":
        engine = cls()
        if not path.exists():
            return engine
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return engine
        rules: Optional[List[Dict[str, Any]]] = None
        if isinstance(data, list):
            rules = data
        elif isinstance(data, dict) and isinstance(data.get("rules"), list):
            rules = data["rules"]
        if rules is not None:
            engine.update(rules)
        return engine
