"""JWT bearer authentication and role-based access (Java ``SecurityConfiguration`` + ``JwtTokenService``).

Access rules:
* ``/admin/**`` requires ``ROLE_ADMIN`` (``require_admin``)
* ``/loans/**`` and ``/customers/**`` require any authenticated user (``require_authenticated``)
* docs and ``/actuator/*`` are public
"""

from dataclasses import dataclass, field

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.adapters.web.errors import ApiError
from src.infrastructure.config.settings import Settings

MSG_AUTH_REQUIRED = "Authentication is required"
MSG_INVALID_TOKEN = "Invalid or expired bearer token"
MSG_FORBIDDEN = "You are not allowed to access this resource"

ROLE_ADMIN = "ROLE_ADMIN"


class InvalidTokenError(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    subject: str | None
    authorities: frozenset[str] = field(default_factory=frozenset)

    def has_role(self, role: str) -> bool:
        return _to_role_authority(role) in self.authorities


class JwtTokenService:
    def __init__(self, secret: str, issuer: str, clock_skew_seconds: int = 60):
        self._secret = secret
        self._issuer = issuer
        self._leeway = clock_skew_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> "JwtTokenService":
        return cls(settings.auth_jwt_secret, settings.auth_jwt_issuer, settings.auth_jwt_clock_skew_seconds)

    def parse_bearer_token(self, token: str) -> Principal:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["iss"], "verify_aud": False},
            )
        except jwt.PyJWTError as ex:
            raise InvalidTokenError(str(ex)) from ex
        return Principal(subject=claims.get("sub"), authorities=frozenset(_to_authorities(claims)))

    def issue(self, subject: str, roles: list[str], ttl_seconds: int = 3600) -> str:
        """Mints a token (local development / tests; the API itself never issues tokens)."""
        import time

        now = int(time.time())
        payload = {"sub": subject, "iss": self._issuer, "iat": now, "exp": now + ttl_seconds, "roles": roles}
        return jwt.encode(payload, self._secret, algorithm="HS256")


def _to_authorities(claims: dict) -> list[str]:
    roles = claims.get("roles")
    if isinstance(roles, str):
        return [_to_role_authority(r) for r in roles.split(",") if r.strip()]
    if isinstance(roles, list):
        return [_to_role_authority(r) for r in roles if isinstance(r, str) and r.strip()]
    raise InvalidTokenError("Token is missing required roles claim")


def _to_role_authority(role: str) -> str:
    role = role.strip()
    return role if role.startswith("ROLE_") else "ROLE_" + role


_bearer = HTTPBearer(auto_error=False, description="JWT signed with HS256 carrying a `roles` claim")


def get_token_service(request: Request) -> JwtTokenService:
    return request.app.state.injector.get(JwtTokenService)


def require_authenticated(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    token_service: JwtTokenService = Depends(get_token_service),
) -> Principal:
    if credentials is None or not credentials.credentials.strip():
        raise ApiError(401, MSG_AUTH_REQUIRED)
    try:
        return token_service.parse_bearer_token(credentials.credentials.strip())
    except InvalidTokenError as ex:
        raise ApiError(401, MSG_INVALID_TOKEN) from ex


def require_admin(principal: Principal = Depends(require_authenticated)) -> Principal:
    if not principal.has_role(ROLE_ADMIN):
        raise ApiError(403, MSG_FORBIDDEN)
    return principal
