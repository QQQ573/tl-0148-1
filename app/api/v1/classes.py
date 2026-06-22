from fastapi import APIRouter, Depends, Query, HTTPException, Body
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from decimal import Decimal

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.services.class_service import MasterClassService
from app.services.user_service import UserService
from app.schemas.user import (
    MasterClassCreate, MasterClassUpdate, MasterClassResponse,
    MasterClassListResponse, ClayQuotaResponse, ApiResponse,
    QuotaCheckResponse, QuotaCheckItem,
)
from app.core.exceptions import raise_http_error, BusinessError, ResourceNotFoundError

router = APIRouter(prefix="/classes", tags=["大师课管理"])


def _enrich_class_response(mc, user=None) -> MasterClassResponse:
    data = MasterClassResponse.model_validate(mc)
    if user:
        data.master_name = user.full_name
    enriched_quotas = []
    for q in mc.clay_quotas:
        qr = ClayQuotaResponse.model_validate(q)
        qr.remaining_kg = q.total_kg - q.used_kg
        enriched_quotas.append(qr)
    data.clay_quotas = enriched_quotas
    return data


@router.post("", response_model=ApiResponse[MasterClassResponse])
async def create_class(
    class_in: MasterClassCreate,
    current_user=Depends(require_roles("workshop_manager")),
    db: AsyncSession = Depends(get_db),
):
    try:
        mc = await MasterClassService.create_class(db, class_in)
        master = await UserService.get_user(db, mc.master_id)
        return ApiResponse(data=_enrich_class_response(mc, master))
    except (BusinessError, ResourceNotFoundError) as e:
        raise_http_error(e)


@router.get("", response_model=ApiResponse[MasterClassListResponse])
async def list_classes(
    year: Optional[int] = Query(None, description="年份"),
    month: Optional[int] = Query(None, ge=1, le=12, description="月份"),
    master_id: Optional[int] = Query(None, description="大师ID"),
    is_published: Optional[bool] = Query(None, description="是否发布"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.user import UserRole
    q_is_published = is_published
    if current_user.role == UserRole.STUDENT and q_is_published is None:
        q_is_published = True

    items, total = await MasterClassService.list_classes(
        db, year=year, month=month, master_id=master_id,
        is_published=q_is_published, page=page, page_size=page_size,
    )
    master_cache = {}
    enriched = []
    for mc in items:
        if mc.master_id not in master_cache:
            m = await UserService.get_user(db, mc.master_id)
            master_cache[mc.master_id] = m.full_name if m else None
        er = _enrich_class_response(mc)
        er.master_name = master_cache.get(mc.master_id)
        enriched.append(er)
    return ApiResponse(data=MasterClassListResponse(
        items=enriched, total=total, page=page, page_size=page_size,
    ))


@router.get("/{class_id}", response_model=ApiResponse[MasterClassResponse])
async def get_class(
    class_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    mc = await MasterClassService.get_class(db, class_id)
    if not mc:
        raise HTTPException(status_code=404, detail="课程不存在")
    master = await UserService.get_user(db, mc.master_id)
    return ApiResponse(data=_enrich_class_response(mc, master))


@router.patch("/{class_id}", response_model=ApiResponse[MasterClassResponse])
async def update_class(
    class_id: int,
    class_in: MasterClassUpdate,
    current_user=Depends(require_roles("workshop_manager")),
    db: AsyncSession = Depends(get_db),
):
    try:
        mc = await MasterClassService.update_class(db, class_id, class_in)
        master = await UserService.get_user(db, mc.master_id)
        return ApiResponse(data=_enrich_class_response(mc, master))
    except ResourceNotFoundError as e:
        raise_http_error(e)


@router.post("/{class_id}/check-quota", response_model=ApiResponse[QuotaCheckResponse])
async def check_quota(
    class_id: int,
    gaobai_ni_kg: Decimal = Body(..., embed=True),
    hongtao_kg: Decimal = Body(..., embed=True),
    xianwei_ni_kg: Decimal = Body(..., embed=True),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sufficient, details = await MasterClassService.check_clay_sufficiency(
        db, class_id, gaobai_ni_kg, hongtao_kg, xianwei_ni_kg,
    )
    quota_items = [QuotaCheckItem(**d) for d in details]
    recommendations = []
    if not sufficient:
        mc = await MasterClassService.get_class(db, class_id)
        if mc:
            adj = await MasterClassService.find_adjacent_classes(
                db, mc.year, mc.month, exclude_class_id=class_id,
            )
            for ac in adj:
                master = await UserService.get_user(db, ac.master_id)
                recommendations.append(_enrich_class_response(ac, master))
    return ApiResponse(data=QuotaCheckResponse(
        sufficient=sufficient,
        details=quota_items,
        recommended_classes=recommendations,
    ))
