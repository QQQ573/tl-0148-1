from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.user import UserRole
from app.services.user_service import UserService
from app.schemas.user import (
    UserResponse, UserListResponse, UserUpdate, ApiResponse,
)

router = APIRouter(prefix="/users", tags=["用户管理"])


@router.get("/me", response_model=ApiResponse[UserResponse])
async def get_me(current_user=Depends(get_current_user)):
    return ApiResponse(data=UserResponse.model_validate(current_user))


@router.get("", response_model=ApiResponse[UserListResponse])
async def list_users(
    role: Optional[UserRole] = Query(None, description="按角色筛选"),
    keyword: Optional[str] = Query(None, description="搜索关键词（用户名/姓名/邮箱）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user=Depends(require_roles("workshop_manager")),
    db: AsyncSession = Depends(get_db),
):
    items, total = await UserService.list_users(db, role=role, keyword=keyword, page=page, page_size=page_size)
    data = UserListResponse(
        items=[UserResponse.model_validate(u) for u in items],
        total=total,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(data=data)


@router.get("/{user_id}", response_model=ApiResponse[UserResponse])
async def get_user(
    user_id: int,
    current_user=Depends(require_roles("workshop_manager", "master", "finance")),
    db: AsyncSession = Depends(get_db),
):
    user = await UserService.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return ApiResponse(data=UserResponse.model_validate(user))


@router.patch("/{user_id}", response_model=ApiResponse[UserResponse])
async def update_user(
    user_id: int,
    user_in: UserUpdate,
    current_user=Depends(require_roles("workshop_manager")),
    db: AsyncSession = Depends(get_db),
):
    user = await UserService.update_user(db, user_id, user_in)
    return ApiResponse(data=UserResponse.model_validate(user))


@router.get("/masters/list", response_model=ApiResponse[list[UserResponse]])
async def list_masters(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    masters = await UserService.get_masters(db)
    return ApiResponse(data=[UserResponse.model_validate(m) for m in masters])
