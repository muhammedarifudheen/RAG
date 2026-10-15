import hmac
from typing import Annotated

from fastapi import Header, HTTPException

from app.config import settings

ADMIN_REQUIRED = {401: {"description": "This needs the admin password (see ADMIN_TOKEN)."}}


def require_admin(authorization: Annotated[str | None, Header()] = None) -> None:
    """Lets a request through if no admin token is configured, or if it carries it."""
    if not settings.admin_token:
        return
    supplied = (authorization or "").encode()
    expected = f"Bearer {settings.admin_token}".encode()
    # Constant-time, so response timing does not reveal how much of a guess was right.
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            401,
            "Adding or removing sources needs the admin password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
