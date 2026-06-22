import uuid
import calendar
from typing import Optional, Tuple, List
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_

from app.models.user import Booking, BookingStatus, BookingStatusLog, MasterClass, User, ClayType
from app.schemas.user import BookingCreate, BookingUpdateStatus
from app.core.exceptions import ResourceNotFoundError, BusinessError, VersionConflictError
from app.services.class_service import MasterClassService
from app.core.redis_client import (
    RedisClient,
    get_student_month_lock_key,
    get_booking_cache_key,
)


ACTIVE_STATUSES = [
    BookingStatus.DRAFT,
    BookingStatus.PENDING_QUOTA,
    BookingStatus.PENDING_SIGNATURE,
    BookingStatus.PENDING_PAYMENT,
]

VALID_TRANSITIONS = {
    BookingStatus.DRAFT: [BookingStatus.PENDING_QUOTA, BookingStatus.REJECTED],
    BookingStatus.PENDING_QUOTA: [BookingStatus.PENDING_SIGNATURE, BookingStatus.REJECTED],
    BookingStatus.PENDING_SIGNATURE: [BookingStatus.PENDING_PAYMENT, BookingStatus.REJECTED],
    BookingStatus.PENDING_PAYMENT: [BookingStatus.CONFIRMED, BookingStatus.REJECTED],
    BookingStatus.CONFIRMED: [],
    BookingStatus.REJECTED: [],
}


def generate_booking_no() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rand = uuid.uuid4().hex[:8].upper()
    return f"BK{ts}{rand}"


class BookingService:
    @staticmethod
    async def _check_student_month_active(db: AsyncSession, student_id: int, year: int, month: int) -> bool:
        last_day = calendar.monthrange(year, month)[1]
        result = await db.execute(
            select(func.count()).select_from(Booking).where(
                and_(
                    Booking.student_id == student_id,
                    Booking.class_year == year,
                    Booking.class_month == month,
                    Booking.status.in_(ACTIVE_STATUSES),
                )
            )
        )
        return result.scalar_one() > 0

    @staticmethod
    async def create_booking(db: AsyncSession, student: User, booking_in: BookingCreate) -> Booking:
        mc = await MasterClassService.get_class_or_404(db, booking_in.master_class_id)
        if not mc.is_published:
            raise BusinessError("该课程尚未发布，无法预约")
        year, month = mc.year, mc.month

        lock_key = get_student_month_lock_key(student.id, year, month)
        lock_acquired = await RedisClient.acquire_lock(lock_key, timeout=10)
        if not lock_acquired:
            raise BusinessError("系统繁忙，请稍后再试")

        try:
            has_active = await BookingService._check_student_month_active(db, student.id, year, month)
            if has_active:
                raise BusinessError(f"您在{year}年{month}月已有进行中的预约，同一自然月内不可重复创建")

            total_kg = booking_in.gaobai_ni_kg + booking_in.hongtao_kg + booking_in.xianwei_ni_kg
            if total_kg <= 0:
                raise BusinessError("至少需要申请一种泥料")

            booking = Booking(
                booking_no=generate_booking_no(),
                student_id=student.id,
                master_class_id=mc.id,
                class_year=year,
                class_month=month,
                status=BookingStatus.DRAFT,
                gaobai_ni_kg=booking_in.gaobai_ni_kg,
                hongtao_kg=booking_in.hongtao_kg,
                xianwei_ni_kg=booking_in.xianwei_ni_kg,
                student_remark=booking_in.student_remark,
                version=1,
            )
            db.add(booking)
            await db.flush()

            log = BookingStatusLog(
                booking_id=booking.id,
                from_status=None,
                to_status=BookingStatus.DRAFT,
                operator_id=student.id,
                remark="学员创建预约草稿",
            )
            db.add(log)
            await db.commit()
            await db.refresh(booking)
            return booking
        finally:
            await RedisClient.release_lock(lock_key)

    @staticmethod
    async def get_booking(db: AsyncSession, booking_id: int) -> Optional[Booking]:
        cache_key = get_booking_cache_key(booking_id)
        result = await db.execute(select(Booking).where(Booking.id == booking_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_booking_or_404(db: AsyncSession, booking_id: int) -> Booking:
        bk = await BookingService.get_booking(db, booking_id)
        if not bk:
            raise ResourceNotFoundError("预约单", booking_id)
        return bk

    @staticmethod
    async def list_bookings(
        db: AsyncSession,
        student_id: Optional[int] = None,
        master_class_id: Optional[int] = None,
        status: Optional[BookingStatus] = None,
        year: Optional[int] = None,
        month: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Booking], int]:
        query = select(Booking)
        if student_id:
            query = query.where(Booking.student_id == student_id)
        if master_class_id:
            query = query.where(Booking.master_class_id == master_class_id)
        if status:
            query = query.where(Booking.status == status)
        if year:
            query = query.where(Booking.class_year == year)
        if month:
            query = query.where(Booking.class_month == month)
        count_query = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_query)).scalar_one()
        query = query.order_by(Booking.id.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        items = result.scalars().all()
        return list(items), total

    @staticmethod
    def _check_transition(current: BookingStatus, target: BookingStatus) -> bool:
        return target in VALID_TRANSITIONS.get(current, [])

    @staticmethod
    async def _write_log(
        db: AsyncSession,
        booking_id: int,
        from_status: Optional[BookingStatus],
        to_status: BookingStatus,
        operator_id: Optional[int],
        remark: Optional[str] = None,
    ) -> None:
        log = BookingStatusLog(
            booking_id=booking_id,
            from_status=from_status,
            to_status=to_status,
            operator_id=operator_id,
            remark=remark,
        )
        db.add(log)

    @staticmethod
    async def _update_with_version(
        db: AsyncSession,
        booking: Booking,
        update_fn,
        expected_version: int,
    ) -> Booking:
        if booking.version != expected_version:
            raise VersionConflictError(current_version=booking.version)
        new_version = expected_version + 1
        update_fn(booking, new_version)
        booking.version = new_version
        booking.last_updated_at = datetime.now(timezone.utc)
        await db.flush()
        await db.refresh(booking)
        return booking

    @staticmethod
    async def submit_for_quota(
        db: AsyncSession,
        booking_id: int,
        operator_id: int,
        version: int,
    ) -> Booking:
        booking = await BookingService.get_booking_or_404(db, booking_id)
        if not BookingService._check_transition(booking.status, BookingStatus.PENDING_QUOTA):
            raise BusinessError(f"当前状态[{booking.status.value}]不支持提交配额确认")

        def apply(bk, nv):
            bk.status = BookingStatus.PENDING_QUOTA
        booking = await BookingService._update_with_version(db, booking, apply, version)
        await BookingService._write_log(
            db, booking.id, BookingStatus.DRAFT, BookingStatus.PENDING_QUOTA,
            operator_id, "提交配额确认",
        )
        await db.commit()
        await db.refresh(booking)
        cache_key = get_booking_cache_key(booking_id)
        await RedisClient.delete(cache_key)
        return booking

    @staticmethod
    async def approve_quota(
        db: AsyncSession,
        booking_id: int,
        operator_id: int,
        version: int,
        quota_remark: Optional[str] = None,
    ) -> Booking:
        booking = await BookingService.get_booking_or_404(db, booking_id)
        if booking.status != BookingStatus.PENDING_QUOTA:
            raise BusinessError(f"当前状态[{booking.status.value}]不支持配额审批")

        sufficient, _ = await MasterClassService.check_clay_sufficiency(
            db, booking.master_class_id,
            booking.gaobai_ni_kg, booking.hongtao_kg, booking.xianwei_ni_kg,
        )
        if not sufficient:
            return await BookingService.reject_booking(
                db, booking_id, operator_id, version,
                reject_reason="泥料配额不足，系统自动驳回",
                auto_recommend=True,
            )

        await MasterClassService.consume_clay_quota(
            db, booking.master_class_id,
            booking.gaobai_ni_kg, booking.hongtao_kg, booking.xianwei_ni_kg,
        )

        def apply(bk, nv):
            bk.status = BookingStatus.PENDING_SIGNATURE
            bk.quota_remark = quota_remark
        booking = await BookingService._update_with_version(db, booking, apply, version)
        await BookingService._write_log(
            db, booking.id, BookingStatus.PENDING_QUOTA, BookingStatus.PENDING_SIGNATURE,
            operator_id, f"配额确认通过 {('- 备注: ' + quota_remark) if quota_remark else ''}",
        )
        await db.commit()
        await db.refresh(booking)
        return booking

    @staticmethod
    async def reject_booking(
        db: AsyncSession,
        booking_id: int,
        operator_id: int,
        version: int,
        reject_reason: str,
        auto_recommend: bool = False,
    ) -> Booking:
        booking = await BookingService.get_booking_or_404(db, booking_id)
        if booking.status not in [BookingStatus.DRAFT, BookingStatus.PENDING_QUOTA, BookingStatus.PENDING_SIGNATURE, BookingStatus.PENDING_PAYMENT]:
            raise BusinessError(f"当前状态[{booking.status.value}]不支持驳回")

        if booking.status == BookingStatus.PENDING_SIGNATURE or booking.status == BookingStatus.PENDING_PAYMENT or booking.status == BookingStatus.PENDING_QUOTA:
            await MasterClassService.release_clay_quota(
                db, booking.master_class_id,
                booking.gaobai_ni_kg, booking.hongtao_kg, booking.xianwei_ni_kg,
            )

        from_status = booking.status
        recommended_info = ""
        if auto_recommend:
            mc = await MasterClassService.get_class(db, booking.master_class_id)
            if mc:
                adj = await MasterClassService.find_adjacent_classes(
                    db, mc.year, mc.month, exclude_class_id=mc.id,
                )
                if adj:
                    names = ", ".join([f"第{c.class_no}课({c.class_date})" for c in adj])
                    recommended_info = f"。推荐相邻班次: {names}"

        def apply(bk, nv):
            bk.status = BookingStatus.REJECTED
            bk.reject_reason = reject_reason + recommended_info
        booking = await BookingService._update_with_version(db, booking, apply, version)
        await BookingService._write_log(
            db, booking.id, from_status, BookingStatus.REJECTED,
            operator_id, f"驳回: {reject_reason}{recommended_info}",
        )
        await db.commit()
        await db.refresh(booking)
        return booking

    @staticmethod
    async def sign_booking(
        db: AsyncSession,
        booking_id: int,
        master_id: int,
        version: int,
        remark: Optional[str] = None,
    ) -> Booking:
        booking = await BookingService.get_booking_or_404(db, booking_id)
        if booking.status != BookingStatus.PENDING_SIGNATURE:
            raise BusinessError(f"当前状态[{booking.status.value}]不支持大师签字")
        mc = await MasterClassService.get_class(db, booking.master_class_id)
        if mc and mc.master_id != master_id:
            raise BusinessError("您不是该课程的授课大师，无权签字")

        def apply(bk, nv):
            bk.status = BookingStatus.PENDING_PAYMENT
            bk.signed_by_id = master_id
            bk.signed_at = datetime.now(timezone.utc)
        booking = await BookingService._update_with_version(db, booking, apply, version)
        await BookingService._write_log(
            db, booking.id, BookingStatus.PENDING_SIGNATURE, BookingStatus.PENDING_PAYMENT,
            master_id, f"大师签字确认 {('- 备注: ' + remark) if remark else ''}",
        )
        await db.commit()
        await db.refresh(booking)
        return booking

    @staticmethod
    async def confirm_payment(
        db: AsyncSession,
        booking_id: int,
        finance_id: int,
        version: int,
        paid_amount: Decimal,
        remark: Optional[str] = None,
    ) -> Booking:
        booking = await BookingService.get_booking_or_404(db, booking_id)
        if booking.status != BookingStatus.PENDING_PAYMENT:
            raise BusinessError(f"当前状态[{booking.status.value}]不支持缴费确认")

        def apply(bk, nv):
            bk.status = BookingStatus.CONFIRMED
            bk.paid_amount = paid_amount
            bk.paid_at = datetime.now(timezone.utc)
        booking = await BookingService._update_with_version(db, booking, apply, version)
        await BookingService._write_log(
            db, booking.id, BookingStatus.PENDING_PAYMENT, BookingStatus.CONFIRMED,
            finance_id, f"缴费确认 金额:{paid_amount} {('- 备注: ' + remark) if remark else ''}",
        )
        await db.commit()
        await db.refresh(booking)
        return booking

    @staticmethod
    async def get_status_logs(db: AsyncSession, booking_id: int) -> List[BookingStatusLog]:
        result = await db.execute(
            select(BookingStatusLog).where(BookingStatusLog.booking_id == booking_id).order_by(BookingStatusLog.id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def find_stale_bookings(db: AsyncSession, hours: int = 24) -> List[Booking]:
        threshold = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await db.execute(
            select(Booking).where(
                and_(
                    Booking.status.in_(ACTIVE_STATUSES),
                    Booking.last_updated_at < threshold,
                    or_(Booking.last_alerted_at.is_(None), Booking.last_alerted_at < threshold),
                )
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def mark_alerted(db: AsyncSession, booking_ids: List[int]) -> None:
        if not booking_ids:
            return
        now = datetime.now(timezone.utc)
        for bid in booking_ids:
            bk = await BookingService.get_booking(db, bid)
            if bk:
                bk.last_alerted_at = now
        await db.commit()
