"""Merge sign fields into outgoing headers and body."""

from __future__ import annotations

import json
from typing import Dict, Tuple
from urllib.parse import parse_qsl, urlencode

from proxy.signing.models import SignerConfig
from proxy.signing.registry import sign as registry_sign


def _stringify_fields(fields: dict) -> Dict[str, str]:
    return {str(k): str(v) for k, v in fields.items()}


def merge_sign_into_body(body: bytes, fields: dict, content_type: str) -> bytes:
    """Merge sign dict into JSON or form body (PHP array_merge behaviour)."""
    ct = (content_type or "").lower().split(";")[0].strip()
    text = body.decode("utf-8") if body else ""
    merged = _stringify_fields(fields)

    def _as_json(data: dict) -> bytes:
        data.update(merged)
        return json.dumps(data, ensure_ascii=False).encode("utf-8")

    def _as_form(pairs: dict) -> bytes:
        pairs.update(merged)
        return urlencode(pairs).encode("utf-8")

    if "json" in ct:
        try:
            parsed = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            return _as_json(parsed)
        return _as_form({})

    if "form" in ct or ct == "application/x-www-form-urlencoded":
        pairs = dict(parse_qsl(text, keep_blank_values=True)) if text else {}
        return _as_form(pairs)

    if text.strip():
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return _as_json(parsed)
        except json.JSONDecodeError:
            pass
        pairs = dict(parse_qsl(text, keep_blank_values=True))
        return _as_form(pairs)

    return _as_form({})


def apply_signer(
    config: SignerConfig,
    headers: dict,
    body: bytes,
) -> Tuple[dict, bytes]:
    """Run signer and optionally inject into headers / body."""
    result = registry_sign(config)
    out_headers = dict(headers)
    out_body = body

    if config.inject_headers:
        for key, value in result.as_header_values().items():
            out_headers[key] = value

    if config.inject_body:
        ct = ""
        for k, v in headers.items():
            if k.lower() == "content-type":
                ct = v
                break
        out_body = merge_sign_into_body(body, result.fields, ct)

    return out_headers, out_body
