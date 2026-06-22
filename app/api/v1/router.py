from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.users import router as users_router
from app.api.v1.classes import router as classes_router
from app.api.v1.bookings import router as bookings_router
from app.api.v1.attachments import router as attachments_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(classes_router)
api_router.include_router(bookings_router)
api_router.include_router(attachments_router)

__all__ = ["api_router"]
