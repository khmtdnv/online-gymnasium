from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from gateway_service.application.errors import AuthenticationError
from gateway_service.config import GatewaySettings
from gateway_service.domain.user import Role, User
from gateway_service.infrastructure.token_service import PyJwtTokenService

SIGNING_SECRET = "test-signing-secret-for-hs256-32-bytes"
OTHER_SECRET = "another-signing-secret-for-hs256-32-bytes"


@pytest.mark.parametrize(
    "kind,field",
    [
        ("access", "sub"),
        ("access", "role"),
        ("access", "type"),
        ("refresh", "sub"),
        ("refresh", "jti"),
        ("refresh", "type"),
        ("access", "exp"),
        ("refresh", "exp"),
    ],
)
@pytest.mark.parametrize("value", [123, [], {}])
def test_malformed_claim_types_are_authentication_errors(kind, field, value):
    """Переводит неверные типы подписанных claims в штатную ошибку авторизации."""
    service = make_service()
    claims = {
        "sub": str(uuid4()),
        "jti": str(uuid4()),
        "role": "student",
        "type": kind,
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }
    claims[field] = value
    token = jwt.encode(claims, SIGNING_SECRET, algorithm="HS256")
    decode = service.decode_access if kind == "access" else service.decode_refresh
    with pytest.raises(AuthenticationError):
        decode(token)


def make_service(*, secret: str = SIGNING_SECRET) -> PyJwtTokenService:
    settings = GatewaySettings(
        database_url="postgresql+asyncpg://gateway:password@localhost/gateway",
        jwt_secret=secret,
        backoffice_service_token="test-backoffice-token",
        _env_file=None,
    )
    return PyJwtTokenService(settings)


def make_user() -> User:
    return User(
        id=uuid4(),
        email="student@example.com",
        role=Role.STUDENT,
        password_hash="stored-hash",
        is_active=True,
        first_name="Тестовый",
        last_name="Пользователь",
    )


def test_issued_refresh_round_trips_with_its_jti_and_expiry() -> None:
    service = make_service()
    user = make_user()

    issued = service.issue_refresh(user)
    decoded = service.decode_refresh(issued.token)
    claims = jwt.decode(issued.token, SIGNING_SECRET, algorithms=["HS256"])

    assert decoded.user_id == user.id
    assert decoded.jti == issued.jti
    assert claims["sub"] == str(user.id)
    assert claims["jti"] == str(issued.jti)
    assert claims["type"] == "refresh"
    assert claims["exp"] == int(issued.expires_at.timestamp())


def test_issued_access_round_trips_with_user_and_role() -> None:
    service = make_service()
    user = make_user()

    token = service.issue_access(user)
    decoded = service.decode_access(token)
    claims = jwt.decode(token, SIGNING_SECRET, algorithms=["HS256"])

    assert decoded.user_id == user.id
    assert decoded.role is Role.STUDENT
    assert claims["type"] == "access"
    assert claims["role"] == "student"


def test_tokens_preserve_the_same_server_session_id() -> None:
    service = make_service()
    user = make_user()
    session_id = uuid4()

    access = service.issue_access(user, session_id=session_id)
    refresh = service.issue_refresh(user, session_id=session_id)

    assert service.decode_access(access).session_id == session_id
    assert service.decode_refresh(refresh.token).session_id == session_id


@pytest.mark.parametrize("kind", ["access", "refresh"])
@pytest.mark.parametrize("value", ["not-a-uuid", 123, [], {}, None])
def test_tokens_reject_invalid_session_id(kind, value) -> None:
    service = make_service()
    claims = {
        "sub": str(uuid4()),
        "jti": str(uuid4()),
        "role": "student",
        "type": kind,
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "sid": value,
    }
    token = jwt.encode(claims, SIGNING_SECRET, algorithm="HS256")
    decode = service.decode_access if kind == "access" else service.decode_refresh
    with pytest.raises(AuthenticationError):
        decode(token)


def test_old_tokens_without_session_id_still_decode() -> None:
    service = make_service()
    user = make_user()
    assert service.decode_access(service.issue_access(user)).session_id is None
    assert service.decode_refresh(service.issue_refresh(user).token).session_id is None


def test_access_and_refresh_tokens_cannot_be_interchanged() -> None:
    service = make_service()
    user = make_user()

    with pytest.raises(AuthenticationError):
        service.decode_access(service.issue_refresh(user).token)

    with pytest.raises(AuthenticationError):
        service.decode_refresh(service.issue_access(user))


@pytest.mark.parametrize("token_type", ["access", "refresh"])
def test_decoding_rejects_expired_and_wrongly_signed_tokens(token_type: str) -> None:
    service = make_service()
    user = make_user()
    claims = {
        "sub": str(user.id),
        "jti": str(uuid4()),
        "role": "student",
        "type": token_type,
        "exp": datetime.now(UTC) - timedelta(seconds=1),
    }
    decode = service.decode_access if token_type == "access" else service.decode_refresh

    expired = jwt.encode(claims, SIGNING_SECRET, algorithm="HS256")
    with pytest.raises(AuthenticationError):
        decode(expired)

    claims["exp"] = datetime.now(UTC) + timedelta(minutes=5)
    wrong_signature = jwt.encode(claims, OTHER_SECRET, algorithm="HS256")
    with pytest.raises(AuthenticationError):
        decode(wrong_signature)


@pytest.mark.parametrize("token_type", ["access", "refresh"])
def test_decoding_rejects_missing_type_and_malformed_user_id(token_type: str) -> None:
    service = make_service()
    claims = {
        "sub": str(uuid4()),
        "jti": str(uuid4()),
        "role": "student",
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }
    decode = service.decode_access if token_type == "access" else service.decode_refresh

    missing_type = jwt.encode(claims, SIGNING_SECRET, algorithm="HS256")
    with pytest.raises(AuthenticationError):
        decode(missing_type)

    claims["type"] = token_type
    claims["sub"] = "not-a-uuid"
    malformed_user_id = jwt.encode(claims, SIGNING_SECRET, algorithm="HS256")
    with pytest.raises(AuthenticationError):
        decode(malformed_user_id)
