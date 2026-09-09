"""Development signing helpers for Capability Pack supply-chain verification.

Production signing belongs to the release pipeline (infra/supply-chain). These
helpers exist so tests, examples, and local tooling can produce and verify
ed25519 signatures over the canonical unsigned manifest payload. They never
weaken verification: a signature produced here is only meaningful against the
public keys configured in the verifier's allowlist.
"""

from __future__ import annotations

from dataclasses import replace

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from autonoesis_capability.manifest import (
    CapabilityPackManifest,
    ManifestError,
    canonical_signature_bytes,
    manifest_content_digest,
)


def generate_signing_key() -> str:
    """Return a fresh ed25519 private key as lowercase hex (development only)."""
    return (
        Ed25519PrivateKey.generate()
        .private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        .hex()
    )


def public_key_hex(private_key_hex: str) -> str:
    key = _load_private_key(private_key_hex)
    return (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )


def sign_manifest_payload(
    manifest: CapabilityPackManifest, private_key_hex: str
) -> CapabilityPackManifest:
    """Return the manifest with a signature over its canonical unsigned payload."""
    key = _load_private_key(private_key_hex)
    signature = key.sign(canonical_signature_bytes(manifest)).hex()
    return replace(manifest, signature=signature)


def verify_manifest_signature(
    manifest: CapabilityPackManifest, public_keys_hex: tuple[str, ...]
) -> bool:
    if manifest.signature is None or not public_keys_hex:
        return False
    for public_hex in public_keys_hex:
        try:
            raw = bytes.fromhex(public_hex)
        except ValueError:
            continue
        if len(raw) != 32:
            continue
        try:
            Ed25519PublicKey.from_public_bytes(raw).verify(
                bytes.fromhex(manifest.signature), canonical_signature_bytes(manifest)
            )
        except (InvalidSignature, ValueError):
            continue
        return True
    return False


def supply_chain_fields(
    manifest: CapabilityPackManifest,
    *,
    private_key_hex: str,
    sbom_ref: str,
    sbom_digest: str,
    artifact_uri: str | None = None,
) -> CapabilityPackManifest:
    """Attach digest, SBOM, and signature fields to a manifest (development)."""
    artifact_uri = artifact_uri or f"artifact://packs/{manifest.pack_id}/{manifest.version}"
    attached = replace(
        manifest,
        artifact_uri=artifact_uri,
        artifact_digest=manifest_content_digest(manifest),
        sbom_ref=sbom_ref,
        sbom_digest=sbom_digest,
    )
    return sign_manifest_payload(attached, private_key_hex)


def _load_private_key(private_key_hex: str) -> Ed25519PrivateKey:
    try:
        raw = bytes.fromhex(private_key_hex)
    except ValueError as exc:
        raise ManifestError("signing key must be lowercase hex") from exc
    if len(raw) != 32:
        raise ManifestError("signing key must be a raw 32-byte ed25519 key")
    return Ed25519PrivateKey.from_private_bytes(raw)


__all__ = [
    "generate_signing_key",
    "public_key_hex",
    "sign_manifest_payload",
    "supply_chain_fields",
    "verify_manifest_signature",
]
