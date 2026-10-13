# Authentication

The API uses stateless **JWT Bearer authentication** (`src.adapters.web.security`).

## Access rules

| Path | Requirement | FastAPI dependency |
|------|-------------|--------------------|
| `/admin/**` | role `ADMIN` | `require_admin` |
| `/loans/**`, `/customers/**` | any valid token | `require_authenticated` |
| `/swagger-ui`, `/api-docs/**`, `/actuator/*` | public | — |

## Token format

Send `Authorization: Bearer <jwt>`. Validation checks:

- HMAC SHA-256 signature (`AUTH_JWT_SECRET`)
- `exp` / `nbf` / `iat` with `AUTH_JWT_CLOCK_SKEW_SECONDS` leeway
- `iss` must be present and equal `AUTH_JWT_ISSUER`
- `roles` claim is required: a JSON array (`["ADMIN"]`) or comma-separated string (`"ADMIN,USER"`)

Roles are normalised with a `ROLE_` prefix (`ADMIN` → `ROLE_ADMIN`).

## Error responses

| Status | Body | When |
|--------|------|------|
| 401 | `{"error":"Authentication is required"}` | missing or empty bearer token |
| 401 | `{"error":"Invalid or expired bearer token"}` | bad signature, expired, wrong issuer, no `roles` |
| 403 | `{"error":"You are not allowed to access this resource"}` | token lacks `ADMIN` on `/admin/**` |

## Local tokens

`scripts/make_jwt.py` signs tokens with the configured secret and issuer:

```bash
export ADMIN_JWT=$(uv run python scripts/make_jwt.py ADMIN)
export USER_JWT=$(uv run python scripts/make_jwt.py USER)
# options: --sub <subject>  --ttl <seconds>
```

In Swagger UI (`http://localhost:8080/swagger-ui`) click **Authorize** and paste the token (without
`Bearer `). Authorization persists across page reloads.

For a step-by-step walkthrough (authorize, create a customer, run the full loan flow), see
[Using the API from Swagger UI](../README.md#using-the-api-from-swagger-ui).

Keep real secrets out of source control; set `AUTH_JWT_SECRET` through the environment.
