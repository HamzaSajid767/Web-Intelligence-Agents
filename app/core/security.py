"""Security utilities — placeholder for future JWT auth."""

from typing import Any


class SecurityStub:
    """No-op security layer for v1 single-tenant API."""

    @staticmethod
    def get_current_user_id() -> str | None:
        """Return current user ID when auth is implemented."""
        return None

    @staticmethod
    async def authenticate_request(_headers: dict[str, Any]) -> bool:
        """Authenticate request — always True in v1."""
        return True
