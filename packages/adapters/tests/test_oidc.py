"""Tests for OIDC identity validation."""

import pytest
from autonoesis_adapters import OIDCSettings, OIDCValidator
from jwt import DecodeError


class TestOIDCValidator:
    def test_settings_defaults(self) -> None:
        settings = OIDCSettings(
            issuer="https://idp.example.com",
            audience="autonoesis",
            jwks_url="https://idp.example.com/.well-known/jwks.json",
        )
        assert settings.issuer == "https://idp.example.com"
        assert settings.audience == "autonoesis"

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
