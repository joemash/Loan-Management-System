"""Mint local JWTs for Swagger/curl (development only).

uv run python scripts/make_jwt.py ADMIN        # admin token
uv run python scripts/make_jwt.py USER --ttl 7200
"""

import argparse

from src.adapters.web.security import JwtTokenService
from src.infrastructure.config.settings import get_settings

parser = argparse.ArgumentParser()
parser.add_argument("roles", nargs="+", help="e.g. ADMIN USER")
parser.add_argument("--sub", default="local-dev")
parser.add_argument("--ttl", type=int, default=3600, help="lifetime in seconds")
args = parser.parse_args()
print(JwtTokenService.from_settings(get_settings()).issue(args.sub, args.roles, args.ttl))
