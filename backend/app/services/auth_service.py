"""Authentication business logic."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.permissions import ALL_PERMISSIONS, ADMIN_ROLE
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.models import User
from app.schemas import TokenResponse, UserRead


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def authenticate(self, username: str, password: str) -> User | None:
        user = (
            self.db.query(User)
            .filter(User.username == username)
            .first()
        )
        if user is None or not user.is_active:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    def issue_token(self, user: User) -> TokenResponse:
        token = create_access_token(
            user_id=user.id,
            username=user.username,
            role=user.role,
            permissions=user.permissions_list,
        )
        return TokenResponse(
            access_token=token,
            token_type="bearer",
            user=UserRead.model_validate(user),
        )

    def change_password(
        self,
        user: User,
        old_password: str,
        new_password: str,
    ) -> None:
        if not verify_password(old_password, user.hashed_password):
            raise ValueError("Mật khẩu cũ không chính xác")
        if len(new_password) < 6:
            raise ValueError("Mật khẩu mới phải có ít nhất 6 ký tự")
        user.hashed_password = hash_password(new_password)
        self.db.add(user)
        self.db.commit()


class AdminUserService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_users(self) -> list[User]:
        return self.db.query(User).order_by(User.id).all()

    def get_user(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def create_user(
        self,
        *,
        username: str,
        email: str,
        password: str,
        role: str,
        permissions: list[str],
        is_active: bool,
    ) -> User:
        if self.db.query(User).filter(User.username == username).first():
            raise ValueError("Username đã tồn tại")
        if self.db.query(User).filter(User.email == email).first():
            raise ValueError("Email đã tồn tại")
        if len(password) < 6:
            raise ValueError("Mật khẩu phải có ít nhất 6 ký tự")
        valid_perms = [p for p in permissions if p in ALL_PERMISSIONS]
        user = User(
            username=username,
            email=email,
            hashed_password=hash_password(password),
            role=role if role in (ADMIN_ROLE, "User") else "User",
            is_active=is_active,
        )
        user.set_permissions(valid_perms)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_user(
        self,
        user_id: int,
        *,
        email: str | None = None,
        password: str | None = None,
        role: str | None = None,
        permissions: list[str] | None = None,
        is_active: bool | None = None,
    ) -> User:
        user = self.db.get(User, user_id)
        if user is None:
            raise ValueError("User không tồn tại")

        if email is not None and email != user.email:
            if self.db.query(User).filter(User.email == email).first():
                raise ValueError("Email đã tồn tại")
            user.email = email

        if password is not None:
            if len(password) < 6:
                raise ValueError("Mật khẩu phải có ít nhất 6 ký tự")
            user.hashed_password = hash_password(password)

        if role is not None and role in (ADMIN_ROLE, "User"):
            user.role = role

        if permissions is not None:
            user.set_permissions(permissions)

        if is_active is not None:
            user.is_active = is_active

        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user
