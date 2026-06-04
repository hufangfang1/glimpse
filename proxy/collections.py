"""
Saved requests & groups — a lightweight, Postman-style collection store.

Saved requests live in ``~/.glimpse/collections.json`` next to ``scope.json``
and ``settings.json``. The store keeps everything in memory and rewrites the
whole file on each mutation (the data set is small — hundreds of requests at
most — so this is simpler and safe enough).

A :class:`SavedRequest` is intentionally close to :class:`proxy.models.FlowModel`
so it round-trips cleanly between the traffic list and the request editor.
Headers are stored as an ordered list of ``(enabled, key, value)`` triples so
the editor can preserve duplicates and disabled rows, which a plain dict can't.
"""
from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

COLLECTIONS_FILE = Path.home() / ".glimpse" / "collections.json"

# (enabled, key, value) — mirrors how the editor's key/value tables store rows.
KVRow = Tuple[bool, str, str]


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class SavedRequest:
    """A single editable/sendable request persisted in a group."""

    id: str = field(default_factory=_new_id)
    name: str = "New Request"
    method: str = "GET"
    url: str = ""
    # Ordered, individually-toggleable rows so the editor keeps duplicates and
    # disabled entries. Cookies are kept separate from headers for UI clarity;
    # they are merged into a single Cookie header only at send time.
    headers: List[KVRow] = field(default_factory=list)
    cookies: List[KVRow] = field(default_factory=list)
    body: str = ""

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "method": self.method,
            "url": self.url,
            "headers": [list(r) for r in self.headers],
            "cookies": [list(r) for r in self.cookies],
            "body": self.body,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SavedRequest":
        return cls(
            id=str(data.get("id") or _new_id()),
            name=str(data.get("name") or "New Request"),
            method=str(data.get("method") or "GET").upper(),
            url=str(data.get("url") or ""),
            headers=cls._rows(data.get("headers")),
            cookies=cls._rows(data.get("cookies")),
            body=str(data.get("body") or ""),
        )

    @staticmethod
    def _rows(raw) -> List[KVRow]:
        out: List[KVRow] = []
        for item in raw or []:
            try:
                enabled, key, value = item
            except (ValueError, TypeError):
                continue
            out.append((bool(enabled), str(key), str(value)))
        return out


@dataclass
class RequestGroup:
    """A named folder of saved requests."""

    id: str = field(default_factory=_new_id)
    name: str = "Group"
    requests: List[SavedRequest] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "requests": [r.to_dict() for r in self.requests],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RequestGroup":
        return cls(
            id=str(data.get("id") or _new_id()),
            name=str(data.get("name") or "Group"),
            requests=[SavedRequest.from_dict(r) for r in (data.get("requests") or [])],
        )


class CollectionStore:
    """Thread-safe in-memory store of request groups, backed by a JSON file."""

    def __init__(self, groups: List[RequestGroup] | None = None) -> None:
        self._groups: List[RequestGroup] = groups or []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Query
    # ------------------------------------------------------------------ #

    def groups(self) -> List[RequestGroup]:
        """Return the live list of groups (caller must not mutate concurrently)."""
        with self._lock:
            return list(self._groups)

    def find_request(self, request_id: str) -> Tuple[RequestGroup, SavedRequest] | None:
        with self._lock:
            for group in self._groups:
                for req in group.requests:
                    if req.id == request_id:
                        return group, req
        return None

    # ------------------------------------------------------------------ #
    # Mutation
    # ------------------------------------------------------------------ #

    def add_group(self, name: str) -> RequestGroup:
        group = RequestGroup(name=name.strip() or "Group")
        with self._lock:
            self._groups.append(group)
        return group

    def rename_group(self, group_id: str, name: str) -> None:
        name = name.strip()
        if not name:
            return
        with self._lock:
            for group in self._groups:
                if group.id == group_id:
                    group.name = name
                    return

    def delete_group(self, group_id: str) -> None:
        with self._lock:
            self._groups = [g for g in self._groups if g.id != group_id]

    def add_request(self, group_id: str, request: SavedRequest) -> bool:
        """Append *request* to a group. Returns False if the group is gone."""
        with self._lock:
            for group in self._groups:
                if group.id == group_id:
                    group.requests.append(request)
                    return True
        return False

    def update_request(self, request: SavedRequest) -> bool:
        """Replace an existing request (matched by id) in place."""
        with self._lock:
            for group in self._groups:
                for i, req in enumerate(group.requests):
                    if req.id == request.id:
                        group.requests[i] = request
                        return True
        return False

    def delete_request(self, request_id: str) -> None:
        with self._lock:
            for group in self._groups:
                group.requests = [r for r in group.requests if r.id != request_id]

    def ensure_default_group(self) -> RequestGroup:
        """Return the first group, creating a default one if the store is empty."""
        with self._lock:
            if self._groups:
                return self._groups[0]
        return self.add_group("My Requests")

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    def save(self, path: Path = COLLECTIONS_FILE) -> None:
        with self._lock:
            payload = {"groups": [g.to_dict() for g in self._groups]}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path = COLLECTIONS_FILE) -> "CollectionStore":
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        groups = [RequestGroup.from_dict(g) for g in (data.get("groups") or [])]
        return cls(groups=groups)
