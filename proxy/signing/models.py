"""Signer configuration models (loaded from ~/.glimpse/auth.json)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class SignerConfig:
    """One named signer profile — rules live in config, not hard-coded in the UI."""

    id: str
    name: str = ""
    type: str = "chenla_uc"
    private_key: str = ""
    app_id: int = 6
    platform: str = "CHENGLA-PHP"
    version: str = "PHP-0.0.1"
    sign_template: str = "{platform}-{version}-{signTime}-{nonce}"
    inject_headers: bool = True
    inject_body: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> Optional["SignerConfig"]:
        if not data or not isinstance(data, dict):
            return None
        sid = str(data.get("id") or "").strip()
        if not sid:
            return None
        inject = data.get("inject") or {}
        if not isinstance(inject, dict):
            inject = {}
        return cls(
            id=sid,
            name=str(data.get("name") or sid),
            type=str(data.get("type") or "chenla_uc"),
            private_key=str(data.get("private_key") or ""),
            app_id=int(data.get("app_id") or 6),
            platform=str(data.get("platform") or "CHENGLA-PHP"),
            version=str(data.get("version") or "PHP-0.0.1"),
            sign_template=str(
                data.get("sign_template") or "{platform}-{version}-{signTime}-{nonce}"
            ),
            inject_headers=bool(inject.get("headers", data.get("inject_headers", True))),
            inject_body=bool(inject.get("body", data.get("inject_body", True))),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "private_key": self.private_key,
            "app_id": self.app_id,
            "platform": self.platform,
            "version": self.version,
            "sign_template": self.sign_template,
            "inject": {
                "headers": self.inject_headers,
                "body": self.inject_body,
            },
        }


@dataclass
class SignResult:
    """Generated sign fields ready to inject into headers / body."""

    fields: Dict[str, Any] = field(default_factory=dict)

    def as_header_values(self) -> Dict[str, str]:
        return {str(k): str(v) for k, v in self.fields.items()}
