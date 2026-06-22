"""Authentication endpoints: login, profile, change password."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_secure_key
from app.database import get_db
from app.models import User
from app.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    MessageResponse,
    TokenResponse,
    UserRead,
)
from app.services.auth_service import AuthService

router = APIRouter(
    prefix="/api/auth",
    tags=["auth"],
    dependencies=[Depends(require_secure_key)],
)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    service = AuthService(db)
    user = service.authenticate(payload.username.strip(), payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Sai tên đăng nhập hoặc mật khẩu")
    return service.issue_token(user)


@router.get("/me", response_model=UserRead)
def get_me(user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(user)


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MessageResponse:
    if payload.new_password != payload.confirm_password:
        raise HTTPException(
            status_code=400,
            detail="Mật khẩu mới và xác nhận không khớp",
        )
    try:
        AuthService(db).change_password(user, payload.old_password, payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MessageResponse(message="Đổi mật khẩu thành công. Vui lòng đăng nhập lại.")
