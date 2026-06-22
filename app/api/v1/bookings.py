from fastapi import APIRouter, Depends, Query, HTTPException, Body, status
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from decimal import Decimal

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.user import UserRole, BookingStatus
from app.services.booking_service import BookingService
from app.services.class_service import MasterClassService
from app.services.user_service import UserService
from app.schemas.user import (
    BookingCreate, BookingUpdateStatus, BookingResponse,
    BookingListResponse, ApiResponse, StatusLogResponse,
    BookingVersionConflictResponse,
)
from app.core.exceptions import (
    raise_http_error, BusinessError, ResourceNotFoundError, VersionConflictError,
)

router = APIRouter(prefix="/bookings", tags=["预约单管理"])


def _enrich_booking(bk, student=None, mc=None, signed_by=None) -> BookingResponse:
    data = BookingResponse.model_validate(bk)
    if student:
        data.student_name = student.full_name
    if mc:
        data.class_title = mc.title
        data.class_date = mc.class_date
    if signed_by:
        data.signed_by_name = signed_by.full_name
    return data


@router.post("", response_model=ApiResponse[BookingResponse])
async def create_booking(
    booking_in: BookingCreate,
    current_user=Depends(require_roles("student")),
    db: AsyncSession = Depends(get_db),
):
    try:
        bk = await BookingService.create_booking(db, current_user, booking_in)
        student = await UserService.get_user(db, bk.student_id)
        mc = await MasterClassService.get_class(db, bk.master_class_id)
        return ApiResponse(data=_enrich_booking(bk, student, mc))
    except (BusinessError, ResourceNotFoundError) as e:
        raise_http_error(e)


@router.get("", response_model=ApiResponse[BookingListResponse])
async def list_bookings(
    master_class_id: Optional[int] = Query(None),
    status: Optional[BookingStatus] = Query(None),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None, ge=1, le=12),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    student_id = None
    if current_user.role == UserRole.STUDENT:
        student_id = current_user.id
    elif current_user.role == UserRole.MASTER:
        pass
    items, total = await BookingService.list_bookings(
        db, student_id=student_id, master_class_id=master_class_id,
        status=status, year=year, month=month, page=page, page_size=page_size,
    )
    student_cache = {}
    class_cache = {}
    signed_cache = {}
    enriched = []
    for bk in items:
        if bk.student_id not in student_cache:
            s = await UserService.get_user(db, bk.student_id)
            student_cache[bk.student_id] = s
        if bk.master_class_id not in class_cache:
            c = await MasterClassService.get_class(db, bk.master_class_id)
            class_cache[bk.master_class_id] = c
        sb = None
        if bk.signed_by_id:
            if bk.signed_by_id not in signed_cache:
                signed_cache[bk.signed_by_id] = await UserService.get_user(db, bk.signed_by_id)
            sb = signed_cache[bk.signed_by_id]
        enriched.append(_enrich_booking(
            bk, student_cache.get(bk.student_id), class_cache.get(bk.master_class_id), sb,
        ))
    return ApiResponse(data=BookingListResponse(
        items=enriched, total=total, page=page, page_size=page_size,
    ))


@router.get("/{booking_id}", response_model=ApiResponse[BookingResponse])
async def get_booking(
    booking_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    bk = await BookingService.get_booking(db, booking_id)
    if not bk:
        raise HTTPException(status_code=404, detail="预约单不存在")
    if current_user.role == UserRole.STUDENT and bk.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权查看他人预约单")
    student = await UserService.get_user(db, bk.student_id)
    mc = await MasterClassService.get_class(db, bk.master_class_id)
    sb = await UserService.get_user(db, bk.signed_by_id) if bk.signed_by_id else None
    return ApiResponse(data=_enrich_booking(bk, student, mc, sb))


@router.post("/{booking_id}/submit-quota", response_model=ApiResponse[BookingResponse])
async def submit_for_quota(
    booking_id: int,
    payload: BookingUpdateStatus,
    current_user=Depends(require_roles("student", "workshop_manager")),
    db: AsyncSession = Depends(get_db),
):
    try:
        bk = await BookingService.submit_for_quota(db, booking_id, current_user.id, payload.version)
        from app.tasks.email_tasks import send_status_email
        student = await UserService.get_user(db, bk.student_id)
        if student:
            send_status_email.delay(student.email, bk.booking_no, "待配额确认", payload.remark or "")
        return ApiResponse(data=_enrich_booking(bk, student, await MasterClassService.get_class(db, bk.master_class_id)))
    except VersionConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=e.message, headers={"X-Current-Version": str(e.data.get("current_version"))})
    except (BusinessError, ResourceNotFoundError) as e:
        raise_http_error(e)


@router.post("/{booking_id}/approve-quota", response_model=ApiResponse[BookingResponse])
async def approve_quota(
    booking_id: int,
    payload: BookingUpdateStatus,
    current_user=Depends(require_roles("workshop_manager")),
    db: AsyncSession = Depends(get_db),
):
    try:
        bk = await BookingService.approve_quota(db, booking_id, current_user.id, payload.version, payload.remark)
        from app.tasks.email_tasks import send_status_email
        student = await UserService.get_user(db, bk.student_id)
        if student:
            send_status_email.delay(student.email, bk.booking_no, "配额确认通过-待大师签字", payload.remark or "")
        return ApiResponse(data=_enrich_booking(bk, student, await MasterClassService.get_class(db, bk.master_class_id)))
    except VersionConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=e.message, headers={"X-Current-Version": str(e.data.get("current_version"))})
    except (BusinessError, ResourceNotFoundError) as e:
        raise_http_error(e)


@router.post("/{booking_id}/reject", response_model=ApiResponse[BookingResponse])
async def reject_booking(
    booking_id: int,
    payload: BookingUpdateStatus,
    current_user=Depends(require_roles("workshop_manager", "master", "finance")),
    db: AsyncSession = Depends(get_db),
):
    if not payload.reject_reason:
        raise HTTPException(status_code=400, detail="必须填写驳回原因")
    try:
        bk = await BookingService.reject_booking(
            db, booking_id, current_user.id, payload.version, payload.reject_reason,
        )
        from app.tasks.email_tasks import send_status_email
        student = await UserService.get_user(db, bk.student_id)
        if student:
            send_status_email.delay(student.email, bk.booking_no, "已驳回", payload.reject_reason)
        return ApiResponse(data=_enrich_booking(bk, student, await MasterClassService.get_class(db, bk.master_class_id)))
    except VersionConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=e.message, headers={"X-Current-Version": str(e.data.get("current_version"))})
    except (BusinessError, ResourceNotFoundError) as e:
        raise_http_error(e)


@router.post("/{booking_id}/sign", response_model=ApiResponse[BookingResponse])
async def sign_booking(
    booking_id: int,
    payload: BookingUpdateStatus,
    current_user=Depends(require_roles("master")),
    db: AsyncSession = Depends(get_db),
):
    try:
        bk = await BookingService.sign_booking(db, booking_id, current_user.id, payload.version, payload.remark)
        from app.tasks.email_tasks import send_status_email
        student = await UserService.get_user(db, bk.student_id)
        if student:
            send_status_email.delay(student.email, bk.booking_no, "大师签字完成-待缴费", payload.remark or "")
        mc = await MasterClassService.get_class(db, bk.master_class_id)
        return ApiResponse(data=_enrich_booking(bk, student, mc, current_user))
    except VersionConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=e.message, headers={"X-Current-Version": str(e.data.get("current_version"))})
    except (BusinessError, ResourceNotFoundError) as e:
        raise_http_error(e)


@router.post("/{booking_id}/confirm-payment", response_model=ApiResponse[BookingResponse])
async def confirm_payment(
    booking_id: int,
    payload: BookingUpdateStatus,
    current_user=Depends(require_roles("finance")),
    db: AsyncSession = Depends(get_db),
):
    if not payload.paid_amount:
        raise HTTPException(status_code=400, detail="必须填写缴费金额")
    try:
        bk = await BookingService.confirm_payment(
            db, booking_id, current_user.id, payload.version, payload.paid_amount, payload.remark,
        )
        from app.tasks.email_tasks import send_status_email
        student = await UserService.get_user(db, bk.student_id)
        if student:
            send_status_email.delay(student.email, bk.booking_no, f"缴费确认已完成 金额:{payload.paid_amount}", payload.remark or "")
        return ApiResponse(data=_enrich_booking(bk, student, await MasterClassService.get_class(db, bk.master_class_id)))
    except VersionConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=e.message, headers={"X-Current-Version": str(e.data.get("current_version"))})
    except (BusinessError, ResourceNotFoundError) as e:
        raise_http_error(e)


@router.get("/{booking_id}/logs", response_model=ApiResponse[list[StatusLogResponse]])
async def get_status_logs(
    booking_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    bk = await BookingService.get_booking(db, booking_id)
    if not bk:
        raise HTTPException(status_code=404, detail="预约单不存在")
    if current_user.role == UserRole.STUDENT and bk.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权查看")
    logs = await BookingService.get_status_logs(db, booking_id)
    op_cache = {}
    result = []
    for log in logs:
        lr = StatusLogResponse.model_validate(log)
        if log.operator_id and log.operator_id not in op_cache:
            u = await UserService.get_user(db, log.operator_id)
            op_cache[log.operator_id] = u.full_name if u else None
        if log.operator_id:
            lr.operator_name = op_cache.get(log.operator_id)
        result.append(lr)
    return ApiResponse(data=result)
