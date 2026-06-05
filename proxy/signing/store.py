"""Load signer profiles from ~/.glimpse/auth.json (with dev fallbacks)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import List, Optional

from proxy.signing.models import SignerConfig

AUTH_FILE = Path.home() / ".glimpse" / "auth.json"
# glimpse repo root (proxy/signing/store.py → proxy → root)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AuthStore:
    """In-memory signer list backed by auth.json."""

    def __init__(self, signers: List[SignerConfig] | None = None) -> None:
        self._signers: List[SignerConfig] = signers or []
        self._source: Optional[Path] = None

    def signers(self) -> List[SignerConfig]:
        return list(self._signers)

    @property
    def source(self) -> Optional[Path]:
        return self._source

    def find(self, signer_id: str) -> Optional[SignerConfig]:
        sid = (signer_id or "").strip()
        if not sid:
            return None
        for signer in self._signers:
            if signer.id == sid:
                return signer
        return None

    @classmethod
    def candidate_paths(cls) -> List[Path]:
        """Search order: user home → project auth.json → project auth.example.json."""
        return [
            AUTH_FILE,
            _PROJECT_ROOT / "auth.json",
            _PROJECT_ROOT / "auth.example.json",
        ]

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AuthStore":
        if path is not None:
            return cls._load_file(path)

        for candidate in cls.candidate_paths():
            if not candidate.exists():
                continue
            store = cls._load_file(candidate)
            if store.signers():
                return store

        cls._bootstrap_from_example()
        if AUTH_FILE.exists():
            store = cls._load_file(AUTH_FILE)
            if store.signers():
                return store
        return cls()

    @classmethod
    def _bootstrap_from_example(cls) -> None:
        """First run: copy auth.example.json into ~/.glimpse/auth.json."""
        if AUTH_FILE.exists():
            return
        example = _PROJECT_ROOT / "auth.example.json"
        if not example.exists():
            return
        AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(example, AUTH_FILE)

    @classmethod
    def _load_file(cls, path: Path) -> "AuthStore":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        raw = data.get("signers") or []
        signers: List[SignerConfig] = []
        for item in raw:
            cfg = SignerConfig.from_dict(item)
            if cfg is not None:
                signers.append(cfg)
        store = cls(signers=signers)
        store._source = path
        return store
