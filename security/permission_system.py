"""PermissionSystem — 权限管理系统"""
from __future__ import annotations
import logging
from enum import Enum
logger = logging.getLogger(__name__)

class Permission(str, Enum):
    READ  = "read"
    WRITE = "write"
    EXEC  = "exec"
    ADMIN = "admin"

class PermissionSystem:
    """用户权限管理。"""
    def __init__(self) -> None:
        self._roles: dict[str, set[Permission]] = {
            "admin": {Permission.READ, Permission.WRITE, Permission.EXEC, Permission.ADMIN},
            "user":  {Permission.READ, Permission.WRITE},
            "guest": {Permission.READ},
        }
        self._user_roles: dict[str, str] = {}

    def assign_role(self, user_id: str, role: str) -> None:
        self._user_roles[user_id] = role

    def has_permission(self, user_id: str, permission: Permission) -> bool:
        role = self._user_roles.get(user_id, "user")
        return permission in self._roles.get(role, set())

    def get_role(self, user_id: str) -> str:
        return self._user_roles.get(user_id, "user")
