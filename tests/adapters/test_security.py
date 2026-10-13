"""JWT parsing (Java ``JwtTokenServiceTest``)."""

import time

import jwt
import pytest

from src.adapters.web.security import InvalidTokenError, JwtTokenService
from tests.conftest import TEST_ISSUER, TEST_SECRET


def _encode(claims: dict, secret: str = TEST_SECRET) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": "x", "iss": TEST_ISSUER, "iat": now, "exp": now + 60, **claims}, secret, "HS256"
    )


def test_parse_bearer_token_maps_roles_to_authorities(tokens):
    token = tokens.issue("test-user", ["ADMIN", "USER"])

    principal = tokens.parse_bearer_token(token)

    assert principal.subject == "test-user"
    assert principal.authorities == {"ROLE_ADMIN", "ROLE_USER"}
    assert principal.has_role("ADMIN")


def test_parse_bearer_token_accepts_comma_separated_roles_and_role_prefix(tokens):
    principal = tokens.parse_bearer_token(_encode({"roles": "ROLE_ADMIN, USER"}))
    assert principal.authorities == {"ROLE_ADMIN", "ROLE_USER"}


def test_parse_bearer_token_rejects_missing_roles_claim(tokens):
    now = int(time.time())
    token = jwt.encode(
        {"sub": "x", "iss": TEST_ISSUER, "iat": now, "exp": now + 60}, TEST_SECRET, algorithm="HS256"
    )
    with pytest.raises(InvalidTokenError):
        tokens.parse_bearer_token(token)


@pytest.mark.parametrize(
    "token_factory",
    [
        lambda: _encode({"roles": ["ADMIN"], "iss": "someone-else"}),
        lambda: _encode({"roles": ["ADMIN"]}, secret="wrong-secret-wrong-secret-wrong-secret"),
        lambda: _encode({"roles": ["ADMIN"], "exp": int(time.time()) - 3600}),
    ],
    ids=["wrong-issuer", "bad-signature", "expired"],
)
def test_parse_bearer_token_rejects_invalid_tokens(token_factory):
    service = JwtTokenService(TEST_SECRET, TEST_ISSUER, clock_skew_seconds=60)
    with pytest.raises(InvalidTokenError):
        service.parse_bearer_token(token_factory())
