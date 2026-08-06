from __future__ import annotations

import os

from fastapi import HTTPException, Request, status

CAPABILITY_ENV_VAR = "BAHLILY_CAPABILITY"
CAPABILITY_HEADER = "x-bahlily-capability"


def get_capability() -> str | None:
    """Return the configured capability token, or None when unset.

    A value of None means the service is running in permissive mode and does
    not enforce the token header. Production deployments must set this env
    var to a per-launch unguessable string.
    """
    raw = os.environ.get(CAPABILITY_ENV_VAR, "").strip()
    return raw or None


def is_required() -> bool:
    return get_capability() is not None


def require_capability(request: Request) -> None:
    """FastAPI dependency that enforces the capability token when configured."""
    expected = get_capability()
    if expected is None:
        return
    provided = request.headers.get(CAPABILITY_HEADER, "")
    if not _safe_compare(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing capability token",
        )


def _safe_compare(a: str, b: str) -> bool:
    """Constant-time string compare that returns False for length mismatches."""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b, strict=False):
        result |= ord(x) ^ ord(y)
    return result == 0
