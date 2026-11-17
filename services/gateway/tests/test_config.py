import pytest

from gateway_service.config import GatewaySettings


@pytest.mark.parametrize("secure", [False, True])
def test_settings_read_gateway_values_from_environment(
    monkeypatch, secure: bool
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://gateway:password@localhost:5434/gateway",
    )
    monkeypatch.setenv("JWT_SECRET", "test-signing-secret")
    monkeypatch.setenv("BACKOFFICE_SERVICE_TOKEN", "test-backoffice-token")
    monkeypatch.setenv("REFRESH_COOKIE_SECURE", str(secure).lower())

    settings = GatewaySettings(_env_file=None)

    assert (
        settings.database_url
        == "postgresql+asyncpg://gateway:password@localhost:5434/gateway"
    )
    assert settings.jwt_secret == "test-signing-secret"
    assert settings.backoffice_service_token == "test-backoffice-token"
    assert settings.access_token_ttl_seconds == 15 * 60
    assert settings.refresh_token_ttl_seconds == 7 * 24 * 60 * 60
    assert settings.refresh_cookie_secure is secure
