"""Permission constants and helpers."""

from typing import TYPE_CHECKING

ALL_PERMISSIONS: list[str] = [
    "read:trades",
    "execute:trades",
    "manage:settings",
    "admin",
]

DEFAULT_USER_PERMISSIONS: list[str] = ["read:trades"]

ADMIN_ROLE = "Admin"
USER_ROLE = "User"

if TYPE_CHECKING:
    from app.models import User


def parse_permissions(raw: str | list[str] | None) -> list[str]:
    """Normalize permissions from JSON string or list."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [p for p in raw if isinstance(p, str) and p in ALL_PERMISSIONS]
    import json

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [p for p in data if isinstance(p, str) and p in ALL_PERMISSIONS]


def has_permission(user: "User", permission: str) -> bool:
    """Admin role or `admin` permission grants all access."""
    if user.role == ADMIN_ROLE:
        return True
    perms = user.permissions_list
    if "admin" in perms:
        return True
    return permission in perms


def is_admin(user: "User") -> bool:
    return user.role == ADMIN_ROLE or "admin" in user.permissions_list
