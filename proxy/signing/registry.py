"""Signer type registry — add new ``type`` values when algorithms change."""

from __future__ import annotations

from proxy.signing import chenla_uc
from proxy.signing.models import SignerConfig, SignResult

# Types that use the CHENGLA UC field layout + RSA-SHA1 pipeline.
_CHENLA_TYPES = frozenset({"chenla_uc", "rsa_pkcs1_sha1", "chenla_uc_v1"})


def sign(config: SignerConfig) -> SignResult:
    if config.type in _CHENLA_TYPES:
        return chenla_uc.sign(config)
    raise ValueError(f"unsupported signer type: {config.type}")
