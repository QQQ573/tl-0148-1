from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import timedelta

from app.core.database import get_db
from app.core.security import create_access_token, require_roles
from app.core.config import settings
from app.core.exceptions import raise_http_error, BusinessError
from app.services.user_service import UserService
from app.schemas.user import (
    Token, UserCreate, UserResponse, UserLogin, ApiResponse,
)

router = APIRouter(prefix="/auth", tags=["认证授权"])


@router.post("/login", response_model=ApiResponse[Token])
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    user = await UserService.authenticate(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(
        subject=user.id,
        additional_claims={"role": user.role.value, "username": user.username},
        expires_delta=access_token_expires,
    )
    return ApiResponse(data=Token(access_token=token))


@router.post("/register", response_model=ApiResponse[UserResponse])
async def register(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    from app.models.user import UserRole
    if user_in.role not in [UserRole.STUDENT]:
        raise HTTPException(status_code=403, detail="自助注册仅支持学员角色")
    try:
        user = await UserService.create_user(db, user_in)
        return ApiResponse(data=UserResponse.model_validate(user))
    except BusinessError as e:
        raise_http_error(e)


@router.post("/users", response_model=ApiResponse[UserResponse])
async def create_user(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("workshop_manager")),
):
    try:
        user = await UserService.create_user(db, user_in)
        return ApiResponse(data=UserResponse.model_validate(user))
    except BusinessError as e:
        raise_http_error(e)
