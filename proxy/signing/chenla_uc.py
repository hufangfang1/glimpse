"""CHENGLA UC signer — mirrors PHP buildSign() (RSA PKCS#1 v1.5 + SHA1)."""

from __future__ import annotations

import base64
import secrets
import string
import time
from typing import Any, Dict

from Crypto.Hash import SHA1
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15

from proxy.signing.models import SignerConfig, SignResult


def _nonce(length: int = 8) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def _sign_time_ms() -> str:
    return str(int(time.time() * 1000))


def _format_template(template: str, values: Dict[str, Any]) -> str:
    try:
        return template.format(**values)
    except KeyError as exc:
        raise ValueError(f"sign_template missing field: {exc}") from exc


def sign(config: SignerConfig) -> SignResult:
    if not config.private_key.strip():
        raise ValueError("private_key is empty")

    nonce = _nonce()
    sign_time = _sign_time_ms()
    payload = {
        "nonce": nonce,
        "signTime": sign_time,
        "platform": config.platform,
        "version": config.version,
        "appId": config.app_id,
    }
    sign_str = _format_template(config.sign_template, payload)

    try:
        key = RSA.import_key(config.private_key.strip())
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid private_key: {exc}") from exc

    digest = SHA1.new(sign_str.encode("utf-8"))
    signature = pkcs1_15.new(key).sign(digest)
    payload["sign"] = base64.b64encode(signature).decode("ascii")
    return SignResult(fields=payload)
