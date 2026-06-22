from typing import Optional, Tuple, List
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.models.user import MasterClass, ClayQuota, ClayType, User, Booking, BookingStatus
from app.schemas.user import MasterClassCreate, MasterClassUpdate
from app.core.exceptions import ResourceNotFoundError, BusinessError


class MasterClassService:
    @staticmethod
    async def create_class(db: AsyncSession, class_in: MasterClassCreate) -> MasterClass:
        if class_in.class_no < 1 or class_in.class_no > 10:
            raise BusinessError("每月最多开放10堂大师课，课程序号必须在1-10之间")
        existing = await db.execute(
            select(MasterClass).where(
                and_(
                    MasterClass.year == class_in.year,
                    MasterClass.month == class_in.month,
                    MasterClass.class_no == class_in.class_no,
                )
            )
        )
        if existing.scalar_one_or_none():
            raise BusinessError(f"{class_in.year}年{class_in.month}月第{class_in.class_no}课已存在")
        clay_types_in = {cq.clay_type for cq in class_in.clay_quotas}
        for ct in ClayType:
            if ct not in clay_types_in:
                raise BusinessError(f"必须包含所有泥料配额，缺少: {ct.value}")
        mc = MasterClass(
            title=class_in.title,
            description=class_in.description,
            master_id=class_in.master_id,
            class_date=class_in.class_date,
            start_time=class_in.start_time,
            end_time=class_in.end_time,
            capacity=class_in.capacity,
            year=class_in.year,
            month=class_in.month,
            class_no=class_in.class_no,
            is_published=class_in.is_published,
        )
        db.add(mc)
        await db.flush()
        for cq in class_in.clay_quotas:
            quota = ClayQuota(
                master_class_id=mc.id,
                clay_type=cq.clay_type,
                total_kg=cq.total_kg,
                used_kg=Decimal("0"),
            )
            db.add(quota)
        await db.commit()
        await db.refresh(mc)
        return mc

    @staticmethod
    async def get_class(db: AsyncSession, class_id: int) -> Optional[MasterClass]:
        result = await db.execute(select(MasterClass).where(MasterClass.id == class_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_class_or_404(db: AsyncSession, class_id: int) -> MasterClass:
        mc = await MasterClassService.get_class(db, class_id)
        if not mc:
            raise ResourceNotFoundError("大师课", class_id)
        return mc

    @staticmethod
    async def list_classes(
        db: AsyncSession,
        year: Optional[int] = None,
        month: Optional[int] = None,
        master_id: Optional[int] = None,
        is_published: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[MasterClass], int]:
        query = select(MasterClass)
        if year:
            query = query.where(MasterClass.year == year)
        if month:
            query = query.where(MasterClass.month == month)
        if master_id:
            query = query.where(MasterClass.master_id == master_id)
        if is_published is not None:
            query = query.where(MasterClass.is_published == is_published)
        count_query = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_query)).scalar_one()
        query = query.order_by(MasterClass.year.desc(), MasterClass.month.desc(), MasterClass.class_no.asc()).offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        items = result.scalars().all()
        return list(items), total

    @staticmethod
    async def update_class(db: AsyncSession, class_id: int, class_in: MasterClassUpdate) -> MasterClass:
        mc = await MasterClassService.get_class_or_404(db, class_id)
        update_data = class_in.model_dump(exclude_unset=True, exclude={"clay_quotas"})
        for field, value in update_data.items():
            setattr(mc, field, value)
        if class_in.clay_quotas:
            for cq_data in class_in.clay_quotas:
                pass
        await db.commit()
        await db.refresh(mc)
        return mc

    @staticmethod
    async def get_class_quota(db: AsyncSession, class_id: int, clay_type: ClayType) -> Optional[ClayQuota]:
        result = await db.execute(
            select(ClayQuota).where(
                and_(ClayQuota.master_class_id == class_id, ClayQuota.clay_type == clay_type)
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all_class_quotas(db: AsyncSession, class_id: int) -> List[ClayQuota]:
        result = await db.execute(select(ClayQuota).where(ClayQuota.master_class_id == class_id))
        return list(result.scalars().all())

    @staticmethod
    async def check_clay_sufficiency(
        db: AsyncSession,
        class_id: int,
        gaobai_ni_kg: Decimal,
        hongtao_kg: Decimal,
        xianwei_ni_kg: Decimal,
    ) -> Tuple[bool, List[dict]]:
        quotas = await MasterClassService.get_all_class_quotas(db, class_id)
        quota_map = {q.clay_type: q for q in quotas}
        requests = [
            (ClayType.GAOBAI_NI, gaobai_ni_kg),
            (ClayType.HONGTAO, hongtao_kg),
            (ClayType.XIANWEI_NI, xianwei_ni_kg),
        ]
        all_sufficient = True
        details = []
        for ct, req_kg in requests:
            q = quota_map.get(ct)
            remaining = (q.total_kg - q.used_kg) if q else Decimal("0")
            sufficient = (q is not None) and (req_kg <= remaining)
            if not sufficient:
                all_sufficient = False
            details.append({
                "clay_type": ct,
                "requested_kg": req_kg,
                "remaining_kg": remaining,
                "sufficient": sufficient,
            })
        return all_sufficient, details

    @staticmethod
    async def consume_clay_quota(
        db: AsyncSession,
        class_id: int,
        gaobai_ni_kg: Decimal,
        hongtao_kg: Decimal,
        xianwei_ni_kg: Decimal,
    ) -> None:
        mapping = {
            ClayType.GAOBAI_NI: gaobai_ni_kg,
            ClayType.HONGTAO: hongtao_kg,
            ClayType.XIANWEI_NI: xianwei_ni_kg,
        }
        for ct, kg in mapping.items():
            if kg <= 0:
                continue
            quota = await MasterClassService.get_class_quota(db, class_id, ct)
            if not quota:
                raise BusinessError(f"课程未配置{ct.value}泥料配额")
            remaining = quota.total_kg - quota.used_kg
            if kg > remaining:
                raise BusinessError(f"{ct.value}泥料不足，剩余{remaining}kg，申请{kg}kg")
            quota.used_kg = quota.used_kg + kg
        await db.flush()

    @staticmethod
    async def release_clay_quota(
        db: AsyncSession,
        class_id: int,
        gaobai_ni_kg: Decimal,
        hongtao_kg: Decimal,
        xianwei_ni_kg: Decimal,
    ) -> None:
        mapping = {
            ClayType.GAOBAI_NI: gaobai_ni_kg,
            ClayType.HONGTAO: hongtao_kg,
            ClayType.XIANWEI_NI: xianwei_ni_kg,
        }
        for ct, kg in mapping.items():
            if kg <= 0:
                continue
            quota = await MasterClassService.get_class_quota(db, class_id, ct)
            if quota:
                quota.used_kg = max(Decimal("0"), quota.used_kg - kg)
        await db.flush()

    @staticmethod
    async def find_adjacent_classes(
        db: AsyncSession,
        year: int,
        month: int,
        exclude_class_id: Optional[int] = None,
    ) -> List[MasterClass]:
        query = select(MasterClass).where(
            and_(
                MasterClass.year == year,
                MasterClass.month == month,
                MasterClass.is_published == True,
            )
        )
        if exclude_class_id:
            query = query.where(MasterClass.id != exclude_class_id)
        query = query.order_by(MasterClass.class_no.asc()).limit(5)
        result = await db.execute(query)
        classes = list(result.scalars().all())
        adj = []
        for mc in classes:
            sufficient, _ = await MasterClassService._check_has_any_quota(db, mc.id)
            if sufficient:
                adj.append(mc)
        return adj

    @staticmethod
    async def _check_has_any_quota(db: AsyncSession, class_id: int) -> Tuple[bool, List]:
        quotas = await MasterClassService.get_all_class_quotas(db, class_id)
        ok = any((q.total_kg - q.used_kg) > Decimal("0") for q in quotas)
        return ok, quotas
