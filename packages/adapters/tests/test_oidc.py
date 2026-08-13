"""Tests for OIDC identity validation."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from autonoesis_adapters import (
    OIDCSettings,
    OIDCValidator,
    cached_oidc_validator,
)
from jwt import DecodeError, InvalidTokenError


class TestOIDCValidator:
    def test_settings_defaults(self) -> None:
        settings = OIDCSettings(
            issuer="https://idp.example.com",
            audience="autonoesis",
            jwks_url="https://idp.example.com/.well-known/jwks.json",
        )
        assert settings.issuer == "https://idp.example.com"
        assert settings.audience == "autonoesis"
        assert settings.allowed_token_types == ("access", "at+jwt")

    def test_validator_is_reused_for_identical_process_settings(self) -> None:
        settings = OIDCSettings("issuer", "audience", "https://idp.example/jwks")
        cached_oidc_validator.cache_clear()
        assert cached_oidc_validator(settings) is cached_oidc_validator(settings)

    def test_validator_construction(self) -> None:
        settings = OIDCSettings(
            issuer="https://idp.example.com",
            audience="autonoesis",
            jwks_url="https://idp.example.com/.well-known/jwks.json",
        )
        validator = OIDCValidator(settings)
        assert validator is not None

    @pytest.mark.asyncio
    async def test_invalid_token_raises(self) -> None:
        settings = OIDCSettings(
            issuer="https://idp.example.com",
            audience="autonoesis",
            jwks_url="https://idp.example.com/.well-known/jwks.json",
        )
        validator = OIDCValidator(settings)
        with pytest.raises((ValueError, OSError, DecodeError)):
            validator.validate("not-a-valid-jwt")

    def test_validator_rejects_wrong_token_type_after_claim_validation(self) -> None:
        settings = OIDCSettings("issuer", "audience", "https://idp.example/jwks")
        validator = OIDCValidator(settings)
        validator._keys = MagicMock()
        validator._keys.get_signing_key_from_jwt.return_value.key = object()
        subject, tenant = uuid4(), uuid4()
        with (
            patch(
                "autonoesis_adapters.governance.jwt.get_unverified_header",
                return_value={"typ": "JWT"},
            ),
            patch(
                "autonoesis_adapters.governance.jwt.decode",
                return_value={
                    "iss": "issuer",
                    "aud": "audience",
                    "sub": str(subject),
                    "tenant_id": str(tenant),
                    "exp": 9_999_999_999,
                    "iat": 1,
                    "token_use": "id",
                },
            ),
            pytest.raises(InvalidTokenError, match="token type"),
        ):
            validator.validate("header.payload.signature")
