from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine, AsyncSessionLocal
from app.core.redis_client import RedisClient
from app.core.minio_client import MinioClient
from app.core.exceptions import AppError, VersionConflictError
from app.api.v1.router import api_router
from app.services.user_service import UserService
from app.services.class_service import MasterClassService
from app.schemas.user import MasterClassCreate, ClayQuotaCreate
from app.models.user import ClayType
from decimal import Decimal


@asynccontextmanager
async def lifespan(app: FastAPI):
    MinioClient.ensure_bucket()
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            await UserService.init_default_users(session)
            try:
                await _seed_demo_classes(session)
            except Exception:
                pass
    except Exception as e:
        print(f"[INIT WARNING] DB init: {e}")
    yield
    await RedisClient.close()


async def _seed_demo_classes(db):
    from datetime import date
    items, total = await MasterClassService.list_classes(db, page=1, page_size=1)
    if total > 0:
        return
    masters = await UserService.get_masters(db)
    if not masters:
        return
    mid = masters[0].id
    import datetime as dt
    now = dt.date.today()
    for i in range(1, 6):
        class_date = date(now.year, now.month, min(15 + i, 28))
        mc_in = MasterClassCreate(
            title=f"非遗泥塑大师课 · 第{i}课",
            description=f"体验传统泥塑技艺，由大师亲授第{i}讲",
            master_id=mid,
            class_date=class_date,
            start_time="09:30",
            end_time="12:00",
            capacity=8,
            year=now.year,
            month=now.month,
            class_no=i,
            is_published=True,
            clay_quotas=[
                ClayQuotaCreate(clay_type=ClayType.GAOBAI_NI, total_kg=Decimal("20.00")),
                ClayQuotaCreate(clay_type=ClayType.HONGTAO, total_kg=Decimal("15.00")),
                ClayQuotaCreate(clay_type=ClayType.XIANWEI_NI, total_kg=Decimal("10.00")),
            ],
        )
        await MasterClassService.create_class(db, mc_in)


app = FastAPI(
    title=settings.APP_NAME,
    description="非遗泥塑工坊预约管理系统 - 支持多角色、预约状态流转、泥料配额管理、并发乐观锁、MinIO附件、Celery异步告警",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    contact={"name": "坊管家", "email": "manager@clayworkshop.local"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Current-Version", "X-Error-Code"],
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    code = exc.code if 100 <= exc.code < 600 else 400
    headers = {"X-Error-Code": str(exc.code)}
    if isinstance(exc, VersionConflictError):
        code = 409
        headers["X-Current-Version"] = str(exc.data.get("current_version"))
    return JSONResponse(
        status_code=code,
        content={"code": exc.code, "message": exc.message, "data": exc.data or {}},
        headers=headers,
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"code": 500, "message": f"服务器内部错误: {str(exc)}", "data": {}},
    )


@app.get("/", tags=["系统"])
async def root():
    return {
        "name": settings.APP_NAME,
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
    }


@app.get("/health", tags=["系统"])
async def health():
    db_ok = False
    redis_ok = False
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass
    try:
        rc = await RedisClient.get_client()
        await rc.ping()
        redis_ok = True
    except Exception:
        pass
    return {
        "status": "ok" if (db_ok and redis_ok) else "degraded",
        "database": db_ok,
        "redis": redis_ok,
    }


app.include_router(api_router)
