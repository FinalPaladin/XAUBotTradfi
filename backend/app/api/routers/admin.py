"""Admin-only user account management."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_secure_key
from app.database import get_db
from app.schemas import AdminUserCreate, AdminUserUpdate, UserRead
from app.services.auth_service import AdminUserService

router = APIRouter(
    prefix="/api/admin/users",
    tags=["admin"],
    dependencies=[Depends(require_secure_key), Depends(require_admin)],
)


@router.get("", response_model=list[UserRead])
def list_users(db: Session = Depends(get_db)) -> list[UserRead]:
    users = AdminUserService(db).list_users()
    return [UserRead.model_validate(u) for u in users]


@router.post("", response_model=UserRead, status_code=201)
def create_user(
    payload: AdminUserCreate,
    db: Session = Depends(get_db),
) -> UserRead:
    try:
        user = AdminUserService(db).create_user(
            username=payload.username.strip(),
            email=payload.email.strip(),
            password=payload.password,
            role=payload.role,
            permissions=payload.permissions,
            is_active=payload.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UserRead.model_validate(user)


@router.put("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
) -> UserRead:
    try:
        user = AdminUserService(db).update_user(
            user_id,
            email=payload.email.strip() if payload.email else None,
            password=payload.password,
            role=payload.role,
            permissions=payload.permissions,
            is_active=payload.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UserRead.model_validate(user)
