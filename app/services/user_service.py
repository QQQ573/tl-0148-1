from typing import Optional, Tuple, List
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from fastapi import HTTPException, status

from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserUpdate
from app.core.security import verify_password, get_password_hash
from app.core.exceptions import ResourceNotFoundError, BusinessError


class UserService:
    @staticmethod
    async def authenticate(db: AsyncSession, username: str, password: str) -> Optional[User]:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if not user or not verify_password(password, user.hashed_password):
            return None
        if not user.is_active:
            raise BusinessError("账号已被禁用")
        return user

    @staticmethod
    async def create_user(db: AsyncSession, user_in: UserCreate) -> User:
        result = await db.execute(select(User).where(or_(User.username == user_in.username, User.email == user_in.email)))
        existing = result.scalar_one_or_none()
        if existing:
            raise BusinessError("用户名或邮箱已存在")
        user = User(
            username=user_in.username,
            email=user_in.email,
            full_name=user_in.full_name,
            phone=user_in.phone,
            role=user_in.role,
            hashed_password=get_password_hash(user_in.password),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def get_user(db: AsyncSession, user_id: int) -> Optional[User]:
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_or_404(db: AsyncSession, user_id: int) -> User:
        user = await UserService.get_user(db, user_id)
        if not user:
            raise ResourceNotFoundError("用户", user_id)
        return user

    @staticmethod
    async def list_users(
        db: AsyncSession,
        role: Optional[UserRole] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[User], int]:
        query = select(User)
        if role:
            query = query.where(User.role == role)
        if keyword:
            query = query.where(or_(User.username.ilike(f"%{keyword}%"), User.full_name.ilike(f"%{keyword}%"), User.email.ilike(f"%{keyword}%")))
        count_query = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_query)).scalar_one()
        query = query.order_by(User.id.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        items = result.scalars().all()
        return list(items), total

    @staticmethod
    async def update_user(db: AsyncSession, user_id: int, user_in: UserUpdate) -> User:
        user = await UserService.get_user_or_404(db, user_id)
        update_data = user_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(user, field, value)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def get_masters(db: AsyncSession) -> List[User]:
        result = await db.execute(select(User).where(User.role == UserRole.MASTER, User.is_active == True))
        return list(result.scalars().all())

    @staticmethod
    async def init_default_users(db: AsyncSession) -> None:
        default_users = [
            {"username": "manager", "email": "manager@clay.local", "password": "123456", "full_name": "坊管家", "role": UserRole.WORKSHOP_MANAGER},
            {"username": "master1", "email": "master1@clay.local", "password": "123456", "full_name": "李大师", "role": UserRole.MASTER},
            {"username": "master2", "email": "master2@clay.local", "password": "123456", "full_name": "王大师", "role": UserRole.MASTER},
            {"username": "finance", "email": "finance@clay.local", "password": "123456", "full_name": "财务员", "role": UserRole.FINANCE},
        ]
        for u in default_users:
            result = await db.execute(select(User).where(User.username == u["username"]))
            if result.scalar_one_or_none():
                continue
            user = User(
                username=u["username"],
                email=u["email"],
                full_name=u["full_name"],
                role=u["role"],
                hashed_password=get_password_hash(u["password"]),
            )
            db.add(user)
        await db.commit()
