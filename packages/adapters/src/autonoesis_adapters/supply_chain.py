"""Strict Capability Pack supply-chain verification adapter.

Enforces, before any install is accepted:
- the artifact source is allowlisted;
- the manifest content digest matches its `artifact_digest` (content addressing);
- an ed25519 signature over the canonical unsigned payload verifies against an
  allowlisted public key;
- an SBOM reference and digest are attached.

Vulnerability and compatibility scanning beyond these structural gates remain
pipeline responsibilities (infra/supply-chain); this adapter fails closed on
every missing or mismatched input.
"""

from __future__ import annotations

import os

from autonoesis_capability import (
    CapabilityPackManifest,
    manifest_content_digest,
)
from autonoesis_capability.signing import verify_manifest_signature


class SupplyChainVerificationError(PermissionError):
    """Raised when a Capability Pack fails supply-chain verification."""


class StrictSupplyChainVerifier:
    """Allowlist + digest + signature + SBOM verification for pack installs."""

    def __init__(
        self,
        *,
        allowed_sources: tuple[str, ...],
        public_keys_hex: tuple[str, ...],
    ) -> None:
        if not allowed_sources:
            raise ValueError("supply chain verifier requires at least one allowed source")
        if not public_keys_hex:
            raise ValueError("supply chain verifier requires at least one public key")
        self._allowed_sources = tuple(source.rstrip("/") + "/" for source in allowed_sources)
        self._public_keys_hex = public_keys_hex

    @classmethod
    def from_env(cls) -> StrictSupplyChainVerifier | None:
        """Configure from env; absent configuration yields no verifier (fail closed)."""
        sources = tuple(
            item.strip()
            for item in os.getenv("AUTONOESIS_PACK_ALLOWED_SOURCES", "").split(",")
            if item.strip()
        )
        keys = tuple(
            item.strip()
            for item in os.getenv("AUTONOESIS_PACK_SIGNING_KEYS", "").split(",")
            if item.strip()
        )
        if not sources or not keys:
            return None
        return cls(allowed_sources=sources, public_keys_hex=keys)

    async def verify_install(self, manifest: CapabilityPackManifest) -> None:
        if manifest.artifact_uri is None:
            raise SupplyChainVerificationError(
                "capability pack declares no artifact URI; refusing install"
            )
        if not manifest.artifact_uri.startswith(self._allowed_sources):
            raise SupplyChainVerificationError(
                f"capability pack source is not allowlisted: {manifest.artifact_uri}"
            )
        if manifest.artifact_digest is None:
            raise SupplyChainVerificationError(
                "capability pack declares no artifact digest; refusing install"
            )
        expected_digest = manifest_content_digest(manifest)
        if manifest.artifact_digest != expected_digest:
            raise SupplyChainVerificationError(
                "capability pack content digest mismatch: manifest content changed "
                f"after digesting (expected {manifest.artifact_digest}, "
                f"computed {expected_digest})"
            )
        if not verify_manifest_signature(manifest, self._public_keys_hex):
            raise SupplyChainVerificationError(
                "capability pack signature is missing or does not verify against "
                "any allowlisted publisher key"
            )
        if manifest.sbom_ref is None or manifest.sbom_digest is None:
            raise SupplyChainVerificationError(
                "capability pack must attach an SBOM reference and digest"
            )


__all__ = ["StrictSupplyChainVerifier", "SupplyChainVerificationError"]
